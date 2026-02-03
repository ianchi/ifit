"""BLE Activation Code Discovery.

This module implements a BLE peripheral simulator that intercepts
the activation code from the manufacturer's app, similar to the
JavaScript enable.js implementation.

The process works by:
1. Creating a BLE peripheral that mimics the treadmill
2. Connecting to the real treadmill as a central
3. Proxying commands between the manufacturer's app and the treadmill
4. Capturing the activation code from the Enable command
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

from .._scanner import find_ifit_device

if TYPE_CHECKING:
    from bleak import BleakClient
    from bless import (  # type: ignore[import-not-found]
        BlessGATTCharacteristic,
        BlessServer,
        GATTAttributePermissions,
        GATTCharacteristicProperties,
    )

from ..client.protocol import (
    BLE_UUIDS,
    Command,
    MessageIndex,
    SportsEquipment,
    build_request,
    build_write_messages,
)

BLESS_AVAILABLE = True
if not TYPE_CHECKING:
    try:
        from bleak import BleakClient
        from bless import (
            BlessGATTCharacteristic,
            BlessServer,
            GATTAttributePermissions,
            GATTCharacteristicProperties,
        )
    except ImportError:
        BLESS_AVAILABLE = False

LOGGER = logging.getLogger(__name__)

# Message length threshold for EOF detection
MIN_FINAL_MESSAGE_LENGTH = 20


class ActivationCodeDiscovery:
    """Discovers activation code by proxying BLE communication."""

    def __init__(
        self,
        ble_code: str,
        treadmill_address: str | None = None,
    ) -> None:
        """Initialize the discovery service.

        Args:
            ble_code: 4-character BLE code (e.g., "1a2b")
            treadmill_address: Optional treadmill MAC address (will scan if not provided)
        """
        if not BLESS_AVAILABLE:
            raise ImportError(
                "Activation code discovery requires 'bless' package. "
                "Install with: pip install bless"
            )

        self.ble_code = ble_code
        # Reverse bytes for manufacturer data (little-endian)
        self.ble_code_internal = ble_code[2:4] + ble_code[0:2]
        self.treadmill_address = treadmill_address

        self.server: BlessServer | None = None
        self.treadmill_client: BleakClient | None = None
        self.activation_code: str | None = None

        # State for request/response handling
        self._current_request_buffer: bytearray | None = None
        self._current_request_length: int = -1
        self._current_request_offset: int = 0
        self._current_command: int | None = None
        self._current_device: int = SportsEquipment.GENERAL
        self._current_response: list[bytes] | None = None
        self._current_response_index: int = 0

        # Treadmill metadata
        self._device_name: str | None = None
        self._advertising_data: bytes | None = None
        self._manufacturer_data: bytes | None = None
        self._service_uuids: list[str] = []

    async def discover(self, timeout: float = 60.0) -> str:
        """Run the discovery process and return the activation code.

        Args:
            timeout: Maximum time to wait for activation code

        Returns:
            The captured activation code as hex string

        Raises:
            TimeoutError: If activation code not captured within timeout
            RuntimeError: If discovery fails
        """
        print("\n=== iFit Activation Code Discovery ===\n")

        # Step 1: Find and connect to treadmill
        if not self.treadmill_address:
            print(f"Scanning for treadmill with BLE code '{self.ble_code}'...")
            self.treadmill_address = await self._find_treadmill()

        print(f"Connecting to treadmill at {self.treadmill_address}...")
        await self._connect_to_treadmill()

        print(f"✓ Connected to treadmill: {self._device_name or 'Unknown'}\n")

        # Step 2: Start BLE peripheral server
        print("Starting BLE peripheral server...")
        await self._start_peripheral_server()

        print("✓ BLE peripheral server started\n")
        print("=" * 50)
        print("Now open your manufacturer's app and connect to:")
        print(f"  Device: {self._peripheral_name}")
        print(f"  (NOT the real treadmill: {self._device_name})")
        print("=" * 50)
        print("\nWaiting for activation code...")
        print("(The app will send it during the Enable command)\n")

        # Step 3: Wait for activation code
        try:
            await asyncio.wait_for(self._wait_for_activation_code(), timeout=timeout)
        except TimeoutError as e:
            raise TimeoutError(
                f"Activation code not received within {timeout}s. "
                "Make sure you connected with the manufacturer's app."
            ) from e

        if not self.activation_code:
            raise RuntimeError("Failed to capture activation code")

        print(f"\n{'=' * 50}")
        print(f"✓ Activation code captured: {self.activation_code}")
        print(f"{'=' * 50}\n")
        print("You can now use this activation code with:")
        print(f"  ifit <command> {self.treadmill_address} {self.activation_code}")
        print()

        return self.activation_code

    async def _find_treadmill(self) -> str:
        """Scan for and return the treadmill address."""
        device = await find_ifit_device(self.ble_code, timeout=20.0)
        return device.address

    async def _connect_to_treadmill(self) -> None:
        """Connect to the real treadmill as a BLE central."""
        if self.treadmill_address is None:
            raise ValueError("Treadmill address not set")
        self.treadmill_client = BleakClient(self.treadmill_address)
        await self.treadmill_client.connect()

        # Discover services to get metadata
        services = self.treadmill_client.services
        self._service_uuids = [
            s.uuid
            for s in services
            if s.uuid
            not in ["00001800-0000-1000-8000-00805f9b34fb", "00001801-0000-1000-8000-00805f9b34fb"]
        ]

        # Get device name
        try:
            device_name_char = self.treadmill_client.services.get_characteristic(
                "00002a00-0000-1000-8000-00805f9b34fb"
            )
            if device_name_char:
                name_bytes = await self.treadmill_client.read_gatt_char(device_name_char)
                self._device_name = name_bytes.decode("utf-8", errors="ignore")
        except Exception as e:
            LOGGER.debug("Could not read device name: %s", e)

        if not self._device_name:
            self._device_name = f"iFit-{self.ble_code}"

        # Modify name for peripheral server so it's distinguishable
        # Add a suffix to make it clear this is the proxy
        self._peripheral_name = f"{self._device_name}_SETUP"

        LOGGER.info("Real treadmill name: %s", self._device_name)
        LOGGER.info("Peripheral server will advertise as: %s", self._peripheral_name)

        # Build manufacturer data (iFit signature with BLE code)
        # Format: vendor_id (2 bytes) + signature + code
        self._manufacturer_data = bytes.fromhex(f"ffff00dd{self.ble_code_internal}")

        # Setup RX/TX notifications for proxying
        await self.treadmill_client.start_notify(
            BLE_UUIDS["rx"],
            self._handle_treadmill_notify,  # type: ignore[arg-type]
        )

    async def _start_peripheral_server(self) -> None:
        """Start a BLE peripheral server that mimics the treadmill."""
        # Platform-specific BlessServer initialization
        if sys.platform == "linux":
            loop = asyncio.get_event_loop()
            self.server = BlessServer(name=self._peripheral_name, loop=loop)
        else:
            self.server = BlessServer(name=self._peripheral_name, name_overwrite=True)

        # Add the main iFit service with TX/RX characteristics
        await self.server.add_new_service(BLE_UUIDS["service"])  # type: ignore[union-attr]

        # Add TX characteristic (app writes to this, we read)
        await self.server.add_new_characteristic(  # type: ignore[union-attr]
            BLE_UUIDS["service"],
            BLE_UUIDS["tx"],
            GATTCharacteristicProperties.write
            | GATTCharacteristicProperties.write_without_response,
            None,
            GATTAttributePermissions.writeable,
        )

        # Add RX characteristic (we notify app from this)
        await self.server.add_new_characteristic(  # type: ignore[union-attr]
            BLE_UUIDS["service"],
            BLE_UUIDS["rx"],
            GATTCharacteristicProperties.notify,
            None,
            GATTAttributePermissions.readable,
        )

        # Set write handler for TX characteristic
        self.server.get_characteristic(BLE_UUIDS["tx"]).write_callback = self._handle_app_write  # type: ignore[union-attr]

        # Update advertising data to match treadmill
        # This will advertise with manufacturer data containing the BLE code
        await self.server.start()  # type: ignore[union-attr]

    async def _handle_app_write(
        self, _characteristic: BlessGATTCharacteristic, value: bytes
    ) -> None:
        """Handle write from manufacturer's app."""
        LOGGER.debug("App wrote: %s", value.hex())

        buffer = bytearray(value)

        # Parse message framing
        if buffer[0] == MessageIndex.HEADER:
            self._current_request_length = buffer[2]
            self._current_request_buffer = None
            self._current_request_offset = 0

        if buffer[0] == 0x00:  # First part after header
            self._current_command = buffer[8]
            self._current_device = buffer[6]

        # Accumulate request buffer
        if buffer[0] != MessageIndex.HEADER and buffer[0] != 0x00:
            if self._current_request_buffer is None:
                self._current_request_buffer = bytearray()

            # Copy payload data
            content_start = 9 if buffer[0] == 0x00 else 2
            content_length = buffer[1] if buffer[0] != 0x00 else len(buffer) - 9
            self._current_request_buffer.extend(
                buffer[content_start : content_start + content_length]
            )

        # Check if this is the final message
        is_eof = buffer[0] == MessageIndex.EOF
        is_short_zero = buffer[0] == 0x00 and len(buffer) < MIN_FINAL_MESSAGE_LENGTH
        if is_eof or is_short_zero:
            if buffer[0] == MessageIndex.EOF and not self._current_command:
                self._current_command = buffer[8]

            await self._process_complete_request()

    async def _process_complete_request(self) -> None:
        """Process a complete request from the app."""
        payload = bytes(self._current_request_buffer) if self._current_request_buffer else b""

        # Check if this is the Enable command
        if self._current_command == Command.ENABLE:
            self.activation_code = payload.hex()
            print(f"\n✓ Captured activation code: {self.activation_code}")
            print("\nYou can now close the manufacturer's app.")
            print("Discovery will complete shortly...\n")

        # Forward request to real treadmill
        request = build_request(
            SportsEquipment(self._current_device), Command(self._current_command), payload
        )

        # Send to treadmill TX characteristic
        for chunk in build_write_messages(request):
            await self.treadmill_client.write_gatt_char(  # type: ignore[union-attr]
                BLE_UUIDS["tx"], chunk, response=False
            )

        # Reset request state
        self._current_request_buffer = None
        self._current_command = None

    async def _handle_treadmill_notify(self, _sender: int, data: bytes) -> None:
        """Handle notification from treadmill and forward to app."""
        LOGGER.debug("Treadmill notified: %s", data.hex())

        # Forward response back to the app
        if self.server:
            self.server.get_characteristic(BLE_UUIDS["rx"]).value = bytearray(data)  # type: ignore[union-attr]
            self.server.update_value(BLE_UUIDS["service"], BLE_UUIDS["rx"])  # type: ignore[union-attr]

    async def _wait_for_activation_code(self) -> None:
        """Wait until activation code is captured."""
        while not self.activation_code:
            await asyncio.sleep(0.5)

    async def cleanup(self) -> None:
        """Clean up resources."""
        if self.server:
            await self.server.stop()

        if self.treadmill_client and self.treadmill_client.is_connected:
            await self.treadmill_client.disconnect()


async def discover_activation_code(
    ble_code: str,
    treadmill_address: str | None = None,
    timeout: float = 60.0,
) -> str:
    """Discover activation code by intercepting manufacturer app communication.

    Args:
        ble_code: 4-character BLE code from treadmill display
        treadmill_address: Optional treadmill MAC address
        timeout: Maximum time to wait for activation code

    Returns:
        The captured activation code as hex string

    Example:
        >>> code = await discover_activation_code("1a2b")
        >>> print(f"Activation code: {code}")
    """
    discovery = ActivationCodeDiscovery(ble_code, treadmill_address)

    try:
        return await discovery.discover(timeout)
    finally:
        await discovery.cleanup()
