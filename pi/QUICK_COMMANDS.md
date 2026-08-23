# Quick Reference Commands for Raspberry Pi

## Kill/Stop Program

### **Fastest way:**
```bash
# If running in terminal, press:
Ctrl + C
```

### **Kill by script name:**
```bash
# Graceful stop
pkill -f start.py

# Force kill
pkill -9 -f start.py
```

### **Use kill script:**
```bash
cd ~/version_bluestar/pi
./kill_radar.sh
```

### **Kill all Python:**
```bash
pkill python3
```

---

## Start Program

### **Start radar system:**
```bash
cd ~/version_bluestar/pi
python3 start.py
```

### **Start in background:**
```bash
cd ~/version_bluestar/pi
nohup python3 start.py > radar.log 2>&1 &
```

### **Start with auto-restart:**
```bash
# Install tmux if needed: sudo apt install tmux
tmux new -s radar
cd ~/version_bluestar/pi
python3 start.py

# Detach: Ctrl+B then D
# Reattach: tmux attach -t radar
```

---

## Check What's Running

### **See Python processes:**
```bash
ps aux | grep python3
```

### **See specific script:**
```bash
pgrep -a python3 | grep start.py
```

### **See network ports:**
```bash
sudo netstat -tulpn | grep LISTEN
```

### **See bladeRF status:**
```bash
bladeRF-cli -p
bladeRF-cli -e "version"
```

---

## Restart Program

### **Quick restart:**
```bash
pkill -f start.py && sleep 1 && cd ~/version_bluestar/pi && python3 start.py
```

### **Using kill script:**
```bash
cd ~/version_bluestar/pi
./kill_radar.sh
python3 start.py
```

---

## Logs and Debugging

### **View live output:**
```bash
# If running in background with nohup:
tail -f ~/version_bluestar/pi/radar.log

# Follow live:
tail -f nohup.out
```

### **Check for errors:**
```bash
grep -i error ~/version_bluestar/pi/radar.log
grep -i exception ~/version_bluestar/pi/radar.log
```

### **Save output to file:**
```bash
cd ~/version_bluestar/pi
python3 start.py 2>&1 | tee radar_$(date +%Y%m%d_%H%M%S).log
```

---

## Flash FPGA

### **Load new FPGA image (temporary):**
```bash
bladeRF-cli -l ~/version_bluestar/fpga_builds/hosted_timestamp_enabled.rbf
```

### **Write to Flash (permanent):**
```bash
bladeRF-cli -L ~/version_bluestar/fpga_builds/hosted_timestamp_enabled.rbf
```

### **Check FPGA version:**
```bash
bladeRF-cli -e "version"
```

---

## System Status

### **Check CPU/memory:**
```bash
htop
# Or
top
```

### **Check disk space:**
```bash
df -h
```

### **Check temperature:**
```bash
vcgencmd measure_temp
```

### **Check USB devices:**
```bash
lsusb
```

---

## Network

### **Check IP address:**
```bash
hostname -I
```

### **Test connectivity to groundstation:**
```bash
ping <groundstation_ip>
```

### **Check if ports are open:**
```bash
sudo netstat -tulpn | grep 9000
sudo netstat -tulpn | grep 9001
sudo netstat -tulpn | grep 9002
```

---

## Update Code from GitHub

### **Pull latest changes:**
```bash
cd ~/version_bluestar
git pull origin main
```

### **Check what changed:**
```bash
cd ~/version_bluestar
git log --oneline -10
git diff HEAD~1
```

---

## Emergency Commands

### **System crashed, can't SSH:**
```bash
# Hard reboot (power cycle)
# Unplug power, wait 5 seconds, plug back in
```

### **Process won't die:**
```bash
sudo kill -9 <PID>
```

### **bladeRF stuck:**
```bash
# Reset bladeRF
bladeRF-cli -d "*:instance=0" -e "clear"

# Or replug USB cable
```

### **Out of disk space:**
```bash
# Find large files
du -sh ~/* | sort -h

# Clean logs
rm -f ~/version_bluestar/pi/*.log
```

---

## Useful Aliases (Add to ~/.bashrc)

```bash
# Edit ~/.bashrc
nano ~/.bashrc

# Add these lines:
alias radar='cd ~/version_bluestar/pi && python3 start.py'
alias killradar='pkill -9 -f start.py'
alias radarlog='tail -f ~/version_bluestar/pi/radar.log'
alias radarstatus='ps aux | grep start.py | grep -v grep'

# Save and reload:
source ~/.bashrc

# Now you can use:
radar         # Start radar
killradar     # Stop radar
radarstatus   # Check if running
radarlog      # View live log
```

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl + C` | Stop running program |
| `Ctrl + Z` | Pause program (use `fg` to resume) |
| `Ctrl + D` | Exit terminal / End of input |
| `Ctrl + L` | Clear screen |
| `Ctrl + R` | Search command history |
| `Ctrl + A` | Move cursor to start of line |
| `Ctrl + E` | Move cursor to end of line |

---

## Common Issues

### **"Address already in use" error:**
```bash
# Find process using port
sudo netstat -tulpn | grep 9000

# Kill it
kill <PID>
```

### **"Permission denied" on bladeRF:**
```bash
# Add user to plugdev group
sudo usermod -a -G plugdev $USER

# Logout and login again
```

### **Python module not found:**
```bash
# Install missing module
pip3 install <module_name>
```

### **Can't connect to groundstation:**
```bash
# Check network
ping <groundstation_ip>

# Check firewall
sudo ufw status

# Check if service is running
ps aux | grep start.py
```

---

**Quick Kill: `pkill -9 -f start.py`**  
**Quick Start: `cd ~/version_bluestar/pi && python3 start.py`**  
**Quick Status: `ps aux | grep python3`**
