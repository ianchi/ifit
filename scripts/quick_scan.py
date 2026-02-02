#!/usr/bin/env python3
"""Quick BLE device service scanner."""

import asyncio
import sys

from bleak import BleakClient


async def quick_scan(address: str):
    """Quickly connect and list all services/characteristics."""
    print(f"Connecting to {address}...")

    try:
        async with BleakClient(address, timeout=10.0) as client:
            print(f"Connected: {client.is_connected}")

            for service in client.services:
                print(f"\nService: {service.uuid}")
                for char in service.characteristics:
                    props = ", ".join(char.properties)
                    print(f"  Char: {char.uuid} [{props}]")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    address = sys.argv[1] if len(sys.argv) > 1 else "DE:09:80:3D:3F:0A"
    asyncio.run(quick_scan(address))
