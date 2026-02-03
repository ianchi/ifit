from __future__ import annotations

import asyncio
import csv
import logging
from collections.abc import AsyncGenerator, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bleak import BleakClient

from .protocol import (
    BLE_UUIDS,
    CHARACTERISTICS,
    CHARACTERISTICS_BY_ID,
    CORE_COMMANDS,
    METADATA_COMMANDS,
    Command,
    CommandConfig,
    EquipmentInformation,
    MessageIndex,
    SportsEquipment,
    WriteValue,
    build_request,
    build_write_messages,
    determine_message_index,
    fill_response,
    get_bitmap,
    get_header_from_response,
    get_write_values,
    parse_command_header,
    parse_equipment_information_response,
    parse_write_and_read_response,
    validate_checksum,
)

LOGGER = logging.getLogger(__name__)


class ActivationError(Exception):
    """Raised when device activation fails."""


@dataclass
class _ResponseState:
    """Track in-flight response assembly state."""

    upcoming_messages: int = -1
    buffer: bytearray | None = None


class IFitBleClient:
    """BLE client for iFit equipment implementing the custom protocol."""

    def __init__(
        self,
        address: str,
        activation_code: str | None = None,
        *,
        response_timeout: float = 10.0,
    ) -> None:
        """Create a client bound to a BLE device address.

        Args:
            address: BLE MAC address of the device
            activation_code: 8-byte hex activation code (optional - enables control if provided)
            response_timeout: Timeout for responses in seconds

        Notes:
            - No activation_code: Monitor-only mode (read-only, no discovery)
            - With activation_code: Discovery + control mode (full commands)
        """
        self.address = address
        self.activation_code = activation_code
        self.response_timeout = response_timeout
        self._client = BleakClient(address)
        self._equipment_information: EquipmentInformation | None = None
        self._response_lock = asyncio.Lock()
        self._response_future: asyncio.Future[bytes] | None = None
        self._response_state = _ResponseState()
        self._current_values_cache: dict[str, Any] | None = None
        self._watch_task: asyncio.Task[None] | None = None

    @property
    def equipment_information(self) -> EquipmentInformation | None:
        """Return cached equipment information when available."""
        return self._equipment_information

    @property
    def current_values(self) -> dict[str, Any] | None:
        """Return cached current values from watch polling."""
        return self._current_values_cache

    def _load_activation_codes(self, codes_file: Path) -> list[tuple[str, str]]:
        """Load activation codes from CSV file."""
        with open(codes_file, encoding="utf-8") as f:
            return [
                (row[0].strip(), row[1].strip().split(";")[0])
                for row in csv.reader(f)
                if len(row) >= 2
            ]

    async def _try_single_code(self, code: str) -> bool:
        """Test if a single activation code works."""
        self.activation_code = code
        try:
            await self._enable_equipment()
            await asyncio.wait_for(
                self.read_characteristics(["MaxIncline", "MinIncline"]), timeout=2.0
            )
            return True
        except (TimeoutError, Exception) as e:
            LOGGER.debug(f"Code verification failed: {e}")
            return False

    async def try_activation_codes(
        self,
        codes_file: str | Path | None = None,
        max_attempts: int | None = None,
    ) -> tuple[str, str]:
        """Try all activation codes until one successfully activates the equipment.

        This method connects to the device and attempts activation with each code
        from the codes file until one succeeds. The device remains connected after
        successful activation.

        Args:
            codes_file: Path to CSV file with activation codes. If None, uses
                       codes_reverse.csv in the same directory as this module.
            max_attempts: Maximum number of codes to try. If None, tries all codes.

        Returns:
            Tuple of (successful_activation_code, model_name)

        Raises:
            ValueError: If no activation code works
            FileNotFoundError: If codes file doesn't exist

        Example:
            >>> client = IFitBleClient("AA:BB:CC:DD:EE:FF")
            >>> code, model = await client.try_activation_codes()
            >>> print(f"Activated with {model}: {code}")
        """
        # Load activation codes from CSV
        if codes_file is None:
            module_dir = Path(__file__).parent
            codes_file = module_dir / "codes.csv"

        codes_file = Path(codes_file)
        if not codes_file.exists():
            raise FileNotFoundError(f"Activation codes file not found: {codes_file}")

        activation_codes = self._load_activation_codes(codes_file)
        if not activation_codes:
            raise ValueError(f"No activation codes found in {codes_file}")

        LOGGER.info(f"Loaded {len(activation_codes)} activation codes from {codes_file}")

        # Limit attempts if specified
        codes_to_try = activation_codes[:max_attempts] if max_attempts else activation_codes

        # Connect to device if not already connected
        if not self._client.is_connected:
            await self.connect()

        # Try each activation code
        for i, (code, model) in enumerate(codes_to_try, 1):
            LOGGER.info(f"Trying activation code {i}/{len(codes_to_try)}: {model}")

            if await self._try_single_code(code):
                LOGGER.info(f"✓ Activation successful with code for {model}")
                return code, model

        # If we get here, no code worked
        self.activation_code = None
        raise ValueError(
            f"Failed to activate equipment. Tried {len(codes_to_try)} codes with no success. "
            "The device may not be supported or may require a different activation method."
        )

    async def connect(self) -> None:
        """Connect to the BLE device and initialize protocol state."""
        await self._client.connect()

        # Wait for services to stabilize after connection (device may reconfigure)
        await asyncio.sleep(0.6)

        # Re-discover services after potential reconfiguration
        services = self._client.services

        # validate the equipment is a valid iFit device by checking uuid
        required_uuids = {BLE_UUIDS["rx"], BLE_UUIDS["tx"]}
        # Normalize UUIDs by removing hyphens for comparison
        available_uuids = {
            char.uuid.replace("-", "") for service in services for char in service.characteristics
        }

        if not required_uuids.issubset(available_uuids):
            missing = required_uuids - available_uuids
            await self._client.disconnect()
            raise ValueError(f"Device is not a valid iFit device. Missing UUIDs: {missing}")

        await self._client.start_notify(
            BLE_UUIDS["rx"],
            self._handle_notify,  # type: ignore[arg-type]
        )
        await asyncio.sleep(0.6)
        await self._initialize_equipment()

    async def disconnect(self) -> None:
        """Disconnect and stop notifications."""
        await self.stop_watch()
        if self._client.is_connected:
            await self._client.stop_notify(BLE_UUIDS["rx"])
            await self._client.disconnect()

    async def _execute_command_configs(self, configs: list[CommandConfig]) -> None:
        """Execute a list of command configurations."""
        if not self._equipment_information:
            raise ValueError("Cannot execute commands: equipment information not initialized")

        for config in configs:
            # Check if command is supported (if required)
            if (
                config.check_supported
                and config.command not in self._equipment_information.supported_commands
            ):
                LOGGER.debug(f"Command {config.command.name} not supported, skipping")
                continue

            try:
                _, response = await self._send_command(config.command, config.payload)
                value = config.parser(response)
                if value is not None:
                    setattr(self._equipment_information, config.store_in, value)
                    LOGGER.info(f"{config.store_in.replace('_', ' ').title()}: {value}")
            except Exception as e:
                LOGGER.warning(f"Could not get {config.command.name}: {e}")

    async def _initialize_equipment(self) -> None:
        """Load equipment metadata using discovery or monitor-only mode."""
        # Run discovery initialization
        # Command 81: EQUIPMENT_INFORMATION - must be first to create the object
        header, response = await self._send_command(Command.EQUIPMENT_INFORMATION)
        characteristics = parse_equipment_information_response(response)
        self._equipment_information = EquipmentInformation(
            equipment=SportsEquipment(header["equipment"]),
            characteristics=characteristics,
        )

        # Execute core initialization commands
        await self._execute_command_configs(CORE_COMMANDS)

        # Query metadata
        await self._execute_command_configs(METADATA_COMMANDS)

        max_min = await self.read_characteristics(
            ["MaxIncline", "MinIncline", "MaxKph", "MinKph", "MaxPulse", "Metric"]
        )
        self._equipment_information.values.update(max_min)

        # Enable if activation code provided
        if self.activation_code:
            await self._enable_equipment()

    async def _send_command(
        self,
        command: Command,
        payload: bytes = b"",
    ) -> tuple[dict[str, Any], bytes]:
        """Send a command and return the parsed header and raw response.

        Args:
            command: Command to send
            payload: Optional payload bytes
            equipment: Equipment type (defaults to GENERAL or current equipment info)

        Returns:
            Tuple of (parsed header dict, raw response bytes)
        """
        equipment_value = (
            self._equipment_information.equipment
            if self._equipment_information
            else SportsEquipment.GENERAL
        )
        request = build_request(equipment_value, command, payload)
        response = await self._send_request(request)
        header = parse_command_header(response, command)
        return header, response

    async def _enable_equipment(self) -> None:
        """Send the activation code so reads/writes are accepted.

        Raises:
            ActivationError: If the activation code is incorrect or device doesn't respond
            ValueError: If activation_code is not provided
        """
        if self.activation_code is None:
            raise ValueError("activation_code is required for standard initialization")
        payload = bytes.fromhex(self.activation_code)
        try:
            _, response = await self._send_command(Command.ENABLE, payload)
            LOGGER.debug(f"Enable response: {response.hex()}")
        except TimeoutError as e:
            raise ActivationError(
                "Device did not respond to activation code. "
                "The code may be incorrect for this device."
            ) from e
        except ValueError as e:
            # ValueError from parse_command_header when response code is not OK
            if "response code not OK" in str(e):
                raise ActivationError(
                    "Device rejected the activation code. The code is incorrect for this device."
                ) from e
            raise

    async def write_and_read(
        self,
        writes: Iterable[WriteValue] | None,
        reads: Iterable[str | int],
    ) -> dict[str, Any]:
        """Write characteristics and return requested read values."""
        info = self._require_equipment_info()
        write_values = list(writes) if writes else []

        # Convert characteristic names/ids to definitions
        read_defs = []
        for item in reads:
            if isinstance(item, int):
                if item not in CHARACTERISTICS_BY_ID:
                    raise ValueError(f"Unknown characteristic id: {item}")
                read_defs.append(CHARACTERISTICS_BY_ID[item])
            else:
                if item not in CHARACTERISTICS:
                    raise ValueError(f"Unknown characteristic name: {item}")
                read_defs.append(CHARACTERISTICS[item])

        write_payload = get_bitmap(info, write_values)
        read_payload = get_bitmap(info, read_defs)
        write_value_payload = get_write_values(write_values)

        # Payload layout: write bitmap, write values, read bitmap.
        payload_parts = [write_payload]
        if write_value_payload:
            payload_parts.append(write_value_payload)
        payload_parts.append(read_payload)
        payload = b"".join(payload_parts)

        _, response = await self._send_command(Command.WRITE_AND_READ, payload)
        return parse_write_and_read_response(info, response, read_defs)

    async def read_characteristics(self, reads: Iterable[str | int]) -> dict[str, Any]:
        """Read characteristic values by name or id."""
        return await self.write_and_read(None, reads)

    async def write_characteristics(self, values: dict[str, Any]) -> None:
        """Write characteristic values by name."""
        writes = []
        for key, value in values.items():
            if key not in CHARACTERISTICS:
                # Find similar characteristic names (case-insensitive match)
                similar = [k for k in CHARACTERISTICS if k.lower() == key.lower()]
                error_msg = f"Unknown characteristic name: '{key}'"
                if similar:
                    error_msg += f". Did you mean '{similar[0]}'?"
                else:
                    valid_names = sorted(CHARACTERISTICS.keys())
                    error_msg += f". Valid names are: {', '.join(valid_names)}"
                raise ValueError(error_msg)
            writes.append(WriteValue(CHARACTERISTICS[key], value))
        await self.write_and_read(writes, [])

    async def read_current_values(self) -> dict[str, Any]:
        """Read commonly updated values from the treadmill."""
        return await self.read_characteristics(
            ["Kph", "CurrentKph", "CurrentIncline", "Pulse", "Mode"]
        )

    async def set_speed(self, kph: float) -> None:
        """Set the treadmill speed in km/h.

        Args:
            kph: Speed in kilometers per hour
        """
        await self.write_characteristics({"Kph": kph})

    async def set_incline(self, percent: float) -> None:
        """Set the treadmill incline in percent.

        Args:
            percent: Incline percentage
        """
        await self.write_characteristics({"Incline": percent})

    async def monitor_basic_state(
        self, interval: float = 5.0, count: int = 5
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Read basic monitoring values in a loop."""
        for _ in range(count):  # Example: read 5 times
            result = await self.read_current_values()
            yield result

            await asyncio.sleep(interval)  # Wait specified interval between reads

    async def start_watch(
        self,
        interval: float = 5.0,
        callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Start background watch to maintain connection and cache current values.

        Args:
            interval: Polling interval in seconds (default: 5.0)
            callback: Optional async or sync function called with each update

        Notes:
            - Runs continuously in the background until stopped
            - Polls current status (speed, incline, pulse, mode)
            - Caches response accessible via .current_values property
            - Helps prevent BLE connection timeout
            - Call stop_watch() to terminate
            - Callback receives dict with: Kph, CurrentKph, CurrentIncline, Pulse, Mode

        Example:
            >>> async def on_update(values):
            ...     print(f"Speed: {values['CurrentKph']} km/h")
            >>> await client.start_watch(interval=2.0, callback=on_update)
        """
        if self._watch_task and not self._watch_task.done():
            LOGGER.warning("Watch already running")
            return

        async def _watch_loop() -> None:
            """Background task that polls current values."""
            LOGGER.info(f"Watch started with {interval}s interval")
            while True:
                if not self._client.is_connected:
                    LOGGER.warning("Watch stopped: client disconnected")
                    self._watch_task = None
                    break

                try:
                    values = await self.read_current_values()
                    self._current_values_cache = values
                    LOGGER.debug(f"Watch poll: {values}")

                    # Call callback if provided
                    if callback:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(values)
                        else:
                            callback(values)
                except Exception as e:
                    LOGGER.error(f"Watch poll failed: {e}")

                await asyncio.sleep(interval)

        self._watch_task = asyncio.create_task(_watch_loop())

    async def stop_watch(self) -> None:
        """Stop the background watch polling task."""
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
            LOGGER.info("Watch stopped")
            self._watch_task = None

    async def calibrate_incline(self) -> None:
        """Request incline calibration on the treadmill."""
        await self._send_command(Command.CALIBRATE, b"\x00")

    async def _send_request(self, request: bytes) -> bytes:
        """Send a raw request and wait for the response."""
        async with self._response_lock:
            loop = asyncio.get_running_loop()
            self._response_future = loop.create_future()
            self._response_state = _ResponseState()

            # Write the request as BLE chunks; response will arrive via notify.
            for message in build_write_messages(request):
                await self._client.write_gatt_char(BLE_UUIDS["tx"], message, response=False)
                await asyncio.sleep(0.2)  # Throttle writes to avoid overwhelming device

            response = await asyncio.wait_for(self._response_future, timeout=self.response_timeout)
            return response

    def _handle_notify(self, _: int, data: bytearray) -> None:
        """Assemble response chunks from BLE notifications."""
        if not self._response_future or self._response_future.done():
            return

        try:
            message_index = determine_message_index(bytes(data))
            if message_index == MessageIndex.HEADER:
                upcoming_messages, buffer = get_header_from_response(bytes(data))
                self._response_state.upcoming_messages = upcoming_messages
                self._response_state.buffer = buffer
                return

            if not self._response_state.buffer:
                raise ValueError("response buffer not initialized")

            # Merge the chunk into the response buffer using the index in byte 0.
            fill_response(
                self._response_state.buffer,
                self._response_state.upcoming_messages,
                bytes(data),
            )

            if message_index == MessageIndex.EOF:
                response = bytes(self._response_state.buffer)
                validate_checksum(response)
                self._response_future.set_result(response)
        except Exception as exc:  # pragma: no cover - defensive guard
            self._response_future.set_exception(exc)

    def _require_equipment_info(self) -> EquipmentInformation:
        """Return equipment info or raise if not available."""
        if self._equipment_information is None:
            raise ValueError("Equipment information not available. Call connect() first.")
        return self._equipment_information
