"""FTMS relay server for iFit CLI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from ..client import ActivationError, IFitBleClient

# Optional FTMS server support
try:
    from ..ftms import FtmsBleRelay, FtmsConfig

    FTMS_AVAILABLE = True
except ImportError:
    FTMS_AVAILABLE = False


LOGGER = logging.getLogger(__name__)


def _handle_activation_error(address: str) -> None:
    """Handle activation code errors with user-friendly messages."""
    print("\n✗ Incorrect activation code")
    print("  The provided activation code is invalid for this device.")
    print(f"\n  Use 'ifit activate {address}' to discover the correct code.")
    sys.exit(1)


async def run_ftms_relay(args: argparse.Namespace) -> None:
    """Run the FTMS relay server until interrupted."""
    if not FTMS_AVAILABLE:
        print('✗ FTMS server not available. Install with: pip install -e ".[ftms]"')
        sys.exit(1)

    client = IFitBleClient(args.address, args.code)
    config = FtmsConfig(name=args.name, update_interval=args.interval)
    relay = FtmsBleRelay(client, config)

    try:
        print(f"Starting FTMS relay server '{args.name}'...")
        await relay.start()
        print("✓ Server running (Ctrl+C to stop)")
        # Block forever; BLE server lifecycle managed by ctrl+c.
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\nStopping server...")
    except ActivationError:
        _handle_activation_error(args.address)
    except ValueError as e:
        print(f"\n✗ Error: {e}")
        LOGGER.error("Relay error", exc_info=True)
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        LOGGER.error("Relay error", exc_info=True)
        sys.exit(1)
    finally:
        await relay.stop()
        print("✓ Server stopped")
