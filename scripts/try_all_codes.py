#!/usr/bin/env python3
"""Try all known activation codes to find one that works."""

import asyncio
import os
import sys

from bleak import BleakClient

BLE_UUIDS = {
    "service": "00001533-1412-efde-1523-785feabcd123",
    "rx": "00001535-1412-efde-1523-785feabcd123",
    "tx": "00001534-1412-efde-1523-785feabcd123",
}

KNOWN_CODES = {
    "0766D40AD0C82C90": "ProForm Treadmill L6.0S",
    "0701CEC4B0AAA2A8": "NordicTrack T 6.5S",
    "0701625C00E43A16": "ProForm Pro 1000",
}

response_received = asyncio.Event()
last_response = None


def handle_notify(sender, data):
    global last_response
    print(f"  <- Received: {data.hex()}")
    last_response = data
    response_received.set()


async def try_activation_code(client, code, description):
    """Try a single activation code."""
    global last_response, response_received

    print(f"\nTrying: {code} ({description})")
    print(f"  Code bytes: {bytes.fromhex(code).hex()}")

    # Build Enable command using the protocol format
    # Header: 02 04 02 <len> <equipment> <len> <cmd> <payload> <checksum>
    equipment = 0x04  # Treadmill
    command = 0x90  # Enable
    payload = bytes.fromhex(code)
    length = len(payload) + 4

    checksum = equipment + length + command
    for byte in payload:
        checksum += byte
    checksum = checksum & 0xFF

    request = (
        bytes([0x02, 0x04, 0x02, length, equipment, length, command]) + payload + bytes([checksum])
    )

    print(f"  -> Sending request: {request.hex()}")

    # Build BLE write messages (chunked)
    num_writes = (len(request) + 17) // 18
    header = bytes([0xFE, 0x02, len(request), num_writes + 1])

    print(f"  -> Sending header: {header.hex()}")
    await client.write_gatt_char(BLE_UUIDS["tx"], header, response=False)
    await asyncio.sleep(0.1)

    # Send payload chunks
    offset = 0
    counter = 1
    while offset < len(request):
        chunk_data = request[offset : offset + 18]
        if offset + 18 >= len(request):
            # Last chunk - use EOF marker
            chunk = bytes([0xFF, len(chunk_data)]) + chunk_data
        else:
            # Continuation chunk
            chunk = bytes([counter]) + chunk_data
            counter += 1

        print(f"  -> Sending chunk {counter - 1}: {chunk.hex()}")
        await client.write_gatt_char(BLE_UUIDS["tx"], chunk, response=False)
        await asyncio.sleep(0.1)
        offset += 18

    # Wait for response
    response_received.clear()
    last_response = None

    try:
        await asyncio.wait_for(response_received.wait(), timeout=3.0)
        if last_response is not None:
            print(f"  ✓ SUCCESS! Got response: {last_response.hex()}")
            return True
        print("  ✗ No response received")
        return False
    except TimeoutError:
        print("  ✗ No response (timeout)")
        return False


async def test_all_codes(address):
    """Test all known activation codes."""
    print(f"Connecting to {address}...")

    async with BleakClient(address) as client:
        print(f"Connected: {client.is_connected}")

        # Wait for services
        await asyncio.sleep(1)

        # Start notifications
        print("Starting notifications...")
        await client.start_notify(BLE_UUIDS["rx"], handle_notify)
        print("Notifications active!\n")
        print("=" * 70)

        # Try each code
        for code, description in KNOWN_CODES.items():
            success = await try_activation_code(client, code, description)
            if success:
                print(f"\n{'=' * 70}")
                print(f"FOUND WORKING CODE: {code}")
                print(f"Model: {description}")
                print(f"{'=' * 70}")

                # Save to file
                config_file = os.path.expanduser("~/.ifit_activation_codes")
                with open(config_file, "a") as f:
                    f.write(f"50dd,{address},{code}\n")
                print(f"\nSaved to: {config_file}")
                break

            await asyncio.sleep(0.5)


if __name__ == "__main__":
    address = sys.argv[1] if len(sys.argv) > 1 else "DE:09:80:3D:3F:0A"
    asyncio.run(test_all_codes(address))
