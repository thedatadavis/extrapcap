import argparse
import json
import pandas as pd

from ..fills import FillAssumptions
from .chain_engine import run_chain_backtest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a chain-backed defined-risk backtest")
    parser.add_argument("--input", required=True)
    parser.add_argument("--allow-reconstructed", action="store_true")
    args = parser.parse_args()
    result = run_chain_backtest(pd.read_csv(args.input), FillAssumptions(), args.allow_reconstructed)
    print(json.dumps(result.as_dict(), indent=2))


if __name__ == "__main__":
    main()
