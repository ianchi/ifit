"""Monitoring commands for iFit CLI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from ..client import ActivationError, IFitBleClient

LOGGER = logging.getLogger(__name__)


def _handle_activation_error(address: str) -> None:
    """Handle activation code errors with user-friendly messages."""
    print("\n✗ Incorrect activation code")
    print("  The provided activation code is invalid for this device.")
    print(f"\n  Use 'ifit activate {address}' to discover the correct code.")
    sys.exit(1)


def _format_value(value: object) -> str:
    """Format a characteristic value for display."""
    if isinstance(value, (int, float)):
        return f"{value:>12.1f}"
    if isinstance(value, dict):
        # For complex values like Pulse, try to get a simple representation
        simple_val = value.get("pulse", value.get("value", str(value)[:10]))
        return f"{simple_val:>12}"
    return f"{str(value)[:12]:>12}"


async def _monitor_custom_characteristics(
    client: IFitBleClient,
    characteristics: list[str | int],
    char_names: list[str],
    interval: float,
) -> None:
    """Monitor custom set of characteristics."""
    print(f"{'Time':>6} | " + " | ".join(f"{c:>12}" for c in char_names))
    print("-" * (10 + len(char_names) * 16))

    iteration = 0
    while True:
        values = await client.read_characteristics(characteristics)

        # Display values for each requested characteristic
        row = f"{iteration:>6} | "
        for char_name in char_names:
            value = values.get(char_name, "N/A")
            row += f"{_format_value(value)} | "

        print(row.rstrip(" |"))
        iteration += 1
        await asyncio.sleep(interval)


async def monitor(args: argparse.Namespace) -> None:
    """Monitor real-time values from equipment."""
    print(f"Connecting to {args.address}...\n")

    client = IFitBleClient(args.address)
    try:
        await client.connect()
        print("Monitoring (Ctrl+C to stop)...\n")

        # Parse custom characteristics if provided, otherwise use defaults
        if args.characteristics:
            custom_chars: list[str | int] = []
            char_names = args.characteristics
            for char in args.characteristics:
                try:
                    custom_chars.append(int(char))
                except ValueError:
                    custom_chars.append(char)
        else:
            # Default characteristics to monitor
            custom_chars: list[str | int] = ["Kph", "CurrentIncline", "Pulse", "Mode"]
            char_names = ["Kph", "Incline", "Pulse", "Mode"]

        await _monitor_custom_characteristics(client, custom_chars, char_names, args.interval)

    except KeyboardInterrupt:
        print("\n\nMonitoring stopped")
    except ActivationError:
        _handle_activation_error(args.address)
    except ValueError as e:
        print(f"\n✗ Error: {e}")
        LOGGER.error("Monitor error", exc_info=True)
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        LOGGER.error("Monitor error", exc_info=True)
        sys.exit(1)
    finally:
        await client.disconnect()
