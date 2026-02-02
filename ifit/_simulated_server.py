#!/usr/bin/env python3
"""Simulated iFit BLE Server
Creates a BLE peripheral that mimics an iFit treadmill without connecting to real hardware.
Useful for testing the server side and capturing commands from the iFit app.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bless import (  # type: ignore[import-not-found]
        BlessGATTCharacteristic,
        BlessServer,
        GATTAttributePermissions,
        GATTCharacteristicProperties,
    )
else:
    with contextlib.suppress(ImportError):
        from bless import (
            BlessGATTCharacteristic,
            BlessServer,
            GATTAttributePermissions,
            GATTCharacteristicProperties,
        )

# cSpell:words XXYY

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# iFit BLE Protocol Constants (captured from real device scan)
IFIT_SERVICE_UUID = "00001533-1412-efde-1523-785feabcd123"
IFIT_RX_CHAR_UUID = (
    "00001535-1412-efde-1523-785feabcd123"  # Treadmill notifies app (RX from app perspective)
)
IFIT_TX_CHAR_UUID = (
    "00001534-1412-efde-1523-785feabcd123"  # App writes to treadmill (TX from app perspective)
)

# Additional service UUIDs from real device
GENERIC_ACCESS_SERVICE = "00001800-0000-1000-8000-00805f9b34fb"
GENERIC_ATTRIBUTE_SERVICE = "00001801-0000-1000-8000-00805f9b34fb"
DFU_SERVICE_UUID = "00001530-1212-efde-1523-785feabcd123"
HDP_SERVICE_UUID = "00001400-555e-e99c-e511-f9f4f8daeb24"

# Company ID from real device advertising: 0x01a5
# Manufacturer data payload: 02cc9c800004dddd50
COMPANY_ID = 0x01A5


class SimulatedIfitServer:
    """Simulated iFit treadmill BLE peripheral server."""

    def __init__(self, device_name: str = "IFIT_SIM", ble_code: str = "60dd"):
        """Initialize the simulated iFit server.

        Args:
            device_name: BLE device name (note: Windows may override with PC hostname)
            ble_code: 4-character hex BLE code displayed on treadmill (e.g., "50dd")
        """
        self.device_name = device_name
        self.ble_code = ble_code
        self.server: BlessServer = None
        self.running = False
        self.received_commands = []

    def _make_manufacturer_data(self) -> bytes:
        """Create manufacturer data with BLE code suffix matching real device.

        Real device format (for code 50dd): 02cc9c800004dddd50
        Breakdown:
        - 02cc: Company ID (0xcc02 in little-endian)
        - 9c800004: Fixed prefix data
        - dddd50: BLE code with 'dd' prefix
        """
        # Format BLE code: ddXXYY where XXYY is the reversed BLE code
        reversed_code = bytes.fromhex(self.ble_code)[::-1]
        code_with_prefix = b"\xdd" + reversed_code

        # Build manufacturer data matching real device
        manufacturer_data = (
            bytes(
                [
                    0x02,
                    0xCC,  # Company ID 0xcc02 (little-endian)
                    0x9C,
                    0x80,
                    0x00,
                    0x04,  # Fixed prefix from real device
                ]
            )
            + code_with_prefix
        )

        return manufacturer_data

    async def _handle_tx_write(self, characteristic: BlessGATTCharacteristic, value: bytearray):
        """Handle writes to TX characteristic (commands from app).

        Args:
            characteristic: The characteristic being written to
            value: The data written by the app
        """
        hex_value = value.hex()
        logger.info(f"📥 Received command from app: {hex_value} ({len(value)} bytes)")

        # Parse the command
        if len(value) >= 3:
            command_type = value[0]
            command_id = value[1]
            data = value[2:]

            logger.info(
                f"   Type: 0x{command_type:02x}, ID: 0x{command_id:02x}, Data: {data.hex()}"
            )

            # Check for Enable command (0x90)
            if command_id == 0x90:
                logger.info("   🎯 ENABLE COMMAND DETECTED!")
                if len(data) >= 14:
                    mac_address = data[:6]
                    activation_code = data[6:14]
                    mac_str = ":".join([f"{b:02x}" for b in mac_address])
                    code_str = activation_code.hex().upper()
                    logger.info(f"   📍 MAC Address: {mac_str}")
                    logger.info(f"   🔑 ACTIVATION CODE: {code_str}")
                    logger.info("   ✅ Successfully captured activation code!")

                    # Send back a success response
                    await self._send_enable_response()

            # Store command
            self.received_commands.append(
                {
                    "timestamp": asyncio.get_event_loop().time(),
                    "type": command_type,
                    "id": command_id,
                    "data": data.hex(),
                    "raw": hex_value,
                }
            )

    async def _send_enable_response(self):
        """Send a simulated response to Enable command."""
        try:
            # Typical Enable response format: [0x01, 0x90, 0x00] (success)
            response = bytearray([0x01, 0x90, 0x00])

            # Update the RX characteristic value and notify
            await self.server.update_value(IFIT_SERVICE_UUID, IFIT_RX_CHAR_UUID, response)
            logger.info(f"📤 Sent Enable response: {response.hex()}")
        except Exception as e:
            logger.error(f"Failed to send Enable response: {e}")

    async def _send_status_updates(self):
        """Periodically send simulated status updates."""
        while self.running:
            try:
                # Send a simple status update (simulated speed, incline, etc.)
                # This is just placeholder data to keep the app happy
                status = bytearray(
                    [
                        0x02,  # Status message type
                        0x00,  # Speed low byte (0.0 km/h)
                        0x00,  # Speed high byte
                        0x00,  # Incline (0%)
                        0x00,  # Watts low byte
                        0x00,  # Watts high byte
                    ]
                )

                await self.server.update_value(IFIT_SERVICE_UUID, IFIT_RX_CHAR_UUID, status)
                logger.debug(f"📤 Sent status update: {status.hex()}")

            except Exception as e:
                logger.error(f"Failed to send status update: {e}")

            await asyncio.sleep(5)  # Send updates every 5 seconds

    async def start(self):
        """Start the simulated iFit BLE server."""
        logger.info(f"Starting simulated iFit server: {self.device_name}")
        logger.info(f"BLE Code: {self.ble_code}")

        # Create the BLE server
        self.server = BlessServer(name=self.device_name)
        await self.server.start()

        # Add Generic Access Profile service (required by BLE spec)
        await self.server.add_new_service(GENERIC_ACCESS_SERVICE)
        logger.info(f"Added Generic Access service: {GENERIC_ACCESS_SERVICE}")

        # Add Generic Attribute Profile service
        await self.server.add_new_service(GENERIC_ATTRIBUTE_SERVICE)
        logger.info(f"Added Generic Attribute service: {GENERIC_ATTRIBUTE_SERVICE}")

        # Add main iFit service
        await self.server.add_new_service(IFIT_SERVICE_UUID)
        logger.info(f"Added iFit service: {IFIT_SERVICE_UUID}")

        # Add RX characteristic (for notifications TO app)
        await self.server.add_new_characteristic(
            IFIT_SERVICE_UUID,
            IFIT_RX_CHAR_UUID,
            GATTCharacteristicProperties.notify | GATTCharacteristicProperties.read,
            bytearray([0x00]),  # Initial value
            GATTAttributePermissions.readable,
        )
        logger.info(f"Added RX characteristic: {IFIT_RX_CHAR_UUID}")

        # Add TX characteristic (for writes FROM app)
        await self.server.add_new_characteristic(
            IFIT_SERVICE_UUID,
            IFIT_TX_CHAR_UUID,
            GATTCharacteristicProperties.write
            | GATTCharacteristicProperties.write_without_response,
            bytearray([0x00]),  # Initial value
            GATTAttributePermissions.writeable,
        )
        logger.info(f"Added TX characteristic: {IFIT_TX_CHAR_UUID}")

        # Set write callback for TX characteristic
        self.server.get_characteristic(IFIT_TX_CHAR_UUID).value = bytearray([0x00])
        self.server.update_value = self.server.update_value

        # Read callback for testing
        def read_callback(characteristic: BlessGATTCharacteristic, **kwargs) -> bytearray:
            logger.debug(f"Read request on {characteristic.uuid}")
            return characteristic.value

        # Write callback
        def write_callback(characteristic: BlessGATTCharacteristic, value: bytearray, **kwargs):
            logger.debug(f"Write callback triggered for {characteristic.uuid}")
            asyncio.create_task(self._handle_tx_write(characteristic, value))

        # Register callbacks
        self.server.read_request_func = read_callback
        self.server.write_request_func = write_callback

        # Start advertising with manufacturer data and service UUID (like real device)
        manufacturer_data = self._make_manufacturer_data()
        logger.info(f"Manufacturer data: {manufacturer_data.hex()}")
        logger.info(f"Advertising service UUID: {IFIT_SERVICE_UUID}")

        await self.server.start_advertising(
            manufacturer_data={COMPANY_ID: manufacturer_data},
            service_uuids=[IFIT_SERVICE_UUID],  # Advertise the main iFit service
        )
        logger.info("✅ Server started and advertising")
        logger.info(
            f"⚠️  Note: Windows may advertise with PC hostname instead of '{self.device_name}'"
        )
        logger.info("Waiting for connections from iFit app...")

        self.running = True

        # Start status update task
        status_task = asyncio.create_task(self._send_status_updates())

        try:
            # Keep running until interrupted
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            status_task.cancel()
            await self.stop()

    async def stop(self):
        """Stop the BLE server."""
        self.running = False
        if self.server:
            await self.server.stop()
        logger.info("Server stopped")

        # Print summary
        if self.received_commands:
            logger.info(f"\n📊 Received {len(self.received_commands)} commands:")
            for i, cmd in enumerate(self.received_commands, 1):
                logger.info(
                    f"  {i}. Type: 0x{cmd['type']:02x}, ID: 0x{cmd['id']:02x}, Data: {cmd['data']}"
                )


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Simulated iFit BLE Server")
    parser.add_argument(
        "--name", default="IFIT_SIM", help="Device name (Windows may override with PC hostname)"
    )
    parser.add_argument(
        "--code", default="50dd", help="BLE code to advertise (4 hex digits, e.g., '50dd')"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create and start server
    server = SimulatedIfitServer(device_name=args.name, ble_code=args.code)
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
