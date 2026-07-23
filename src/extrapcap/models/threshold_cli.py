from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import AppConfig
from ..selection import core_streak_gate
from ..signals import relative_features, sniper_dataset, SNIPER_FEATURES
from .sniper import SniperModel, calibration_report, time_split
from .threshold import select_threshold, sweep_thresholds


def _thresholds(start: float, stop: float, step: float) -> list[float]:
    values = np.arange(start, stop + step / 2, step)
    return [round(float(value), 6) for value in values]


def _split_metrics(
    split_name: str,
    split_indices,
    features: pd.DataFrame,
    probabilities: np.ndarray,
    labels: np.ndarray,
    proxy_returns: np.ndarray,
    thresholds: list[float],
    z_threshold: float,
    *,
    minimum_observations: int,
    maximum_drawdown: float,
) -> dict:
    indices = sorted(split_indices, key=lambda index: features.loc[index, "date"])
    positions = [features.index.get_loc(index) for index in indices]
    context = features.loc[indices]
    gate = np.array(
        [core_streak_gate(row.to_dict(), z_threshold).allowed for _, row in context.iterrows()],
        dtype=bool,
    )
    gated_probabilities = probabilities[positions][gate]
    gated_labels = labels[positions][gate]
    gated_returns = proxy_returns[positions][gate]
    results = sweep_thresholds(
        gated_probabilities,
        gated_labels,
        gated_returns,
        thresholds,
    )
    selected = None
    selection_error = None
    if split_name == "validation":
        try:
            selected = select_threshold(
                results,
                minimum_observations=minimum_observations,
                maximum_drawdown=maximum_drawdown,
            ).as_dict()
        except ValueError as exc:
            selection_error = str(exc)
    return {
        "split": split_name,
        "observations_before_gate": len(indices),
        "observations_after_gate": int(gate.sum()),
        "base_rate_after_gate": float(gated_labels.mean()) if len(gated_labels) else None,
        "calibration": calibration_report(probabilities[positions], labels[positions]),
        "thresholds": [result.as_dict() for result in results],
        "selected": selected,
        "selection_error": selection_error,
    }


def analyze(
    input_path: str | Path,
    model_path: str | Path,
    *,
    z_threshold: float = -2.0,
    threshold_start: float = 0.50,
    threshold_stop: float = 0.80,
    threshold_step: float = 0.01,
    minimum_observations: int = 50,
    maximum_drawdown: float = -0.10,
) -> dict:
    bars = pd.read_csv(input_path, parse_dates=["date"])
    benchmark = bars.loc[bars.symbol == "SPY"].set_index("date")["close"]
    features = relative_features(bars[bars.symbol != "SPY"], benchmark)
    x, y = sniper_dataset(features)
    model = SniperModel.load(model_path, SNIPER_FEATURES)
    probabilities = model.predict_probability(x[SNIPER_FEATURES].astype(float))
    labels = y.to_numpy(dtype=int)
    # A deliberately simple one-step proxy: the improved vertical collects 22%
    # of width and loses the remaining 78% when the next-day directional label
    # is wrong. This is not historical option P&L; it is a ranking baseline.
    strategy = AppConfig().strategy
    position_risk_fraction = 0.01
    proxy_win = strategy.spread_width * 0.22 / (strategy.spread_width * (1 - 0.22))
    proxy_returns = np.where(
        labels == 1,
        proxy_win * position_risk_fraction,
        -position_risk_fraction,
    )
    splits = time_split(x, y)
    thresholds = _thresholds(threshold_start, threshold_stop, threshold_step)
    validation = _split_metrics(
        "validation",
        splits["validation"][0].index,
        features.loc[x.index],
        probabilities,
        labels,
        proxy_returns,
        thresholds,
        z_threshold,
        minimum_observations=minimum_observations,
        maximum_drawdown=maximum_drawdown,
    )
    selected_threshold = (validation.get("selected") or {}).get("threshold")
    test = _split_metrics(
        "test",
        splits["test"][0].index,
        features.loc[x.index],
        probabilities,
        labels,
        proxy_returns,
        thresholds,
        z_threshold,
        minimum_observations=minimum_observations,
        maximum_drawdown=maximum_drawdown,
    )
    if selected_threshold is not None:
        test["selected_threshold_result"] = next(
            row for row in test["thresholds"] if row["threshold"] == selected_threshold
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path),
        "model": str(model_path),
        "model_version": model.version,
        "label": "next_relative_return_nonnegative",
        "data_scope": "reconstructed_one_step_option_proxy",
        "proxy_assumption": {
            "variant": "improved",
            "credit_pct_width": 0.22,
            "position_risk_fraction": position_risk_fraction,
            "win_return_on_nav": proxy_win * position_risk_fraction,
            "loss_return_on_nav": -position_risk_fraction,
        },
        "constraints": {
            "z_threshold": z_threshold,
            "minimum_observations": minimum_observations,
            "maximum_drawdown": maximum_drawdown,
        },
        "validation": validation,
        "test": test,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Select a Sniper probability cutoff from walk-forward proxy results")
    parser.add_argument("--input", default="data/normalized/bars.csv")
    parser.add_argument("--model", default="models/sniper.cbm")
    parser.add_argument("--output", default="reports/sniper/threshold-baseline.json")
    parser.add_argument("--z-threshold", type=float, default=-2.0)
    parser.add_argument("--threshold-start", type=float, default=0.50)
    parser.add_argument("--threshold-stop", type=float, default=0.80)
    parser.add_argument("--threshold-step", type=float, default=0.01)
    parser.add_argument("--minimum-observations", type=int, default=50)
    parser.add_argument("--maximum-drawdown", type=float, default=-0.10)
    args = parser.parse_args()
    report = analyze(
        args.input,
        args.model,
        z_threshold=args.z_threshold,
        threshold_start=args.threshold_start,
        threshold_stop=args.threshold_stop,
        threshold_step=args.threshold_step,
        minimum_observations=args.minimum_observations,
        maximum_drawdown=args.maximum_drawdown,
    )
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "written", "output": str(target), "selected": report["validation"].get("selected")}, indent=2))


if __name__ == "__main__":
    main()
