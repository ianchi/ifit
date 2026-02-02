"""iFit BLE Library.

A Python library for communicating with iFit-enabled fitness equipment via Bluetooth Low Energy.
Supports protocol communication, FTMS relay, activation code discovery, and more.
"""

from ._scanner import IFitDevice, find_all_ifit_devices, find_ifit_device
from .client import IFitBleClient
from .client.protocol import (
    Command,
    EquipmentInformation,
    Mode,
    PulseSource,
    SportsEquipment,
    WriteValue,
)

# Optional FTMS support
try:
    from .ftms import FtmsBleRelay, FtmsConfig

    __ftms_available = True
except ImportError:
    __ftms_available = False

# Optional activation discovery support
try:
    from .interceptor import discover_activation_code

    __interceptor_available = True
except ImportError:
    __interceptor_available = False

__version__ = "0.1.0b1"

__all__ = [
    "Command",
    "EquipmentInformation",
    "IFitBleClient",
    "IFitDevice",
    "Mode",
    "PulseSource",
    "SportsEquipment",
    "WriteValue",
    "find_all_ifit_devices",
    "find_ifit_device",
]

if __ftms_available:
    __all__.extend(["FtmsBleRelay", "FtmsConfig"])

if __interceptor_available:
    __all__.append("discover_activation_code")
