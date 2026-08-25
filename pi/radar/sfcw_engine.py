"""Stepped-Frequency Continuous Wave (SFCW) radar engine.

Orchestrates the bladeRF to sweep through discrete frequency steps,
capture IQ at each, and compute range profiles via IFFT.

Uses dual-channel reference: TX1+RX1 for antenna signal, TX2+RX2 as
phase reference (short cable loopback). Dividing signal by reference
eliminates random PLL phase offsets between TX and RX synthesizers.
"""

import threading
import time
import numpy as np
from datetime import datetime

from bladerf_driver import BladeRFDriver
from bladerf._bladerf import ffi, libbladeRF
import bladerf

SPEED_OF_LIGHT = 299_792_458


def _log_timing(event, **details):
    """Log timing events in human-readable format."""
    timestamp = datetime.now().strftime('%H:%M:%S.%f')  # Microsecond precision
    detail_str = ' '.join(f'{k}={v}' for k, v in details.items()) if details else ''
    print(f"[{timestamp}] SFCW | {event:<30} {detail_str}", flush=True)


def _log_separator(char='─'):
    """Print a visual separator line."""
    timestamp = datetime.now().strftime('%H:%M:%S.%f')  # Microsecond precision
    print(f"[{timestamp}] SFCW | {char * 70}", flush=True)


def _format_duration(seconds):
    """Format duration in human-readable way."""
    if seconds < 0.001:
        return f"{seconds*1000000:.0f}µs"
    elif seconds < 1:
        return f"{seconds*1000:.1f}ms"
    else:
        return f"{seconds:.3f}s"

# Master quick-tune table: covers the whole usable band at a fixed grid, generated
# once per device connection. Any sweep's start/stop/step is snapped onto this grid
# (see _snap_freq/_snap_step), so retuning never needs the table to be regenerated —
# start/stop/step can change freely at runtime with no device reset. See CLAUDE.md
# "Quick-tune master table" for the history of why this replaced per-grid caching.
#
# bladerf_get_quick_tune() isn't a stateless read — every call WRITES a new fastlock
# profile into a fixed-size on-device table (bladerf2.c: board_data->quick_tune_tx/
# rx_profile, capped at NUM_BBP_FASTLOCK_PROFILES). That counter only resets on a
# full device close+reopen. Past the cap, bladerf_get_quick_tune() returns an error
# and leaves the profile struct unpopulated — MAX_QUICK_TUNE_PROFILES here must stay
# under that hardware ceiling or the table silently contains garbage profiles for
# every frequency past it (this happened: a prior 1-6 GHz/10 MHz table needed 501
# profiles against a 256 cap).
MAX_QUICK_TUNE_PROFILES = 256  # NUM_BBP_FASTLOCK_PROFILES, fpga_common/bladerf2_common.h
QT_MASTER_START_FREQ = 2_000_000_000
QT_MASTER_STOP_FREQ = 5_000_000_000
QT_MASTER_STEP = 20_000_000


class SFCWEngine:
    def __init__(self, driver: BladeRFDriver):
        self.driver = driver
        self.start_freq = 2_000_000_000
        self.stop_freq = 5_000_000_000
        self.step_size = 60_000_000
        self.num_buffers = 4
        self.settle_count = 10
        self.tx1_gain = 60
        self.rx1_gain = 40
        self.tx2_gain = 30
        self.rx2_gain = 20
        self.rx_gain_min = 5
        self.rx_gain_max = 38
        self.range_offset = 0.5
        self.bscan_avg_count = 1
        self.bscan_primer = False
        self.running = False
        self._stop_event = threading.Event()
        self._thread = None
        self._callback = None
        self._lock = threading.Lock()
        self._fpga_tuning = False
        self._gains_dirty = False
        self._warm = False
        self._sweep_lock = threading.Lock()
        self._qt_master_freqs = None
        self._qt_master_rx = None
        self._qt_master_tx = None
        self._use_quick_tune = True

    @property
    def num_steps(self):
        return int((self.stop_freq - self.start_freq) / self.step_size) + 1

    @property
    def bandwidth(self):
        return self.stop_freq - self.start_freq

    @property
    def range_resolution(self):
        if self.bandwidth == 0:
            return float('inf')
        return SPEED_OF_LIGHT / (2 * self.bandwidth)

    @property
    def max_range(self):
        if self.step_size == 0:
            return float('inf')
        return SPEED_OF_LIGHT / (2 * self.step_size)

    @staticmethod
    def _snap_freq(value):
        """Round to the nearest 10 MHz grid point and clamp into the master table's range."""
        snapped = round(float(value) / QT_MASTER_STEP) * QT_MASTER_STEP
        return int(min(max(snapped, QT_MASTER_START_FREQ), QT_MASTER_STOP_FREQ))

    @staticmethod
    def _snap_step(value):
        snapped = round(float(value) / QT_MASTER_STEP) * QT_MASTER_STEP
        return int(max(snapped, QT_MASTER_STEP))

    def set_params(self, **kwargs):
        with self._lock:
            if 'start_freq' in kwargs:
                self.start_freq = self._snap_freq(kwargs['start_freq'])
            if 'stop_freq' in kwargs:
                self.stop_freq = self._snap_freq(kwargs['stop_freq'])
            if 'step_size' in kwargs:
                self.step_size = self._snap_step(kwargs['step_size'])
            if 'num_buffers' in kwargs:
                self.num_buffers = max(1, int(kwargs['num_buffers']))
            if 'settle_count' in kwargs:
                self.settle_count = max(1, int(kwargs['settle_count']))
            if 'tx1_gain' in kwargs:
                self.tx1_gain = int(kwargs['tx1_gain'])
                self._gains_dirty = True
            if 'rx1_gain' in kwargs:
                self.rx1_gain = int(kwargs['rx1_gain'])
                self._gains_dirty = True
            if 'tx2_gain' in kwargs:
                self.tx2_gain = int(kwargs['tx2_gain'])
                self._gains_dirty = True
            if 'rx2_gain' in kwargs:
                self.rx2_gain = int(kwargs['rx2_gain'])
                self._gains_dirty = True
            if 'rx_gain_min' in kwargs:
                self.rx_gain_min = int(kwargs['rx_gain_min'])
            if 'rx_gain_max' in kwargs:
                self.rx_gain_max = int(kwargs['rx_gain_max'])
            if 'range_offset' in kwargs:
                self.range_offset = float(kwargs['range_offset'])
            if 'bscan_avg_count' in kwargs:
                self.bscan_avg_count = max(1, int(kwargs['bscan_avg_count']))
            if 'bscan_primer' in kwargs:
                self.bscan_primer = bool(kwargs['bscan_primer'])

    def get_params(self):
        return {
            'start_freq': self.start_freq,
            'stop_freq': self.stop_freq,
            'step_size': self.step_size,
            'num_buffers': self.num_buffers,
            'settle_count': self.settle_count,
            'tx1_gain': self.tx1_gain,
            'rx1_gain': self.rx1_gain,
            'tx2_gain': self.tx2_gain,
            'rx2_gain': self.rx2_gain,
            'rx_gain_min': self.rx_gain_min,
            'rx_gain_max': self.rx_gain_max,
            'range_offset': self.range_offset,
            'num_steps': self.num_steps,
            'bandwidth': self.bandwidth,
            'range_resolution': self.range_resolution,
            'max_range': self.max_range,
            'bscan_avg_count': self.bscan_avg_count,
            'bscan_primer': self.bscan_primer,
        }

    def run_coherence_test(self, callback=None):
        """Run 3 consecutive sweeps and compute repeatability + correlation metrics.

        Runs in a new thread. Results sent via callback as a dict with type='coherence_result'.
        """
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        t = threading.Thread(target=self._coherence_test_worker, args=(callback,), daemon=True)
        t.start()

    def _coherence_test_worker(self, callback):
        try:
            self._configure_hardware()
            self._start_tx_rx()
            time.sleep(0.1)

            sweeps = []
            for i in range(3):
                if self._stop_event.is_set():
                    return
                if callback:
                    callback({'type': 'progress', 'step': i, 'total': 3, 'freq_mhz': 0})
                result = self._perform_sweep()
                if result and result.get('type') == 'range_profile':
                    h_cal = np.array(result['h_cal_real']) + 1j * np.array(result['h_cal_imag'])
                    sweeps.append(h_cal)

            if len(sweeps) < 2:
                if callback:
                    callback({'error': 'Not enough sweeps completed'})
                return

            reps = []
            corrs = []
            for i in range(len(sweeps) - 1):
                a_raw = sweeps[i]
                b_raw = sweeps[i + 1]
                residual = b_raw - a_raw
                rep = 1.0 - (np.std(residual) / np.std(a_raw))
                reps.append(float(rep))
                a = a_raw - np.mean(a_raw)
                b = b_raw - np.mean(b_raw)
                corr = np.abs(np.sum(a * np.conj(b))) / (
                    np.sqrt(np.sum(np.abs(a) ** 2)) * np.sqrt(np.sum(np.abs(b) ** 2))
                )
                corrs.append(float(corr))

            if callback:
                callback({
                    'type': 'coherence_result',
                    'repeatability': reps,
                    'correlation': corrs,
                    'avg_repeatability': float(np.mean(reps)),
                    'avg_correlation': float(np.mean(corrs)),
                    'num_sweeps': len(sweeps),
                })
        except Exception as e:
            if callback:
                callback({'error': str(e)})
        finally:
            self._stop_tx_rx()
            self.running = False

    def run_single(self, callback):
        """Run a single sweep and stop. Used for B-scan position captures."""
        if self._warm:
            self._callback = callback
            t = threading.Thread(target=self._warm_sweep_worker, args=(callback,), daemon=True)
            t.start()
            return
        if self.running:
            return
        self._callback = callback
        self._stop_event.clear()
        self.running = True
        self._thread = threading.Thread(target=self._single_sweep_worker, daemon=True)
        self._thread.start()

    def _warm_sweep_worker(self, callback):
        """Perform averaged sweeps with hardware already running (warm B-scan mode)."""
        with self._sweep_lock:
            try:
                if self.bscan_primer:
                    self._perform_sweep_raw()

                avg_count = self.bscan_avg_count
                if avg_count <= 1:
                    result = self._perform_sweep()
                else:
                    h_cal_accum = None
                    completed = 0
                    for i in range(avg_count):
                        raw = self._perform_sweep_raw()
                        if raw is None:
                            continue
                        if h_cal_accum is None:
                            h_cal_accum = raw.copy()
                        else:
                            h_cal_accum += raw
                        completed += 1
                    if completed == 0:
                        result = None
                    else:
                        h_cal_avg = h_cal_accum / completed
                        result = self._process_h_cal(h_cal_avg)
                if result is not None and callback:
                    callback(result)
            except Exception as e:
                print(f"[sfcw] Warm sweep error: {e}")
                if callback:
                    callback({'error': str(e)})

    def _single_sweep_worker(self):
        try:
            self._configure_hardware()
            self._start_tx_rx()
            time.sleep(0.1)
            result = self._perform_sweep()
            if result is not None and self._callback:
                self._callback(result)
        except Exception as e:
            print(f"[sfcw] Single sweep error: {e}")
            if self._callback:
                self._callback({'error': str(e)})
        finally:
            self._stop_tx_rx()
            self.running = False

    def warm_up(self):
        """Start hardware and keep it running for multiple on-demand sweeps (B-scan mode)."""
        if self._warm or self.running:
            return
        self._stop_event.clear()
        self._configure_hardware()
        self._start_tx_rx()
        time.sleep(0.1)
        self._perform_sweep_raw()
        self._warm = True
        self.running = True

    def cool_down(self):
        """Stop hardware after warm B-scan session."""
        if not self._warm:
            return
        self._stop_tx_rx()
        self._warm = False
        self.running = False

    def start(self, callback):
        if self.running:
            return
        self._callback = callback
        self._stop_event.clear()
        self.running = True
        self._thread = threading.Thread(target=self._sweep_loop, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.running:
            return
        if self._warm:
            self.cool_down()
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self.running = False

    def _sweep_loop(self):
        try:
            _log_separator('═')
            _log_timing("SFCW ENGINE STARTING",
                       note="Pi_initializing_bladeRF_for_sweeps")
            loop_start = time.time()

            self._configure_hardware()
            self._start_tx_rx()

            _log_timing("READY — ENTERING SWEEP LOOP",
                       setup_time=_format_duration(time.time() - loop_start))

            while not self._stop_event.is_set():
                if not self.driver.tx_running or not self.driver.rx_running:
                    _log_timing("ERROR: TX/RX STREAM DIED",
                               tx_running=self.driver.tx_running,
                               rx_running=self.driver.rx_running)
                    if self._callback:
                        self._callback({'error': 'USB stream died — restart sweep'})
                    break
                if self._gains_dirty:
                    self._apply_gains()
                range_profile = self._perform_sweep()
                if range_profile is not None and self._callback:
                    self._callback(range_profile)

        except Exception as e:
            _log_timing("SWEEP ERROR", error=str(e))
            if self._callback:
                self._callback({'error': str(e)})
        finally:
            self._stop_tx_rx()
            self.running = False
            _log_timing("SFCW ENGINE STOPPED",
                       note="bladeRF_fully_idle")
            _log_separator('═')

    def _ensure_master_quick_tune_table(self):
        """Generate the full-band quick_tune table once, covering QT_MASTER_START_FREQ..
        QT_MASTER_STOP_FREQ at QT_MASTER_STEP spacing.

        This is the one place that pays the full-VCO-cal cost (one bladerf_set_frequency
        per master grid point) and consumes the device's fixed BBP fastlock profile
        budget (MAX_QUICK_TUNE_PROFILES, see the module comment). It's independent of
        start_freq/stop_freq/step_size, so it only needs to happen once per device
        connection: after this, changing sweep params never requires a device reset,
        since every sweep's frequencies are just slices of this table (see
        _build_sweep_grid). Must be called before streaming starts and before switching
        to FPGA tuning mode (set_frequency needs normal tuning mode to calibrate).
        """
        if self._qt_master_freqs is not None:
            return

        freqs = np.arange(QT_MASTER_START_FREQ, QT_MASTER_STOP_FREQ + QT_MASTER_STEP,
                           QT_MASTER_STEP, dtype=np.int64)
        if len(freqs) > MAX_QUICK_TUNE_PROFILES:
            raise RuntimeError(
                f"Master quick-tune table needs {len(freqs)} profiles but the bladeRF2 "
                f"firmware caps BBP fastlock profiles at {MAX_QUICK_TUNE_PROFILES} per "
                f"direction. Narrow QT_MASTER_STOP_FREQ - QT_MASTER_START_FREQ or widen "
                f"QT_MASTER_STEP in sfcw_engine.py."
            )

        dev_ptr = self.driver.device.dev[0]

        _log_separator('═')
        _log_timing("QT TABLE BUILD START",
                   num_profiles=len(freqs),
                   range=f"{freqs[0]/1e9:.2f}-{freqs[-1]/1e9:.2f}GHz",
                   step=f"{QT_MASTER_STEP/1e6:.0f}MHz")
        _log_timing("  Per profile: 2x set_frequency (VCO cal) + 2x get_quick_tune (save fastlock)")
        _log_timing("  set_frequency = Pi>>>bladeRF [EP0x02] 16x64 NIOS magic=0x45 target=AD9361_SPI (multiple SPI writes for VCO cal)")
        _log_timing("  get_quick_tune = Pi>>>bladeRF [EP0x02] 8x32 NIOS magic=0x43 target=0x05 (AD9361_FASTLOCK save)")
        _log_timing("  Each command gets Pi<<<bladeRF [EP0x82] 16-byte ACK back")

        qt_rx = []
        qt_tx = []
        table_start = time.time()
        for f in freqs:
            f_int = int(f)
            t0 = time.time()
            rc_sf_rx = libbladeRF.bladerf_set_frequency(dev_ptr, bladerf.CHANNEL_RX(0), f_int)
            t1 = time.time()
            rc_sf_tx = libbladeRF.bladerf_set_frequency(dev_ptr, bladerf.CHANNEL_TX(0), f_int)
            t2 = time.time()

            if rc_sf_rx != 0 or rc_sf_tx != 0:
                raise RuntimeError(
                    f"bladerf_set_frequency failed at {f_int/1e6:.0f} MHz "
                    f"(rx_rc={rc_sf_rx}, tx_rc={rc_sf_tx}) — a profile captured after a "
                    f"failed tune would contain garbage PLL state."
                )

            qr = ffi.new('struct bladerf_quick_tune *')
            qt_val = ffi.new('struct bladerf_quick_tune *')
            rc_rx = libbladeRF.bladerf_get_quick_tune(dev_ptr, bladerf.CHANNEL_RX(0), qr)
            t3 = time.time()
            rc_tx = libbladeRF.bladerf_get_quick_tune(dev_ptr, bladerf.CHANNEL_TX(0), qt_val)
            t4 = time.time()

            if rc_rx != 0 or rc_tx != 0:
                raise RuntimeError(
                    f"bladerf_get_quick_tune failed at {f_int/1e6:.0f} MHz "
                    f"(rx_rc={rc_rx}, tx_rc={rc_tx}) after {len(qt_rx)} profiles built — "
                    f"likely exhausted the device's {MAX_QUICK_TUNE_PROFILES}-profile "
                    f"fastlock table. A device reset reclaims the budget (fresh "
                    f"bladerf_open() resets the on-device counter to 0)."
                )
            qt_rx.append(qr)
            qt_tx.append(qt_val)

            # One line per profile: each of the 4 transactions timed separately.
            _log_timing(f"  Profile {len(qt_rx):3d}/{len(freqs)}",
                       freq=f"{f_int/1e9:.3f}GHz",
                       set_freq_rx=_format_duration(t1 - t0),
                       set_freq_tx=_format_duration(t2 - t1),
                       get_qt_rx=_format_duration(t3 - t2),
                       get_qt_tx=_format_duration(t4 - t3),
                       total=_format_duration(t4 - t0))

        table_duration = time.time() - table_start
        self._qt_master_freqs = freqs
        self._qt_master_rx = qt_rx
        self._qt_master_tx = qt_tx
        _log_timing("QT TABLE BUILD DONE",
                   profiles=len(freqs),
                   usb_round_trips=f"{len(freqs)*4} (2x set_freq + 2x get_qt per profile)",
                   total_time=_format_duration(table_duration),
                   per_profile=_format_duration(table_duration / len(freqs)))
        _log_separator('═')

    def invalidate_quick_tune_table(self):
        """Drop the cached master table so it regenerates on next use.

        Call after a device.reset() — a fresh device open can leave the AD9361 in a
        state where previously-captured quick_tune profiles no longer apply.
        """
        self._qt_master_freqs = None
        self._qt_master_rx = None
        self._qt_master_tx = None

    def _build_sweep_grid(self, start, stop, step):
        """Compute this sweep's frequencies and, if available, their quick_tune profiles
        by indexing straight into the master table — no regeneration needed regardless
        of what start/stop/step are, as long as they're on the master's 10 MHz grid
        within its range (set_params() guarantees this via _snap_freq/_snap_step).
        """
        num_steps = int((stop - start) / step) + 1

        if self._use_quick_tune and self._qt_master_freqs is not None:
            n_master = len(self._qt_master_freqs)
            start_idx = int(round((start - QT_MASTER_START_FREQ) / QT_MASTER_STEP))
            step_idx = max(1, int(round(step / QT_MASTER_STEP)))
            idxs = np.clip(start_idx + np.arange(num_steps) * step_idx, 0, n_master - 1)
            freqs = self._qt_master_freqs[idxs]
            qt_rx = [self._qt_master_rx[k] for k in idxs]
            qt_tx = [self._qt_master_tx[k] for k in idxs]
            return freqs, qt_rx, qt_tx

        freqs = (start + np.arange(num_steps) * step).astype(np.int64)
        return freqs, None, None

    def _configure_hardware(self):
        _log_separator('─')
        _log_timing("CONFIGURE HW START")

        t0 = time.time()
        # Pure Python attribute writes — NO device traffic happens here. The
        # values are pushed to the device below in _configure_channels_dual().
        self.driver.tx_gain = self.tx1_gain
        self.driver.rx_gain = self.rx1_gain
        self.driver.tx2_gain = self.tx2_gain
        self.driver.rx2_gain = self.rx2_gain
        self.driver.sample_rate = 10_000_000
        self.driver.bandwidth = 8_000_000
        _log_timing("  ... Pi CPU ONLY (no USB)",
                   what="stage_params_in_driver_RAM",
                   tx1_gain=self.tx1_gain, rx1_gain=self.rx1_gain,
                   tx2_gain=self.tx2_gain, rx2_gain=self.rx2_gain,
                   sample_rate="10Msps", bandwidth="8MHz")

        t1 = time.time()
        self.driver.set_waveform('cw', offset=100_000, amplitude=0.9)
        _log_timing("  ... Pi CPU ONLY (no USB)",
                   what="generate_CW_waveform_in_RAM",
                   offset="100kHz", amplitude=0.9,
                   time=_format_duration(time.time() - t1))

        if self._use_quick_tune:
            self._ensure_master_quick_tune_table()

        # Real device traffic: the driver logs each individual libbladeRF call
        # (one "USB |" line per channel with per-call times).
        t2 = time.time()
        self.driver._configure_channels_dual()
        _log_timing("  configure_dual_channels total",
                   time=_format_duration(time.time() - t2))

        t3 = time.time()
        self.driver.set_tuning_mode_fpga()
        self._fpga_tuning = True
        _log_timing("  set_tuning_mode=FPGA total",
                   note="retunes_now_use_scheduled_pkt_retune2_path",
                   time=_format_duration(time.time() - t3))

        _log_timing("CONFIGURE HW DONE",
                   total=_format_duration(time.time() - t0))
        _log_separator('─')

    def _start_tx_rx(self):
        _log_separator('─')
        _log_timing("START TX/RX STREAMING")

        self._rx_cond = threading.Condition()
        self._rx_latest = None
        self._rx_seq = 0
        n = 4096
        t = np.arange(n, dtype=np.float64) / self.driver.sample_rate
        self._ref_tone = np.exp(-1j * 2 * np.pi * self.driver.cw_offset * t)
        self._ref_tone_scaled = self._ref_tone / 2047.0

        # The driver logs each real transaction (sync_config, enable_module x2)
        # with individual times as "USB |" lines.
        t1 = time.time()
        self.driver.start_tx_dual()
        _log_timing("  start_tx_dual total",
                   time=_format_duration(time.time() - t1),
                   note="TX_thread_now_streaming_bulk_OUT_continuously")

        t2 = time.time()
        self.driver.start_rx_dual(self._rx_capture, num_samples=n)
        _log_timing("  start_rx_dual total",
                   time=_format_duration(time.time() - t2),
                   buffer_size=f"{n}_samples={n*2*2*2}_bytes")

        _log_timing("  ... WAITING 50ms for stream to spin up")
        time.sleep(0.05)
        _log_timing("  first RX buffers arrived",
                   buffers_in_50ms=self._rx_seq)

        t3 = time.time()
        self.driver.reapply_dual_gains()
        _log_timing("  reapply_dual_gains total",
                   what="enable_module resets gain state",
                   time=_format_duration(time.time() - t3))

        _log_timing("TX/RX STREAMING ACTIVE",
                   tx="Pi>>>bladeRF EP0x01 Bulk OUT (continuous, TX thread)",
                   rx="bladeRF>>>Pi EP0x81 Bulk IN (continuous, ~0.41ms/buffer)")
        _log_separator('─')

    def _apply_gains(self):
        dev_ptr = self.driver.device.dev[0]
        times = []
        rcs = []
        for ch, gain in ((bladerf.CHANNEL_TX(0), self.tx1_gain),
                         (bladerf.CHANNEL_TX(1), self.tx2_gain),
                         (bladerf.CHANNEL_RX(0), self.rx1_gain),
                         (bladerf.CHANNEL_RX(1), self.rx2_gain)):
            t0 = time.time()
            rcs.append(libbladeRF.bladerf_set_gain(dev_ptr, ch, int(gain)))
            times.append(time.time() - t0)
        _log_timing("APPLY GAINS (mid-sweep)",
                   tx0=_format_duration(times[0]), tx1=_format_duration(times[1]),
                   rx0=_format_duration(times[2]), rx1=_format_duration(times[3]))
        if any(rc != 0 for rc in rcs):
            _log_timing("*** APPLY GAINS FAILED", rcs=rcs)
        self._gains_dirty = False

    def _stop_tx_rx(self):
        _log_separator('─')
        _log_timing("STOP TX/RX STREAMING")

        # The disable_module transactions happen inside the stream threads'
        # finally blocks; the driver logs them there with real times.
        t1 = time.time()
        self.driver.stop_rx_dual()
        _log_timing("  stop_rx_dual total (join RX thread + disables)",
                   time=_format_duration(time.time() - t1))

        t2 = time.time()
        self.driver.stop_tx_dual()
        _log_timing("  stop_tx_dual total (join TX thread + disables)",
                   time=_format_duration(time.time() - t2))

        t3 = time.time()
        self.driver._configure_channels()
        _log_timing("  restore single-channel config total",
                   time=_format_duration(time.time() - t3))

        _log_timing("TX/RX STREAMING STOPPED — bladeRF fully idle, no USB traffic")
        _log_separator('─')



    def _rx_capture(self, rx1_iq, rx2_iq):
        with self._rx_cond:
            self._rx_latest = (rx1_iq, rx2_iq)
            self._rx_seq += 1
            self._rx_cond.notify_all()

    def _perform_sweep(self):
        with self._lock:
            start = self.start_freq
            stop = self.stop_freq
            step = self.step_size
            num_buffers = self.num_buffers
            settle_count = self.settle_count

        freqs, qt_rx, qt_tx = self._build_sweep_grid(start, stop, step)
        num_steps = len(freqs)

        _log_separator('═')
        _log_timing("SWEEP START",
                   start=f"{start/1e9:.3f}GHz",
                   stop=f"{stop/1e9:.3f}GHz",
                   step=f"{step/1e6:.0f}MHz",
                   num_steps=num_steps,
                   num_buffers=num_buffers,
                   settle_count=settle_count)

        sweep_start = time.time()

        def progress(i):
            if self._callback and i % 10 == 0:
                self._callback({
                    'type': 'progress',
                    'step': i,
                    'total': num_steps,
                    'freq_mhz': freqs[i] / 1e6,
                })

        capture_start = time.time()
        h_cal, dropped_steps = self._sweep_core(freqs, qt_rx, qt_tx, num_buffers, settle_count, progress)
        capture_duration = time.time() - capture_start

        if h_cal is None:
            return None

        _log_timing("CAPTURE COMPLETE",
                   duration=_format_duration(capture_duration),
                   valid_steps=f"{num_steps-dropped_steps}/{num_steps}")

        if dropped_steps > 0:
            print(f"[sfcw] WARNING: {dropped_steps}/{num_steps} steps had incomplete captures")

        postproc_start = time.time()
        result = self._process_h_cal(h_cal)
        postproc_duration = time.time() - postproc_start

        total_duration = time.time() - sweep_start

        _log_timing("SWEEP END",
                   total=_format_duration(total_duration),
                   capture=_format_duration(capture_duration),
                   postproc=_format_duration(postproc_duration))
        _log_separator('═')

        return result

    def _perform_sweep_raw(self):
        """Like _perform_sweep but returns raw h_cal array for averaging."""
        with self._lock:
            start = self.start_freq
            stop = self.stop_freq
            step = self.step_size
            num_buffers = self.num_buffers
            settle_count = self.settle_count

        freqs, qt_rx, qt_tx = self._build_sweep_grid(start, stop, step)

        h_cal, _ = self._sweep_core(freqs, qt_rx, qt_tx, num_buffers, settle_count)
        return h_cal

    def _sweep_core(self, freqs, qt_rx, qt_tx, num_buffers, settle_count, progress_cb=None):
        """Sweep loop: retune, settle, capture num_buffers buffers and average them
        (noise averaging — 10*log10(num_buffers) dB of SNR for free), reference-divide.

        settle_count is the number of RX buffer arrivals to wait, after issuing a
        retune, before trusting the data — see CLAUDE.md's Sweep Timing / quick-tune
        regression note for why this matters and shouldn't be dropped carelessly.

        Returns (h_cal, dropped_steps) or (None, 0) if stopped.
        """
        num_steps = len(freqs)
        h_signal = np.zeros(num_steps, dtype=np.complex128)
        h_reference = np.zeros(num_steps, dtype=np.complex128)

        dev_ptr = self.driver.device.dev[0]
        tx_ch = bladerf.CHANNEL_TX(0)
        rx_ch = bladerf.CHANNEL_RX(0)

        use_qt = qt_rx is not None
        ref_tone_scaled = self._ref_tone_scaled
        rx_cond = self._rx_cond
        stop_event = self._stop_event

        dropped_steps = 0
        retune_failures = 0

        # Verbose per-packet detail only for these steps; every step still gets
        # a one-line summary with each transaction's time.
        log_steps = {0, 1, 2, 3, 50, 150, num_steps // 2, num_steps - 1}
        total_wait = settle_count + num_buffers

        def issue_retune(idx):
            """Send the RX+TX retune commands for freqs[idx].

            Each call is one 16-byte packet out and one ACK back; timed and
            rc-checked individually. Returns (rx_duration, tx_duration)."""
            nonlocal retune_failures
            f_r = int(freqs[idx])
            # Minimal send/ACK markers: the line's own wall-clock prefix IS the
            # measurement — printed at the exact moment of each event.
            _log_timing(f"  Step {idx:3d} >>> RX retune CMD SENT", freq=f"{f_r/1e9:.3f}GHz")
            t0 = time.time()
            if use_qt:
                rc1 = libbladeRF.bladerf_schedule_retune(dev_ptr, rx_ch, 0, f_r, qt_rx[idx])
            else:
                rc1 = libbladeRF.bladerf_set_frequency(dev_ptr, rx_ch, f_r)
            t1 = time.time()
            _log_timing(f"  Step {idx:3d} <<< RX retune ACK RECEIVED",
                       took=_format_duration(t1 - t0))
            _log_timing(f"  Step {idx:3d} >>> TX retune CMD SENT")
            t_tx = time.time()
            if use_qt:
                rc2 = libbladeRF.bladerf_schedule_retune(dev_ptr, tx_ch, 0, f_r, qt_tx[idx])
            else:
                rc2 = libbladeRF.bladerf_set_frequency(dev_ptr, tx_ch, f_r)
            t2 = time.time()
            _log_timing(f"  Step {idx:3d} <<< TX retune ACK RECEIVED",
                       took=_format_duration(t2 - t_tx))

            if rc1 != 0 or rc2 != 0:
                # Always logged, every step: that step's data is at the WRONG
                # frequency (the Nios rejected the retune, e.g. full queue).
                retune_failures += 1
                _log_timing(f"  Step {idx:3d} *** RETUNE FAILED",
                           freq=f"{f_r/1e9:.3f}GHz",
                           rx_rc=rc1, tx_rc=rc2,
                           note="step_data_captured_at_previous_frequency")

            # (rx_duration, tx_duration, rx_ack_wallclock, tx_ack_wallclock)
            return t1 - t0, t2 - t_tx, t1, t2

        # Pipelining: step 0's retunes are issued here; every later step's are
        # issued at the END of the previous step — right after its capture,
        # before its compute — so the ~2-3ms of USB command latency overlaps
        # the Pi-side NumPy work instead of extending the step. seq_at_retune
        # snapshots the buffer counter at retune time so buffers arriving
        # during the compute already count toward the next step's settling.
        pending_retune = issue_retune(0)
        seq_at_retune = self._rx_seq

        for i in range(num_steps):
            if stop_event.is_set():
                return None, 0

            step_start = time.time()
            f = int(freqs[i])
            # This step's own retune stats: durations and when their ACKs
            # landed (measured back when issue_retune ran, possibly during
            # the previous step's window).
            cur_rx_dur, cur_tx_dur, cur_rx_ack, cur_tx_ack = pending_retune

            # Wait for settling packets (bladeRF streams continuously on EP0x81, Pi just counts arrivals)
            if i in log_steps:
                _log_timing(f"  Step {i:3d} ... Pi WAITING (no USB sent)",
                           waiting_for=f"{settle_count}_buffers_on_EP0x81",
                           note="bladeRF_streaming_continuously_Pi_just_counts")

            wait_start = time.time()
            last_pkt_time = wait_start


            with rx_cond:
                target_seq = seq_at_retune + settle_count
                pkt_num = 1
                all_bufs_sig = [] if i in log_steps else None
                all_bufs_ref = [] if i in log_steps else None
                while self._rx_seq < target_seq:
                    if not rx_cond.wait(timeout=1.0):
                        break
                    # Log each settling packet and save it for comparison
                    if i in log_steps and self._rx_seq <= target_seq:
                        now = time.time()
                        pkt_delta = now - last_pkt_time
                        _log_timing(f"  Step {i:3d}      Pi<<<bladeRF [EP0x81] pkt {pkt_num:2d}/{total_wait}",
                                   type="SETTLE(discard)",
                                   size=f"{4096*2*2*2}B",
                                   dt=_format_duration(pkt_delta))
                        last_pkt_time = now
                        pkt_num += 1
                        all_bufs_sig.append(np.array(self._rx_latest[0], copy=True))
                        all_bufs_ref.append(np.array(self._rx_latest[1], copy=True))

                settle_end = time.time()
                if i in log_steps:
                    _log_timing(f"  Step {i:3d}      SETTLE DONE ({settle_count} buffers discarded)",
                               time=_format_duration(settle_end - wait_start))
                    _log_timing(f"  Step {i:3d}      NOW KEEPING next {num_buffers} buffers from EP0x81",
                               note="noise_averaging")

                sig_bufs = []
                ref_bufs = []
                last_seq = self._rx_seq
                for buf_idx in range(num_buffers):
                    while self._rx_seq <= last_seq:
                        if not rx_cond.wait(timeout=1.0):
                            break
                    if self._rx_seq <= last_seq:
                        break
                    last_seq = self._rx_seq
                    sig_bufs.append(self._rx_latest[0])
                    ref_bufs.append(self._rx_latest[1])

                    # Log capture packets and save for comparison
                    if i in log_steps:
                        now = time.time()
                        pkt_delta = now - last_pkt_time
                        _log_timing(f"  Step {i:3d}      Pi<<<bladeRF [EP0x81] pkt {pkt_num:2d}/{total_wait}",
                                   type="CAPTURE(keep)",
                                   buf=f"{buf_idx+1}/{num_buffers}",
                                   size=f"{4096*2*2*2}B",
                                   dt=_format_duration(pkt_delta))
                        last_pkt_time = now
                        pkt_num += 1
                        all_bufs_sig.append(np.array(self._rx_latest[0], copy=True))
                        all_bufs_ref.append(np.array(self._rx_latest[1], copy=True))

            wait_end = time.time()
            wait_duration = wait_end - wait_start

            # Printed BEFORE the pipelined retunes so log line order matches
            # transaction order (buffers done -> next retune -> compute).
            if i in log_steps:
                _log_timing(f"  Step {i:3d}      ALL {total_wait} EP0x81 BUFFERS DONE",
                           total_time=_format_duration(wait_duration),
                           data=f"{total_wait*4096*2*2*2}B_received_from_bladeRF")

            # PIPELINE: this step's data is safely captured — send the NEXT
            # step's retunes immediately, before this step's compute, so their
            # USB latency runs concurrently with the NumPy work below.
            if i + 1 < num_steps and not stop_event.is_set():
                next_retune = issue_retune(i + 1)
                seq_at_retune = self._rx_seq
            else:
                next_retune = (0.0, 0.0, 0.0, 0.0)

            if i in log_steps:
                # Compare all 14 buffers side-by-side to check for duplicates
                if all_bufs_sig and len(all_bufs_sig) >= 2:
                    _log_timing(f"  Step {i:3d} ... BUFFER COMPARISON (all {len(all_bufs_sig)} buffers)")
                    duplicates = []
                    for a_idx in range(len(all_bufs_sig)):
                        for b_idx in range(a_idx + 1, len(all_bufs_sig)):
                            if np.array_equal(all_bufs_sig[a_idx], all_bufs_sig[b_idx]):
                                duplicates.append((a_idx + 1, b_idx + 1))
                    if duplicates:
                        dup_str = ', '.join(f"{a}=={b}" for a, b in duplicates)
                        _log_timing(f"  Step {i:3d}      *** DUPLICATES FOUND ***",
                                   pairs=dup_str,
                                   note="bladeRF_sent_same_data_twice")
                    else:
                        _log_timing(f"  Step {i:3d}      ALL UNIQUE",
                                   note=f"all_{len(all_bufs_sig)}_buffers_are_different")
                    # Also show how much each buffer differs from the last capture buffer
                    last_buf = all_bufs_sig[-1].astype(np.float64)
                    diffs = []
                    for b_idx in range(len(all_bufs_sig) - 1):
                        diff = np.mean(np.abs(all_bufs_sig[b_idx].astype(np.float64) - last_buf))
                        diffs.append(f"{b_idx+1}:{diff:.1f}")
                    _log_timing(f"  Step {i:3d}      MEAN_ABS_DIFF vs last",
                               buffers=f"[{', '.join(diffs)}]",
                               note="0=identical")

            # Compute IQ at this frequency (Pi-only, no bladeRF communication)
            if i in log_steps:
                _log_timing(f"  Step {i:3d} ... PROCESSING (Pi CPU)",
                           operation="extract_IQ_via_ref_tone_mixing",
                           num_buffers=len(sig_bufs),
                           note="no_USB_here")

            compute_start = time.time()

            if sig_bufs:
                sig_arr = np.asarray(sig_bufs, dtype=np.float64)
                ref_arr = np.asarray(ref_bufs, dtype=np.float64)
                sig_cplx = (sig_arr[:, 0::2] + 1j * sig_arr[:, 1::2]) * ref_tone_scaled
                ref_cplx = (ref_arr[:, 0::2] + 1j * ref_arr[:, 1::2]) * ref_tone_scaled
                h_signal[i] = sig_cplx.mean()
                h_reference[i] = ref_cplx.mean()
            else:
                dropped_steps += 1
            compute_end = time.time()
            compute_duration = compute_end - compute_start

            step_end = time.time()
            step_total = step_end - step_start
            settle_duration = settle_end - wait_start
            capture_duration = wait_end - settle_end

            # This step's own retune cost COUNTED FROM step_start: how much of
            # the [cmd sent .. ACK received] window fell inside this step. With
            # pipelining the ACKs landed during the previous step, so this is
            # 0 — the step never waited for its own tuning.
            rx_in_step = max(0.0, min(cur_rx_dur, cur_rx_ack - step_start))
            tx_in_step = max(0.0, min(cur_tx_dur, cur_tx_ack - step_start))

            # One line for EVERY step: each transaction's time as this step
            # experienced it. next_retune is the time spent in THIS window
            # sending the following step's commands (the pipelined cost).
            _log_timing(f"  Step {i:3d} {f/1e9:.3f}GHz",
                       ok="yes" if sig_bufs else "NO_DATA",
                       retune_rx=_format_duration(rx_in_step),
                       retune_tx=_format_duration(tx_in_step),
                       settle=_format_duration(settle_duration),
                       capture=_format_duration(capture_duration),
                       next_retune=_format_duration(next_retune[0] + next_retune[1]),
                       compute=_format_duration(compute_duration),
                       total=_format_duration(step_total))

            if i in log_steps:
                _log_timing(f"  Step {i:3d}     USB summary: 2x Retune OUT(16B)+ACK(16B) + {total_wait}x Bulk IN({4096*2*2*2}B)")
                # Add blank line between steps for readability
                if i < num_steps - 1:
                    print(flush=True)

            if progress_cb and i % 10 == 0:
                progress_cb(i)

            # Hand over the pipelined retune stats measured after this step's
            # capture — they belong to step i+1's summary line.
            pending_retune = next_retune

        # Reference division (phase correction)
        _log_separator('─')
        _log_timing("REF DIVISION START", valid_steps=f"{num_steps-dropped_steps}/{num_steps}")
        ref_start = time.time()
        ref_mag = np.abs(h_reference)
        valid = ref_mag > 1e-10
        h_cal = np.zeros(num_steps, dtype=np.complex128)
        h_cal[valid] = h_signal[valid] / h_reference[valid]
        _log_timing("REF DIVISION DONE", time=_format_duration(time.time() - ref_start))

        if retune_failures > 0:
            _log_timing("*** SWEEP HAD RETUNE FAILURES",
                       failed_steps=f"{retune_failures}/{num_steps}",
                       note="those_steps_captured_at_wrong_frequency")

        return h_cal, dropped_steps

    def _process_h_cal(self, h_cal):
        num_steps = len(h_cal)
        start = self.start_freq
        stop = self.stop_freq
        step = self.step_size

        _log_timing("POST-PROC START", operation="phase_unwrap")
        t1 = time.time()
        phase_raw = np.angle(h_cal)
        phase_unwrapped = np.unwrap(phase_raw)
        coeffs = np.polyfit(np.arange(num_steps), phase_unwrapped, 1)
        residuals = phase_unwrapped - np.polyval(coeffs, np.arange(num_steps))
        phase_std = float(np.std(residuals))
        _log_timing("  Phase unwrap done", time=_format_duration(time.time() - t1))

        _log_timing("  Starting IFFT", nfft=num_steps*4)
        t2 = time.time()
        window = np.hanning(num_steps)
        h_windowed = h_cal * window
        nfft = num_steps * 4
        range_profile = np.fft.ifft(h_windowed, n=nfft)
        magnitude_db = 20 * np.log10(np.abs(range_profile) + 1e-12)
        _log_timing("  IFFT done", time=_format_duration(time.time() - t2))

        t3 = time.time()
        max_range = SPEED_OF_LIGHT / (2 * step)
        distances = np.arange(nfft) / nfft * max_range - self.range_offset

        half = nfft // 2
        magnitude_db = magnitude_db[:half]
        distances = distances[:half]

        valid = distances >= 0
        distances = distances[valid]
        magnitude_db = magnitude_db[valid]

        h_cal_real = h_cal.real.tolist()
        h_cal_imag = h_cal.imag.tolist()
        _log_timing("  Array formatting done", time=_format_duration(time.time() - t3))

        return {
            'type': 'range_profile',
            'distances': distances.tolist(),
            'magnitudes': magnitude_db.tolist(),
            'h_cal_real': [round(v, 8) for v in h_cal_real],
            'h_cal_imag': [round(v, 8) for v in h_cal_imag],
            'range_resolution': SPEED_OF_LIGHT / (2 * (stop - start)),
            'unambiguous_range': max_range,
            'displayed_range_max': max_range / 2 - self.range_offset,
            'num_steps': num_steps,
            'step_size': step,
            'range_offset': self.range_offset,
            'timestamp': time.time(),
            'phase_coherence': {
                'phase_std_rad': phase_std,
                'phase_std_deg': float(np.degrees(phase_std)),
                'coherent': phase_std < 0.3,
                'slope_rad_per_step': float(coeffs[0]),
            },
        }
