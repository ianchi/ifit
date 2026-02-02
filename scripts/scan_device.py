#!/usr/bin/env python3
"""Scan a BLE device to discover all its services and characteristics."""

import asyncio
import sys

from bleak import BleakClient, BleakScanner


async def scan_device_services(address: str):
    """Connect to a device and print all its services and characteristics."""
    print(f"\nConnecting to {address}...")

    async with BleakClient(address) as client:
        print(f"[OK] Connected to: {client.address}")
        print(f"   Is connected: {client.is_connected}")
        print(f"   MTU size: {client.mtu_size}")

        # Wait a bit for services to be discovered
        await asyncio.sleep(2)

        print("\nDiscovering services and characteristics...\n")
        print("=" * 80)

        services_list = list(client.services)
        print(f"Total services found: {len(services_list)}\n")

        for service in services_list:
            print(f"\n📦 Service: {service.uuid}")
            print(f"   Description: {service.description}")

            for char in service.characteristics:
                props = ", ".join(char.properties)
                print(f"   📄 Characteristic: {char.uuid}")
                print(f"      Properties: {props}")
                print(f"      Handle: {char.handle}")

                # Try to read if readable
                if "read" in char.properties:
                    try:
                        value = await client.read_gatt_char(char.uuid)
                        print(f"      Value: {value.hex()}")
                    except Exception as e:
                        print(f"      Value: (read failed: {e})")

        print("\n" + "=" * 80)


async def find_and_scan(ble_code: str):
    """Find device by BLE code and scan it."""
    # Reverse the BLE code for searching
    reversed_code = ble_code[2:4] + ble_code[0:2]
    suffix = bytes.fromhex(f"dd{reversed_code}")

    print(f"Scanning for device with BLE code '{ble_code}'...")
    print(f"Looking for manufacturer data ending with: {suffix.hex()}")

    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)

    for device, adv_data in devices.values():
        if not adv_data.manufacturer_data:
            continue

        for payload in adv_data.manufacturer_data.values():
            if payload.endswith(suffix):
                print(f"\n[OK] Found: {device.name} at {device.address}")
                print(f"   Manufacturer data: {payload.hex()}")
                await scan_device_services(device.address)
                return

    print(f"\n[X] No device found with BLE code '{ble_code}'")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scan_device.py <ble_code>")
        print("Example: python scan_device.py 50dd")
        sys.exit(1)

    ble_code = sys.argv[1].lower().strip()
    asyncio.run(find_and_scan(ble_code))
