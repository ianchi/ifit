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


async def monitor(args: argparse.Namespace) -> None:
    """Monitor real-time values from equipment (code optional for read-only)."""
    # Code is optional - without it, we're in read-only mode
    code = args.code if args.code else None
    mode = "full access" if code else "read-only"

    print(f"Connecting to {args.address} ({mode} mode)...\n")

    client = IFitBleClient(args.address, code)
    try:
        await client.connect()
        print("Monitoring (Ctrl+C to stop)...\n")

        # Print header
        print(f"{'Time':>6} | {'Speed':>8} | {'Incline':>8} | {'Pulse':>8} | {'Mode':>6}")
        print("-" * 50)

        iteration = 0
        while True:
            values = await client.read_current_values()

            speed = values.get("CurrentKph", values.get("Kph", 0.0))
            incline = values.get("CurrentIncline", values.get("Incline", 0.0))
            pulse_data = values.get("Pulse", {})
            pulse = pulse_data.get("pulse", 0) if isinstance(pulse_data, dict) else pulse_data
            mode_val = values.get("Mode", 0)

            print(f"{iteration:>6} | {speed:>8.1f} | {incline:>8.1f} | {pulse:>8} | {mode_val:>6}")

            iteration += 1
            await asyncio.sleep(args.interval)

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
