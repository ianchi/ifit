#!/usr/bin/env python3
"""Discover unknown characteristics by reading each one individually.

This script connects to an iFit device and reads all characteristics that don't have
a known converter (Unknown_* characteristics). It reads them one at a time to discover
their data length and content, which is logged for later analysis.

Usage:
    python scripts/discover_unknown_characteristics.py <device_address>

Example:
    python scripts/discover_unknown_characteristics.py D4:AD:FC:00:00:00
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path so we can import ifit
sys.path.insert(0, str(Path(__file__).parent.parent))

from ifit.client import IFitBleClient


async def discover_unknown_characteristics(address: str):
    """Connect to device and read all unknown characteristics."""
    print(f"\nConnecting to {address}...")

    client = IFitBleClient(address)
    await client.connect()

    try:
        print(f"[OK] Connected to: {client.address}")

        # Get equipment information - this is done automatically during connect
        # but we access it via the property
        info = client.equipment_information

        if not info:
            print("[ERROR] Failed to get equipment information")
            return

        print(f"\nEquipment type: {info.equipment.name}")
        print(f"Total characteristics: {len(info.characteristics)}")

        # Find all unknown characteristics (those with converter=None)
        unknown_chars = [
            char
            for char in info.characteristics.values()
            if char.converter is None and char.name.startswith("Unknown_")
        ]

        if not unknown_chars:
            print("\n[OK] No unknown characteristics found - all are documented!")
            return

        print(f"\nFound {len(unknown_chars)} unknown characteristics:")
        for char in sorted(unknown_chars, key=lambda c: c.id):
            print(f"  - {char.name} (ID={char.id})")

        print("\n" + "=" * 80)
        print("Reading each unknown characteristic individually...")
        print("=" * 80)

        # Read each unknown characteristic one by one
        success_count = 0
        failed_count = 0

        for char in sorted(unknown_chars, key=lambda c: c.id):
            print(f"\nReading {char.name} (ID={char.id})...")
            try:
                # Read this single characteristic
                result = await client.read_characteristics([char.id])

                if char.name in result:
                    data = result[char.name]
                    print(f"  [+] Success: {len(data)} bytes = {data.hex()}")
                    success_count += 1
                else:
                    print("  [-] Failed: No data returned")
                    failed_count += 1

            except Exception as e:
                print(f"  [-] Error: {e}")
                failed_count += 1

            # Small delay between reads
            await asyncio.sleep(0.2)

        print("\n" + "=" * 80)
        print(f"Discovery complete: {success_count} successful, {failed_count} failed")
        print("=" * 80)
        print("\nCheck the logs above for discovered data lengths and hex values.")
        print("Use this information to create proper converters in protocol.py")

    finally:
        await client.disconnect()


async def main():
    """Main entry point."""
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    address = sys.argv[1]

    # Configure logging to see the discovery output
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s - %(name)s - %(message)s",
    )

    try:
        await discover_unknown_characteristics(address)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
