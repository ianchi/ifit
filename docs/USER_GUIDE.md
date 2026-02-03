# iFit CLI Quick Reference Guide

Complete guide for using the iFit BLE command-line interface.

## Installation

```bash
# Install with poetry (recommended)
poetry install

# Install with server support (required for FTMS relay)
poetry install --extras server

# Or install with pip
pip install -e .
```

## Quick Start

The typical workflow is:

1. **Scan** for your device to find its address
2. **Activate** the device to get the activation code
3. **Use** the device with various commands

```bash
# 1. Find your device
ifit scan --code 1a2b

# 2. Auto-discover activation code
ifit activate AA:BB:CC:DD:EE:FF

# 3. Start using it
ifit monitor AA:BB:CC:DD:EE:FF 12345678
```

## Command Reference

### Discovery Commands

**Scan for devices:**

```bash
ifit scan                          # List all iFit devices
ifit scan --code 1a2b              # Find device by BLE code
ifit scan --timeout 20             # Custom scan timeout
```

**Auto-discover activation code:**

```bash
# Brute-force method (tries known codes)
ifit activate AA:BB:CC:DD:EE:FF              # Try all known codes
ifit activate AA:BB:CC:DD:EE:FF --max-attempts 10

# Intercept method (requires manufacturer app and bless package)
ifit discover-activation 1a2b                # Intercept from app
ifit discover-activation 1a2b --address AA:BB:CC:DD:EE:FF
ifit discover-activation 1a2b --timeout 60
```

### Information

**Show equipment info:**

```bash
ifit info AA:BB:CC:DD:EE:FF CODE       # Basic info
ifit info AA:BB:CC:DD:EE:FF CODE -v    # Verbose (capabilities, commands)
```

### Reading Values

```bash
ifit get AA:BB:CC:DD:EE:FF CODE                  # Read current values
ifit get AA:BB:CC:DD:EE:FF CODE Kph Incline      # Read specific characteristics
ifit get AA:BB:CC:DD:EE:FF CODE --json           # JSON output
```

### Writing Values

```bash
ifit set AA:BB:CC:DD:EE:FF CODE Kph=5.0          # Set speed to 5 km/h
ifit set AA:BB:CC:DD:EE:FF CODE Mode=1           # Start treadmill
ifit set AA:BB:CC:DD:EE:FF CODE Mode=0           # Stop treadmill
ifit set AA:BB:CC:DD:EE:FF CODE Kph=8.0 Incline=3.5   # Set multiple values
```

### Monitoring

```bash
ifit monitor AA:BB:CC:DD:EE:FF CODE              # Monitor with full access
ifit monitor AA:BB:CC:DD:EE:FF                   # Read-only mode (no code needed)
ifit monitor AA:BB:CC:DD:EE:FF CODE --interval 0.5   # Custom update interval
```

### FTMS Relay (for Zwift, TrainerRoad, etc.)

```bash
ifit relay AA:BB:CC:DD:EE:FF CODE                      # Start FTMS relay
ifit relay AA:BB:CC:DD:EE:FF CODE --name "My Treadmill"   # Custom BLE name
ifit relay AA:BB:CC:DD:EE:FF CODE --interval 1         # Custom update interval
```

## Complete Examples

### First Time Setup

```bash
# 1. Scan for your device (press connect button on treadmill to see BLE code)
ifit scan --code 1a2b

# Output:
# ✓ Found device:
#   Address: AA:BB:CC:DD:EE:FF
#   Name: iFit Treadmill
#   BLE Code: 1a2b

# 2. Get activation code automatically
ifit activate AA:BB:CC:DD:EE:FF

# Output:
# Trying activation codes for AA:BB:CC:DD:EE:FF...
# ✓ Found working activation code: 12345678

# 3. Test the connection
ifit info AA:BB:CC:DD:EE:FF 12345678 -v

# 4. Start monitoring
ifit monitor AA:BB:CC:DD:EE:FF 12345678
```

### Getting Your Activation Code

The activation code is an 8-character hex string required to control the equipment.

**Method 1: Auto-discovery (Recommended)**

```bash
ifit activate AA:BB:CC:DD:EE:FF
```

Tries known activation codes until one works. Fast and easy.

**Method 2: Intercept from manufacturer app (Advanced)**

```bash
ifit discover-activation 1a2b
```

Then open your manufacturer's app and connect to the equipment. The tool will intercept and capture the activation code.

**What codes do I need?**

- **BLE Code** (4 chars like "1a2b"): Shown on treadmill display when you press connect
- **Activation Code** (8 hex chars like "12345678"): Discovered automatically or from manufacturer app

### Quick Workout

```bash
# Set initial values and start
ifit set AA:BB:CC:DD:EE:FF 12345678 Kph=4 Incline=0
ifit set AA:BB:CC:DD:EE:FF 12345678 Mode=1

# Monitor in another terminal
ifit monitor AA:BB:CC:DD:EE:FF 12345678

# Adjust during workout
ifit set AA:BB:CC:DD:EE:FF 12345678 Kph=6.5
ifit set AA:BB:CC:DD:EE:FF 12345678 Incline=2

# Stop when done
ifit set AA:BB:CC:DD:EE:FF 12345678 Mode=0
```

### Use with Zwift

```bash
# Terminal 1: Start FTMS relay
ifit relay AA:BB:CC:DD:EE:FF 12345678 --name "My Treadmill"

# Terminal 2: Open Zwift
# In Zwift: Search for "My Treadmill" and connect as FTMS device
# Leave relay running while using Zwift
# Press Ctrl+C in Terminal 1 to stop when done
```

### Read-Only Monitoring (No Code Needed)

If you just want to see data without controlling the equipment:

```bash
# Monitor without activation code
ifit monitor AA:BB:CC:DD:EE:FF

# Shows: Speed, Incline, Distance, Heart Rate, Timer
# No control commands available in this mode
```

### Scripting & Automation

```bash
# Get current speed in bash
SPEED=$(ifit get AA:BB:CC:DD:EE:FF 12345678 --json | jq -r '.CurrentKph')
echo "Current speed: $SPEED km/h"

# Automated interval training script
#!/bin/bash
ADDR="AA:BB:CC:DD:EE:FF"
CODE="12345678"

# Warm up
ifit set $ADDR $CODE Mode=1 Kph=4
sleep 120

# Interval 1
ifit set $ADDR $CODE Kph=10
sleep 60
ifit set $ADDR $CODE Kph=5
sleep 60

# Interval 2
ifit set $ADDR $CODE Kph=12
sleep 60
ifit set $ADDR $CODE Kph=5
sleep 60

# Cool down
ifit set $ADDR $CODE Kph=3
sleep 120

# Stop
ifit set $ADDR $CODE Mode=0
```

## Common Characteristics

| Name | Description | Typical Range |
|------|-------------|---------------|
| Kph | Target speed | 0-25 km/h |
| CurrentKph | Actual speed | 0-25 km/h |
| Incline | Target incline | -3 to 15% |
| CurrentIncline | Actual incline | -3 to 15% |
| Pulse | Heart rate | 0-220 bpm |
| Mode | Running mode | 0=stopped, 1=running |
| MaxKph | Max speed | Equipment limit |
| MinKph | Min speed | Equipment limit |
| MaxIncline | Max incline | Equipment limit |
| MinIncline | Min incline | Equipment limit |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Device not found | Increase `--timeout`, ensure BLE enabled, move closer |
| Connection fails | Verify address and activation code are correct |
| Permission denied (Linux) | Run with sudo or grant BLE permissions |
| Import errors | Run `poetry install` or `pip install -e .` |
| FTMS relay not working | Install server extras: `poetry install --extras server` |
| activate command fails | Try `discover-activation` method with manufacturer app |

## Command Options

### Common Options

- `--timeout <seconds>` - Scan timeout (default: 10.0)
- `--interval <seconds>` - Update interval for monitoring/relay (default: 1.0)
- `--json` - Output as JSON (for `get` command)
- `-v, --verbose` - Show detailed information (for `info` command)

### Address Format

The BLE address format varies by platform:

- **Linux**: `AA:BB:CC:DD:EE:FF`
- **macOS**: `12345678-1234-1234-1234-123456789ABC`
- **Windows**: Similar to Linux

## Tips & Best Practices

- **Save your codes**: Keep your device address and activation code handy
- **Multiple terminals**: Monitor in one terminal while controlling from another
- **JSON output**: Use `--json` with `get` for scripting and automation
- **FTMS relay**: Must stay running while using apps like Zwift
- **Ctrl+C**: Cleanly stop monitoring or relay server
- **Read-only mode**: Use `monitor` without code to just observe values
- **Verbose info**: Use `-v` flag with `info` to see all capabilities and limits
