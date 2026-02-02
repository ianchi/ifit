from __future__ import annotations

# DEPRECATED: This module is deprecated in favor of the generalized CLI.
# Use `ifit ftms` command instead:
#   ifit ftms <address> <activation_code> --name "iFit FTMS" --interval 1.0
#
# For installation: pip install -e .
# For more commands: ifit --help
import argparse
import asyncio
import logging

from ..client import IFitBleClient
from ._server import FtmsBleRelay, FtmsConfig


async def _run_server(args: argparse.Namespace) -> None:
    """Run the FTMS relay server until interrupted."""
    client = IFitBleClient(args.address, args.activation_code)
    config = FtmsConfig(name=args.name, update_interval=args.interval)
    relay = FtmsBleRelay(client, config)

    try:
        await relay.start()
        # Block forever; BLE server lifecycle managed by ctrl+c.
        await asyncio.Event().wait()
    finally:
        await relay.stop()


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the FTMS relay."""
    parser = argparse.ArgumentParser(description="Run an FTMS BLE relay for iFit")
    parser.add_argument("address", help="BLE address of the iFit equipment")
    parser.add_argument("activation_code", help="Activation code for iFit equipment")
    parser.add_argument("--name", default="iFit FTMS", help="BLE advertising name")
    parser.add_argument("--interval", type=float, default=1.0, help="Update interval seconds")
    return parser.parse_args()


def main() -> None:
    """Entry point for running the FTMS relay."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args()
    asyncio.run(_run_server(args))


if __name__ == "__main__":
    main()
