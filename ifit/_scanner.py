from __future__ import annotations

from dataclasses import dataclass

from bleak import BleakScanner


@dataclass(frozen=True)
class IFitDevice:
    """Metadata for a discovered iFit device."""

    address: str
    name: str | None
    manufacturer_data: bytes
    code: str
    manufacturer_company_id: int | None = None


def _normalize_ble_code(code: str) -> str:
    """Normalize and validate a 4-character BLE code."""
    cleaned = code.strip().lower()
    if len(cleaned) != 4 or any(c not in "0123456789abcdef" for c in cleaned):
        raise ValueError("BLE code must be a 4-character hex string")
    return cleaned


def _extract_displayed_code(manufacturer_data: bytes) -> str:
    """Extract the displayed BLE code from manufacturer data.

    The last 3 bytes contain: 0xdd + reversed 2-byte code.
    Reverse the code bytes to get the displayed format.
    """
    if len(manufacturer_data) < 3 or manufacturer_data[-3] != 0xDD:
        raise ValueError("Invalid manufacturer data format")
    # Last 2 bytes are the reversed code, reverse them back
    reversed_code = manufacturer_data[-2:]
    return reversed_code[::-1].hex()


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
        for company_id, payload in adv_data.manufacturer_data.items():
            if payload.endswith(suffix):
                return IFitDevice(
                    address=device.address,
                    name=device.name,
                    manufacturer_data=payload,
                    code=_extract_displayed_code(payload),
                    manufacturer_company_id=company_id,
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
        for company_id, payload in adv_data.manufacturer_data.items():
            if len(payload) >= 3 and payload[-3] == 0xDD:
                ifit_devices.append(
                    IFitDevice(
                        address=device.address,
                        name=device.name,
                        manufacturer_data=payload,
                        code=_extract_displayed_code(payload),
                        manufacturer_company_id=company_id,
                    )
                )
                break

    return ifit_devices
