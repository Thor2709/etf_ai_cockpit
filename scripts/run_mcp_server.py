"""Launch the optional local stdio MCP server.

Usage: python scripts/run_mcp_server.py --root DATA_ROOT [--tiers read,research,paper] [--profile core|full]
The root is set before importing etf_cockpit because path constants resolve at import time.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("ETF_COCKPIT_ROOT"), help="owner data root (or ETF_COCKPIT_ROOT)")
    parser.add_argument(
        "--tiers",
        default=os.environ.get("ETF_COCKPIT_MCP_TIERS", "read"),
        help="comma-separated enabled tiers (default: read)",
    )
    parser.add_argument(
        "--profile",
        choices=("core", "full"),
        default=os.environ.get("ETF_COCKPIT_MCP_PROFILE", "core"),
        help="tool profile (default: core)",
    )
    parser.add_argument(
        "--client-id",
        default=os.environ.get("ETF_COCKPIT_MCP_CLIENT_ID", "local-stdio"),
        help="local audit identity",
    )
    args = parser.parse_args(argv)
    if not args.root:
        parser.error("--root (or ETF_COCKPIT_ROOT) is required")
    root = Path(args.root).expanduser().resolve()
    if not (root / "configs" / "universe.yaml").is_file():
        parser.error("--root must contain configs/universe.yaml")
    os.environ["ETF_COCKPIT_ROOT"] = str(root)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

    try:
        from etf_cockpit.mcp.errors import MCPServerUnavailable
        from etf_cockpit.mcp.server import run_server

        run_server(profile=args.profile, tiers=args.tiers, client_id=args.client_id)
    except MCPServerUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
