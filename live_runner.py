from __future__ import annotations

import argparse
from pathlib import Path

from trading_system.agent import TradingAgent
from trading_system.config.settings import Settings, ensure_watchlist


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live or paper trading runner")
    parser.add_argument("--watchlist", default="trading_system/config/watchlist.txt")
    parser.add_argument("--output-dir", default="live_logs")
    parser.add_argument("--poll-seconds", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-loops", type=int, default=None)
    parser.add_argument("--paper", action="store_true", default=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--dashboard-port", type=int, default=8080)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings(poll_seconds=args.poll_seconds, dashboard_port=args.dashboard_port)
    watchlist_path = Path(args.watchlist)
    ensure_watchlist(watchlist_path)
    agent = TradingAgent(settings, Path(args.output_dir), watchlist_path, dry_run=args.dry_run, paper=not args.live, dashboard_port=args.dashboard_port)
    agent.run(args.max_loops)


if __name__ == "__main__":
    main()
