import argparse
import json
from pathlib import Path
import pandas as pd
from ..config import AppConfig, StrategyConfig
from .engine import run_backtest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="reports/sample-backtest.json")
    args = parser.parse_args()
    bars = pd.read_csv(args.input, parse_dates=["date"])
    benchmark = bars.loc[bars.symbol == "SPY"].set_index("date")["close"]
    # The fixture is intentionally small; production runs should use the default 20-bar warmup.
    config = AppConfig(strategy=StrategyConfig(z_window=5, z_threshold=-0.5))
    result = run_backtest(bars[bars.symbol != "SPY"], benchmark, "improved", config)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result.as_dict(), indent=2) + "\n")
    print(json.dumps(result.as_dict(), indent=2))


if __name__ == "__main__":
    main()
