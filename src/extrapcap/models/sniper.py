from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import numpy as np
import pandas as pd


@dataclass
class SniperModel:
    """CatBoost-backed probability model with explicit decision buckets.

    CatBoost is optional for the offline core. Training raises an actionable error
    when the research dependency is not installed rather than silently substituting
    an untracked model.
    """

    model: object
    feature_names: list[str]
    version: str = "sniper-v1"

    @classmethod
    def train(cls, features, labels, feature_names: list[str]) -> "SniperModel":
        try:
            from catboost import CatBoostClassifier
        except ImportError as exc:
            raise RuntimeError("install the optional CatBoost research dependency to train Sniper") from exc
        model = CatBoostClassifier(iterations=250, depth=5, learning_rate=0.05, verbose=False, random_seed=7)
        model.fit(features, labels)
        return cls(model, feature_names)

    def predict_probability(self, features) -> np.ndarray:
        return self.model.predict_proba(features)[:, 1]

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(self.model, "save_model"):
            self.model.save_model(str(target))
        self.save_metadata(target.with_suffix(target.suffix + ".json"))

    @classmethod
    def load(cls, path: str | Path, feature_names: list[str]) -> "SniperModel":
        try:
            from catboost import CatBoostClassifier
        except ImportError as exc:
            raise RuntimeError("install the optional CatBoost research dependency to load Sniper") from exc
        model = CatBoostClassifier()
        model.load_model(str(path))
        return cls(model, feature_names)

    @staticmethod
    def bucket(probability: float) -> str:
        if probability < 0.50:
            return "crash_protocol"
        if probability < 0.65:
            return "trap"
        return "premium_candidate"

    def save_metadata(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({"version": self.version, "features": self.feature_names}, indent=2) + "\n")


def time_split(features: pd.DataFrame, labels: pd.Series, train_pct: float = 0.60, validation_pct: float = 0.20) -> dict[str, tuple[pd.DataFrame, pd.Series]]:
    if len(features) != len(labels) or len(features) < 5:
        raise ValueError("features and labels must align and contain at least five rows")
    first = max(1, int(len(features) * train_pct))
    second = max(first + 1, int(len(features) * (train_pct + validation_pct)))
    second = min(second, len(features) - 1)
    return {"train": (features.iloc[:first], labels.iloc[:first]), "validation": (features.iloc[first:second], labels.iloc[first:second]), "test": (features.iloc[second:], labels.iloc[second:])}


def calibration_report(probabilities, labels, bins: int = 10) -> dict:
    probabilities = np.asarray(probabilities, dtype=float)
    labels = np.asarray(labels, dtype=float)
    if len(probabilities) != len(labels) or len(labels) == 0:
        raise ValueError("probabilities and labels must be non-empty and aligned")
    edges = np.linspace(0, 1, bins + 1)
    histogram = []
    ece = 0.0
    for low, high in zip(edges[:-1], edges[1:]):
        mask = (probabilities >= low) & ((probabilities < high) if high < 1 else (probabilities <= high))
        count = int(mask.sum())
        if count:
            confidence = float(probabilities[mask].mean())
            accuracy = float(labels[mask].mean())
            ece += count / len(labels) * abs(confidence - accuracy)
        else:
            confidence = accuracy = 0.0
        histogram.append({"low": float(low), "high": float(high), "count": count, "confidence": confidence, "accuracy": accuracy})
    return {"brier": float(np.mean((probabilities - labels) ** 2)), "ece": float(ece), "histogram": histogram}
