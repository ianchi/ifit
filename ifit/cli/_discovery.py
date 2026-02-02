"""Discovery and scanning commands for iFit CLI."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .._scanner import find_all_ifit_devices, find_ifit_device

LOGGER = logging.getLogger(__name__)


async def scan_devices(args: argparse.Namespace) -> None:
    """Scan for iFit devices - optionally filter by BLE code."""
    if args.code:
        print(f"Scanning for iFit device with code '{args.code}'...")
        try:
            device = await find_ifit_device(args.code, timeout=args.timeout)
            print("\n✓ Found device:")
            print(f"  Address: {device.address}")
            print(f"  Name: {device.name or 'Unknown'}")
            print(f"  BLE Code: {args.code}")
        except TimeoutError:
            print(f"\n✗ No device found with code '{args.code}' after {args.timeout}s")
            sys.exit(1)
        except ValueError as e:
            print(f"\n✗ Error: {e}")
            sys.exit(1)
    else:
        print(f"Scanning for iFit devices (timeout: {args.timeout}s)...")
        try:
            devices = await find_all_ifit_devices(timeout=args.timeout)

            if not devices:
                print("\n✗ No iFit devices found")
                sys.exit(1)

            print(f"\n✓ Found {len(devices)} iFit device(s):\n")
            for i, device in enumerate(devices, 1):
                ble_code = device.manufacturer_data[-2:].hex()
                ble_code_display = ble_code[2:4] + ble_code[0:2]
                print(f"{i}. {device.name or 'Unknown Device'}")
                print(f"   Address: {device.address}")
                print(f"   BLE Code: {ble_code_display}")
                print()
        except Exception as e:
            print(f"\n✗ Error during scan: {e}")
            sys.exit(1)


async def discover_activation_code(args: argparse.Namespace) -> None:
    """Discover activation code by intercepting manufacturer app."""
    try:
        from ..interceptor import discover_activation_code as discover_code  # noqa: PLC0415
    except ImportError as e:
        print("\n✗ Activation code discovery requires additional dependencies:")
        print("  pip install bless")
        print(f"\nError: {e}")
        sys.exit(1)

    try:
        activation_code = await discover_code(
            args.code, treadmill_address=args.address, timeout=args.timeout
        )

        # Save to a file for easy reference
        config_file = os.path.expanduser("~/.ifit_activation_codes")
        with open(config_file, "a") as f:
            address = args.address or "discovered"
            f.write(f"{args.code},{address},{activation_code}\n")

        print(f"Activation code saved to: {config_file}\n")

    except ImportError as e:
        print(f"\n✗ Missing dependencies: {e}")
        print("Install with: pip install bless")
        sys.exit(1)
    except TimeoutError as e:
        print(f"\n✗ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Discovery failed: {e}")
        LOGGER.error("Discovery error", exc_info=True)
        sys.exit(1)
