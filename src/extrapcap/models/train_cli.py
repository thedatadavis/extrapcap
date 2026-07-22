from __future__ import annotations

import argparse
import json
from pathlib import Path
import pandas as pd

from ..signals import relative_features, sniper_dataset, SNIPER_FEATURES
from .sniper import SniperModel, calibration_report, time_split


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate the CatBoost Sniper model")
    parser.add_argument("--input", required=True, help="normalized bars CSV including SPY")
    parser.add_argument("--output", default="reports/sniper")
    args = parser.parse_args()
    bars = pd.read_csv(args.input, parse_dates=["date"])
    benchmark = bars.loc[bars.symbol == "SPY"].set_index("date")["close"]
    features = relative_features(bars[bars.symbol != "SPY"], benchmark)
    x, y = sniper_dataset(features)
    splits = time_split(x, y)
    model = SniperModel.train(*splits["train"], SNIPER_FEATURES)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    model.save(output / "sniper.cbm")
    evaluation = {}
    for name in ("validation", "test"):
        split_x, split_y = splits[name]
        probabilities = model.predict_probability(split_x)
        evaluation[name] = calibration_report(probabilities, split_y)
    (output / "evaluation.json").write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evaluation, indent=2))


if __name__ == "__main__":
    main()
