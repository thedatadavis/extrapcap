from __future__ import annotations

import argparse
import json

import pandas as pd

from ..config import AppConfig, StrategyConfig
from ..models.sniper import SniperModel
from ..signals import SNIPER_FEATURES
from .matrix import run_matrix, write_matrix_report


def _load_news(path: str | None) -> pd.DataFrame | None:
    if not path:
        return None
    frame = pd.read_csv(path, parse_dates=["date"])
    if frame["structural_risk"].dtype == "object":
        frame["structural_risk"] = frame["structural_risk"].astype(str).str.lower().isin({"1", "true", "yes", "y"})
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Extrapcap ablation and operating-mode matrix")
    parser.add_argument("--input", required=True)
    parser.add_argument("--model", help="versioned Sniper artifact; enables classifier scenarios")
    parser.add_argument("--news", help="CSV with date,symbol,structural_risk columns")
    parser.add_argument("--basket", help="CSV produced by universe.streak_cli; limits research to its symbols")
    parser.add_argument("--output", default="reports/research-matrix.md")
    args = parser.parse_args()
    bars = pd.read_csv(args.input, parse_dates=["date"])
    benchmark = bars.loc[bars.symbol == "SPY"].set_index("date")["close"]
    cfg = AppConfig(strategy=StrategyConfig(z_window=5, z_threshold=-0.5))
    sniper = SniperModel.load(args.model, SNIPER_FEATURES) if args.model else None
    basket_symbols = None
    if args.basket:
        basket = pd.read_csv(args.basket)
        basket_symbols = set(basket["symbol"].astype(str).str.upper())
    results = run_matrix(
        bars[bars.symbol != "SPY"],
        benchmark,
        cfg,
        sniper=sniper,
        news_events=_load_news(args.news),
        eligible_symbols=basket_symbols,
    )
    write_matrix_report(results, args.output)
    print(json.dumps([row.as_dict() for row in results], indent=2))


if __name__ == "__main__":
    main()
