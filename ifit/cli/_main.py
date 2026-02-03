from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from ._device import activate, get_values, set_values, show_info
from ._discovery import discover_activation_code, scan_devices
from ._monitor import monitor
from ._relay import run_ftms_relay

LOGGER = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the iFit BLE tool."""
    parser = argparse.ArgumentParser(
        prog="ifit",
        description="iFit BLE Command-Line Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. Scan for devices:        ifit scan
  2. Activate a device:        ifit activate ADDRESS
  3. Use the device:           ifit monitor ADDRESS CODE

Examples:
  # Discovery - Find devices
  ifit scan                                    # List all iFit devices
  ifit scan --code 1a2b                        # Find specific device by BLE code

  # Activation - Get activation code
  ifit activate AA:BB:CC:DD:EE:FF              # Auto-discover activation code
  ifit activate AA:BB:CC:DD:EE:FF --max-attempts 10

  # Information
  ifit info AA:BB:CC:DD:EE:FF CODE             # Show device info
  ifit info AA:BB:CC:DD:EE:FF CODE -v          # Verbose (capabilities, commands)

  # Reading values
  ifit get AA:BB:CC:DD:EE:FF CODE              # Read current values
  ifit get AA:BB:CC:DD:EE:FF CODE Kph Incline  # Read specific characteristics
  ifit get AA:BB:CC:DD:EE:FF CODE --json       # JSON output

  # Writing values
  ifit set AA:BB:CC:DD:EE:FF CODE Kph=5.0      # Set speed to 5 km/h
  ifit set AA:BB:CC:DD:EE:FF CODE Mode=1       # Start treadmill
  ifit set AA:BB:CC:DD:EE:FF CODE Mode=0       # Stop treadmill
  ifit set AA:BB:CC:DD:EE:FF CODE Kph=8.0 Incline=3.5

  # Monitoring
  ifit monitor AA:BB:CC:DD:EE:FF CODE          # Monitor with full access
  ifit monitor AA:BB:CC:DD:EE:FF               # Monitor read-only (no code needed)
  ifit monitor AA:BB:CC:DD:EE:FF CODE --interval 0.5

  # FTMS Relay - Expose as standard Bluetooth fitness device
  ifit relay AA:BB:CC:DD:EE:FF CODE            # Start FTMS relay server
  ifit relay AA:BB:CC:DD:EE:FF CODE --name "My Treadmill"
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute", required=True)

    # Scan command - unified discovery
    scan_parser = subparsers.add_parser(
        "scan", help="Scan for iFit devices (optionally filter by BLE code)"
    )
    scan_parser.add_argument("--code", help="4-character BLE code to filter by (optional)")
    scan_parser.add_argument(
        "--timeout", type=float, default=10.0, help="Scan timeout in seconds (default: 10.0)"
    )
    scan_parser.set_defaults(func=scan_devices)

    # Activate command - auto-discover activation code
    activate_parser = subparsers.add_parser(
        "activate", help="Auto-discover activation code for device"
    )
    activate_parser.add_argument("address", help="BLE address of the iFit equipment")
    activate_parser.add_argument(
        "--max-attempts", type=int, help="Maximum number of codes to try (default: all)"
    )
    activate_parser.set_defaults(func=activate)

    # Info command
    info_parser = subparsers.add_parser("info", help="Display equipment information")
    info_parser.add_argument("address", help="BLE address of the iFit equipment")
    info_parser.add_argument("code", help="Activation code")
    info_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show detailed information"
    )
    info_parser.set_defaults(func=show_info)

    # Get command - read values
    get_parser = subparsers.add_parser("get", help="Read characteristic values")
    get_parser.add_argument("address", help="BLE address of the iFit equipment")
    get_parser.add_argument("code", help="Activation code")
    get_parser.add_argument(
        "characteristics",
        nargs="*",
        help="Characteristic names or IDs to read (omit for current values)",
    )
    get_parser.add_argument("--json", action="store_true", help="Output as JSON")
    get_parser.set_defaults(func=get_values)

    # Set command - write values
    set_parser = subparsers.add_parser("set", help="Write characteristic values")
    set_parser.add_argument("address", help="BLE address of the iFit equipment")
    set_parser.add_argument("code", help="Activation code")
    set_parser.add_argument(
        "values", nargs="+", help="Key=Value pairs to write (e.g., Kph=5.0 Mode=1)"
    )
    set_parser.set_defaults(func=set_values)

    # Monitor command - unified monitoring (code optional)
    monitor_parser = subparsers.add_parser(
        "monitor", help="Monitor real-time values (code optional for read-only mode)"
    )
    monitor_parser.add_argument("address", help="BLE address of the iFit equipment")
    monitor_parser.add_argument(
        "code", nargs="?", help="Activation code (optional - without it, read-only mode)"
    )
    monitor_parser.add_argument(
        "--interval", type=float, default=1.0, help="Update interval in seconds (default: 1.0)"
    )
    monitor_parser.set_defaults(func=monitor)

    # Relay command - FTMS relay server
    relay_parser = subparsers.add_parser("relay", help="Run FTMS BLE relay server")
    relay_parser.add_argument("address", help="BLE address of the iFit equipment")
    relay_parser.add_argument("code", help="Activation code")
    relay_parser.add_argument(
        "--name", default="iFit FTMS", help="BLE advertising name (default: 'iFit FTMS')"
    )
    relay_parser.add_argument(
        "--interval", type=float, default=1.0, help="Update interval in seconds (default: 1.0)"
    )
    relay_parser.set_defaults(func=run_ftms_relay)

    # Advanced: Discover activation by intercepting manufacturer app
    discover_activation_parser = subparsers.add_parser(
        "discover-activation",
        help="Discover activation code by intercepting manufacturer app (advanced)",
    )
    discover_activation_parser.add_argument(
        "code", help="4-character BLE code displayed on equipment"
    )
    discover_activation_parser.add_argument(
        "--address", help="BLE address of the equipment (optional, will scan if not provided)"
    )
    discover_activation_parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Timeout in seconds to wait for activation code (default: 60.0)",
    )
    discover_activation_parser.set_defaults(func=discover_activation_code)

    return parser.parse_args()


def main() -> None:
    """Entry point for the iFit CLI."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    args = _parse_args()

    try:
        asyncio.run(args.func(args))
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(0)
    except Exception as e:
        LOGGER.error("Error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
