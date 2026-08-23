"""
Enable FPGA timestamps in bladeRF - NO FPGA recompilation needed!

The bladeRF FPGA already has timestamp functionality built-in.
You just need to enable metadata format when configuring sync.
"""

import bladerf
from bladerf._bladerf import Format

# ==============================================================================
# SOLUTION: Change format from SC16_Q11 to SC16_Q11_META
# ==============================================================================

# OLD CODE (no timestamps):
# device.sync_config(
#     layout=ChannelLayout.RX_X1,
#     fmt=Format.SC16_Q11,        # ← Regular format
#     ...
# )

# NEW CODE (with timestamps):
device.sync_config(
    layout=ChannelLayout.RX_X1,
    fmt=Format.SC16_Q11_META,  # ← Metadata format (includes timestamps!)
    num_buffers=16,
    buffer_size=4096,
    num_transfers=8,
    stream_timeout=3500
)

# ==============================================================================
# When receiving, samples now include metadata header:
# ==============================================================================
#
# Metadata structure (16 bytes prepended to each buffer):
#   Offset 0x00: uint64_t timestamp  (FPGA sample counter)
#   Offset 0x08: uint32_t flags
#   Offset 0x0c: uint32_t status
#
# The timestamp increments at sample rate - this is what you wanted!

# ==============================================================================
# Example: Parse metadata from RX buffer
# ==============================================================================

import struct
import numpy as np

def parse_rx_with_metadata(buf, num_samples):
    """
    Parse RX buffer that includes metadata header.

    buf: bytearray received from sync_rx (with SC16_Q11_META format)
    num_samples: number of I/Q samples (NOT including metadata)

    Returns: (timestamp, flags, status, iq_samples)
    """
    # First 16 bytes are metadata
    metadata = buf[:16]

    # Parse metadata header
    timestamp = struct.unpack('<Q', metadata[0:8])[0]   # uint64_t
    flags = struct.unpack('<I', metadata[8:12])[0]      # uint32_t
    status = struct.unpack('<I', metadata[12:16])[0]    # uint32_t

    # Remaining bytes are I/Q samples
    sample_bytes = buf[16:]
    iq = np.frombuffer(sample_bytes, dtype=np.int16)

    return timestamp, flags, status, iq


# ==============================================================================
# Example usage in your SFCW code
# ==============================================================================

def rx_with_timestamps():
    """Example showing how to receive samples with timestamps."""

    dev = bladerf.BladeRF()

    # Configure with metadata format
    dev.sync_config(
        layout=bladerf.ChannelLayout.RX_X1,
        fmt=Format.SC16_Q11_META,  # ← KEY: Enable metadata
        num_buffers=16,
        buffer_size=4096,
        num_transfers=8,
        stream_timeout=3500
    )

    dev.enable_module(bladerf.CHANNEL_RX(0), True)

    # Allocate buffer including space for metadata header (16 bytes)
    num_samples = 16384
    metadata_size = 16
    buffer_size = metadata_size + (num_samples * 2 * 2)  # 16 + samples * (I+Q) * 2bytes
    buf = bytearray(buffer_size)

    # Receive samples
    dev.sync_rx(buf, num_samples)

    # Parse timestamp and samples
    timestamp, flags, status, iq_samples = parse_rx_with_metadata(buf, num_samples)

    print(f"FPGA Timestamp: {timestamp:,}")
    print(f"Flags: 0x{flags:08x}")
    print(f"Status: 0x{status:08x}")
    print(f"Samples: {len(iq_samples)//2} I/Q pairs")

    dev.enable_module(bladerf.CHANNEL_RX(0), False)
    dev.close()

# ==============================================================================
# SIMPLE FIX for your bladerf_driver.py:
# ==============================================================================
#
# In bladerf_driver.py, change line ~242:
#
# OLD:
#     self.device.sync_config(
#         layout=ChannelLayout.RX_X1,
#         fmt=Format.SC16_Q11,        # ← Change this
#         ...
#     )
#
# NEW:
#     self.device.sync_config(
#         layout=ChannelLayout.RX_X1,
#         fmt=Format.SC16_Q11_META,   # ← To this
#         ...
#     )
#
# Then modify your _rx_loop to parse the metadata header!
#
# ==============================================================================

"""
SUMMARY:

✅ Timestamps already exist in FPGA hardware
✅ No FPGA recompilation needed
✅ No VHDL changes needed
✅ Just change sync_config format parameter
✅ Parse 16-byte metadata header from RX buffers

The FPGA timestamp counter runs at sample rate and is embedded in every
RX buffer automatically when you use Format.SC16_Q11_META!
"""
