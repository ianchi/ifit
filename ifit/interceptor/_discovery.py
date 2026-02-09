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
from typing import TYPE_CHECKING, Self, TypeAlias

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

# Type aliases for clarity
CharacteristicUUID: TypeAlias = str
ServiceUUID: TypeAlias = str

# Standard UUIDs as constants
GAP_SERVICE_UUID = "00001800-0000-1000-8000-00805f9b34fb"
GATT_SERVICE_UUID = "00001801-0000-1000-8000-00805f9b34fb"
DEVICE_NAME_UUID = "00002a00-0000-1000-8000-00805f9b34fb"

# Message parsing constants
HEADER_INDEX = MessageIndex.HEADER
EOF_INDEX = MessageIndex.EOF
FIRST_PART_INDEX = 0x00
COMMAND_OFFSET = 8
DEVICE_OFFSET = 6
FIRST_PART_CONTENT_START = 9
CONTINUATION_CONTENT_START = 2

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
        self._current_command: int | None = None
        self._current_device: int = SportsEquipment.GENERAL

        # Treadmill metadata
        self._device_name: str | None = None
        self._peripheral_name: str | None = None
        self._manufacturer_company_id: int | None = None
        self._manufacturer_data: bytes | None = None

    async def discover(self, timeout: float = 60.0) -> str:
        """Run the discovery process and return the activation code.

        Args:
            timeout: Maximum time to wait for activation code

        Returns:
            The captured activation code as hex string

        Raises:
            TimeoutError: If activation code not captured within timeout
            RuntimeError: If discovery fails
            NotImplementedError: If running on Windows (not supported)
        """
        # Check if running on Windows
        if sys.platform == "win32":
            raise NotImplementedError(
                "\n"
                "══════════════════════════════════════════════════════════════════════\n"
                "  Activation Code Discovery is NOT supported on Windows\n"
                "══════════════════════════════════════════════════════════════════════\n\n"
                "REASON:\n"
                "  Windows Bluetooth APIs do not support advertising both:\n"
                "    • Service UUIDs (required for GATT server)\n"
                "    • Manufacturer data (required to mimic iFit devices)\n\n"
                "  Only ONE can be advertised at a time, making it impossible\n"
                "  to create a proper peripheral that the iFit app will recognize.\n\n"
                "SOLUTION:\n"
                "  Use Linux or macOS for activation code discovery, or:\n"
                "  1. Try codes from scripts/try_all_codes.py\n"
                "  2. Ask in the community for known codes\n"
                "  3. Use a Raspberry Pi or Linux VM for discovery\n\n"
                "Sorry for the inconvenience. This is a Windows BLE API limitation.\n"
            )

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

    async def __aenter__(self) -> Self:
        """Start the discovery process as an async context manager."""
        await self.discover()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Clean up resources when exiting context."""
        await self.cleanup()

    async def _find_treadmill(self) -> str:
        """Scan for and return the treadmill address.

        Also captures manufacturer data for later use in advertisement.

        Returns:
            The MAC address of the discovered treadmill

        Raises:
            TimeoutError: If no treadmill found within scan timeout
        """
        device = await find_ifit_device(self.ble_code, timeout=20.0)
        self._manufacturer_data = device.manufacturer_data
        self._manufacturer_company_id = device.manufacturer_company_id
        LOGGER.info(
            "Captured manufacturer data from device: company_id=0x%04X, data=%s",
            self._manufacturer_company_id if self._manufacturer_company_id else 0,
            self._manufacturer_data.hex() if self._manufacturer_data else "None",
        )
        return device.address

    async def _connect_to_treadmill(self) -> None:
        """Connect to the real treadmill as a BLE central.

        Establishes connection, discovers device metadata, and sets up
        notification handlers for proxying responses back to the app.

        Raises:
            ValueError: If treadmill address not set
            RuntimeError: If connection or setup fails
        """
        if self.treadmill_address is None:
            raise ValueError("Treadmill address not set")

        try:
            self.treadmill_client = BleakClient(self.treadmill_address)
            await self.treadmill_client.connect()
            LOGGER.info("Connected to treadmill at %s", self.treadmill_address)
        except Exception as e:
            raise RuntimeError(f"Failed to connect to treadmill: {e}") from e

        try:
            await self._discover_treadmill_metadata()
            await self._setup_treadmill_notifications()
        except Exception as e:
            await self.treadmill_client.disconnect()
            raise RuntimeError(f"Failed to setup treadmill connection: {e}") from e

    async def _discover_treadmill_metadata(self) -> None:
        """Discover treadmill device name and build peripheral server name.

        Reads the device name characteristic and creates a distinguishable
        name for the peripheral server by appending "_SETUP" suffix.
        """
        if self.treadmill_client is None:
            return

        # Get device name from GAP service
        try:
            device_name_char = self.treadmill_client.services.get_characteristic(DEVICE_NAME_UUID)
            if device_name_char:
                name_bytes = await self.treadmill_client.read_gatt_char(device_name_char)
                self._device_name = name_bytes.decode("utf-8", errors="ignore")
                LOGGER.debug("Read device name: %s", self._device_name)
        except Exception as e:
            LOGGER.debug("Could not read device name: %s", e)

        if not self._device_name:
            self._device_name = f"iFit-{self.ble_code}"

        # Add suffix to make peripheral server distinguishable from real treadmill
        self._peripheral_name = f"{self._device_name}_SETUP"

        LOGGER.info("Real treadmill name: %s", self._device_name)
        LOGGER.info("Peripheral server will advertise as: %s", self._peripheral_name)

    async def _setup_treadmill_notifications(self) -> None:
        """Enable notifications from treadmill RX characteristic for proxying.

        Raises:
            RuntimeError: If notification setup fails
        """
        if self.treadmill_client is None:
            raise RuntimeError("Treadmill client not initialized")

        try:
            await self.treadmill_client.start_notify(
                BLE_UUIDS["rx"],
                self._handle_treadmill_notify,  # type: ignore[arg-type]
            )
            LOGGER.debug("Enabled notifications on treadmill RX characteristic")
        except Exception as e:
            raise RuntimeError(f"Failed to enable treadmill notifications: {e}") from e

    def _build_gatt_structure(
        self,
    ) -> dict[ServiceUUID, dict[CharacteristicUUID, dict[str, object]]]:
        """Build iFit proxy service GATT structure.

        Creates the service and characteristics needed to proxy communication
        between the manufacturer's app and the real treadmill.

        Returns:
            Dictionary mapping service UUID to characteristics configuration
        """
        return {
            BLE_UUIDS["service"]: {
                BLE_UUIDS["tx"]: {
                    "Properties": (
                        GATTCharacteristicProperties.write
                        | GATTCharacteristicProperties.write_without_response
                    ),
                    "Permissions": GATTAttributePermissions.writeable,
                    "Value": bytearray(),
                },
                BLE_UUIDS["rx"]: {
                    "Properties": GATTCharacteristicProperties.notify,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": bytearray(),
                },
            },
        }

    async def _configure_advertisement(self) -> None:
        """Configure BLE advertisement with manufacturer data from source device.

        Replicates the exact manufacturer data from the real iFit equipment
        so the peripheral appears identical to the manufacturer's app.
        Supports macOS (CoreBluetooth) and Linux (BlueZ).
        
        Note: Windows is not supported due to BLE API limitations.
        """
        if not self.server:
            return

        if not self._manufacturer_data:
            LOGGER.warning(
                "No manufacturer data captured from source device, "
                "advertisement may not match exactly"
            )
            return

        try:
            # Access the platform-specific advertiser backend
            # Bless uses different backends: CoreBluetoothBackend (macOS), BlueZBackend (Linux)
            success = False
            if sys.platform == "darwin":
                # macOS uses CoreBluetooth
                success = await self._configure_corebluetooth_advertisement()
            else:
                # Linux uses BlueZ
                success = await self._configure_bluez_advertisement()

            if success:
                LOGGER.info(
                    "Configured advertisement with manufacturer data: %s",
                    self._manufacturer_data.hex(),
                )
            else:
                LOGGER.warning(
                    "Manufacturer data configuration not fully supported on this platform. "
                    "The peripheral will advertise with default settings."
                )
        except Exception as e:
            LOGGER.warning("Failed to configure manufacturer data in advertisement: %s", e)
            LOGGER.info("Continuing without manufacturer data replication")



    async def _configure_corebluetooth_advertisement(self) -> bool:
        """Configure advertisement using CoreBluetooth on macOS.

        Returns:
            True if manufacturer data was successfully configured, False otherwise
        """
        if not self.server or not self._manufacturer_data:
            return False

        # Try to access the Bless CoreBluetooth backend
        if not hasattr(self.server, "app"):
            LOGGER.debug("Bless server doesn't have 'app' backend attribute")
            return False

        backend = self.server.app

        # CoreBluetooth uses CBPeripheralManager for advertising
        # The advertisement data dictionary can include manufacturer data
        # Key: CBAdvertisementDataManufacturerDataKey
        # However, Bless may not expose this directly

        # Try to set manufacturer data in the advertisement dictionary
        if not hasattr(backend, "advertisement_data"):
            return False

        # Import CoreBluetooth constants
        try:
            from CoreBluetooth import (  # type: ignore[import-not-found]  # noqa: PLC0415
                CBAdvertisementDataManufacturerDataKey,
            )

            # Set manufacturer data
            backend.advertisement_data[CBAdvertisementDataManufacturerDataKey] = (  # type: ignore[attr-defined]
                self._manufacturer_data
            )
            LOGGER.info("Successfully configured CoreBluetooth manufacturer data")
            return True
        except ImportError:
            LOGGER.debug("CoreBluetooth modules not available")
            return False
        except Exception as e:
            LOGGER.debug("CoreBluetooth advertisement configuration failed: %s", e)
            return False

    async def _configure_bluez_advertisement(self) -> bool:  # noqa: PLR0911
        """Configure advertisement using BlueZ on Linux.

        Returns:
            True if manufacturer data was successfully configured, False otherwise
        """
        if not self.server or not self._manufacturer_data:
            return False

        try:
            # Try to access the Bless BlueZ backend
            if not hasattr(self.server, "app"):
                LOGGER.debug("Bless server doesn't have 'app' backend attribute")
                return False

            backend = self.server.app

            # BlueZ uses DBus for BLE operations
            # The advertisement is configured through org.bluez.LEAdvertisement1 interface
            # Manufacturer data is a dict where key is the company ID (uint16) and value is bytes

            # Try to access the advertisement object
            if not (hasattr(backend, "advertisement") and backend.advertisement):  # type: ignore[attr-defined]
                return False

            adv = backend.advertisement  # type: ignore[attr-defined]

            # Set manufacturer data on the advertisement
            # The format should be: {company_id: [byte, byte, ...]}
            # Use the captured company ID or fallback
            company_id = self._manufacturer_company_id or 0xFFFF

            if hasattr(adv, "manufacturer_data"):
                # Set as a dict with company ID as key
                adv.manufacturer_data = {company_id: list(self._manufacturer_data)}
                LOGGER.info(
                    "Successfully configured BlueZ manufacturer data with company ID 0x%04X",
                    company_id,
                )
                return True
            if hasattr(adv, "ManufacturerData"):
                # Alternative property name
                adv.ManufacturerData = {company_id: list(self._manufacturer_data)}
                LOGGER.info(
                    "Successfully configured BlueZ manufacturer data with company ID 0x%04X",
                    company_id,
                )
                return True

            return False

        except Exception as e:
            LOGGER.debug("BlueZ advertisement configuration failed: %s", e)
            return False

    async def _start_peripheral_server(self) -> None:
        """Start a BLE peripheral server that mimics the treadmill.

        Initializes BlessServer, adds GATT structure, and starts advertising
        to allow the manufacturer's app to connect.

        Raises:
            RuntimeError: If server initialization fails
        """
        if self._peripheral_name is None:
            raise RuntimeError("Peripheral name not set")

        try:
            # Unified BlessServer initialization (name_overwrite works on all platforms)
            self.server = BlessServer(name=self._peripheral_name, name_overwrite=True)
            LOGGER.debug("Initialized BlessServer with name: %s", self._peripheral_name)

            # Build and add GATT structure
            gatt_structure = self._build_gatt_structure()
            await self.server.add_gatt(gatt_structure)
            LOGGER.debug("Added iFit service and characteristics")

            # Set write request handler
            self.server.write_request_func = self._handle_app_write
            LOGGER.debug("Configured write request handler")

            # Configure advertisement with manufacturer data AFTER server starts
            # This ensures the GATT server is running before we add the auxiliary advertiser
            await self._configure_advertisement()
            await asyncio.sleep(60)  # Ensure advertisement is set up before starting server
            LOGGER.debug("Advertisement configured, starting server...")
            # Start server and begin advertising
            await self.server.start()
            LOGGER.info("BLE peripheral server started as '%s'", self._peripheral_name)

        except Exception as e:
            raise RuntimeError(f"Failed to start peripheral server: {e}") from e

    async def _handle_app_write(
        self,
        characteristic: BlessGATTCharacteristic,
        value: bytes,
        **kwargs,  # type: ignore[no-untyped-def]
    ) -> None:
        """Handle write from manufacturer's app.

        Processes incoming BLE messages from the manufacturer's app,
        reassembles fragmented messages, and forwards complete requests
        to the treadmill.

        Args:
            characteristic: The characteristic being written to
            value: The data written by the app
            **kwargs: Additional arguments from bless
        """
        LOGGER.debug("App wrote to %s: %s", characteristic.uuid, value.hex())

        if characteristic.uuid != BLE_UUIDS["tx"]:
            LOGGER.warning("Unexpected write to characteristic %s", characteristic.uuid)
            return

        try:
            buffer = bytearray(value)
            self._process_message_fragment(buffer)

            # Check if message is complete
            if self._is_complete_message(buffer[0], len(buffer)):
                await self._process_complete_request()
        except Exception as e:
            LOGGER.exception("Failed to process app write: %s", e)

    def _process_message_fragment(self, buffer: bytearray) -> None:
        """Process a single BLE message fragment.

        Handles different message types: headers, first parts, continuations,
        and accumulates payload data for reassembly.

        Args:
            buffer: Message fragment data
        """
        index = buffer[0]

        # Parse message framing
        if index == HEADER_INDEX:
            self._current_request_length = buffer[2]
            self._current_request_buffer = bytearray()
            LOGGER.debug("Received header, expecting %d bytes", self._current_request_length)
            return

        if index == FIRST_PART_INDEX:
            # First part contains command and device info
            self._current_command = buffer[COMMAND_OFFSET]
            self._current_device = buffer[DEVICE_OFFSET]
            # Extract payload from first part
            content_length = buffer[1]
            content = buffer[FIRST_PART_CONTENT_START : FIRST_PART_CONTENT_START + content_length]
            if self._current_request_buffer is None:
                self._current_request_buffer = bytearray()
            self._current_request_buffer.extend(content)
            LOGGER.debug(
                "First part: cmd=0x%02x, device=%d, content=%d bytes",
                self._current_command,
                self._current_device,
                content_length,
            )
        elif index == EOF_INDEX:
            # EOF marker may contain command if not previously set
            if not self._current_command and len(buffer) > COMMAND_OFFSET:
                self._current_command = buffer[COMMAND_OFFSET]
        else:
            # Continuation message
            if self._current_request_buffer is None:
                LOGGER.warning("Continuation message without header, discarding")
                return
            content_length = buffer[1]
            content = buffer[
                CONTINUATION_CONTENT_START : CONTINUATION_CONTENT_START + content_length
            ]
            self._current_request_buffer.extend(content)
            LOGGER.debug("Continuation: %d bytes", content_length)

    def _is_complete_message(self, index: int, length: int) -> bool:
        """Check if we have received a complete message.

        Args:
            index: Message index byte
            length: Length of current fragment

        Returns:
            True if message is complete and ready to process
        """
        return index == EOF_INDEX or (
            index == FIRST_PART_INDEX and length < MIN_FINAL_MESSAGE_LENGTH
        )

    async def _process_complete_request(self) -> None:
        """Process a complete request from the app and forward to treadmill.

        This method is called when a complete message has been received from
        the manufacturer's app. It extracts the activation code if this is
        an ENABLE command, then forwards the request to the real treadmill.

        The request is reconstructed using the protocol's build_request()
        function and split into write messages appropriate for BLE MTU.
        """
        if self._current_command is None:
            LOGGER.warning("Complete request without command, discarding")
            self._reset_request_state()
            return

        payload = bytes(self._current_request_buffer) if self._current_request_buffer else b""

        LOGGER.info(
            "Processing complete request: cmd=0x%02x, device=%d, payload=%d bytes",
            self._current_command,
            self._current_device,
            len(payload),
        )

        # Check if this is the Enable command and capture activation code
        if self._current_command == Command.ENABLE:
            self.activation_code = payload.hex()
            print(f"\n✓ Captured activation code: {self.activation_code}")
            print("\nYou can now close the manufacturer's app.")
            print("Discovery will complete shortly...\n")
            LOGGER.info("Activation code captured: %s", self.activation_code)

        # Forward request to real treadmill
        request = build_request(
            SportsEquipment(self._current_device), Command(self._current_command), payload
        )
        await self._forward_to_treadmill(request)

        # Reset request state for next message
        self._reset_request_state()

    def _reset_request_state(self) -> None:
        """Reset request parsing state for next message."""
        self._current_request_buffer = None
        self._current_command = None
        self._current_device = SportsEquipment.GENERAL

    async def _forward_to_treadmill(self, request: bytes) -> None:
        """Forward a complete request to the treadmill.

        Splits the request into appropriately-sized BLE write messages
        and sends them to the treadmill TX characteristic.

        Args:
            request: Complete request message to forward

        Raises:
            RuntimeError: If treadmill client not connected
        """
        if not self.treadmill_client:
            raise RuntimeError("Treadmill client not connected")

        try:
            chunks = list(build_write_messages(request))
            LOGGER.debug("Forwarding request to treadmill: %d chunks", len(chunks))
            for chunk in chunks:
                await self.treadmill_client.write_gatt_char(BLE_UUIDS["tx"], chunk, response=False)
            LOGGER.debug("Successfully forwarded %d-byte request", len(request))
        except Exception as e:
            LOGGER.error("Failed to forward request to treadmill: %s", e)
            raise

    def _notify_app(self, char_uuid: CharacteristicUUID, value: bytes) -> None:
        """Send notification to connected manufacturer's app.

        Updates the characteristic value and triggers a BLE notification
        to any subscribed clients (the manufacturer's app).

        Args:
            char_uuid: UUID of characteristic to notify
            value: Value to send in notification
        """
        if not self.server:
            LOGGER.warning("Server not initialized, cannot send notification")
            return

        characteristic = self.server.get_characteristic(char_uuid)
        if characteristic:
            characteristic.value = bytearray(value)
            self.server.update_value(BLE_UUIDS["service"], char_uuid)
            LOGGER.debug(
                "Sent notification to app on %s (%d bytes)",
                char_uuid,
                len(value),
            )
        else:
            LOGGER.error("Characteristic %s not found", char_uuid)

    async def _handle_treadmill_notify(self, _sender: int, data: bytes) -> None:
        """Handle notification from treadmill and forward to app.

        Receives responses from the real treadmill and proxies them back
        to the manufacturer's app via BLE notifications.

        Args:
            _sender: BLE sender identifier (unused)
            data: Response data from treadmill
        """
        LOGGER.debug("Treadmill notified: %s", data.hex())
        self._notify_app(BLE_UUIDS["rx"], data)

    async def _wait_for_activation_code(self) -> None:
        """Wait until activation code is captured."""
        while not self.activation_code:
            await asyncio.sleep(0.5)

    async def cleanup(self) -> None:
        """Clean up BLE resources.

        Stops the peripheral server and disconnects from the treadmill.
        Safe to call multiple times.
        """
        LOGGER.debug("Cleaning up discovery resources")

        if self.server:
            try:
                await self.server.stop()
                LOGGER.debug("Stopped peripheral server")
            except Exception as e:
                LOGGER.warning("Error stopping server: %s", e)

        if self.treadmill_client and self.treadmill_client.is_connected:
            try:
                await self.treadmill_client.disconnect()
                LOGGER.debug("Disconnected from treadmill")
            except Exception as e:
                LOGGER.warning("Error disconnecting from treadmill: %s", e)


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
