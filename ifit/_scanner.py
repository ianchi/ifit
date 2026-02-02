from __future__ import annotations

from dataclasses import dataclass

from bleak import BleakScanner


@dataclass(frozen=True)
class IFitDevice:
    """Metadata for a discovered iFit device."""

    address: str
    name: str | None
    manufacturer_data: bytes


def _normalize_ble_code(code: str) -> str:
    """Normalize and validate a 4-character BLE code."""
    cleaned = code.strip().lower()
    if len(cleaned) != 4 or any(c not in "0123456789abcdef" for c in cleaned):
        raise ValueError("BLE code must be a 4-character hex string")
    return cleaned


async def find_ifit_device(code: str, timeout: float = 10.0) -> IFitDevice:
    """Scan for an iFit device matching the displayed BLE code."""
    normalized = _normalize_ble_code(code)
    # Reverse byte order: displayed code "50dd" -> search for "dd" + "dd50" (little-endian)
    reversed_code = normalized[2:4] + normalized[0:2]
    suffix = bytes.fromhex(f"dd{reversed_code}")

    # Manufacturer data suffix matches the BLE code shown on the equipment.
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for device, adv_data in devices.values():
        if not adv_data.manufacturer_data:
            continue
        for payload in adv_data.manufacturer_data.values():
            if payload.endswith(suffix):
                return IFitDevice(
                    address=device.address,
                    name=device.name,
                    manufacturer_data=payload,
                )

    raise TimeoutError("No iFit device found with the provided BLE code")


async def find_all_ifit_devices(timeout: float = 10.0) -> list[IFitDevice]:
    """Scan for all iFit devices in range."""
    ifit_devices = []

    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for device, adv_data in devices.values():
        if not adv_data.manufacturer_data:
            continue

        # Look for iFit manufacturer data pattern (ends with 'dd' + 4-char hex code)
        for payload in adv_data.manufacturer_data.values():
            if len(payload) >= 3 and payload[-3] == 0xDD:
                ifit_devices.append(
                    IFitDevice(
                        address=device.address,
                        name=device.name,
                        manufacturer_data=payload,
                    )
                )
                break

    return ifit_devices
