# Activation Code Discovery

This document explains how to automatically discover your iFit equipment's activation code.

## Overview

The iFit BLE protocol requires two pieces of information:

- **BLE Code** (4 characters): Displayed on your treadmill when you press connect
- **Activation Code** (72 hex characters): Sent by the manufacturer's app during authentication

While the BLE code is easy to obtain, the activation code is not normally visible. This tool solves that problem by intercepting it from the manufacturer's app.

## How It Works

The activation discovery process works by creating a BLE "man-in-the-middle" proxy:

```
[Manufacturer App] ←→ [This Tool] ←→ [Your Treadmill]
```

1. **Setup**: The tool connects to your real treadmill and collects its BLE metadata
2. **Advertising**: Creates a virtual BLE peripheral that mimics your treadmill
3. **Interception**: When you connect via the manufacturer's app, it proxies all commands
4. **Capture**: When the app sends the "Enable" command with the activation code, it's captured
5. **Storage**: The code is saved for future use

This is identical to how the JavaScript implementation (`enable.js`) works in the original Zwifit project.

## Usage

### Requirements

Install the additional `bless` package for BLE peripheral support:

```bash
pip install bless
```

### Basic Usage

```bash
ifit discover-activation <ble-code>
```

Example:

```bash
ifit discover-activation 1a2b
```

### Full Workflow

1. **Turn on your treadmill** and press the connect button to see the BLE code (e.g., "1a2b")

2. **Run the discovery command**:

   ```bash
   ifit discover-activation 1a2b
   ```

3. **Open your manufacturer's app** (iFit, NordicTrack, ProForm, etc.)

4. **Connect to your equipment** in the app as you normally would

5. **Wait for capture**: The tool will automatically detect and display the activation code:

   ```
   ✓ Captured activation code: a1b2c3d4
   ```

6. **Use the code**: The activation code is saved to `~/.ifit_activation_codes` and can now be used:

   ```bash
   ifit info AA:BB:CC:DD:EE:FF a1b2c3d4
   ```

### Advanced Options

Specify the treadmill address if already known:

```bash
ifit discover-activation 1a2b --address AA:BB:CC:DD:EE:FF
```

Adjust timeout (default 60 seconds):

```bash
ifit discover-activation 1a2b --timeout 120
```

## Platform Support

- **Linux**: Full support (requires `bless` and BLE permissions)
- **macOS**: Full support (requires `bless`)
- **Windows**: Limited support (BLE peripheral mode may not be fully supported)

## Troubleshooting

### "Missing dependencies: bless"

Install the required package:

```bash
pip install bless
```

### "No device found with code"

- Ensure your treadmill is on and in pairing mode
- Check that the BLE code is correct (shown on treadmill display)
- Increase timeout: `--timeout 30`

### "Activation code not received within timeout"

- Make sure you actually connected via the manufacturer's app
- Some apps may have a delay - try increasing timeout
- Verify the app is the correct one for your equipment brand

### Permission Errors (Linux)

Grant BLE permissions:

```bash
sudo setcap 'cap_net_raw,cap_net_admin+eip' $(which python3)
```

## Security & Privacy

This tool:

- ✓ Only works locally on your machine
- ✓ Only intercepts communication between YOUR app and YOUR equipment
- ✓ Stores codes locally in `~/.ifit_activation_codes`
- ✓ Does not transmit any data over the internet
