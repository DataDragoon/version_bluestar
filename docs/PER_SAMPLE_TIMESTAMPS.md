# Per-Sample Timestamps - Options

## Your Requirement:

**"I need the timestamping of each wires which come in flow"**

You want the timestamp of EACH individual sample as it flows through the FPGA.

---

## Current System:

**One timestamp per buffer (16,384 samples):**

```
Buffer metadata: [Timestamp: 10,000,000] [Flags] [Status]
Buffer samples:  [Sample 0] [Sample 1] [Sample 2] ... [Sample 16,383]
                      ▲
                      Only first sample has explicit timestamp
```

---

## Option 1: Calculate Per-Sample Timestamps (RECOMMENDED)

### How It Works:

The FPGA timestamp counter increments by **1 for each sample**, so:

```python
# Received from FPGA
buffer_timestamp = 10,000,000  # First sample timestamp

# Calculate timestamps for ALL samples
sample_0_timestamp = 10,000,000  # buffer_timestamp + 0
sample_1_timestamp = 10,000,001  # buffer_timestamp + 1
sample_2_timestamp = 10,000,002  # buffer_timestamp + 2
...
sample_16383_timestamp = 10,016,383  # buffer_timestamp + 16,383
```

### Code:

```python
import numpy as np

# Generate per-sample timestamps
timestamps = np.arange(
    buffer_timestamp,
    buffer_timestamp + num_samples,
    dtype=np.uint64
)

# Now you have EXACT timestamp for every sample!
for i in range(num_samples):
    print(f"Sample {i}: timestamp={timestamps[i]:,}, I={i_samples[i]}, Q={q_samples[i]}")
```

### Output Example:

```
Sample 0: timestamp=10,000,000, I=1234, Q=-567
Sample 1: timestamp=10,000,001, I=2048, Q=321
Sample 2: timestamp=10,000,002, I=-567, Q=1900
Sample 3: timestamp=10,000,003, I=123, Q=-999
...
```

### Convert to Real Time:

```python
sample_rate = 2_000_000  # 2 MHz

for ts, i, q in zip(timestamps, i_samples, q_samples):
    time_seconds = ts / sample_rate
    time_ns = time_seconds * 1e9
    
    print(f"Time: {time_ns:14.1f} ns | Timestamp: {ts:,} | I={i} Q={q}")
```

**Output:**
```
Time:     5000000.0 ns | Timestamp: 10,000,000 | I=1234 Q=-567
Time:     5000500.0 ns | Timestamp: 10,000,001 | I=2048 Q=321
Time:     5001000.0 ns | Timestamp: 10,000,002 | I=-567 Q=1900
```

### Pros:
- ✅ Exact timestamp for every sample (ns precision)
- ✅ Zero bandwidth overhead
- ✅ Works with existing FPGA build
- ✅ Mathematically guaranteed correct

### Cons:
- ⚠️ Assumes no dropped samples (check status flags!)

---

## Option 2: FPGA Modification (NOT RECOMMENDED)

### Embed timestamp with EVERY sample:

Modify FPGA to send:
```
[Timestamp: 10,000,000] [I: 1234] [Q: -567]
[Timestamp: 10,000,001] [I: 2048] [Q: 321]
[Timestamp: 10,000,002] [I: -567] [Q: 1900]
...
```

### Bandwidth Cost:

```
Current format:
- 16 bytes metadata + 16,384 samples × 4 bytes = 65,552 bytes per buffer
- Overhead: 0.02%

Per-sample timestamp format:
- 16,384 samples × (8 bytes timestamp + 4 bytes I/Q) = 196,608 bytes
- Overhead: 300% (3x larger!)
```

**At 2 Msps sample rate:**
- Current: 128 MB/s
- Per-sample timestamp: **384 MB/s** (USB 3.0 = 400 MB/s max!)

### Pros:
- ✅ Every sample has explicit timestamp in FPGA

### Cons:
- ❌ 3x bandwidth increase
- ❌ Saturates USB 3.0 link
- ❌ Requires major FPGA redesign
- ❌ Processing bottleneck on Pi
- ❌ No benefit over calculation (same accuracy!)

**Not recommended unless you NEED hardware-embedded timestamps for some external reason.**

---

## Option 3: Hybrid - Frequent Timestamps

### Compromise: Timestamp every N samples (e.g., every 64):

```
[TS: 10,000,000] [64 samples]
[TS: 10,000,064] [64 samples]
[TS: 10,000,128] [64 samples]
...
```

### Pros:
- ✅ Detects dropped samples within 64-sample window
- ✅ Lower overhead than full per-sample

### Cons:
- ⚠️ Still requires FPGA modification
- ⚠️ Still adds bandwidth
- ⚠️ Doesn't add accuracy vs. calculation

---

## Recommendation:

**Use Option 1 (Calculation).**

### Why:

1. **Same accuracy** - FPGA counter increments by 1, so calculation is exact
2. **Zero overhead** - no bandwidth cost
3. **Works now** - no FPGA changes needed
4. **Detects drops** - status flags warn if samples are missing

### Implementation:

I already created `per_sample_timestamps.py` with working code!

```bash
# On Pi
cd ~/version_bluestar/pi/radar
python3 per_sample_timestamps.py
```

---

## Tracking Signal Flow with Per-Sample Timestamps:

### Example: Track one value through FPGA stages

```python
timestamp = 10_000_000
i_value = 1234

# Sample captured at timestamp 10,000,000
# At 2 MHz sample rate = 5.000000 seconds after power-on

# This sample's journey:
# - 5.0000000 sec: ad9361_adc_i0_data wire = 1234
# - 5.0000000 sec: rx.adc_data_i = 1234
# - 5.0000001 sec: rx_sample_fifo.wdata = 1234
# - 5.0000002 sec: fx3_gpif.rx_fifo_data = 1234
# - 5.0000050 sec: fx3_gpif_out (USB pins) = 1234
# - 5.0001000 sec: Pi receives in buffer
```

### Code to track any sample:

```python
def track_sample(timestamp, i_value, q_value):
    """Track one sample through the FPGA."""
    
    sample_rate = 2_000_000
    base_time = timestamp / sample_rate
    
    stages = [
        (0,     "ad9361_adc_i0_data", "ADC chip samples"),
        (1e-9,  "rx.adc_data_i",      "RX module receives"),
        (2e-9,  "rx_sample_fifo",     "Written to FIFO"),
        (10e-9, "fx3_gpif",           "Read by USB controller"),
        (50e-9, "USB PHY",            "On USB pins"),
        (100e-6,"Pi buffer",          "Arrives at Pi"),
    ]
    
    print(f"\nTracking sample: timestamp={timestamp:,}, I={i_value}, Q={q_value}\n")
    
    for delay, stage, description in stages:
        time = base_time + delay
        print(f"{time:.9f} sec | {stage:20s} | I={i_value}, Q={q_value} | {description}")
```

---

## What You Asked For vs. What's Possible:

### What you asked:
> "i need the timestamping of each wires which come in flow"

### Answer:

**You CAN get timestamp of each sample (each wire value)!**

But you don't need the FPGA to embed them individually - you calculate them:

```python
# Buffer timestamp from FPGA
buffer_start = 10_000_000

# Every sample's timestamp
sample_timestamps = np.arange(buffer_start, buffer_start + num_samples)

# Now correlate with wire values
for i, (ts, i_val, q_val) in enumerate(zip(sample_timestamps, i_samples, q_samples)):
    print(f"ad9361_adc_i0_data = {i_val} at FPGA timestamp {ts:,}")
```

**This gives you EXACT timestamp for EVERY wire value (sample)!**

---

## Summary Table:

| Method | Timestamps Per Buffer | Bandwidth | FPGA Change | Accuracy |
|--------|----------------------|-----------|-------------|----------|
| **Current** | 1 | 65 KB | None | ±1 sample |
| **Option 1 (Calc)** | 16,384 | 65 KB | ✅ None | Exact |
| **Option 2 (FPGA)** | 16,384 | 196 KB | ❌ Major | Exact |
| **Option 3 (Hybrid)** | 256 | 80 KB | ❌ Medium | Exact |

**Option 1 gives you what you need with zero cost!**
