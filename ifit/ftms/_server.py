from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from struct import unpack
from typing import Self, TypeAlias

from bless import (
    BlessGATTCharacteristic,
    BlessServer,
    GATTAttributePermissions,
    GATTCharacteristicProperties,
)
from pydantic import BaseModel, Field

from ..client import IFitBleClient
from ..client.protocol import Mode
from ._ftms import (
    APPEARANCE_TREADMILL,
    APPEARANCE_UUID,
    DEVICE_INFORMATION_SERVICE_UUID,
    DEVICE_NAME_UUID,
    FIRMWARE_REVISION_UUID,
    FITNESS_MACHINE_CONTROL_POINT_UUID,
    FITNESS_MACHINE_FEATURE_UUID,
    FITNESS_MACHINE_STATUS_UUID,
    FTMS_SERVICE_UUID,
    GAP_SERVICE_UUID,
    GATT_SERVICE_UUID,
    HARDWARE_REVISION_UUID,
    MANUFACTURER_NAME_UUID,
    MODEL_NUMBER_UUID,
    SERIAL_NUMBER_UUID,
    SERVICE_CHANGED_UUID,
    SOFTWARE_REVISION_UUID,
    SUPPORTED_INCLINE_RANGE_UUID,
    SUPPORTED_SPEED_RANGE_UUID,
    TREADMILL_DATA_UUID,
    ControlPointOpcode,
    ControlPointResult,
    FtmsRanges,
    encode_control_point_response,
    encode_fitness_machine_feature,
    encode_status_started,
    encode_status_stopped,
    encode_supported_incline_range,
    encode_supported_speed_range,
    encode_treadmill_data,
)

LOGGER = logging.getLogger(__name__)

# Type aliases for clarity
CharacteristicUUID: TypeAlias = str
ServiceUUID: TypeAlias = str

# Control point message length constants
CONTROL_POINT_MIN_LENGTH = 1  # Minimum opcode byte
TARGET_VALUE_LENGTH = 3  # Opcode + 2-byte value

# FTMS unknown value sentinels
FTMS_UNKNOWN_UINT16 = 0xFFFF
FTMS_UNKNOWN_SINT16 = 0x7FFF


@dataclass
class DeviceInformation:
    """Device information for FTMS server."""

    manufacturer: str = "iFit"
    model: str = "FTMS Relay"
    serial: str = "0000001"
    firmware: str = "1.0.0"
    hardware: str = "1.0"
    software: str = "1.0.0"


class FtmsConfig(BaseModel):
    """Configuration for the FTMS relay server."""

    name: str = "iFit FTMS"
    update_interval: float = Field(default=1.0, gt=0.0)


class FtmsBleRelay:
    """Bridge iFit BLE equipment to an FTMS-compatible BLE server."""

    def __init__(
        self,
        client: IFitBleClient,
        config: FtmsConfig,
        ranges: FtmsRanges | None = None,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """Initialize relay state and BLE characteristics."""
        self._client = client
        self._config = config
        self._ranges = ranges or FtmsRanges()
        self._loop = loop or asyncio.get_event_loop()
        self._server = BlessServer(name=config.name, name_overwrite=True)
        self._update_task: asyncio.Task[None] | None = None
        self._status_value = bytearray(b"\x00")
        self._control_point_value = bytearray(b"\x00")
        self._treadmill_value = bytearray(b"")
        self._feature_value = bytearray(self._build_feature_value())
        self._supported_speed_range = bytearray(encode_supported_speed_range(self._ranges))
        self._supported_incline_range = bytearray(encode_supported_incline_range(self._ranges))
        self._device_info = DeviceInformation()

        # Control point handlers dispatch dictionary
        self._control_handlers: dict[ControlPointOpcode, Callable[[int, bytes], None]] = {
            ControlPointOpcode.REQUEST_CONTROL: self._handle_request_control,
            ControlPointOpcode.SET_TARGET_SPEED: self._handle_target_speed,
            ControlPointOpcode.SET_TARGET_INCLINE: self._handle_target_incline,
        }
        LOGGER.info(
            "Initialized FTMS relay for '%s' with update interval %.1fs",
            config.name,
            config.update_interval,
        )

    async def start(self) -> None:
        """Start the BLE server and connect to the iFit equipment."""
        LOGGER.info("Connecting to iFit equipment...")
        await self._client.connect()
        LOGGER.info("Connected to iFit equipment")

        LOGGER.debug("Updating ranges from equipment metadata...")
        self._update_ranges_from_equipment()

        LOGGER.debug("Initializing GATT services and characteristics...")
        await self._init_gatt()

        LOGGER.info("Starting BLE server '%s'...", self._config.name)
        # Configure advertisement to include FTMS service UUID
        await self._server.start()

        # Note: Bless automatically advertises service UUIDs from added services
        # The FTMS service UUID will be included in the advertisement

        self._update_task = self._loop.create_task(self._notify_loop())
        LOGGER.info("FTMS server started successfully")

    async def stop(self) -> None:
        """Stop the BLE server and disconnect from the equipment."""
        if self._update_task:
            self._update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._update_task
        await self._server.stop()
        await self._client.disconnect()
        LOGGER.info("FTMS server stopped")

    async def __aenter__(self) -> Self:
        """Start the relay server."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Stop the relay server."""
        await self.stop()

    async def _init_gatt(self) -> None:
        """Register GATT characteristics and request handlers."""
        # Build GATT structure
        gatt_structure = self._build_ftms_gatt_structure()

        # On Linux, add baseline GAP/GATT/Device Info services
        # (Windows provides these automatically)
        if sys.platform == "linux":
            gatt_structure.update(self._build_baseline_gatt_structure())
            LOGGER.debug("Including GAP/GATT/Device Info services for Linux")
        else:
            LOGGER.debug(
                "Skipping GAP/GATT/Device Info services on %s (provided by OS BLE stack)",
                sys.platform,
            )

        # Add all services and characteristics at once
        await self._server.add_gatt(gatt_structure)
        LOGGER.info("Added all GATT services and characteristics")

        # Set up request handlers
        self._server.read_request_func = self._read_request
        self._server.write_request_func = self._write_request
        LOGGER.debug("Request handlers configured")

    def _build_baseline_gatt_structure(self) -> dict[str, dict[str, dict[str, object]]]:
        """Build baseline GAP/GATT/Device Info services structure for Linux.

        Returns:
            Dictionary mapping service UUIDs to their characteristics
        """
        return {
            GAP_SERVICE_UUID: {
                DEVICE_NAME_UUID: {
                    "Properties": GATTCharacteristicProperties.read,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": bytearray(self._config.name.encode("utf-8")),
                },
                APPEARANCE_UUID: {
                    "Properties": GATTCharacteristicProperties.read,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": bytearray(APPEARANCE_TREADMILL.to_bytes(2, "little")),
                },
            },
            GATT_SERVICE_UUID: {
                SERVICE_CHANGED_UUID: {
                    "Properties": GATTCharacteristicProperties.indicate,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": bytearray(4),  # Start and end handles
                },
            },
            DEVICE_INFORMATION_SERVICE_UUID: {
                MANUFACTURER_NAME_UUID: {
                    "Properties": GATTCharacteristicProperties.read,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": bytearray(self._device_info.manufacturer.encode("utf-8")),
                },
                MODEL_NUMBER_UUID: {
                    "Properties": GATTCharacteristicProperties.read,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": bytearray(self._device_info.model.encode("utf-8")),
                },
                SERIAL_NUMBER_UUID: {
                    "Properties": GATTCharacteristicProperties.read,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": bytearray(self._device_info.serial.encode("utf-8")),
                },
                FIRMWARE_REVISION_UUID: {
                    "Properties": GATTCharacteristicProperties.read,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": bytearray(self._device_info.firmware.encode("utf-8")),
                },
                HARDWARE_REVISION_UUID: {
                    "Properties": GATTCharacteristicProperties.read,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": bytearray(self._device_info.hardware.encode("utf-8")),
                },
                SOFTWARE_REVISION_UUID: {
                    "Properties": GATTCharacteristicProperties.read,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": bytearray(self._device_info.software.encode("utf-8")),
                },
            },
        }

    def _build_ftms_gatt_structure(self) -> dict[str, dict[str, dict[str, object]]]:
        """Build FTMS service GATT structure.

        Returns:
            Dictionary mapping FTMS service UUID to its characteristics
        """
        return {
            FTMS_SERVICE_UUID: {
                FITNESS_MACHINE_FEATURE_UUID: {
                    "Properties": GATTCharacteristicProperties.read,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": self._feature_value,
                },
                SUPPORTED_SPEED_RANGE_UUID: {
                    "Properties": GATTCharacteristicProperties.read,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": self._supported_speed_range,
                },
                SUPPORTED_INCLINE_RANGE_UUID: {
                    "Properties": GATTCharacteristicProperties.read,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": self._supported_incline_range,
                },
                TREADMILL_DATA_UUID: {
                    "Properties": GATTCharacteristicProperties.notify,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": self._treadmill_value,
                },
                FITNESS_MACHINE_CONTROL_POINT_UUID: {
                    "Properties": (
                        GATTCharacteristicProperties.write | GATTCharacteristicProperties.indicate
                    ),
                    "Permissions": GATTAttributePermissions.writeable,
                    "Value": self._control_point_value,
                },
                FITNESS_MACHINE_STATUS_UUID: {
                    "Properties": GATTCharacteristicProperties.notify,
                    "Permissions": GATTAttributePermissions.readable,
                    "Value": self._status_value,
                },
            },
        }

    def _read_request(self, characteristic: BlessGATTCharacteristic, **kwargs) -> bytearray:
        """Return the current cached value for the requested characteristic.

        Args:
            characteristic: The characteristic being read
            **kwargs: Additional arguments from bless

        Returns:
            The current value of the characteristic
        """
        LOGGER.info("Read request on %s", characteristic.uuid)
        return bytearray(characteristic.value)

    def _write_request(
        self,
        characteristic: BlessGATTCharacteristic,
        value: bytes,
        **kwargs,  # type: ignore[no-untyped-def]
    ) -> None:
        """Handle FTMS control point writes for speed/incline targets.

        Args:
            characteristic: The characteristic being written to
            value: The value being written
            **kwargs: Additional arguments from bless
        """
        LOGGER.info("Write request on %s: %s", characteristic.uuid, value.hex())
        if characteristic.uuid != FITNESS_MACHINE_CONTROL_POINT_UUID:
            return
        if not value:
            self._send_control_point_response(
                0x00,
                result=ControlPointResult.INVALID_PARAMETER,
            )
            return

        opcode = value[0]
        try:
            operation = ControlPointOpcode(opcode)
            handler = self._control_handlers.get(operation)
            if handler:
                handler(opcode, value)
            else:
                LOGGER.warning("Unsupported control point opcode %s", operation.name)
                self._send_control_point_response(
                    opcode,
                    result=ControlPointResult.OP_CODE_NOT_SUPPORTED,
                )
        except ValueError:
            LOGGER.warning("Unknown control point opcode 0x%02x", opcode)
            self._send_control_point_response(
                opcode,
                result=ControlPointResult.OP_CODE_NOT_SUPPORTED,
            )
        except Exception:  # pragma: no cover - defensive guard
            LOGGER.exception("Control point handling failed")
            self._send_control_point_response(
                opcode,
                result=ControlPointResult.OPERATION_FAILED,
            )

    def _handle_request_control(self, opcode: int, _value: bytes) -> None:
        """Handle REQUEST_CONTROL opcode.

        Args:
            opcode: The control point opcode
            _value: The full control point message (unused for this opcode)
        """
        LOGGER.info("Client requested control - granting")
        self._send_control_point_response(opcode, result=ControlPointResult.SUCCESS)

    def _handle_target_value(
        self,
        opcode: int,
        value: bytes,
        *,
        is_signed: bool,
        scale: float,
        min_val: float,
        max_val: float,
        characteristic_name: str,
        unit: str,
    ) -> None:
        """Generic handler for target speed/incline requests.

        Args:
            opcode: The control point opcode
            value: The full control point message
            is_signed: Whether the value is signed (incline) or unsigned (speed)
            scale: Scale factor to convert from FTMS units to actual units
            min_val: Minimum allowed value
            max_val: Maximum allowed value
            characteristic_name: Name of the iFit characteristic to write
            unit: Unit string for logging (e.g., "kph", "%")
        """
        if len(value) < TARGET_VALUE_LENGTH:
            self._send_control_point_response(
                opcode,
                result=ControlPointResult.INVALID_PARAMETER,
            )
            return

        fmt = "<h" if is_signed else "<H"
        (raw_value,) = unpack(fmt, value[1:3])
        actual_value = raw_value / scale

        if not (min_val <= actual_value <= max_val):
            LOGGER.warning(
                "Target %s %.2f %s out of range [%.2f, %.2f], rejecting",
                characteristic_name.lower(),
                actual_value,
                unit,
                min_val,
                max_val,
            )
            self._send_control_point_response(
                opcode,
                result=ControlPointResult.INVALID_PARAMETER,
            )
            return

        LOGGER.info("Setting target %s to %.2f %s", characteristic_name.lower(), actual_value, unit)
        self._schedule_task(
            self._client.write_characteristics({characteristic_name: actual_value}),
            f"set_{characteristic_name.lower()}",
        )
        self._send_control_point_response(opcode, result=ControlPointResult.SUCCESS)

    def _handle_target_speed(self, opcode: int, value: bytes) -> None:
        """Parse a speed target request and forward it to the iFit client.

        Args:
            opcode: The control point opcode
            value: The full control point message
        """
        self._handle_target_value(
            opcode,
            value,
            is_signed=False,
            scale=100.0,
            min_val=self._ranges.min_kph,
            max_val=self._ranges.max_kph,
            characteristic_name="Kph",
            unit="kph",
        )

    def _handle_target_incline(self, opcode: int, value: bytes) -> None:
        """Parse an incline target request and forward it to the iFit client.

        Args:
            opcode: The control point opcode
            value: The full control point message
        """
        self._handle_target_value(
            opcode,
            value,
            is_signed=True,
            scale=10.0,
            min_val=self._ranges.min_incline,
            max_val=self._ranges.max_incline,
            characteristic_name="Incline",
            unit="%",
        )

    def _notify_characteristic(
        self, service_uuid: ServiceUUID, char_uuid: CharacteristicUUID, value: bytearray
    ) -> None:
        """Update a characteristic value and send notification/indication.

        Args:
            service_uuid: UUID of the service containing the characteristic
            char_uuid: UUID of the characteristic to update
            value: New value for the characteristic
        """
        characteristic = self._server.get_characteristic(char_uuid)
        if characteristic:
            characteristic.value = value
            self._server.update_value(service_uuid, char_uuid)
            LOGGER.debug("Sent notification for %s (%d bytes)", char_uuid, len(value))
        else:
            LOGGER.error("Characteristic %s not found", char_uuid)

    def _send_control_point_response(
        self,
        opcode: int,
        *,
        result: ControlPointResult,
    ) -> None:
        """Send a control point response via indication.

        Args:
            opcode: The original request opcode
            result: The result code to send
        """
        payload = bytearray(encode_control_point_response(opcode, result))
        self._control_point_value = payload

        # Send indication immediately. Per FTMS spec, clients must enable indications
        # before writing to control point, so we assume they're subscribed.
        self._notify_characteristic(FTMS_SERVICE_UUID, FITNESS_MACHINE_CONTROL_POINT_UUID, payload)
        LOGGER.debug("Sent control point indication: opcode=0x%02x, result=%s", opcode, result.name)

        # If this is REQUEST_CONTROL with success, send initial treadmill data
        # to help clients that wait for first notification before completing connection
        if opcode == ControlPointOpcode.REQUEST_CONTROL and result == ControlPointResult.SUCCESS:
            self._schedule_task(self._update_treadmill_data(), "initial_data_update")

    def _schedule_task(self, coro: Coroutine[object, object, None], label: str) -> None:
        """Schedule a background task and log failures.

        Args:
            coro: The coroutine to schedule
            label: A descriptive label for logging
        """
        LOGGER.debug("Scheduling background task: %s", label)
        task = self._loop.create_task(coro)
        task.add_done_callback(lambda t: self._log_task_exception(t, label))

    @staticmethod
    def _log_task_exception(task: asyncio.Future[None], label: str) -> None:
        """Log exceptions from background tasks.

        Args:
            task: The completed task
            label: The descriptive label for the task
        """
        if task.cancelled():
            LOGGER.debug("Background task %s was cancelled", label)
            return
        exc = task.exception()
        if exc:
            LOGGER.error("Background task %s failed: %s", label, exc, exc_info=exc)

    async def _notify_loop(self) -> None:
        """Continuously poll the iFit client and notify FTMS subscribers."""
        while True:
            await self._update_treadmill_data()
            await asyncio.sleep(self._config.update_interval)

    async def _update_treadmill_data(self) -> None:
        """Read iFit values and update FTMS treadmill/status characteristics."""
        try:
            values = await self._client.read_characteristics(
                ["CurrentKph", "Kph", "CurrentIncline", "Incline", "Distance", "Pulse", "Mode"]
            )
        except Exception as e:  # noqa: BLE001  # Catch all connection/read errors
            LOGGER.error("Failed to read iFit characteristics: %s", e)
            return

        current_kph = float(values.get("CurrentKph", 0.0)) or float(values.get("Kph", 0.0))
        current_incline = float(values.get("CurrentIncline", 0.0)) or float(
            values.get("Incline", 0.0)
        )
        distance = float(values.get("Distance", 0.0))
        pulse_data = values.get("Pulse", {})
        heart_rate = int(pulse_data.get("pulse", 0)) if isinstance(pulse_data, dict) else 0
        mode = values.get("Mode")

        LOGGER.debug(
            "Treadmill data: speed=%.2f kph, incline=%.1f%%, distance=%.2f km, hr=%s, mode=%s",
            current_kph,
            current_incline,
            distance,
            heart_rate if heart_rate else "N/A",
            mode,
        )

        # Compose FTMS treadmill data with optional fields for incline/distance/hr.
        self._treadmill_value = encode_treadmill_data(
            speed_kph=current_kph,
            incline_percent=current_incline,
            distance_m=distance,
            heart_rate_bpm=heart_rate if heart_rate else None,
        )

        # Update and notify treadmill data
        self._notify_characteristic(FTMS_SERVICE_UUID, TREADMILL_DATA_UUID, self._treadmill_value)

        # Update status if changed
        self._update_status(mode)

    def _update_status(self, mode: object) -> None:
        """Update fitness machine status based on mode.

        Args:
            mode: The current iFit mode
        """
        status = self._encode_status_from_mode(mode)
        if not status or status == bytes(self._status_value):
            return

        self._status_value = bytearray(status)
        self._notify_characteristic(
            FTMS_SERVICE_UUID, FITNESS_MACHINE_STATUS_UUID, self._status_value
        )
        LOGGER.info("Sent status notification: mode=%s", mode)

    @staticmethod
    def _build_feature_value() -> bytes:
        """Build the FTMS feature bitfield payload."""
        return encode_fitness_machine_feature(
            supports_inclination=True,
            supports_heart_rate=True,
            supports_total_distance=True,
            supports_speed_target=True,
            supports_incline_target=True,
        )

    def _update_ranges_from_equipment(self) -> None:
        """Update supported ranges based on the iFit equipment metadata."""
        info = self._client.equipment_information
        if not info:
            LOGGER.warning("No equipment information available, using default ranges")
            return
        min_kph = float(info.values.get("MinKph", self._ranges.min_kph))
        max_kph = float(info.values.get("MaxKph", self._ranges.max_kph))
        min_incline = float(info.values.get("MinIncline", self._ranges.min_incline))
        max_incline = float(info.values.get("MaxIncline", self._ranges.max_incline))
        self._ranges = FtmsRanges(
            min_kph=min_kph,
            max_kph=max_kph,
            min_incline=min_incline,
            max_incline=max_incline,
            speed_increment=self._ranges.speed_increment,
            incline_increment=self._ranges.incline_increment,
        )
        LOGGER.info(
            "Updated ranges from equipment: speed=%.1f-%.1f kph, incline=%.1f-%.1f%%",
            min_kph,
            max_kph,
            min_incline,
            max_incline,
        )
        self._supported_speed_range = bytearray(encode_supported_speed_range(self._ranges))
        self._supported_incline_range = bytearray(encode_supported_incline_range(self._ranges))

        speed_range_char = self._server.get_characteristic(SUPPORTED_SPEED_RANGE_UUID)
        if speed_range_char is not None:
            speed_range_char.value = self._supported_speed_range

        incline_range_char = self._server.get_characteristic(SUPPORTED_INCLINE_RANGE_UUID)
        if incline_range_char is not None:
            incline_range_char.value = self._supported_incline_range

    @staticmethod
    def _encode_status_from_mode(mode: object) -> bytes | None:
        """Map iFit mode values to FTMS status messages."""
        if isinstance(mode, Mode):
            if mode in {Mode.ACTIVE, Mode.WARMUP}:
                return encode_status_started()
            if mode in {Mode.PAUSE, Mode.SUMMARY, Mode.IDLE}:
                return encode_status_stopped()
        return None
