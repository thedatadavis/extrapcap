from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .streak_screen import StreakPolicy, screen_streaks, write_streak_screen


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen the Greenlist by completed relative-return streak")
    parser.add_argument("--bars", default="data/normalized/bars.csv")
    parser.add_argument("--greenlist", required=True, help="pinned Greenlist CSV")
    parser.add_argument("--output", default="data/universe/tradable-basket.csv")
    parser.add_argument("--min-length", type=int, default=2)
    parser.add_argument("--max-length", type=int, default=5)
    parser.add_argument("--directions", default="negative,positive")
    args = parser.parse_args()
    bars = pd.read_csv(args.bars, parse_dates=["date"])
    greenlist = pd.read_csv(args.greenlist)
    symbols = set(greenlist["ticker"].astype(str).str.upper())
    benchmark = bars.loc[bars["symbol"].eq("SPY")].set_index("date")["close"]
    policy = StreakPolicy(args.min_length, args.max_length, tuple(args.directions.split(",")))
    selected, decisions = screen_streaks(bars, benchmark, symbols, policy)
    output = write_streak_screen(selected, decisions, args.output, policy, args.bars)
    print(json.dumps({"status": "written", "output": str(output), "accepted": len(selected), "screened": len(decisions)}, indent=2))


if __name__ == "__main__":
    main()
