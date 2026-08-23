# FPGA Signal Flow - ADC to USB with Timestamp

## Complete Signal Path:

```
AD9361 ADC → RX Module → RX FIFO → FX3 GPIF → USB → Pi
    ↓            ↓          ↓          ↓
  (WHAT)      (WHAT)    (WHAT)    (MERGES)
                ↓                     ↑
              (WHEN) → META FIFO ─────┘
```

---

## Detailed Flow:

### 1. **AD9361 ADC Chip** (Analog → Digital)
```vhdl
ad9361_adc_i0_data[15:0]  ← I sample (WHAT)
ad9361_adc_q0_data[15:0]  ← Q sample (WHAT)
```
**Wire values:** Actual radio signal, -2048 to +2047

---

### 2. **RX Module** (bladerf-hosted.vhd line 625)
```vhdl
U_rx : entity work.rx
    port map (
        ...
        -- ADC data in
        adc_data_i => ad9361.ch(0).adc.i.data,
        adc_data_q => ad9361.ch(0).adc.q.data,
        
        -- Sample FIFO out (WHAT)
        sample_fifo_write => rx_sample_fifo.wreq,
        sample_fifo_data  => rx_sample_fifo.wdata,  ← I/Q samples
        
        -- Meta FIFO out (WHEN)
        meta_fifo_write => rx_meta_fifo.wreq,
        meta_fifo_data  => rx_meta_fifo.wdata,      ← Timestamp
        meta_enable     => meta_en_rx               ← Our change!
    );
```

**What happens:**
- RX module receives ADC I/Q samples
- RX module has a **timestamp counter** inside
- When `meta_enable` = '1' (our change!):
  - Writes I/Q samples → `rx_sample_fifo`
  - Writes timestamp → `rx_meta_fifo` (separate!)

---

### 3. **Two Parallel FIFOs** (bladerf-hosted.vhd lines 69, 73)

```
┌─────────────────┐        ┌─────────────────┐
│ rx_sample_fifo  │        │ rx_meta_fifo    │
│                 │        │                 │
│ [I,Q,I,Q,I,Q]   │        │ [timestamp]     │
│ [I,Q,I,Q,I,Q]   │        │ [flags]         │
│ [I,Q,I,Q,I,Q]   │        │ [status]        │
│ ...16,384 pairs │        │ [reserved]      │
└────────┬────────┘        └────────┬────────┘
         │                          │
         └──────────┬───────────────┘
                    ↓
              FX3 GPIF Controller
```

**Key point:** Timestamp and samples flow in **separate FIFOs**!

---

### 4. **FX3 GPIF Controller** (bladerf-hosted.vhd line 285)
```vhdl
U_fx3_gpif : entity work.fx3_gpif
    port map (
        ...
        meta_enable         => meta_en_pclk,  ← Controls merging
        
        -- RX Sample FIFO (WHAT)
        rx_fifo_read        => rx_sample_fifo.rreq,
        rx_fifo_data        => rx_sample_fifo.rdata,  ← [I,Q,I,Q...]
        
        -- RX Meta FIFO (WHEN)  
        rx_meta_fifo_read   => rx_meta_fifo.rreq,
        rx_meta_fifo_data   => rx_meta_fifo.rdata,    ← [timestamp,flags,status]
        
        -- USB output
        gpif_out            => fx3_gpif_out           ← Merged packet!
    );
```

**This is where timestamp and samples get MERGED:**

```
When meta_enable = '1':
    Read 16 bytes from rx_meta_fifo    → [timestamp, flags, status]
    Read N samples from rx_sample_fifo → [I,Q,I,Q,I,Q...]
    Prepend metadata to samples
    Send to USB: [metadata][samples]

When meta_enable = '0':
    Skip rx_meta_fifo
    Read only rx_sample_fifo
    Send to USB: [samples]
```

---

### 5. **Physical USB Connection**
```vhdl
fx3_gpif[31:0] → Physical pins → USB PHY → USB cable → Pi
```

**Line 338-342:**
```vhdl
if( fx3_gpif_oe = '1' ) then
    fx3_gpif <= fx3_gpif_out;  ← Drive USB pins with merged data
```

---

### 6. **Pi Receives**
```python
self.device.sync_rx(buf, num_samples)

# buf now contains:
# [16 bytes metadata] + [I/Q samples from rx_sample_fifo]
```

---

## Where Our Change Happens:

### **Before our change** (RESET_LEVEL = '0'):
```vhdl
U_sync_meta_en_rx : entity work.synchronizer
    generic map (
        RESET_LEVEL => '0'  ← Starts disabled
    )
```
**Result:**
- `meta_en_rx` = '0' at power-on
- RX module **doesn't write to rx_meta_fifo**
- FX3 GPIF **doesn't prepend metadata**
- USB packet = only samples, no timestamp

---

### **After our change** (RESET_LEVEL = '1'):
```vhdl
U_sync_meta_en_rx : entity work.synchronizer
    generic map (
        RESET_LEVEL => '1'  ← Starts ENABLED
    )
```
**Result:**
- `meta_en_rx` = '1' at power-on
- RX module **writes timestamp to rx_meta_fifo**
- FX3 GPIF **prepends 16-byte metadata header**
- USB packet = [timestamp+flags+status][samples]

---

## Signal Timeline (Microsecond Scale):

```
Time:  0 μs         0.5 μs        1.0 μs        1.5 μs
       ↓            ↓             ↓             ↓
ADC:  [I=1234,     [I=2048,      [I=-567,      [I=123,
       Q=-567]      Q=321]        Q=1900]       Q=-999]
       ↓            ↓             ↓             ↓
RX:   Write to     Write to      Write to      Write to
      sample_fifo  sample_fifo   sample_fifo   sample_fifo
       ↓                                         ↓
      Write timestamp=10,000,000 to meta_fifo  (once per buffer)
                                  ↓
                            FX3 GPIF merges:
                            [timestamp=10,000,000]
                            [I=1234,Q=-567]
                            [I=2048,Q=321]
                            [I=-567,Q=1900]
                            [I=123,Q=-999]
                                  ↓
                            USB packet → Pi
```

---

## Summary - Answering Your Question:

**Q: "Does the timestamp tell the value of the adc_data_i wire?"**

**A: No!**

| What | Where | Contains |
|------|-------|----------|
| **adc_data_i wire** | AD9361 → RX module | **WHAT** - Actual signal values (I/Q) |
| **rx_sample_fifo** | RX module → FX3 GPIF | **WHAT** - I/Q samples (adc_data values) |
| **rx_meta_fifo** | RX module → FX3 GPIF | **WHEN** - Timestamp counter |
| **USB packet** | FX3 GPIF → Pi | Both merged: [WHEN][WHAT] |

**The timestamp tells you WHEN those ADC values were captured, not WHAT they are.**

**The I/Q samples in the buffer ARE the adc_data_i/q wire values!**

---

## Verification After FPGA Recompile:

Once you flash the new .rbf file:

```python
# You will see
[bladerf] Packet #1 | timestamp: 10,000,000 | status=0x00000000
              ▲                     ▲
              │                     └─ From rx_meta_fifo (WHEN)
              │
              └─ Buffer contains adc_data_i/q values (WHAT)
```

Both are in the packet, but they mean different things!
