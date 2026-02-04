from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import Coroutine
from struct import unpack
from typing import TYPE_CHECKING

# Try to import bless - optional dependency
try:
    from bless import (
        BlessGATTCharacteristic,
        BlessServer,
        GATTAttributePermissions,
        GATTCharacteristicProperties,
    )

    BLESS_AVAILABLE = True
except ImportError:
    BLESS_AVAILABLE = False
    if TYPE_CHECKING:
        # Type stubs for type checking when bless is not installed
        from bless import (  # type: ignore[import-not-found]
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
    DEVICE_NAME_UUID,
    FITNESS_MACHINE_CONTROL_POINT_UUID,
    FITNESS_MACHINE_FEATURE_UUID,
    FITNESS_MACHINE_STATUS_UUID,
    FTMS_SERVICE_UUID,
    GAP_SERVICE_UUID,
    GATT_SERVICE_UUID,
    SERVICE_CHANGED_UUID,
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

# Control point message length constants
MIN_TARGET_VALUE_LENGTH = 3


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
        if not BLESS_AVAILABLE:
            msg = (
                "FTMS server requires 'bless' library. Install with: poetry install --extras server"
            )
            raise RuntimeError(msg)

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
        LOGGER.info(
            "Initialized FTMS relay for '%s' with update interval %.1fs",
            config.name,
            config.update_interval,
        )
        LOGGER.debug(
            "Initial ranges: speed=%.1f-%.1f kph, incline=%.1f-%.1f%%",
            self._ranges.min_kph,
            self._ranges.max_kph,
            self._ranges.min_incline,
            self._ranges.max_incline,
        )

    async def start(self) -> None:
        """Start the BLE server and connect to the iFit equipment."""
        LOGGER.info("Connecting to iFit equipment...")
        await self._client.connect()
        LOGGER.info("Connected to iFit equipment")

        LOGGER.debug("Initializing GATT services and characteristics...")
        await self._init_gatt()

        LOGGER.debug("Updating ranges from equipment metadata...")
        self._update_ranges_from_equipment()

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

    async def _init_gatt(self) -> None:
        """Register GATT characteristics and request handlers."""
        # On Linux, add baseline GAP/GATT services (Windows provides these automatically)
        if sys.platform == "linux":
            # Add baseline GAP service (required by iOS)
            await self._server.add_new_service(GAP_SERVICE_UUID)
            await self._server.add_new_characteristic(
                GAP_SERVICE_UUID,
                DEVICE_NAME_UUID,
                GATTCharacteristicProperties.read,
                bytearray(self._config.name.encode("utf-8")),
                GATTAttributePermissions.readable,
            )
            await self._server.add_new_characteristic(
                GAP_SERVICE_UUID,
                APPEARANCE_UUID,
                GATTCharacteristicProperties.read,
                bytearray(APPEARANCE_TREADMILL.to_bytes(2, "little")),
                GATTAttributePermissions.readable,
            )
            LOGGER.debug("Added GAP service with Device Name and Appearance")

            # Add baseline GATT service (recommended for iOS)
            await self._server.add_new_service(GATT_SERVICE_UUID)
            await self._server.add_new_characteristic(
                GATT_SERVICE_UUID,
                SERVICE_CHANGED_UUID,
                GATTCharacteristicProperties.indicate,
                bytearray(4),  # Start and end handles (will be updated if service table changes)
                GATTAttributePermissions.readable,
            )
            LOGGER.debug("Added GATT service with Service Changed")
        else:
            LOGGER.debug(
                "Skipping GAP/GATT services on %s (provided by OS BLE stack)", sys.platform
            )

        # Add FTMS service
        await self._server.add_new_service(FTMS_SERVICE_UUID)
        LOGGER.info("Added FTMS service: %s", FTMS_SERVICE_UUID)

        # Add characteristics to the service
        await self._server.add_new_characteristic(
            FTMS_SERVICE_UUID,
            FITNESS_MACHINE_FEATURE_UUID,
            GATTCharacteristicProperties.read,
            self._feature_value,
            GATTAttributePermissions.readable,
        )
        LOGGER.debug("Added characteristic: Fitness Machine Feature")

        await self._server.add_new_characteristic(
            FTMS_SERVICE_UUID,
            SUPPORTED_SPEED_RANGE_UUID,
            GATTCharacteristicProperties.read,
            self._supported_speed_range,
            GATTAttributePermissions.readable,
        )
        LOGGER.debug("Added characteristic: Supported Speed Range")

        await self._server.add_new_characteristic(
            FTMS_SERVICE_UUID,
            SUPPORTED_INCLINE_RANGE_UUID,
            GATTCharacteristicProperties.read,
            self._supported_incline_range,
            GATTAttributePermissions.readable,
        )
        LOGGER.debug("Added characteristic: Supported Incline Range")

        await self._server.add_new_characteristic(
            FTMS_SERVICE_UUID,
            TREADMILL_DATA_UUID,
            GATTCharacteristicProperties.notify,
            self._treadmill_value,
            GATTAttributePermissions.readable,
        )
        LOGGER.debug("Added characteristic: Treadmill Data")

        await self._server.add_new_characteristic(
            FTMS_SERVICE_UUID,
            FITNESS_MACHINE_CONTROL_POINT_UUID,
            GATTCharacteristicProperties.write | GATTCharacteristicProperties.indicate,
            self._control_point_value,
            GATTAttributePermissions.writeable,
        )
        LOGGER.debug("Added characteristic: Fitness Machine Control Point")

        await self._server.add_new_characteristic(
            FTMS_SERVICE_UUID,
            FITNESS_MACHINE_STATUS_UUID,
            GATTCharacteristicProperties.notify,
            self._status_value,
            GATTAttributePermissions.readable,
        )
        LOGGER.debug("Added characteristic: Fitness Machine Status")

        # Set up request handlers
        self._server.read_request_func = self._read_request
        self._server.write_request_func = self._write_request
        LOGGER.debug("Request handlers configured")

    def _read_request(self, characteristic: BlessGATTCharacteristic, **kwargs) -> bytearray:
        """Return the current cached value for the requested characteristic."""
        LOGGER.info("Read request on %s", characteristic.uuid)
        return bytearray(characteristic.value)

    def _write_request(
        self, characteristic: BlessGATTCharacteristic, value: bytes, **kwargs
    ) -> None:
        """Handle FTMS control point writes for speed/incline targets."""
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
            try:
                op = ControlPointOpcode(opcode)
            except ValueError:
                op = None
            match op:
                case ControlPointOpcode.REQUEST_CONTROL:
                    # Always grant control to the FTMS client.
                    LOGGER.info("Client requested control - granting")
                    self._send_control_point_response(opcode, result=ControlPointResult.SUCCESS)
                case ControlPointOpcode.SET_TARGET_SPEED:
                    self._handle_target_speed(opcode, value)
                case ControlPointOpcode.SET_TARGET_INCLINE:
                    self._handle_target_incline(opcode, value)
                case ControlPointOpcode.START_OR_RESUME | ControlPointOpcode.STOP_OR_PAUSE:
                    LOGGER.warning("Start/stop control not supported by IFitBleClient")
                    self._send_control_point_response(
                        opcode,
                        result=ControlPointResult.OP_CODE_NOT_SUPPORTED,
                    )
                case _:
                    LOGGER.warning("Unsupported control point opcode %s", opcode)
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

    def _handle_target_speed(self, opcode: int, value: bytes) -> None:
        """Parse a speed target request and forward it to the iFit client."""
        if len(value) < MIN_TARGET_VALUE_LENGTH:
            self._send_control_point_response(
                opcode,
                result=ControlPointResult.INVALID_PARAMETER,
            )
            return
        (raw,) = unpack("<H", value[1:3])
        kph = raw / 100
        # Convert FTMS 0.01 km/h units to kph.

        # Validate against supported speed range
        if not (self._ranges.min_kph <= kph <= self._ranges.max_kph):
            LOGGER.warning(
                "Target speed %.2f kph out of range [%.2f, %.2f], rejecting",
                kph,
                self._ranges.min_kph,
                self._ranges.max_kph,
            )
            self._send_control_point_response(
                opcode,
                result=ControlPointResult.INVALID_PARAMETER,
            )
            return

        LOGGER.info("Setting target speed to %.2f kph", kph)
        self._schedule_task(self._client.write_characteristics({"Kph": kph}), "set_speed")
        self._send_control_point_response(opcode, result=ControlPointResult.SUCCESS)

    def _handle_target_incline(self, opcode: int, value: bytes) -> None:
        """Parse an incline target request and forward it to the iFit client."""
        if len(value) < MIN_TARGET_VALUE_LENGTH:
            self._send_control_point_response(
                opcode,
                result=ControlPointResult.INVALID_PARAMETER,
            )
            return
        (raw,) = unpack("<h", value[1:3])
        incline = raw / 10
        # Convert FTMS 0.1% units to incline percentage.

        # Validate against supported incline range
        if not (self._ranges.min_incline <= incline <= self._ranges.max_incline):
            LOGGER.warning(
                "Target incline %.1f%% out of range [%.1f, %.1f], rejecting",
                incline,
                self._ranges.min_incline,
                self._ranges.max_incline,
            )
            self._send_control_point_response(
                opcode,
                result=ControlPointResult.INVALID_PARAMETER,
            )
            return

        LOGGER.info("Setting target incline to %.1f%%", incline)
        self._schedule_task(self._client.write_characteristics({"Incline": incline}), "set_incline")
        self._send_control_point_response(opcode, result=ControlPointResult.SUCCESS)

    def _send_control_point_response(
        self,
        opcode: int,
        *,
        result: ControlPointResult,
    ) -> None:
        """Send a control point response via indication."""
        payload = bytearray(encode_control_point_response(opcode, result))
        self._control_point_value = payload

        char = self._server.get_characteristic(FITNESS_MACHINE_CONTROL_POINT_UUID)
        if char is None:
            LOGGER.error("Control Point characteristic not found")
            return

        char.value = payload

        # Send indication immediately. Per FTMS spec, clients must enable indications
        # before writing to control point, so we assume they're subscribed.
        # Note: On Windows, bless doesn't expose subscription state via subscribed_centrals
        self._server.update_value(FTMS_SERVICE_UUID, FITNESS_MACHINE_CONTROL_POINT_UUID)
        LOGGER.debug("Sent control point indication: opcode=0x%02x, result=%s", opcode, result.name)

        # If this is REQUEST_CONTROL with success, send initial treadmill data
        # to help clients that wait for first notification before completing connection
        if opcode == ControlPointOpcode.REQUEST_CONTROL and result == ControlPointResult.SUCCESS:
            self._schedule_task(self._update_treadmill_data(), "initial_data_update")

    def _schedule_task(self, coro: Coroutine[object, object, None], label: str) -> None:
        """Schedule a background task and log failures."""
        LOGGER.debug("Scheduling background task: %s", label)
        task = self._loop.create_task(coro)
        task.add_done_callback(lambda t: self._log_task_exception(t, label))

    @staticmethod
    def _log_task_exception(task: asyncio.Future[None], label: str) -> None:
        """Log exceptions from background tasks."""
        if task.cancelled():
            LOGGER.debug("Background task %s was cancelled", label)
            return
        exc = task.exception()
        if exc:
            LOGGER.error("Background task %s failed: %s", label, exc, exc_info=exc)

    def _is_subscribed(self, characteristic_uuid: str) -> bool:
        """Check if any client has enabled notifications/indications for a characteristic."""
        char = self._server.get_characteristic(characteristic_uuid)
        if char is None:
            LOGGER.debug(
                "Characteristic %s not found when checking subscription", characteristic_uuid
            )
            return False
        # Bless tracks subscribed centrals; check if any exist
        subscribed_centrals = getattr(char, "subscribed_centrals", [])
        LOGGER.debug(
            "Subscription check for %s: subscribed_centrals=%s, has_attr=%s",
            characteristic_uuid,
            subscribed_centrals,
            hasattr(char, "subscribed_centrals"),
        )
        return len(subscribed_centrals) > 0

    async def _notify_loop(self) -> None:
        """Continuously poll the iFit client and notify FTMS subscribers."""
        while True:
            await self._update_treadmill_data()
            await asyncio.sleep(self._config.update_interval)

    async def _update_treadmill_data(self) -> None:
        """Read iFit values and update FTMS treadmill/status characteristics."""
        values = await self._client.read_characteristics(
            ["Kph", "CurrentIncline", "Distance", "Pulse", "Mode"]
        )
        current_kph = float(values.get("Kph", 0.0))
        current_incline = float(values.get("CurrentIncline", 0.0))
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
        self._treadmill_value = bytearray(
            encode_treadmill_data(
                speed_kph=current_kph,
                incline_percent=current_incline,
                distance_km=distance,
                heart_rate_bpm=heart_rate if heart_rate else None,
            )
        )

        # Update treadmill data and notify only if client is subscribed
        treadmill_char = self._server.get_characteristic(TREADMILL_DATA_UUID)
        if treadmill_char is not None:
            treadmill_char.value = self._treadmill_value
            # Always send notification - if no one is subscribed, it's ignored by BLE stack
            self._server.update_value(FTMS_SERVICE_UUID, TREADMILL_DATA_UUID)
            LOGGER.debug("Sent treadmill data notification (%d bytes)", len(self._treadmill_value))

        # Update status if changed and notify only if client is subscribed
        status = self._encode_status_from_mode(mode)
        if status and status != bytes(self._status_value):
            self._status_value = bytearray(status)
            status_char = self._server.get_characteristic(FITNESS_MACHINE_STATUS_UUID)
            if status_char is not None:
                status_char.value = self._status_value
                # Always send notification - if no one is subscribed, it's ignored by BLE stack
                self._server.update_value(FTMS_SERVICE_UUID, FITNESS_MACHINE_STATUS_UUID)
                LOGGER.info("Sent status notification: mode=%s", mode)

    @staticmethod
    def _build_feature_value() -> bytes:
        """Build the FTMS feature bitfield payload."""
        return encode_fitness_machine_feature(
            supports_inclination=True,
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
