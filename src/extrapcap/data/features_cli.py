from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ..signals import relative_features


def build_features(input_path: str | Path, output_path: str | Path, benchmark_symbol: str = "SPY") -> Path:
    bars = pd.read_csv(input_path, parse_dates=["date"])
    if bars["date"].dt.tz is None:
        bars["date"] = bars["date"].dt.tz_localize("UTC")
    else:
        bars["date"] = bars["date"].dt.tz_convert("UTC")
    if bars.empty:
        raise RuntimeError("bars input produced no normalized rows")
    benchmark = bars.loc[bars["symbol"].eq(benchmark_symbol)].set_index("date")["close"]
    if benchmark.empty:
        raise RuntimeError(f"benchmark {benchmark_symbol} is missing from bars input")
    features = relative_features(bars, benchmark)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    features.to_csv(target, index=False)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate versioned signal features from normalized bars")
    parser.add_argument("--input", default="data/normalized/bars.csv")
    parser.add_argument("--output", default="data/features/features.csv")
    parser.add_argument("--benchmark", default="SPY")
    args = parser.parse_args()
    output = build_features(args.input, args.output, args.benchmark)
    print(json.dumps({"status": "written", "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
