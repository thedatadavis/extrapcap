from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ..config import AppConfig
from .sniper import SniperModel
from ..signals import SNIPER_FEATURES


def score_features(input_path: str | Path, model_path: str | Path, output_path: str | Path) -> Path:
    features = pd.read_csv(input_path, parse_dates=["date"])
    missing = set(SNIPER_FEATURES) - set(features.columns)
    if missing:
        raise ValueError(f"features missing required columns: {sorted(missing)}")
    model = SniperModel.load(model_path, SNIPER_FEATURES)
    scored = features.copy()
    scored["sniper_probability"] = model.predict_probability(scored[SNIPER_FEATURES].astype(float))
    trap_high = AppConfig().strategy.trap_high
    scored["sniper_bucket"] = pd.cut(
        scored["sniper_probability"],
        bins=[-float("inf"), 0.50, trap_high, float("inf")],
        labels=["crash_protocol", "trap", "premium_candidate"],
        right=False,
    ).astype(str)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    scored.to_csv(target, index=False)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Score generated features with a versioned Sniper model")
    parser.add_argument("--input", default="data/features/features.csv")
    parser.add_argument("--model", default="models/sniper.cbm")
    parser.add_argument("--output", default="data/features/scored.csv")
    args = parser.parse_args()
    output = score_features(args.input, args.model, args.output)
    print(json.dumps({"status": "written", "output": str(output), "model": args.model}, indent=2))


if __name__ == "__main__":
    main()
