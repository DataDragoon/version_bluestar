"""
Example: How to use FPGA timestamps for timing analysis
"""

# Example: 8 packets received
timestamps = [
    10_000_000,  # Packet 1
    10_016_384,  # Packet 2
    10_032_768,  # Packet 3
    10_049_152,  # Packet 4
    10_065_536,  # Packet 5
    10_081_920,  # Packet 6
    10_098_304,  # Packet 7
    10_114_688,  # Packet 8
]

sample_rate = 2_000_000  # 2 MHz

# ============================================================================
# 1. Time of first packet (relative to FPGA power-on)
# ============================================================================
first_packet_time = timestamps[0] / sample_rate
print(f"First packet captured at: {first_packet_time:.6f} seconds")
# Output: First packet captured at: 5.000000 seconds

# ============================================================================
# 2. Time of last packet
# ============================================================================
last_packet_time = timestamps[-1] / sample_rate
print(f"Last packet captured at: {last_packet_time:.6f} seconds")
# Output: Last packet captured at: 5.057344 seconds

# ============================================================================
# 3. Total duration for 8 packets
# ============================================================================
duration = (timestamps[-1] - timestamps[0]) / sample_rate
print(f"Total duration: {duration*1000:.3f} milliseconds")
# Output: Total duration: 57.344 milliseconds

# ============================================================================
# 4. Time between packets (inter-packet gap)
# ============================================================================
for i in range(1, len(timestamps)):
    gap_samples = timestamps[i] - timestamps[i-1]
    gap_ms = (gap_samples / sample_rate) * 1000
    print(f"Packet {i} to {i+1}: {gap_ms:.3f} ms ({gap_samples:,} samples)")

# Output:
# Packet 1 to 2: 8.192 ms (16,384 samples)
# Packet 2 to 3: 8.192 ms (16,384 samples)
# Packet 3 to 4: 8.192 ms (16,384 samples)
# ...

# ============================================================================
# 5. Detect dropped packets
# ============================================================================
expected_gap = 16_384  # Your buffer size

for i in range(1, len(timestamps)):
    actual_gap = timestamps[i] - timestamps[i-1]
    if actual_gap != expected_gap:
        dropped = actual_gap - expected_gap
        print(f"⚠️  Between packet {i-1} and {i}: {dropped:,} samples dropped!")

# ============================================================================
# 6. Command-to-first-packet delay (requires time.time())
# ============================================================================
import time

# When sending command, save time
command_sent_time = time.time()  # e.g., 1724425180.5

# When first packet arrives
first_timestamp = 10_000_000
first_arrival_time = time.time()  # e.g., 1724425180.505

# Delay = wall-clock time difference (command → first packet)
delay_ms = (first_arrival_time - command_sent_time) * 1000
print(f"Command to first packet delay: {delay_ms:.3f} ms")
# Output: Command to first packet delay: 5.000 ms

# ============================================================================
# 7. Align multiple sweeps using timestamps
# ============================================================================

# Sweep 1
sweep1_start_timestamp = 10_000_000
sweep1_end_timestamp = 10_114_688

# Sweep 2 (started 1 second later)
sweep2_start_timestamp = 12_000_000  # +2,000,000 samples = +1 second
sweep2_end_timestamp = 12_114_688

# Calculate time between sweep starts
time_between_sweeps = (sweep2_start_timestamp - sweep1_start_timestamp) / sample_rate
print(f"Time between sweeps: {time_between_sweeps:.3f} seconds")
# Output: Time between sweeps: 1.000 seconds

# ============================================================================
# Summary
# ============================================================================
print("\n" + "="*60)
print("Summary:")
print("="*60)
print(f"Total packets:      {len(timestamps)}")
print(f"First timestamp:    {timestamps[0]:,}")
print(f"Last timestamp:     {timestamps[-1]:,}")
print(f"Total samples:      {timestamps[-1] - timestamps[0]:,}")
print(f"Duration:           {duration*1000:.3f} ms")
print(f"Samples per packet: {timestamps[1] - timestamps[0]:,}")
print(f"Packet rate:        {1000/((timestamps[1]-timestamps[0])/sample_rate*1000):.1f} Hz")
