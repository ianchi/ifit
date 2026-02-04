from __future__ import annotations

from enum import IntEnum
from struct import pack

from pydantic import BaseModel, Field


def bt16(uuid16: int) -> str:
    """Convert a 16-bit SIG UUID to a 128-bit UUID string."""
    return f"0000{uuid16:04x}-0000-1000-8000-00805f9b34fb"


# Standard Bluetooth services
GAP_SERVICE_UUID = bt16(0x1800)
GATT_SERVICE_UUID = bt16(0x1801)

# GAP characteristics
DEVICE_NAME_UUID = bt16(0x2A00)
APPEARANCE_UUID = bt16(0x2A01)

# GATT characteristics
SERVICE_CHANGED_UUID = bt16(0x2A05)

# FTMS Service and characteristics
FTMS_SERVICE_UUID = bt16(0x1826)

FITNESS_MACHINE_FEATURE_UUID = bt16(0x2ACC)
TREADMILL_DATA_UUID = bt16(0x2ACD)
FITNESS_MACHINE_CONTROL_POINT_UUID = bt16(0x2AD9)
FITNESS_MACHINE_STATUS_UUID = bt16(0x2ADA)
SUPPORTED_SPEED_RANGE_UUID = bt16(0x2AD4)
SUPPORTED_INCLINE_RANGE_UUID = bt16(0x2AD5)

# GAP Appearance value for treadmill (Generic Running Walking Sensor)
APPEARANCE_TREADMILL = 0x0480

TREADMILL_FLAG_MORE_DATA = 0x0001
TREADMILL_FLAG_INCLINE = 0x0008
TREADMILL_FLAG_DISTANCE = 0x0010
TREADMILL_FLAG_HEART_RATE = 0x0040


class ControlPointOpcode(IntEnum):
    """Fitness Machine Control Point opcodes used by the relay."""

    REQUEST_CONTROL = 0x00
    SET_TARGET_SPEED = 0x02
    SET_TARGET_INCLINE = 0x03
    START_OR_RESUME = 0x07
    STOP_OR_PAUSE = 0x08
    RESPONSE_CODE = 0x80


class ControlPointResult(IntEnum):
    """Fitness Machine Control Point result codes used by the relay."""

    SUCCESS = 0x01
    OP_CODE_NOT_SUPPORTED = 0x02
    INVALID_PARAMETER = 0x03
    OPERATION_FAILED = 0x04


class FitnessMachineStatus(IntEnum):
    """Fitness Machine Status opcodes used by the relay."""

    STOPPED_OR_PAUSED = 0x02
    STARTED_OR_RESUMED = 0x04


class FtmsRanges(BaseModel):
    """Supported ranges for FTMS characteristics."""

    min_kph: float = Field(default=0.0, ge=0.0)
    max_kph: float = Field(default=0.0, ge=0.0)
    min_incline: float = 0.0
    max_incline: float = 0.0
    speed_increment: float = Field(default=0.1, gt=0.0)
    incline_increment: float = Field(default=0.5, gt=0.0)


def encode_fitness_machine_feature(
    *,
    supports_inclination: bool = True,
    supports_speed_target: bool = True,
    supports_incline_target: bool = True,
) -> bytes:
    """Encode Fitness Machine Feature bitfields."""
    fitness_features = 0
    if supports_inclination:
        fitness_features |= 1 << 3

    target_features = 0
    if supports_speed_target:
        target_features |= 1 << 0
    if supports_incline_target:
        target_features |= 1 << 1

    return pack("<II", fitness_features, target_features)


def encode_supported_speed_range(ranges: FtmsRanges) -> bytes:
    """Encode Supported Speed Range (uint16 values in 0.01 km/h)."""
    minimum = max(0, min(round(ranges.min_kph * 100), 0xFFFF))
    maximum = max(0, min(round(ranges.max_kph * 100), 0xFFFF))
    increment = max(1, min(round(ranges.speed_increment * 100), 0xFFFF))
    return pack("<HHH", minimum, maximum, increment)


def encode_supported_incline_range(ranges: FtmsRanges) -> bytes:
    """Encode Supported Incline Range (sint16 values in 0.1%)."""
    minimum = max(-32768, min(round(ranges.min_incline * 10), 32767))
    maximum = max(-32768, min(round(ranges.max_incline * 10), 32767))
    increment = max(1, min(round(ranges.incline_increment * 10), 0xFFFF))
    return pack("<hhH", minimum, maximum, increment)


def _u16_or_unknown(value: float | None, scale: float, unknown: int) -> int:
    """Scale a value into uint16 or return the FTMS unknown sentinel."""
    if value is None:
        return unknown
    raw = round(value * scale)
    return max(0, min(raw, 0xFFFF))


def _s16_or_unknown(value: float | None, scale: float, unknown: int) -> int:
    """Scale a value into sint16 or return the FTMS unknown sentinel."""
    if value is None:
        return unknown
    raw = round(value * scale)
    return max(-32768, min(raw, 32767))


def encode_treadmill_data(
    *,
    speed_kph: float | None,
    incline_percent: float | None,
    distance_km: float | None,
    heart_rate_bpm: int | None,
) -> bytes:
    """Encode treadmill data with optional incline, distance, and heart rate."""
    flags = 0
    # Signal that additional fields may follow.
    flags |= TREADMILL_FLAG_MORE_DATA

    speed_raw = _u16_or_unknown(speed_kph, 100.0, 0xFFFF)
    payload = bytearray(pack("<H", flags))
    payload += pack("<H", speed_raw)

    if incline_percent is not None:
        flags |= TREADMILL_FLAG_INCLINE
        incline_raw = _s16_or_unknown(incline_percent, 10.0, 0x7FFF)
        payload += pack("<h", incline_raw)

    if distance_km is not None:
        flags |= TREADMILL_FLAG_DISTANCE
        distance_raw = max(0, min(round(distance_km * 10), 0xFFFFFF))
        payload += distance_raw.to_bytes(3, "little")

    if heart_rate_bpm is not None:
        flags |= TREADMILL_FLAG_HEART_RATE
        hr_raw = max(0, min(int(heart_rate_bpm), 0xFF))
        payload += pack("<B", hr_raw)

    payload[0:2] = pack("<H", flags)
    return bytes(payload)


def encode_control_point_response(
    request_opcode: int,
    result: ControlPointResult,
) -> bytes:
    """Encode an FTMS Control Point response."""
    return pack(
        "<BBB",
        ControlPointOpcode.RESPONSE_CODE,
        request_opcode & 0xFF,
        int(result) & 0xFF,
    )


def encode_status_started() -> bytes:
    """Encode started/resumed fitness machine status."""
    return pack("<B", FitnessMachineStatus.STARTED_OR_RESUMED)


def encode_status_stopped() -> bytes:
    """Encode stopped/paused fitness machine status."""
    return pack("<B", FitnessMachineStatus.STOPPED_OR_PAUSED)
