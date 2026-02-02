"""iFit BLE client and protocol implementation.

For protocol definitions, import from ifit.client.protocol:
    from ifit.client.protocol import Command, Mode, SportsEquipment, etc.
"""

from ._client import IFitBleClient
from .protocol import (
    Command,
    EquipmentInformation,
    Mode,
    PulseSource,
    SportsEquipment,
    WriteValue,
)

__all__ = [
    "Command",
    "EquipmentInformation",
    "IFitBleClient",
    "Mode",
    "PulseSource",
    "SportsEquipment",
    "WriteValue",
]
