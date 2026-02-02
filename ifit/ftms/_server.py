from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Coroutine
from struct import unpack
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

from pydantic import BaseModel, Field

from ..client import IFitBleClient
from ..client.protocol import Mode
from ._ftms import (
    FITNESS_MACHINE_CONTROL_POINT_UUID,
    FITNESS_MACHINE_FEATURE_UUID,
    FITNESS_MACHINE_STATUS_UUID,
    FTMS_SERVICE_UUID,
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
        self._client = client
        self._config = config
        self._ranges = ranges or FtmsRanges()
        self._loop = loop or asyncio.get_event_loop()
        self._server = BlessServer(name=config.name, loop=self._loop)
        self._update_task: asyncio.Task[None] | None = None
        self._status_value = b"\x00"
        self._control_point_value = b"\x00"
        self._treadmill_value = b""
        self._feature_value = self._build_feature_value()
        self._supported_speed_range = encode_supported_speed_range(self._ranges)
        self._supported_incline_range = encode_supported_incline_range(self._ranges)
        self._init_gatt()

    async def start(self) -> None:
        """Start the BLE server and connect to the iFit equipment."""
        await self._client.connect()
        self._update_ranges_from_equipment()
        await self._server.start()
        self._update_task = self._loop.create_task(self._notify_loop())
        LOGGER.info("FTMS server started")

    async def stop(self) -> None:
        """Stop the BLE server and disconnect from the equipment."""
        if self._update_task:
            self._update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._update_task
        await self._server.stop()
        await self._client.disconnect()
        LOGGER.info("FTMS server stopped")

    def _init_gatt(self) -> None:
        """Register GATT characteristics and request handlers."""
        treadmill_data = BlessGATTCharacteristic(
            TREADMILL_DATA_UUID,
            GATTCharacteristicProperties.notify,
            GATTAttributePermissions.readable,
            value=self._treadmill_value,
        )
        control_point = BlessGATTCharacteristic(
            FITNESS_MACHINE_CONTROL_POINT_UUID,
            GATTCharacteristicProperties.write | GATTCharacteristicProperties.indicate,
            GATTAttributePermissions.writeable,
            value=self._control_point_value,
        )
        status = BlessGATTCharacteristic(
            FITNESS_MACHINE_STATUS_UUID,
            GATTCharacteristicProperties.notify,
            GATTAttributePermissions.readable,
            value=self._status_value,
        )
        feature = BlessGATTCharacteristic(
            FITNESS_MACHINE_FEATURE_UUID,
            GATTCharacteristicProperties.read,
            GATTAttributePermissions.readable,
            value=self._feature_value,
        )
        supported_speed_range = BlessGATTCharacteristic(
            SUPPORTED_SPEED_RANGE_UUID,
            GATTCharacteristicProperties.read,
            GATTAttributePermissions.readable,
            value=self._supported_speed_range,
        )
        supported_incline_range = BlessGATTCharacteristic(
            SUPPORTED_INCLINE_RANGE_UUID,
            GATTCharacteristicProperties.read,
            GATTAttributePermissions.readable,
            value=self._supported_incline_range,
        )

        self._server.add_gatt(
            FTMS_SERVICE_UUID,
            {
                FITNESS_MACHINE_FEATURE_UUID: feature,
                SUPPORTED_SPEED_RANGE_UUID: supported_speed_range,
                SUPPORTED_INCLINE_RANGE_UUID: supported_incline_range,
                TREADMILL_DATA_UUID: treadmill_data,
                FITNESS_MACHINE_CONTROL_POINT_UUID: control_point,
                FITNESS_MACHINE_STATUS_UUID: status,
            },
        )

        self._server.read_request_func = self._read_request
        self._server.write_request_func = self._write_request

    def _read_request(self, characteristic: BlessGATTCharacteristic) -> bytes:
        """Return the current cached value for the requested characteristic."""
        uuid_to_value = {
            FITNESS_MACHINE_FEATURE_UUID: self._feature_value,
            FITNESS_MACHINE_STATUS_UUID: self._status_value,
            FITNESS_MACHINE_CONTROL_POINT_UUID: self._control_point_value,
            SUPPORTED_SPEED_RANGE_UUID: self._supported_speed_range,
            SUPPORTED_INCLINE_RANGE_UUID: self._supported_incline_range,
            TREADMILL_DATA_UUID: self._treadmill_value,
        }
        return uuid_to_value.get(characteristic.uuid, b"")

    def _write_request(self, characteristic: BlessGATTCharacteristic, value: bytes) -> bool:  # noqa: PLR0911
        """Handle FTMS control point writes for speed/incline targets."""
        if characteristic.uuid != FITNESS_MACHINE_CONTROL_POINT_UUID:
            return False
        if not value:
            self._send_control_point_response(
                0x00,
                result=ControlPointResult.INVALID_PARAMETER,
            )
            return False

        opcode = value[0]
        try:
            try:
                op = ControlPointOpcode(opcode)
            except ValueError:
                op = None
            match op:
                case ControlPointOpcode.REQUEST_CONTROL:
                    # Always grant control to the FTMS client.
                    self._send_control_point_response(opcode, result=ControlPointResult.SUCCESS)
                    return True
                case ControlPointOpcode.SET_TARGET_SPEED:
                    return self._handle_target_speed(opcode, value)
                case ControlPointOpcode.SET_TARGET_INCLINE:
                    return self._handle_target_incline(opcode, value)
                case ControlPointOpcode.START_OR_RESUME | ControlPointOpcode.STOP_OR_PAUSE:
                    LOGGER.warning("Start/stop control not supported by IFitBleClient")
                    self._send_control_point_response(
                        opcode,
                        result=ControlPointResult.OP_CODE_NOT_SUPPORTED,
                    )
                    return False
                case _:
                    LOGGER.warning("Unsupported control point opcode %s", opcode)
                    self._send_control_point_response(
                        opcode,
                        result=ControlPointResult.OP_CODE_NOT_SUPPORTED,
                    )
                    return False
        except Exception:  # pragma: no cover - defensive guard
            LOGGER.exception("Control point handling failed")
            self._send_control_point_response(
                opcode,
                result=ControlPointResult.OPERATION_FAILED,
            )
            return False

    def _handle_target_speed(self, opcode: int, value: bytes) -> bool:
        """Parse a speed target request and forward it to the iFit client."""
        if len(value) < MIN_TARGET_VALUE_LENGTH:
            self._send_control_point_response(
                opcode,
                result=ControlPointResult.INVALID_PARAMETER,
            )
            return False
        (raw,) = unpack("<H", value[1:3])
        kph = raw / 100
        # Convert FTMS 0.01 km/h units to kph.
        LOGGER.info("Setting target speed to %.2f kph", kph)
        self._schedule_task(self._client.write_characteristics({"Kph": kph}), "set_speed")
        self._send_control_point_response(opcode, result=ControlPointResult.SUCCESS)
        return True

    def _handle_target_incline(self, opcode: int, value: bytes) -> bool:
        """Parse an incline target request and forward it to the iFit client."""
        if len(value) < MIN_TARGET_VALUE_LENGTH:
            self._send_control_point_response(
                opcode,
                result=ControlPointResult.INVALID_PARAMETER,
            )
            return False
        (raw,) = unpack("<h", value[1:3])
        incline = raw / 10
        # Convert FTMS 0.1% units to incline percentage.
        LOGGER.info("Setting target incline to %.1f", incline)
        self._schedule_task(self._client.write_characteristics({"Incline": incline}), "set_incline")
        self._send_control_point_response(opcode, result=ControlPointResult.SUCCESS)
        return True

    def _send_control_point_response(
        self,
        opcode: int,
        *,
        result: ControlPointResult,
    ) -> None:
        """Send a control point response via indication."""
        payload = encode_control_point_response(opcode, result)
        self._control_point_value = payload
        self._server.get_characteristic(FITNESS_MACHINE_CONTROL_POINT_UUID).value = payload
        self._server.update_value(FTMS_SERVICE_UUID, FITNESS_MACHINE_CONTROL_POINT_UUID)

    def _schedule_task(self, coro: Coroutine[object, object, None], label: str) -> None:
        """Schedule a background task and log failures."""
        task = self._loop.create_task(coro)
        task.add_done_callback(lambda t: self._log_task_exception(t, label))

    @staticmethod
    def _log_task_exception(task: asyncio.Future[None], label: str) -> None:
        """Log exceptions from background tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            LOGGER.error("Background task %s failed: %s", label, exc)

    async def _notify_loop(self) -> None:
        """Continuously poll the iFit client and notify FTMS subscribers."""
        while True:
            await self._update_treadmill_data()
            await asyncio.sleep(self._config.update_interval)

    async def _update_treadmill_data(self) -> None:
        """Read iFit values and update FTMS treadmill/status characteristics."""
        values = await self._client.read_characteristics(
            ["CurrentKph", "CurrentIncline", "Distance", "Pulse", "Mode"]
        )
        current_kph = float(values.get("CurrentKph", 0.0))
        current_incline = float(values.get("CurrentIncline", 0.0))
        distance = float(values.get("Distance", 0.0))
        pulse_data = values.get("Pulse", {})
        heart_rate = int(pulse_data.get("pulse", 0)) if isinstance(pulse_data, dict) else 0
        mode = values.get("Mode")

        # Compose FTMS treadmill data with optional fields for incline/distance/hr.
        self._treadmill_value = encode_treadmill_data(
            speed_kph=current_kph,
            incline_percent=current_incline,
            distance_km=distance,
            heart_rate_bpm=heart_rate if heart_rate else None,
        )
        self._server.get_characteristic(TREADMILL_DATA_UUID).value = self._treadmill_value
        self._server.update_value(FTMS_SERVICE_UUID, TREADMILL_DATA_UUID)

        status = self._encode_status_from_mode(mode)
        if status:
            self._status_value = status
            self._server.get_characteristic(FITNESS_MACHINE_STATUS_UUID).value = status
            self._server.update_value(FTMS_SERVICE_UUID, FITNESS_MACHINE_STATUS_UUID)

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
        self._supported_speed_range = encode_supported_speed_range(self._ranges)
        self._supported_incline_range = encode_supported_incline_range(self._ranges)
        self._server.get_characteristic(
            SUPPORTED_SPEED_RANGE_UUID
        ).value = self._supported_speed_range
        self._server.get_characteristic(
            SUPPORTED_INCLINE_RANGE_UUID
        ).value = self._supported_incline_range

    @staticmethod
    def _encode_status_from_mode(mode: object) -> bytes | None:
        """Map iFit mode values to FTMS status messages."""
        if isinstance(mode, Mode):
            if mode == Mode.ACTIVE:
                return encode_status_started()
            if mode in {Mode.PAUSE, Mode.SUMMARY, Mode.IDLE}:
                return encode_status_stopped()
        return None
