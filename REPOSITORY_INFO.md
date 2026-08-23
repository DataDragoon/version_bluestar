# Repository Information

## Origin

**version_bluestar** is based on (forked from):
```
https://github.com/StoneForge-Research/version0
```

## Current Repository

**Now maintained at:**
```
https://github.com/DataDragoon/version_bluestar
```

## Git History

Found in commit `cc8f77c`:
```
Merge branch 'sfcw-default-range-offset' of https://github.com/StoneForge-Research/version0 into sfcw-default-range-offset
```

This shows the repo was originally from StoneForge-Research/version0 and later moved/forked to DataDragoon/version_bluestar.

## To Clone on Raspberry Pi

### Current Active Repo (Recommended):
```bash
cd ~
git clone https://github.com/DataDragoon/version_bluestar.git
```

### Original Repo (If needed for reference):
```bash
cd ~
git clone https://github.com/StoneForge-Research/version0.git
```

## Relationship Between Repos

```
StoneForge-Research/version0 (original)
           ↓
       (forked/copied)
           ↓
DataDragoon/version_bluestar (current)
```

**Note:** All recent development (FPGA timestamps, per-sample timing, etc.) is in `DataDragoon/version_bluestar`.

## Recent Additions (Not in Original)

The following features were added to version_bluestar after it diverged from version0:

1. **FPGA Timestamp Support** (2026-08-23)
   - Modified FPGA with metadata enabled
   - Per-sample timestamp calculation
   - Packet tracking and drop detection
   - `fpga_builds/hosted_timestamp_enabled.rbf`

2. **Documentation** (2026-08-23)
   - `docs/FPGA_SIGNAL_FLOW_TIMESTAMP.md`
   - `docs/PER_SAMPLE_TIMESTAMPS.md`
   - `docs/TIMESTAMP_VS_ADC_DATA.md`
   - `fpga_builds/README.md`
   - `pi/QUICK_COMMANDS.md`

3. **Helper Scripts** (2026-08-23)
   - `pi/kill_radar.sh`
   - `pi/per_sample_timestamps.py`
   - `pi/timestamp_example.py`

4. **Modified bladeRF Driver** (2026-08-23)
   - `pi/radar/bladerf_driver.py` with timestamp parsing
   - Format.SC16_Q11_META support
   - Per-sample timestamp generation

## Branches

Check available branches:
```bash
cd ~/version_bluestar
git branch -a
```

Current branches visible in history:
- `main` (current)
- `sfcw-default-range-offset`
- `fpga_branch`

## Contact

- **Current Maintainer:** DataDragoon
- **Original Project:** StoneForge-Research

---

**For all new work, use:**
```
https://github.com/DataDragoon/version_bluestar.git
```
