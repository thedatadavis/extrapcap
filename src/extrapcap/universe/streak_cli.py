from __future__ import annotations

import argparse
import json

import pandas as pd

from ..data.normalize import completed_daily_bars
from .streak_screen import StreakPolicy, screen_streaks, write_streak_screen


def bar_coverage(greenlist: pd.DataFrame, bars: pd.DataFrame, benchmark_symbol: str = "SPY") -> dict:
    requested = list(dict.fromkeys(greenlist["ticker"].astype(str).str.upper()))
    benchmark = benchmark_symbol.strip().upper()
    if benchmark not in requested:
        requested.insert(0, benchmark)
    observed = sorted(set(bars["symbol"].astype(str).str.upper()))
    missing = [symbol for symbol in requested if symbol not in observed]
    return {
        "requested_symbols": requested,
        "requested_symbol_count": len(requested),
        "observed_symbols": observed,
        "observed_symbol_count": len(set(requested) & set(observed)),
        "missing_symbols": missing,
        "missing_symbol_count": len(missing),
        "complete": not missing,
    }


def missing_bar_decisions(greenlist: pd.DataFrame, coverage: dict) -> list[dict]:
    sector_lookup = {
        str(row.ticker).upper(): str(row.sector)
        for row in greenlist[["ticker", "sector"]].itertuples(index=False)
    }
    return [
        {
            "ticker": ticker,
            "as_of": None,
            "signed_streak": None,
            "streak_length": None,
            "streak_direction": None,
            "relative_return": None,
            "accepted": False,
            "reasons": ["missing_bars"],
            "sector": sector_lookup.get(ticker),
        }
        for ticker in coverage["missing_symbols"]
        if ticker != "SPY"
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen the Greenlist by completed relative-return streak")
    parser.add_argument("--bars", default="data/normalized/bars.csv")
    parser.add_argument("--greenlist", required=True, help="pinned Greenlist CSV")
    parser.add_argument("--output", default="data/universe/tradable-basket.csv")
    parser.add_argument("--min-length", type=int, default=2)
    parser.add_argument("--max-length", type=int, default=5)
    parser.add_argument("--directions", default="negative,positive")
    parser.add_argument("--require-coverage", action="store_true", help="fail unless every Greenlist ticker has completed bars")
    args = parser.parse_args()
    bars = pd.read_csv(args.bars, parse_dates=["date"])
    bars = completed_daily_bars(bars)
    if bars.empty:
        raise RuntimeError("streak screen requires completed daily bars")
    greenlist = pd.read_csv(args.greenlist)
    symbols = set(greenlist["ticker"].astype(str).str.upper())
    benchmark = bars.loc[bars["symbol"].str.upper().eq("SPY")].set_index("date")["close"]
    if benchmark.empty:
        raise RuntimeError("streak screen requires benchmark bars for SPY")
    policy = StreakPolicy(args.min_length, args.max_length, tuple(args.directions.split(",")))
    selected, decisions = screen_streaks(bars, benchmark, symbols, policy)
    sector_lookup = {
        str(row.ticker).upper(): str(row.sector)
        for row in greenlist[["ticker", "sector"]].itertuples(index=False)
    }
    selected["sector"] = selected["symbol"].str.upper().map(sector_lookup)
    for decision in decisions:
        decision["sector"] = sector_lookup.get(str(decision["ticker"]).upper())
    coverage = bar_coverage(greenlist, bars)
    decisions.extend(missing_bar_decisions(greenlist, coverage))
    output = write_streak_screen(selected, decisions, args.output, policy, args.bars, coverage)
    result = {
        "status": "written",
        "output": str(output),
        "accepted": len(selected),
        "screened": len(decisions),
        "missing_bars": coverage["missing_symbol_count"],
        "coverage_complete": coverage["complete"],
    }
    print(json.dumps(result, indent=2))
    if args.require_coverage and not coverage["complete"]:
        raise RuntimeError(
            f"streak screen coverage incomplete: {coverage['missing_symbol_count']} Greenlist tickers lack completed bars"
        )


if __name__ == "__main__":
    main()
