import argparse
import json
import pandas as pd
from ..config import AppConfig, StrategyConfig
from .compare import compare_variants
from .report import write_comparison_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare baseline and improved premium variants")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="reports/variant-comparison.md")
    args = parser.parse_args()
    bars = pd.read_csv(args.input, parse_dates=["date"])
    benchmark = bars.loc[bars.symbol == "SPY"].set_index("date")["close"]
    config = AppConfig(strategy=StrategyConfig(z_window=5, z_threshold=-0.5))
    results = compare_variants(bars[bars.symbol != "SPY"], benchmark, config)
    write_comparison_report(results, args.output)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
