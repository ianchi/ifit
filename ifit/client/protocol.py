from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

RESPONSE_OK_CODE = 2
MAX_BYTES_PER_MESSAGE = 18

# Message format constants
MIN_HEADER_LENGTH = 4
MIN_CHUNK_LENGTH = 2
MIN_COMMAND_HEADER_LENGTH = 4
MIN_FEATURES_RESPONSE_LENGTH = 9
MIN_CHECKSUM_LENGTH = 5


class SportsEquipment(IntEnum):
    """Sports equipment identifiers used by the iFit protocol."""

    GENERAL = 2
    TREADMILL = 4


class PulseSource(IntEnum):
    """Pulse source identifiers reported by the equipment."""

    NO = 0
    HAND = 1
    UNKNOWN = 2
    UNKNOWN2 = 3
    BLE = 4


class Mode(IntEnum):
    """Equipment mode identifiers."""

    UNKNOWN = 0
    IDLE = 1
    ACTIVE = 2
    PAUSE = 3
    SUMMARY = 4
    SETTINGS = 7
    MISSING_SAFETY_KEY = 8


class Command(IntEnum):
    """Command identifiers used in request headers."""

    WRITE_AND_READ = 0x02
    CALIBRATE = 0x06
    SUPPORTED_CAPABILITIES = 0x80
    EQUIPMENT_INFORMATION = 0x81
    EQUIPMENT_REFERENCE = 0x82
    EQUIPMENT_FIRMWARE = 0x84
    SUPPORTED_COMMANDS = 0x88
    ENABLE = 0x90
    EQUIPMENT_SERIAL = 0x95


class MessageIndex(IntEnum):
    """Chunk index markers for BLE message framing."""

    HEADER = 0xFE
    EOF = 0xFF


@dataclass(frozen=True)
class Converter:
    """Converter describing buffer encoding/decoding for a characteristic."""

    size: int
    from_buffer: Callable[[bytes, int], Any]
    to_buffer: Callable[[bytearray, int, Any], int]


@dataclass(frozen=True)
class CharacteristicDefinition:
    """Definition of a characteristic and its converter."""

    name: str
    id: int
    read_only: bool
    converter: Converter | None


@dataclass(frozen=True)
class CapabilityDefinition:
    """Definition of a high-level capability and its characteristic id."""

    id: int
    characteristic_id: int


@dataclass
class EquipmentInformation:
    """Stateful equipment metadata and current values."""

    equipment: SportsEquipment
    characteristics: dict[int, CharacteristicDefinition]
    supported_capabilities: list[int] = field(default_factory=list)
    supported_commands: list[int] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    serial_number: str | None = None
    firmware_version: str | None = None
    reference_number: int | None = None


@dataclass(frozen=True)
class WriteValue:
    """Represents a write request for a single characteristic."""

    characteristic: CharacteristicDefinition
    value: Any


def _make_int_converter(size: int, byteorder: str = "little") -> Converter:  # pyright: ignore[reportUnknownParameterType]
    """Factory for integer converters."""

    def from_buffer(buffer: bytes, pos: int) -> int:
        return int.from_bytes(buffer[pos : pos + size], byteorder)  # type: ignore[arg-type]

    def to_buffer(buf: bytearray, pos: int, value: int) -> int:
        buf[pos : pos + size] = int(value).to_bytes(size, byteorder)  # type: ignore[arg-type]
        return pos + size

    return Converter(size, from_buffer, to_buffer)


def _make_scaled_converter(scale: float, size: int = 2) -> Converter:
    """Factory for scaled numeric converters."""

    def from_buffer(buffer: bytes, pos: int) -> float:
        return int.from_bytes(buffer[pos : pos + size], "little") / scale

    def to_buffer(buf: bytearray, pos: int, value: float) -> int:
        buf[pos : pos + size] = int(value * scale).to_bytes(size, "little")
        return pos + size

    return Converter(size, from_buffer, to_buffer)


def _make_bool_converter() -> Converter:
    """Factory for boolean converters."""

    def from_buffer(buffer: bytes, pos: int) -> bool:
        return buffer[pos] == 1

    def to_buffer(buf: bytearray, pos: int, value: bool) -> int:
        buf[pos] = 1 if value else 0
        return pos + 1

    return Converter(1, from_buffer, to_buffer)


def _pulse_from_buffer(buffer: bytes, pos: int) -> dict[str, Any]:
    """Decode pulse data including source information."""
    pulse = buffer[pos]
    average = buffer[pos + 1]
    count = buffer[pos + 2]
    source = PulseSource(buffer[pos + 3])
    return {"pulse": pulse, "average": average, "count": count, "source": source}


def _pulse_to_buffer(buffer: bytearray, pos: int, value: Mapping[str, Any]) -> int:
    """Encode pulse data; only pulse and source are used."""
    pulse = int(value.get("pulse", 0))
    source = PulseSource(value.get("source", PulseSource.NO))
    buffer[pos] = pulse & 0xFF
    buffer[pos + 1] = 0
    buffer[pos + 2] = 0
    buffer[pos + 3] = int(source)
    return pos + 4


CONVERTERS = {
    "double": _make_scaled_converter(100.0),
    "boolean": _make_bool_converter(),
    "mode": _make_int_converter(1),
    "calories": _make_scaled_converter(100000000 / 1024, size=4),
    "pulse": Converter(4, _pulse_from_buffer, _pulse_to_buffer),
    "one_byte_int": _make_int_converter(1),
    "two_bytes_int": _make_int_converter(2),
    "four_bytes_int": _make_int_converter(4),
}


CHARACTERISTICS = {
    "Kph": CharacteristicDefinition("Kph", 0, read_only=False, converter=CONVERTERS["double"]),
    "Incline": CharacteristicDefinition(
        "Incline", 1, read_only=False, converter=CONVERTERS["double"]
    ),
    "CurrentDistance": CharacteristicDefinition(
        "CurrentDistance", 4, read_only=True, converter=CONVERTERS["four_bytes_int"]
    ),
    "Distance": CharacteristicDefinition(
        "Distance", 6, read_only=True, converter=CONVERTERS["four_bytes_int"]
    ),
    "Volume": CharacteristicDefinition(
        "Volume", 9, read_only=False, converter=CONVERTERS["one_byte_int"]
    ),
    "Pulse": CharacteristicDefinition("Pulse", 10, read_only=False, converter=CONVERTERS["pulse"]),
    "UpTime": CharacteristicDefinition(
        "UpTime", 11, read_only=True, converter=CONVERTERS["four_bytes_int"]
    ),
    "Mode": CharacteristicDefinition("Mode", 12, read_only=False, converter=CONVERTERS["mode"]),
    "Calories": CharacteristicDefinition(
        "Calories", 13, read_only=True, converter=CONVERTERS["calories"]
    ),
    "CurrentKph": CharacteristicDefinition(
        "CurrentKph", 16, read_only=True, converter=CONVERTERS["double"]
    ),
    "CurrentIncline": CharacteristicDefinition(
        "CurrentIncline", 17, read_only=True, converter=CONVERTERS["double"]
    ),
    "CurrentTime": CharacteristicDefinition(
        "CurrentTime", 20, read_only=True, converter=CONVERTERS["four_bytes_int"]
    ),
    "CurrentCalories": CharacteristicDefinition(
        "CurrentCalories", 21, read_only=True, converter=CONVERTERS["calories"]
    ),
    "MaxIncline": CharacteristicDefinition(
        "MaxIncline", 27, read_only=True, converter=CONVERTERS["double"]
    ),
    "MinIncline": CharacteristicDefinition(
        "MinIncline", 28, read_only=True, converter=CONVERTERS["double"]
    ),
    "MaxKph": CharacteristicDefinition(
        "MaxKph", 30, read_only=True, converter=CONVERTERS["double"]
    ),
    "MinKph": CharacteristicDefinition(
        "MinKph", 31, read_only=True, converter=CONVERTERS["double"]
    ),
    "Metric": CharacteristicDefinition(
        "Metric", 36, read_only=False, converter=CONVERTERS["boolean"]
    ),
    "MaxPulse": CharacteristicDefinition(
        "MaxPulse", 49, read_only=True, converter=CONVERTERS["one_byte_int"]
    ),
    "AverageIncline": CharacteristicDefinition(
        "AverageIncline", 52, read_only=True, converter=CONVERTERS["double"]
    ),
    "TotalTime": CharacteristicDefinition(
        "TotalTime", 70, read_only=True, converter=CONVERTERS["four_bytes_int"]
    ),
    "PausedTime": CharacteristicDefinition(
        "PausedTime", 103, read_only=True, converter=CONVERTERS["four_bytes_int"]
    ),
    "X1": CharacteristicDefinition(
        "X1", 34, read_only=False, converter=CONVERTERS["two_bytes_int"]
    ),
    "X2": CharacteristicDefinition(
        "X2", 35, read_only=False, converter=CONVERTERS["two_bytes_int"]
    ),
    "X3": CharacteristicDefinition("X3", 43, read_only=False, converter=CONVERTERS["double"]),
    "X4": CharacteristicDefinition(
        "X4", 46, read_only=False, converter=CONVERTERS["two_bytes_int"]
    ),
    "X5": CharacteristicDefinition(
        "X5", 69, read_only=False, converter=CONVERTERS["four_bytes_int"]
    ),
    "X6": CharacteristicDefinition(
        "X6", 71, read_only=False, converter=CONVERTERS["two_bytes_int"]
    ),
    "X7": CharacteristicDefinition(
        "X7", 100, read_only=False, converter=CONVERTERS["one_byte_int"]
    ),
}

CHARACTERISTICS_BY_ID = {value.id: value for value in CHARACTERISTICS.values()}

CAPABILITIES = {
    "Speed": CapabilityDefinition(65, 0),
    "Incline": CapabilityDefinition(66, 1),
    "Pulse": CapabilityDefinition(70, 10),
    "Key": CapabilityDefinition(71, 7),
    "Distance": CapabilityDefinition(77, 6),
    "Time": CapabilityDefinition(78, 11),
}

BLE_UUIDS = {
    "service": "000015331412efde1523785feabcd123",
    "rx": "000015351412efde1523785feabcd123",
    "tx": "000015341412efde1523785feabcd123",
}


def get_bitmap(
    equipment_information: EquipmentInformation,
    values: Iterable[CharacteristicDefinition | WriteValue] | None,
) -> bytearray:
    """Build a bitmap of characteristic ids used in a request."""
    payload = bytearray([0])
    if values is None:
        return payload

    for item in values:
        characteristic = item.characteristic if isinstance(item, WriteValue) else item
        # Only include characteristics supported by the connected equipment.
        if characteristic.id not in equipment_information.characteristics:
            continue
        pos = (characteristic.id // 8) + 1
        if pos > payload[0]:
            payload[0] = pos
            payload.extend([0] * (pos - len(payload) + 1))
        bit = characteristic.id - (pos - 1) * 8
        mask = 1 << bit
        payload[pos] |= mask

    for index in range(1, payload[0]):
        if index >= len(payload):
            payload.extend([0])
    return payload


def get_write_values(writes: Iterable[WriteValue] | None) -> bytearray | None:
    """Encode write values in ascending characteristic id order."""
    if not writes:
        return None

    writes_list = list(writes)
    size = 0
    for write in writes_list:
        converter = write.characteristic.converter
        size += converter.size if converter else 1

    payload = bytearray(size)
    pos = 0
    # iFit expects values ordered by characteristic id.
    for write in sorted(writes_list, key=lambda item: item.characteristic.id):
        converter = write.characteristic.converter
        if converter:
            pos = converter.to_buffer(payload, pos, write.value)
        else:
            payload[pos] = 0
            pos += 1
    return payload


def build_request(
    equipment: SportsEquipment | int,
    command: Command | int,
    payload: bytes | None = None,
) -> bytes:
    """Build the raw request payload for a command."""
    payload = payload or b""
    length = len(payload) + 4
    buf = bytearray(length + 4)

    checksum = int(equipment) + length + int(command)

    # Fixed header prefix used by iFit equipment.
    pos = 0
    buf[pos] = 2
    pos += 1
    buf[pos] = 4
    pos += 1
    buf[pos] = 2
    pos += 1
    buf[pos] = length
    pos += 1
    buf[pos] = int(equipment)
    pos += 1
    buf[pos] = length
    pos += 1
    buf[pos] = int(command)
    pos += 1
    for byte in payload:
        checksum += byte
        buf[pos] = byte
        pos += 1
    # Checksum is the low byte of the sum of header fields and payload bytes.
    buf[pos] = checksum & 0xFF
    return bytes(buf)


def request_header(request: bytes, number_of_writes: int) -> bytes:
    """Build the BLE header chunk for a framed request."""
    buf = bytearray(4)
    buf[0] = MessageIndex.HEADER
    buf[1] = 2
    buf[2] = len(request)
    buf[3] = number_of_writes + 1
    return bytes(buf)


def build_write_messages(request: bytes) -> list[bytes]:
    """Split a request into BLE chunks (header + payload fragments)."""
    number_of_writes = (len(request) + MAX_BYTES_PER_MESSAGE - 1) // MAX_BYTES_PER_MESSAGE
    messages = [request_header(request, number_of_writes)]

    offset = 0
    counter = 1
    done = offset == len(request)
    while not done:
        message = bytearray(20)
        length = (
            MAX_BYTES_PER_MESSAGE
            if counter < number_of_writes
            else ((len(request) - 1) % MAX_BYTES_PER_MESSAGE + 1)
        )
        # First byte is the chunk index (or EOF for the final chunk).
        message[0] = counter - 1
        message[1] = length
        message[2 : 2 + length] = request[offset : offset + length]

        offset += length
        done = offset == len(request)

        if done:
            message[0] = MessageIndex.EOF
        else:
            counter += 1
        messages.append(bytes(message))
    return messages


def determine_message_index(message: bytes) -> int:
    """Return the chunk index byte from a BLE message."""
    if len(message) < 1:
        raise ValueError(f"unexpected message format: {message.hex()}")
    return message[0]


def get_header_from_response(message: bytes) -> tuple[int, bytearray]:
    """Parse the response header chunk and return expected count + buffer."""
    if len(message) < MIN_HEADER_LENGTH:
        raise ValueError("unexpected message format - four bytes expected")
    if message[0] != MessageIndex.HEADER:
        raise ValueError(f"message is not a header: expected 0xfe got {message[0]}")
    buf_length = message[2]
    upcoming_messages = message[3] - 1
    buffer = bytearray(buf_length)
    return upcoming_messages, buffer


def fill_response(buffer: bytearray, number_of_reads: int, message: bytes) -> None:
    """Copy a response chunk into the buffer based on its index."""
    if buffer is None:
        raise ValueError("undefined buffer")
    if len(message) < MIN_CHUNK_LENGTH:
        raise ValueError("unexpected message format - two bytes expected")

    index = message[0]
    if index != MessageIndex.EOF and index >= number_of_reads:
        raise ValueError(
            f"index of message exceeds number of expected reads: {index}>={number_of_reads}"
        )

    # Map the chunk index to its offset in the full response buffer.
    pos = (number_of_reads - 1 if index == MessageIndex.EOF else index) * 18
    length = message[1]
    if length + pos > len(buffer):
        raise ValueError(
            f"amount of data in message exceeds buffer size: {length + pos}>{len(buffer)}"
        )
    buffer[pos : pos + length] = message[2 : 2 + length]


def parse_command_header(response: bytes, expected_command: Command | int) -> dict[str, Any]:
    """Validate and parse the command response header."""
    if len(response) < MIN_COMMAND_HEADER_LENGTH:
        raise ValueError("unexpected buffer length - must be greater than 4 bytes")
    length = response[3]
    if len(response) != length + 4:
        raise ValueError(f"buffer length is {len(response)} but header says {length + 4} bytes")

    pos = 4
    equipment = response[pos]
    pos += 1
    pos += 1
    command = response[pos]
    pos += 1
    if command != int(expected_command):
        raise ValueError(f"expected command {int(expected_command)} but got {command}")
    status = response[pos]
    if status != RESPONSE_OK_CODE:
        raise ValueError(f"response code not OK: {status}")
    return {"equipment": equipment}


def parse_equipment_information_response(response: bytes) -> dict[int, CharacteristicDefinition]:
    """Parse equipment information and return supported characteristics."""
    pos = 16
    length = response[pos]
    pos += 1
    characteristics: dict[int, CharacteristicDefinition] = {}
    for offset in range(length):
        byte = response[pos]
        pos += 1
        for bit in range(8):
            mask = 1 << bit
            if byte & mask:
                char_id = offset * 8 + bit
                characteristic = CHARACTERISTICS_BY_ID.get(char_id)
                if characteristic:
                    characteristics[characteristic.id] = characteristic
    return characteristics


def parse_features_response(response: bytes) -> list[int]:
    """Parse a list of supported feature ids from a response."""
    if len(response) < MIN_FEATURES_RESPONSE_LENGTH:
        # Response too short, return empty list
        return []
    pos = 8
    count = response[pos]
    pos += 1

    # Validate we have enough data for all expected items
    if len(response) < pos + count:
        # Not enough data, return what we can parse
        count = len(response) - pos

    capabilities: list[int] = []
    for _ in range(count):
        capabilities.append(response[pos])
        pos += 1
    return capabilities


def parse_write_and_read_response(
    equipment_information: EquipmentInformation,
    response: bytes,
    reads: Iterable[CharacteristicDefinition],
) -> dict[str, Any]:
    """Parse read values from a write-and-read response."""
    result: dict[str, Any] = {}
    read_list = sorted(reads, key=lambda item: item.id)

    pos = 8
    for characteristic in read_list:
        if characteristic.id not in equipment_information.characteristics:
            continue
        converter = characteristic.converter
        if converter:
            result[characteristic.name] = converter.from_buffer(response, pos)
            pos += converter.size
    return result


@dataclass
class _ResponseParser:
    """Generic response parser configuration."""

    min_length: int
    extractor: Callable[[bytes], Any]


def _parse_firmware(response: bytes) -> str | None:
    """Extract firmware version string from response."""
    firmware_str = response[11:].decode("ascii", errors="ignore")
    firmware_clean = firmware_str.split("\x01")[0].split("\x00")[0]
    return firmware_clean if firmware_clean else None


def _parse_reference(response: bytes) -> int:
    """Extract reference number from response."""
    return int.from_bytes(response[15:19], "little")


def _parse_serial(response: bytes) -> str | None:
    """Extract serial number from response."""
    serial_length = response[8]
    if len(response) < 9 + serial_length:
        return None
    serial_bytes = response[9 : 9 + serial_length]
    serial_number = serial_bytes.decode("ascii", errors="ignore").strip()
    return serial_number if serial_number else None


_RESPONSE_PARSERS = {
    Command.EQUIPMENT_FIRMWARE: _ResponseParser(12, _parse_firmware),
    Command.EQUIPMENT_REFERENCE: _ResponseParser(19, _parse_reference),
    Command.EQUIPMENT_SERIAL: _ResponseParser(10, _parse_serial),
}


def _parse_metadata_response(response: bytes, command: Command) -> str | int | None:
    """Unified response parser for metadata commands."""
    parser = _RESPONSE_PARSERS.get(command)
    if not parser or len(response) < parser.min_length:
        return None
    try:
        return parser.extractor(response)
    except Exception:  # noqa: BLE001
        return None


def parse_equipment_firmware_response(response: bytes) -> str | None:
    """Parse firmware version from EQUIPMENT_FIRMWARE response."""
    result = _parse_metadata_response(response, Command.EQUIPMENT_FIRMWARE)
    return result if isinstance(result, str) else None


def parse_equipment_reference_response(response: bytes) -> int | None:
    """Parse reference number from EQUIPMENT_REFERENCE response."""
    result = _parse_metadata_response(response, Command.EQUIPMENT_REFERENCE)
    return result if isinstance(result, int) else None


def parse_equipment_serial_response(response: bytes) -> str | None:
    """Parse serial number from EQUIPMENT_SERIAL response."""
    result = _parse_metadata_response(response, Command.EQUIPMENT_SERIAL)
    return result if isinstance(result, str) else None


def validate_checksum(response: bytes) -> None:
    """Validate the response checksum; raises on mismatch."""
    if len(response) <= MIN_CHECKSUM_LENGTH:
        return
    checksum = sum(response[4:-1]) & 0xFF
    if checksum != response[-1]:
        raise ValueError("checksum invalid")


@dataclass
class CommandConfig:
    """Configuration for equipment command queries."""

    command: Command
    parser: Callable[[bytes], Any]
    store_in: str  # Field name in EquipmentInformation to store result
    payload: bytes = b""  # Payload to send with command
    check_supported: bool = True  # Whether to check if command is supported first


# Core initialization commands - always executed
CORE_COMMANDS = [
    CommandConfig(
        Command.SUPPORTED_CAPABILITIES,
        parse_features_response,
        "supported_capabilities",
        check_supported=False,
    ),
    CommandConfig(
        Command.SUPPORTED_COMMANDS,
        parse_features_response,
        "supported_commands",
        check_supported=False,
    ),
]

# Metadata commands - only executed if supported
METADATA_COMMANDS = [
    CommandConfig(
        Command.EQUIPMENT_REFERENCE,
        parse_equipment_reference_response,
        "reference_number",
        b"\x00\x00",
    ),
    CommandConfig(
        Command.EQUIPMENT_FIRMWARE,
        parse_equipment_firmware_response,
        "firmware_version",
        b"\x00\x00",
    ),
    CommandConfig(
        Command.EQUIPMENT_SERIAL, parse_equipment_serial_response, "serial_number", b"\x00\x00"
    ),
]
