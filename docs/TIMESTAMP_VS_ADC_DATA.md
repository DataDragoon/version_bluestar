# Timestamp vs ADC Data - What's the Difference?

## Quick Answer:

- **Timestamp** = **WHEN** the data was captured (a counter)
- **ADC data** = **WHAT** was captured (the actual signal values)

---

## FPGA Signal Flow:

```
AD9361 ADC Chip → FPGA Wires → FIFO → USB → Pi
     ↓
  ad9361.ch(0).adc.i.data  ← 16-bit I value (WHAT)
  ad9361.ch(0).adc.q.data  ← 16-bit Q value (WHAT)
                              ↓
                        RX Module packs:
                        - Timestamp (WHEN)
                        - I/Q samples (WHAT)
                              ↓
                          USB packet
```

---

## In the FPGA Hardware:

### ADC Data Wires (bladerf-hosted.vhdl lines 404-414):
```vhdl
ad9361_adc_i0_data => ad9361.ch(0).adc.i.data,  -- 16-bit I sample
ad9361_adc_q0_data => ad9361.ch(0).adc.q.data,  -- 16-bit Q sample
ad9361_adc_i1_data => ad9361.ch(1).adc.i.data,  -- 16-bit I sample (CH1)
ad9361_adc_q1_data => ad9361.ch(1).adc.q.data,  -- 16-bit Q sample (CH1)
```

**These wires carry the ACTUAL radio signal values:**
- Range: -2048 to +2047 (12-bit ADC scaled to 16-bit)
- Updates at sample rate (e.g., 2 MHz = every 0.5 microseconds)
- Example values: `I=1234, Q=-567` = one complex sample

---

## What the RX Buffer Contains:

```python
# Structure of one RX buffer:
┌─────────────────────────────────────────────────────────────┐
│ Byte 0-7:   Timestamp = 10,016,384                          │  ← WHEN
│ Byte 8-11:  Flags = 0x00000000                              │
│ Byte 12-15: Status = 0x00000000                             │
├─────────────────────────────────────────────────────────────┤
│ Byte 16-17:    I[0] = 1234   ← ad9361.adc.i.data sample 1   │  ← WHAT
│ Byte 18-19:    Q[0] = -567   ← ad9361.adc.q.data sample 1   │
│ Byte 20-21:    I[1] = 2048   ← ad9361.adc.i.data sample 2   │
│ Byte 22-23:    Q[1] = -123   ← ad9361.adc.q.data sample 2   │
│ ...                                                          │
│ Byte N-1:      Q[16383] = 456  ← last sample                │
└─────────────────────────────────────────────────────────────┘
```

---

## Example: Understanding One Packet

**FPGA at sample #10,016,384:**

1. **ADC wire values at this instant:**
   - `ad9361.ch(0).adc.i.data` = 1234  ← Signal I value
   - `ad9361.ch(0).adc.q.data` = -567  ← Signal Q value

2. **Timestamp counter:**
   - `timestamp` = 10,016,384  ← Sample number (WHEN)

3. **What gets sent to Pi:**
   ```
   [Timestamp: 10,016,384] [I:1234, Q:-567] [I:2048, Q:-123] ... 16,384 samples
       ▲                         ▲
       WHEN                      WHAT (adc_data values)
   ```

---

## In Python Code:

```python
# Receive buffer
self.device.sync_rx(buf, num_samples)

# Parse WHEN (timestamp)
timestamp = struct.unpack('<Q', buf[0:8])[0]
print(f"Captured at sample #{timestamp:,}")
# Output: Captured at sample #10,016,384

# Parse WHAT (ADC data)
iq = np.frombuffer(buf[16:], dtype=np.int16)
i_samples = iq[0::2]  # ad9361.adc.i.data values
q_samples = iq[1::2]  # ad9361.adc.q.data values

print(f"First I/Q sample: I={i_samples[0]}, Q={q_samples[0]}")
# Output: First I/Q sample: I=1234, Q=-567
#         ▲
#         These ARE the adc_data_i wire values!
```

---

## What You DON'T Get:

**The timestamp does NOT show:**
- ❌ Individual wire value at a specific clock cycle
- ❌ `ad9361.adc.i.data` wire changing every clock
- ❌ Internal FPGA signals between modules

**The timestamp only shows:**
- ✅ When the FIRST sample in the buffer was captured
- ✅ A counter that increments by 1 per sample

---

## Real-World Example:

### Scenario: Receiving 8 packets

```bash
[bladerf] Packet #1 | timestamp: 10,000,000
   Contains: 16,384 I/Q samples (ad9361.adc.i/q.data values)
   From sample #10,000,000 to #10,016,383

[bladerf] Packet #2 | timestamp: 10,016,384
   Contains: 16,384 I/Q samples (ad9361.adc.i/q.data values)
   From sample #10,016,384 to #10,032,767

...

[bladerf] Packet #8 | timestamp: 10,114,688
   Contains: 16,384 I/Q samples (ad9361.adc.i/q.data values)
   From sample #10,114,688 to #10,131,071
```

**Each packet gives you:**
- **1 timestamp** = when this packet's data started
- **16,384 I/Q pairs** = the actual ADC wire values

---

## Converting Timestamp to Time:

```python
sample_rate = 2_000_000  # 2 MHz

# Timestamp → wall-clock time (relative to FPGA power-on)
time_seconds = timestamp / sample_rate

# Example
timestamp = 10_016_384
time_seconds = 10_016_384 / 2_000_000 = 5.008192 seconds
```

**Meaning:** This packet contains ADC samples that were captured 5.008 seconds after the FPGA was powered on.

---

## Summary Table:

| Field | Type | What It Shows | Example |
|-------|------|---------------|---------|
| **Timestamp** | 64-bit counter | **WHEN** samples were captured | 10,016,384 |
| **Flags** | 32-bit bitfield | Special conditions | 0x00000000 |
| **Status** | 32-bit bitfield | Error flags | 0x00000000 |
| **I/Q samples** | 16-bit signed ints | **WHAT** was captured (ADC wire values) | [1234, -567, 2048...] |

---

## Key Point:

**The timestamp tells you WHEN the ADC data was captured.**

**The I/Q samples ARE the ADC data itself** (the values from `ad9361.adc.i.data` and `ad9361.adc.q.data` wires).

Both are needed:
- **Timestamp** → synchronize/correlate events
- **I/Q samples** → process the actual signal
