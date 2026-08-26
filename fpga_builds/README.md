# FPGA Builds for bladeRF

## ⚠️ CORRECTION (2026-08-26) — read this before the section below

**The "What It Does" description below is WRONG.** It documents a `RESET_LEVEL => '1'` edit
to the three `meta_en` synchronizers in `bladerf-hosted.vhd` (lines 802/813/824). That is
**not** the change in this .rbf, and it would not have worked anyway: all three instances
wire `reset => '0'`, so the reset branch is dead logic and `RESET_LEVEL` only sets a
power-up value that the Nios overwrites within 3 clocks via the `meta_sync` GPO.

**The actual change is one line in `rx.vhd:140`:**

```vhdl
-- stock
if( meta_en = '1' ) then
    timestamp_reset <= '0';

-- this .rbf
if( meta_en = '1' or rx_enable = '1' ) then
    timestamp_reset <= '0';
```

**What it really does:** `timestamp_reset` becomes `rx_ts_reset`, which is the RX
`time_tamer`'s `ts_reset`. Releasing it whenever RX is enabled does two things, not one:
1. the 64-bit sample counter free-runs, giving the Nios a time reference; and
2. **the tamer's compare/interrupt FSM leaves reset**, which is what makes
   `bladerf_schedule_retune()` actually function without `SC16_Q11_META`. With stock HDL
   and a non-META format, `tamer_schedule()` is a silent no-op — entries stick in
   `ENTRY_STATE_SCHEDULED` forever and the host eventually gets `QUEUE_FULL` with no
   indication of the cause.

**KNOWN GAP — TX is not patched.** `tx.vhd:110` carries the byte-identical
`if( meta_en = '1' )` and was left unchanged, so the **TX** tamer is still held in reset.
`pkt_retune2` schedules RX retunes on `RX_TAMER_IRQ` and TX retunes on `TX_TAMER_IRQ`, and
`sfcw_engine.py` retunes *both* channels per step — so on this image a scheduled sweep
would half-work: RX steps fire, TX steps never do. The mirror edit
(`or tx_enable = '1'` at `tx.vhd:110`) is needed to close it.

Note `rx_enable` is the correct signal to have used: it is the 3-FF synchronized copy of
`rx_enable_pclk` already in the `rx_clock` domain, so the edit introduces no CDC hazard.

---

## hosted_timestamp_enabled.rbf

**Built:** 2026-08-23  
**Size:** 13 MB  
**For:** bladeRF Micro (Cyclone V 5CEBA9F23C8)

### What It Does:

Enables **FPGA timestamp metadata by default** - no software configuration needed!

**Changes from stock FPGA:**
- Modified `bladerf-hosted.vhd` lines 802, 813, 824
- Changed `RESET_LEVEL => '0'` to `'1'` for metadata synchronizers
- Enables timestamp embedding at power-on

**Effect:**
- Every RX buffer includes 16-byte metadata header
- Header contains: 64-bit timestamp + 32-bit flags + 32-bit status
- Timestamp increments by 1 for each sample
- Works with `Format.SC16_Q11_META` in software

---

## How to Flash:

### Option 1: Temporary (RAM) - Safe for Testing

```bash
# Load to RAM (lost on power cycle)
bladeRF-cli -l fpga_builds/hosted_timestamp_enabled.rbf
```

**Use this first to test!**

### Option 2: Permanent (Flash) - After Testing

```bash
# Write to Flash (survives reboot)
bladeRF-cli -L fpga_builds/hosted_timestamp_enabled.rbf
```

**Only use after verifying it works in RAM mode!**

---

## Verify After Flashing:

```bash
# Check FPGA version
bladeRF-cli -e "version"

# Check device info
bladeRF-cli -e "info"
```

**Expected output:**
```
bladeRF-cli version:        1.x.x
libbladeRF version:         2.x.x
Firmware version:           2.4.0
FPGA version:               0.15.x (or custom)
```

---

## Software Requirements:

Your Pi code must use `Format.SC16_Q11_META` to parse timestamps:

```python
# In bladerf_driver.py (ALREADY DONE!)
self.device.sync_config(
    layout=ChannelLayout.RX_X1,
    fmt=Format.SC16_Q11_META,  # ← Enable metadata
    num_buffers=16,
    buffer_size=4096,
    num_transfers=8,
    stream_timeout=3500
)
```

**This is already implemented in `pi/radar/bladerf_driver.py`!**

---

## What You'll See:

**On Pi console when running SFCW:**

```bash
[bladerf] Packet #1 | timestamp: 10,000,000 | status=0x00000000
[bladerf] Packet #2 | timestamp: 10,016,384 | status=0x00000000
[bladerf] Packet #3 | timestamp: 10,032,768 | status=0x00000000
[bladerf] Packet #4 | timestamp: 10,049,152 | status=0x00000000
...
```

**Each timestamp shows:**
- FPGA sample counter (increments by 1 per sample)
- Timestamp gap = number of samples in buffer
- Convert to seconds: `timestamp / sample_rate`

**Example at 2 MHz sample rate:**
```
Timestamp 10,000,000 = 5.0 seconds after FPGA power-on
Timestamp 10,016,384 = 5.008192 seconds
Gap = 16,384 samples = 8.192 milliseconds
```

---

## Per-Sample Timestamps:

Since the FPGA counter increments by 1 per sample, you can calculate the exact timestamp for **every** sample:

```python
# Buffer timestamp (from metadata)
buffer_timestamp = 10_000_000

# Generate per-sample timestamps
import numpy as np
sample_timestamps = np.arange(
    buffer_timestamp,
    buffer_timestamp + num_samples,
    dtype=np.uint64
)

# Now you have timestamp for EVERY sample!
# Sample 0: timestamp = 10,000,000
# Sample 1: timestamp = 10,000,001
# Sample 2: timestamp = 10,000,002
# ...
```

**See `pi/radar/per_sample_timestamps.py` for examples.**

---

## Dropped Sample Detection:

The driver automatically detects dropped samples:

```bash
[bladerf] Packet #1 | timestamp: 10,000,000 | status=0x00000000
[bladerf] Packet #2 | timestamp: 10,016,384 | status=0x00000000
[bladerf] WARNING: 16,384 samples dropped!
[bladerf] Packet #3 | timestamp: 10,049,152 | status=0x00000000
                                     ▲
                     Should be 10,032,768, gap is 2× expected!
```

---

## Status Flags:

**status=0x00000000** = Good (no errors)

**If status bit 0 set (0x00000001):**
```bash
[bladerf] Packet #5 | timestamp: 10,065,536 | status=0x00000001
                                                            ▲
                                                  Overrun flag!
```

**Meaning:** FIFO overflow, samples were dropped by FPGA.

**Common causes:**
- Processing too slow
- USB congested
- CPU load too high

---

## Reverting to Stock FPGA:

To go back to original bladeRF FPGA:

```bash
# Download stock FPGA from Nuand
wget https://www.nuand.com/fpga/v0.15.0/hostedxA9.rbf

# Flash stock FPGA
bladeRF-cli -L hostedxA9.rbf
```

Or flash the bladeRF firmware package:
```bash
bladeRF-cli -f bladeRF_fw_latest.img
```

---

## Technical Details:

### FPGA Modification:

**File:** `bladeRF/hdl/fpga/platforms/bladerf-micro/vhdl/bladerf-hosted.vhd`

**Changes:**
```vhdl
-- Line 802: pclk domain synchronizer
U_sync_meta_en_pclk : entity work.synchronizer
    generic map (
        RESET_LEVEL => '1'  -- Was '0', now '1'
    )

-- Line 813: RX domain synchronizer  
U_sync_meta_en_rx : entity work.synchronizer
    generic map (
        RESET_LEVEL => '1'  -- Was '0', now '1'
    )

-- Line 824: TX domain synchronizer
U_sync_meta_en_tx : entity work.synchronizer
    generic map (
        RESET_LEVEL => '1'  -- Was '0', now '1'
    )
```

**Effect:**
- `meta_en_pclk`, `meta_en_rx`, `meta_en_tx` signals start at '1' instead of '0'
- RX module writes timestamp to `rx_meta_fifo` from power-on
- FX3 GPIF controller prepends metadata header automatically

### Signal Flow:

```
AD9361 ADC → RX Module → rx_sample_fifo (I/Q samples)
                    ↓
                rx_meta_fifo (timestamp)
                    ↓
            FX3 GPIF Controller (merges both)
                    ↓
                USB packet: [16 bytes metadata][I/Q samples]
```

### Metadata Structure:

```
Offset  Size  Field
------  ----  -----
0x00    8     timestamp (uint64_t, little-endian)
0x08    4     flags (uint32_t)
0x0C    4     status (uint32_t)
------
Total: 16 bytes
```

**Flags (0x08-0x0B):**
- Bit 0: `BLADERF_META_FLAG_TX_BURST_START`
- Bit 1: `BLADERF_META_FLAG_TX_BURST_END`
- Bit 2: `BLADERF_META_FLAG_TX_NOW`
- Bit 3: `BLADERF_META_FLAG_RX_NOW`

**Status (0x0C-0x0F):**
- Bit 0: `BLADERF_META_STATUS_OVERRUN` (FIFO overflow)
- Bit 1: `BLADERF_META_STATUS_UNDERRUN` (TX starved)

---

## Build Information:

**Toolchain:**
- Quartus Prime Lite 20.1.1 Build 720
- Target: Cyclone V 5CEBA9F23C8
- Build time: 11 minutes 24 seconds

**Resource Usage:**
- Logic ALMs: 6,748 / 113,560 (6%)
- Registers: 14,601
- Block Memory: 2,209,280 bits / 12,492,800 (18%)
- DSP Blocks: 8 / 342 (2%)
- PLLs: 3 / 8 (38%)

**Timing:**
- All timing constraints met (with 2 warnings)
- May be slightly unstable at full speed
- Tested stable in normal operation

---

## Troubleshooting:

### bladeRF not detected after flashing:

```bash
# Power cycle bladeRF
# Unplug USB, wait 5 seconds, plug back in

# Check if detected
bladeRF-cli -p
```

### Timestamps not appearing in output:

1. **Check FPGA is loaded:**
   ```bash
   bladeRF-cli -e "version"
   ```

2. **Check software is using SC16_Q11_META format:**
   ```python
   # In your code, verify:
   fmt=Format.SC16_Q11_META  # NOT Format.SC16_Q11
   ```

3. **Check buffer allocation includes metadata:**
   ```python
   # Buffer must be 16 bytes larger:
   buf = bytearray(16 + num_samples * 2 * 2)
   ```

### Wrong timestamp values:

**If timestamps are all zero:**
- FPGA may not have timestamp module enabled
- Check FPGA version, may need to reflash

**If timestamps are random:**
- Buffer parsing may be wrong
- Ensure little-endian unpacking: `struct.unpack('<Q', ...)`

**If timestamps jump unexpectedly:**
- This is CORRECT behavior after dropped samples
- Check status flags and system load

---

## Files in This Directory:

- `hosted_timestamp_enabled.rbf` - Modified FPGA image (this file)
- `README.md` - This documentation
- (Future builds will be added here)

---

## See Also:

- `docs/FPGA_SIGNAL_FLOW_TIMESTAMP.md` - Signal flow explanation
- `docs/PER_SAMPLE_TIMESTAMPS.md` - Per-sample timing guide
- `docs/TIMESTAMP_VS_ADC_DATA.md` - What timestamps show
- `pi/radar/per_sample_timestamps.py` - Example code
- `pi/radar/timestamp_example.py` - Timing calculations

---

**Last updated:** 2026-08-23  
**Tested on:** bladeRF Micro 2.0  
**Compatible with:** libbladeRF 2.x
