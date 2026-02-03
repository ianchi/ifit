"""Device management commands for iFit CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from ..client import IFitBleClient

LOGGER = logging.getLogger(__name__)


async def activate(args: argparse.Namespace) -> None:
    """Auto-discover activation code for a device."""
    print(f"Attempting to activate {args.address}...")
    print("This may take a while as we try different activation codes.\n")

    client = IFitBleClient(args.address)
    try:
        code, model = await client.try_activation_codes(max_attempts=args.max_attempts)

        print("\n✓ Success! Device activated")
        print(f"  Model: {model}")
        print(f"  Code: {code}\n")
        print("Use this code for future commands:")
        print(f"  ifit info {args.address} {code}")
        print(f"  ifit monitor {args.address} {code}")
        print(f"  ifit set {args.address} {code} Kph=5.0")

    except ValueError as e:
        print(f"\n✗ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        LOGGER.error("Activation error", exc_info=True)
        sys.exit(1)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


async def connect(args: argparse.Namespace) -> None:
    """Connect to equipment and hold connection."""
    print(f"Connecting to {args.address}...\n")

    client = IFitBleClient(args.address, activation_code=args.code)
    try:
        await client.connect()
        print("✓ Connected successfully!")

        # Show basic info
        info = client.equipment_information
        if info:
            print(f"\nEquipment Type: {info.equipment.name}")
            if info.serial_number:
                print(f"Serial Number: {info.serial_number}")
            if info.firmware_version:
                print(f"Firmware Version: {info.firmware_version}")

        print("\nConnection active. Press Ctrl+C to disconnect.")

        # Keep connection alive
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n\nDisconnecting...")

    except Exception as e:
        print(f"\n✗ Connection failed: {e}")
        LOGGER.error("Connection error", exc_info=True)
        raise

    finally:
        try:
            await client.disconnect()
            print("Disconnected.")
        except Exception as e:
            LOGGER.debug(f"Error during disconnect: {e}")


async def show_info(args: argparse.Namespace) -> None:
    """Connect and display equipment information."""
    client = IFitBleClient(args.address, args.code)
    try:
        print("Connecting to device...")
        await client.connect()

        info = client.equipment_information
        if not info:
            print("✗ Failed to retrieve equipment information")
            sys.exit(1)

        print("\n✓ Equipment Information:")
        print(f"  Type: {info.equipment.name}")
        print(f"  Characteristics: {len(info.characteristics)}")
        print(f"  Supported Capabilities: {len(info.supported_capabilities)}")

        if args.verbose:
            print("\n  Values:")
            for key, value in sorted(info.values.items()):
                print(f"    {key}: {value}")

            print(f"\n  Characteristics ({len(info.characteristics)}):")
            for char in info.characteristics.values():
                print(f"    {char.name} (ID: {char.id})")

            print(f"\n  Capabilities ({len(info.supported_capabilities)}):")
            for cap_id in sorted(info.supported_capabilities):
                print(f"    ID: {cap_id}")

            # Show supported commands
            if hasattr(info, "supported_commands"):
                supported_commands = info.supported_commands
                print(f"\n  Commands ({len(supported_commands)}):")
                for cmd_id in sorted(supported_commands):
                    print(f"    ID: {cmd_id}")

    finally:
        await client.disconnect()


async def get_values(args: argparse.Namespace) -> None:
    """Read characteristic values from the equipment."""
    client = IFitBleClient(args.address, args.code)
    try:
        await client.connect()

        # If no characteristics specified, read current values
        if not args.characteristics:
            values = await client.read_current_values()
        else:
            # Parse characteristic names or IDs
            characteristics = []
            for char in args.characteristics:
                try:
                    characteristics.append(int(char))
                except ValueError:
                    characteristics.append(char)
            values = await client.read_characteristics(characteristics)

        if args.json:
            print(json.dumps(values, indent=2))
        else:
            for key, value in sorted(values.items()):
                print(f"{key}: {value}")

    finally:
        await client.disconnect()


async def set_values(args: argparse.Namespace) -> None:
    """Write characteristic values to the equipment."""
    client = IFitBleClient(args.address, args.code)
    try:
        await client.connect()

        # Parse key=value pairs
        values: dict[str, Any] = {}
        for pair in args.values:
            if "=" not in pair:
                print(f"✗ Invalid format: {pair}. Use KEY=VALUE")
                sys.exit(1)

            key, value_str = pair.split("=", 1)
            # Try to parse as number, otherwise keep as string
            try:
                value: Any = float(value_str)
                if value.is_integer():
                    value = int(value)
            except ValueError:
                value = value_str

            values[key] = value

        try:
            await client.write_characteristics(values)
            print(f"✓ Set {', '.join(f'{k}={v}' for k, v in values.items())}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

    finally:
        await client.disconnect()
