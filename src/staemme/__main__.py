"""Entry point for the Staemme bot."""

from __future__ import annotations

import argparse
import asyncio
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Staemme Bot")
    parser.add_argument(
        "--profile",
        default="default",
        help="Profile name — isolates config, data, and logs (e.g. de250, de251)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (Xvfb) with API server instead of side panel",
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=None,
        help="API server port (default: 8000). Implies --headless if not already set.",
    )
    args = parser.parse_args()

    # --api-port implies headless mode
    headless = args.headless or args.api_port is not None

    from staemme.app import Application

    app = Application(
        profile=args.profile,
        headless=headless,
        api_port=args.api_port,
    )
    sys.exit(asyncio.run(app.run()))


if __name__ == "__main__":
    main()
