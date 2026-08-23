# Setup Instructions - Based on sfcw-default-range-offset Branch

## ✅ What Was Done

1. **Cloned from:** `https://github.com/StoneForge-Research/version0`
2. **Started from branch:** `sfcw-default-range-offset`
3. **Added all timestamp features on top**
4. **Changed remote to:** `https://github.com/DataDragoon/version_bluestar`
5. **Pushed to:** `DataDragoon/version_bluestar` sfcw-default-range-offset branch

**This repo now has:**
- ✅ All code from version0's sfcw-default-range-offset branch
- ✅ FPGA timestamp support (metadata enabled by default)
- ✅ Per-sample timestamp calculation
- ✅ Helper scripts (kill_radar.sh, etc.)
- ✅ Complete documentation
- ✅ FPGA build (hosted_timestamp_enabled.rbf)

---

## Clone on Raspberry Pi

### **Option 1: Use sfcw-default-range-offset Branch (RECOMMENDED)**

```bash
cd ~
git clone -b sfcw-default-range-offset https://github.com/DataDragoon/version_bluestar.git
cd version_bluestar
```

This gets you the sfcw-default-range-offset branch with all timestamp features!

### **Option 2: Clone and Switch Branch**

```bash
cd ~
git clone https://github.com/DataDragoon/version_bluestar.git
cd version_bluestar
git checkout sfcw-default-range-offset
```

---

## Verify Branch

```bash
cd ~/version_bluestar
git branch
# Output should show: * sfcw-default-range-offset

git log --oneline -5
# Should show: "Add FPGA timestamp support..." as latest commit
```

---

## Flash FPGA

```bash
cd ~/version_bluestar
bladeRF-cli -l fpga_builds/hosted_timestamp_enabled.rbf
```

---

## Run

```bash
cd ~/version_bluestar/pi
python3 start.py
```

---

## Available Branches

```bash
git branch -a
```

**You should see:**
- `sfcw-default-range-offset` (current) ← USE THIS
- `origin/sfcw-default-range-offset`
- `origin/main` (old, different code)

---

## What's Different from main Branch

The **sfcw-default-range-offset** branch has:
- Latest SFCW optimizations from StoneForge-Research
- Fixed num buffers
- Editable settle buffers  
- Full quick tune table generation
- Pinned amplitude limits in SFCW display
- **PLUS all timestamp features on top**

The **main** branch is older code (before these SFCW improvements).

---

## Repository Structure

```
StoneForge-Research/version0 (sfcw-default-range-offset)
              ↓
           (cloned)
              ↓
  version_bluestar_new (local)
              ↓
        (added timestamps)
              ↓
  DataDragoon/version_bluestar (sfcw-default-range-offset)
```

---

## Important Files Added

### FPGA:
- `fpga_builds/hosted_timestamp_enabled.rbf` (13 MB)
- `fpga_builds/README.md`

### Driver:
- Modified `pi/radar/bladerf_driver.py` (timestamp parsing)

### Tools:
- `pi/radar/per_sample_timestamps.py`
- `pi/radar/timestamp_example.py`
- `pi/radar/enable_timestamps.py`

### Scripts:
- `pi/kill_radar.sh`
- `pi/QUICK_COMMANDS.md`

### Docs:
- `docs/FPGA_SIGNAL_FLOW_TIMESTAMP.md`
- `docs/PER_SAMPLE_TIMESTAMPS.md`
- `docs/TIMESTAMP_VS_ADC_DATA.md`

### Info:
- `REPOSITORY_INFO.md`
- `SETUP_INSTRUCTIONS.md` (this file)

---

## Quick Start

```bash
# On Pi
cd ~
git clone -b sfcw-default-range-offset https://github.com/DataDragoon/version_bluestar.git
cd version_bluestar

# Flash FPGA
bladeRF-cli -l fpga_builds/hosted_timestamp_enabled.rbf

# Run
cd pi
python3 start.py
```

**You'll see:**
```
[bladerf] Packet #1 | timestamp: 10,000,000 | status=0x00000000
[bladerf] Packet #2 | timestamp: 10,016,384 | status=0x00000000
...
```

---

## Branches Explained

| Branch | What It Has | Use? |
|--------|-------------|------|
| **sfcw-default-range-offset** | Latest SFCW code + timestamps | ✅ YES |
| main | Older code (pre-SFCW improvements) | ❌ NO |
| fpga_branch | Old experimental FPGA work | ❌ NO |

**Always use:** `sfcw-default-range-offset`

---

## Update from GitHub

```bash
cd ~/version_bluestar
git pull origin sfcw-default-range-offset
```

---

**Repository:** https://github.com/DataDragoon/version_bluestar  
**Branch:** sfcw-default-range-offset  
**Based on:** StoneForge-Research/version0 sfcw-default-range-offset  
**Created:** 2026-08-23
