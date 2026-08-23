#!/bin/bash
# Kill radar system gracefully

echo "Stopping radar system..."

# Kill Python processes
echo "Killing Python processes..."
pkill -f start.py
sleep 1

# Check if still running
if pgrep -f start.py > /dev/null; then
    echo "Force killing..."
    pkill -9 -f start.py
fi

# Kill any orphaned bladeRF processes
echo "Checking for bladeRF processes..."
pkill -f bladerf

echo "✓ Radar system stopped"

# Show what's still running (if anything)
if pgrep -f python3 > /dev/null; then
    echo ""
    echo "Other Python processes still running:"
    pgrep -a python3
fi
