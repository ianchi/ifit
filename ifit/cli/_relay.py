"""FTMS relay server for iFit CLI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from ..client import IFitBleClient

# Optional FTMS server support
try:
    from ..ftms import FtmsBleRelay, FtmsConfig

    FTMS_AVAILABLE = True
except ImportError:
    FTMS_AVAILABLE = False


LOGGER = logging.getLogger(__name__)


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
    finally:
        await relay.stop()
        print("✓ Server stopped")
