"""
Generate per-sample timestamps from buffer metadata.

Since the FPGA timestamp counter increments by 1 per sample,
we can calculate the exact timestamp for every sample.
"""

import struct
import numpy as np


def rx_with_per_sample_timestamps(device, num_samples):
    """
    Receive samples and generate timestamp for EACH sample.

    Returns:
        timestamps: array of uint64, one per sample
        i_samples: array of int16
        q_samples: array of int16
    """
    import bladerf

    # Allocate buffer with metadata
    buf = bytearray(16 + num_samples * 2 * 2)

    # Receive
    device.sync_rx(buf, num_samples)

    # Parse metadata header
    buffer_timestamp = struct.unpack('<Q', buf[0:8])[0]
    flags = struct.unpack('<I', buf[8:12])[0]
    status = struct.unpack('<I', buf[12:16])[0]

    # Parse I/Q samples
    iq = np.frombuffer(buf[16:], dtype=np.int16)
    i_samples = iq[0::2]
    q_samples = iq[1::2]

    # Generate per-sample timestamps
    # Timestamp counter increments by 1 for each sample
    timestamps = np.arange(
        buffer_timestamp,
        buffer_timestamp + num_samples,
        dtype=np.uint64
    )

    return timestamps, i_samples, q_samples, flags, status


# ============================================================================
# Example usage
# ============================================================================

def example():
    import bladerf
    from bladerf._bladerf import Format, ChannelLayout

    dev = bladerf.BladeRF()

    # Configure with metadata
    dev.sync_config(
        layout=ChannelLayout.RX_X1,
        fmt=Format.SC16_Q11_META,
        num_buffers=16,
        buffer_size=4096,
        num_transfers=8,
        stream_timeout=3500
    )

    dev.enable_module(bladerf.CHANNEL_RX(0), True)

    # Receive with per-sample timestamps
    timestamps, i_samples, q_samples, flags, status = \
        rx_with_per_sample_timestamps(dev, num_samples=16384)

    # Now you have timestamp for EVERY sample!
    print(f"Sample 0: timestamp={timestamps[0]:,}, I={i_samples[0]}, Q={q_samples[0]}")
    print(f"Sample 1: timestamp={timestamps[1]:,}, I={i_samples[1]}, Q={q_samples[1]}")
    print(f"Sample 2: timestamp={timestamps[2]:,}, I={i_samples[2]}, Q={q_samples[2]}")

    # Output:
    # Sample 0: timestamp=10,000,000, I=1234, Q=-567
    # Sample 1: timestamp=10,000,001, I=2048, Q=321
    # Sample 2: timestamp=10,000,002, I=-567, Q=1900

    dev.enable_module(bladerf.CHANNEL_RX(0), False)
    dev.close()


# ============================================================================
# Save to CSV with per-sample timestamps
# ============================================================================

def save_with_timestamps(timestamps, i_samples, q_samples, filename):
    """Save samples with their exact timestamps to CSV."""
    import csv

    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'I', 'Q', 'time_seconds'])

        sample_rate = 2_000_000  # 2 MHz

        for ts, i, q in zip(timestamps, i_samples, q_samples):
            time_sec = ts / sample_rate
            writer.writerow([ts, i, q, f'{time_sec:.9f}'])

    print(f"Saved {len(timestamps)} samples with timestamps to {filename}")


# ============================================================================
# Example output format:
# ============================================================================
"""
timestamp,I,Q,time_seconds
10000000,1234,-567,5.000000000
10000001,2048,321,5.000000500
10000002,-567,1900,5.000001000
10000003,123,-999,5.000001500
...
"""


# ============================================================================
# Track signal flow with exact timing
# ============================================================================

def track_signal_flow():
    """
    Show how adc_data_i wire values map to exact timestamps.
    """

    # Example: received buffer
    buffer_timestamp = 10_000_000
    i_samples = np.array([1234, 2048, -567, 123, 890, -1234])

    sample_rate = 2_000_000  # 2 MHz
    sample_period_ns = 1e9 / sample_rate  # 500 ns

    print("Wire value flow with timestamps:\n")
    print("FPGA Time (ns)  |  Timestamp  |  adc_data_i  |  Wire Event")
    print("-" * 70)

    for idx, i_val in enumerate(i_samples):
        ts = buffer_timestamp + idx
        time_ns = ts * sample_period_ns

        print(f"{time_ns:14.1f}  |  {ts:10,}  |  {i_val:6}       |  ADC samples wire")

    # Output:
    # FPGA Time (ns)  |  Timestamp  |  adc_data_i  |  Wire Event
    # ----------------------------------------------------------------------
    #      5000000.0  |  10,000,000  |    1234       |  ADC samples wire
    #      5000500.0  |  10,000,001  |    2048       |  ADC samples wire
    #      5001000.0  |  10,000,002  |    -567       |  ADC samples wire
    #      5001500.0  |  10,000,003  |     123       |  ADC samples wire
    #      5002000.0  |  10,000,004  |     890       |  ADC samples wire
    #      5002500.0  |  10,000,005  |   -1234       |  ADC samples wire


# ============================================================================
# Correlate wire values across signal flow stages
# ============================================================================

def correlate_signal_stages():
    """
    Show the same wire value at different FPGA stages with timestamps.
    """

    # Stages in FPGA (same sample, different stages)
    timestamp = 10_000_000
    adc_value_i = 1234

    print(f"\nTracking one sample (I={adc_value_i}) through FPGA:\n")

    stages = [
        (0, "ad9361_adc_i0_data wire", "ADC chip output"),
        (2, "rx.adc_data_i", "RX module input"),
        (5, "rx_sample_fifo.wdata", "Written to sample FIFO"),
        (10, "fx3_gpif.rx_fifo_data", "Read by FX3 controller"),
        (50, "fx3_gpif_out", "On USB pins"),
    ]

    sample_rate = 2_000_000

    for clocks_later, stage_name, description in stages:
        stage_time_ns = (timestamp / sample_rate * 1e9) + (clocks_later * 5)  # 200 MHz clock = 5ns

        print(f"  {stage_time_ns:10.0f} ns | {stage_name:25s} | {description}")
        print(f"               Value: I={adc_value_i}")
        print()


# ============================================================================
# Real-time timestamp monitoring
# ============================================================================

def monitor_with_timestamps():
    """
    Monitor RX stream and print timestamp for each interesting sample.
    """
    import bladerf
    from bladerf._bladerf import Format, ChannelLayout

    dev = bladerf.BladeRF()
    dev.sync_config(
        layout=ChannelLayout.RX_X1,
        fmt=Format.SC16_Q11_META,
        num_buffers=16,
        buffer_size=4096,
        num_transfers=8,
        stream_timeout=3500
    )

    dev.enable_module(bladerf.CHANNEL_RX(0), True)

    print("Monitoring for strong signals...\n")

    try:
        while True:
            timestamps, i_samples, q_samples, flags, status = \
                rx_with_per_sample_timestamps(dev, 16384)

            # Find strong signals
            magnitude = np.sqrt(i_samples**2 + q_samples**2)
            strong_indices = np.where(magnitude > 1500)[0]

            for idx in strong_indices[:5]:  # Print first 5 strong signals
                print(f"Strong signal at timestamp {timestamps[idx]:,}: "
                      f"I={i_samples[idx]}, Q={q_samples[idx]}, "
                      f"mag={magnitude[idx]:.0f}")

    except KeyboardInterrupt:
        pass

    dev.enable_module(bladerf.CHANNEL_RX(0), False)
    dev.close()


if __name__ == '__main__':
    # Run examples
    track_signal_flow()
    correlate_signal_stages()
