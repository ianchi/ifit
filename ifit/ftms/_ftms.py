from __future__ import annotations

from enum import IntEnum
from struct import pack

from pydantic import BaseModel, Field, model_validator


def bt16(uuid16: int) -> str:
    """Convert a 16-bit SIG UUID to a 128-bit UUID string."""
    return f"0000{uuid16:04x}-0000-1000-8000-00805f9b34fb"


# Standard Bluetooth services
GAP_SERVICE_UUID = bt16(0x1800)
GATT_SERVICE_UUID = bt16(0x1801)
DEVICE_INFORMATION_SERVICE_UUID = bt16(0x180A)

# GAP characteristics
DEVICE_NAME_UUID = bt16(0x2A00)
APPEARANCE_UUID = bt16(0x2A01)

# GATT characteristics
SERVICE_CHANGED_UUID = bt16(0x2A05)

# Device Information Service characteristics
MANUFACTURER_NAME_UUID = bt16(0x2A29)
MODEL_NUMBER_UUID = bt16(0x2A24)
SERIAL_NUMBER_UUID = bt16(0x2A25)
HARDWARE_REVISION_UUID = bt16(0x2A27)
FIRMWARE_REVISION_UUID = bt16(0x2A26)
SOFTWARE_REVISION_UUID = bt16(0x2A28)

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

# FTMS Treadmill Data flags (bits indicate which optional fields are present)
TREADMILL_FLAG_MORE_DATA = 0x0001  # Bit 0: More Data (1 if fragmented, 0 if complete)
TREADMILL_FLAG_DISTANCE = 0x0004  # Bit 2: Total Distance Present
TREADMILL_FLAG_INCLINE = 0x0008  # Bit 3: Inclination and Ramp Angle Setting Present
TREADMILL_FLAG_HEART_RATE = 0x0100  # Bit 8: Heart Rate Present


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

    @model_validator(mode="after")
    def validate_ranges(self) -> FtmsRanges:
        """Ensure min <= max for all ranges."""
        if self.min_kph > self.max_kph:
            msg = f"min_kph ({self.min_kph}) > max_kph ({self.max_kph})"
            raise ValueError(msg)
        if self.min_incline > self.max_incline:
            msg = f"min_incline ({self.min_incline}) > max_incline ({self.max_incline})"
            raise ValueError(msg)
        return self


def encode_fitness_machine_feature(
    *,
    supports_inclination: bool = True,
    supports_total_distance: bool = True,
    supports_heart_rate: bool = True,
    supports_speed_target: bool = True,
    supports_incline_target: bool = True,
) -> bytes:
    """Encode Fitness Machine Feature bitfields."""
    fitness_features = 0
    if supports_total_distance:
        fitness_features |= 1 << 2
    if supports_inclination:
        fitness_features |= 1 << 3
    if supports_heart_rate:
        fitness_features |= 1 << 10

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
    distance_m: float | None,
    heart_rate_bpm: int | None,
) -> bytearray:
    """Encode treadmill data with optional incline, distance, and heart rate.

    Field order per FTMS spec:
    1. Flags (uint16)
    2. Instantaneous Speed (uint16) - always present
    3. Average Speed (uint16) - if bit 1 set
    4. Total Distance (uint24) - if bit 2 set
    5. Inclination (sint16) - if bit 3 set
    6. Ramp Angle Setting (sint16) - if bit 3 set
    7. Positive Elevation Gain (uint16) - if bit 4 set
    8. Instantaneous Pace (uint8) - if bit 5 set
    9. Average Pace (uint8) - if bit 6 set
    10. Expended Energy (complex) - if bit 7 set
    11. Heart Rate (uint8) - if bit 8 set
    12. Metabolic Equivalent (uint8) - if bit 9 set
    13. Elapsed Time (uint16) - if bit 10 set
    14. Remaining Time (uint16) - if bit 11 set
    15. Force on Belt and Power Output (complex) - if bit 12 set
    """
    flags = 0
    # More Data bit = 0: Our data always fits in one notification (~12 bytes max)
    # More Data bit would be 1 only if we needed to fragment across multiple notifications

    speed_raw = _u16_or_unknown(speed_kph, 100.0, 0xFFFF)
    payload = bytearray(pack("<H", flags))
    payload += pack("<H", speed_raw)

    # Note: Average Speed (bit 1) not implemented - skip to Distance

    if distance_m is not None:
        flags |= TREADMILL_FLAG_DISTANCE
        distance_raw = max(0, min(round(distance_m), 0xFFFFFF))
        payload += distance_raw.to_bytes(3, "little")

    if incline_percent is not None:
        flags |= TREADMILL_FLAG_INCLINE
        incline_raw = _s16_or_unknown(incline_percent, 10.0, 0x7FFF)
        # Per FTMS spec, when bit 3 is set, BOTH inclination and ramp angle must be present
        payload += pack("<h", incline_raw)
        # Ramp angle setting - for simple treadmills, same as inclination
        payload += pack("<h", incline_raw)

    # Note: Elevation Gain (bit 4), Pace fields (bits 5-6), Energy (bit 7) not implemented

    if heart_rate_bpm is not None:
        flags |= TREADMILL_FLAG_HEART_RATE
        hr_raw = max(0, min(int(heart_rate_bpm), 0xFF))
        payload += pack("<B", hr_raw)

    # Update flags at the beginning of payload
    payload[0:2] = pack("<H", flags)
    return payload


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
