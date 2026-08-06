"""Candidate evaluation and paper order entry execution engine."""

from __future__ import annotations

import argparse
import csv
from datetime import date
import json
import os
from pathlib import Path

import pandas as pd

from ..execution.alpaca import AlpacaPaperClient
from ..ledger import AuditLedger
from ..models.sniper import SniperModel
from ..selection import core_streak_gate, streak_priority_key
from ..signals import SNIPER_FEATURES
from ..secrets import paper_crash_protocol_enabled
from .live_cycle import run_live_cycle


def _optional_float(value) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _optional_int(value) -> int | None:
    if value in (None, ""):
        return None
    return int(float(value))


def _optional_bool(value) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def basket_rows(path_or_rows: str | Path | list[dict] | None = None) -> list[dict]:
    if isinstance(path_or_rows, list):
        rows = path_or_rows
        source_name = "d1_database"
    else:
        rows = []
        try:
            from modal_app.cf_client import CloudflareAPIClient
            client = CloudflareAPIClient()
            rows = client.get_basket()
        except Exception:
            rows = []
        if not rows and path_or_rows and Path(path_or_rows).exists():
            with Path(path_or_rows).open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        source_name = "d1_database"
    symbol_key = "symbol" if rows and "symbol" in rows[0] else "ticker"
    selected = []
    for row in rows:
        symbol = str(row.get(symbol_key, "")).strip().upper()
        if not symbol:
            continue
        selected.append(
            {
                "ticker": symbol,
                "sector": row.get("sector") or None,
                "formation_date": row.get("date") or None,
                "streak_length": _optional_int(row.get("streak_length")),
                "streak_depth": _optional_int(row.get("streak_depth")),
                "streak_direction": row.get("streak_direction") or None,
                "signed_streak": _optional_int(row.get("signed_streak")),
                "relative_return": _optional_float(row.get("relative_return")),
                "robust_z": _optional_float(row.get("robust_z")),
                "stock_return": _optional_float(row.get("stock_return")),
                "benchmark_return": _optional_float(row.get("benchmark_return")),
                "turn_of_month": _optional_bool(row.get("turn_of_month")),
                "dollar_volume": _optional_float(row.get("dollar_volume")),
                "liquidity_context": _optional_float(row.get("liquidity_context")),
                "volatility_context": _optional_float(row.get("volatility_context")),
                "market_regime": _optional_float(row.get("market_regime")),
                "intraday_range_pct": _optional_float(row.get("intraday_range_pct")),
                "selection_source": source_name,
            }
        )
    return sorted(selected, key=streak_priority_key)


def score_core_candidates(
    selections: list[dict],
    model_path: str | Path,
    *,
    z_threshold: float = -2.0,
    model_loader=SniperModel.load,
) -> tuple[list[dict], dict[str, str]]:
    """Score every core-qualified row before applying the candidate limit."""
    eligible = [selection for selection in selections if core_streak_gate(selection, z_threshold).allowed]
    if not eligible:
        return [], {}
    features = pd.DataFrame(eligible)
    missing = set(SNIPER_FEATURES) - set(features.columns)
    if missing:
        raise ValueError(f"basket rows missing model features: {sorted(missing)}")
    if features[SNIPER_FEATURES].isnull().any().any():
        missing_values = [name for name in SNIPER_FEATURES if features[name].isnull().any()]
        raise ValueError(f"basket rows contain missing model features: {sorted(missing_values)}")
    model = model_loader(model_path, SNIPER_FEATURES)
    probabilities = model.predict_probability(features[SNIPER_FEATURES].astype(float))
    buckets = {}
    for selection, probability in zip(eligible, probabilities):
        selection["model_probability"] = float(probability)
        selection["model_bucket"] = model.bucket(float(probability))
        buckets[selection["ticker"]] = selection["model_bucket"]
    ranked = sorted(
        eligible,
        key=lambda row: (row.get("model_probability", 0.0), streak_priority_key(row)),
        reverse=True,
    )
    return ranked, buckets


def run_basket(
    basket: str | Path,
    model: str | Path | None = None,
    expiration_gte: str | None = None,
    expiration_lte: str | None = None,
    timeframe: str = "1Day",
    max_candidates: int = 10,
    z_threshold: float = -2.0,
    audit: AuditLedger | None = None,
    runner=run_live_cycle,
    model_loader=None,
    review_phase: str = "entry",
    fast_ev: bool = True,
    prep_only: bool = False,
    min_ev: float = 10.0,
) -> list[dict]:
    """Run EV paper trading cycle across tradable basket using empirical Bayesian reversion probabilities."""
    audit = audit or AuditLedger()
    expiration_gte = expiration_gte or date.today().isoformat()
    selections = basket_rows(basket)
    from ..orchestration.paper_run import get_bayesian_model
    bayes_model = get_bayesian_model()

    crash_enabled = paper_crash_protocol_enabled()
    if fast_ev:
        tradeable_candidates = []
        for selection in selections:
            dec = core_streak_gate(selection, z_threshold, fast_ev=True)
            if bayes_model is not None:
                prob = bayes_model.predict_reversion_probability(
                    streak_length=int(selection.get("streak_length") or 2),
                    streak_direction=str(selection.get("streak_direction") or "negative"),
                    day_of_week=date.today().weekday(),
                    sector=str(selection.get("sector") or "Unknown"),
                )
            else:
                prob = float(selection.get("model_probability") or 0.50)
            selection["reversion_probability"] = prob
            selection["model_probability"] = prob
            if dec.allowed and prob > 0.50:
                tradeable_candidates.append(selection)
    else:
        tradeable_candidates = selections
    selected_tickers = {selection["ticker"] for selection in tradeable_candidates}
    selection_ranks = {
        selection["ticker"]: rank
        for rank, selection in enumerate(tradeable_candidates, start=1)
    }
    results = []
    for selection in selections:
        ticker = selection["ticker"]
        decision = core_streak_gate(selection, z_threshold, fast_ev=fast_ev)
        model_bucket = selection.get("model_bucket") or "bayesian_ev"
        prob = selection.get("reversion_probability") or 0.0
        selection = {
            **selection,
            "selection_rank": selection_ranks.get(ticker),
            "model_bucket": model_bucket,
            "strategy_route": decision.strategy_route,
            "signal_gate": decision.as_dict(),
        }
        crash_candidate = model_bucket == "crash_protocol" and crash_enabled
        is_tradeable = (prob > 0.50) if fast_ev else (model_bucket in {"premium_candidate", "watch_list"})
        if not decision.allowed or (not is_tradeable and not crash_candidate):
            if not decision.allowed:
                reason = decision.reason
            else:
                reason = f"reversion prob {prob:.1%}" if prob > 0.50 else f"bayes prob {prob:.4f} <= 0.50"
            status = "vetoed" if not decision.allowed else "deferred"
            event = {
                "kind": "basket_selection",
                "ticker": ticker,
                "status": status,
                "reason": reason,
                "provider": "system",
                "sleeve": "core",
                "strategy_variant": "fast_ev" if fast_ev else "improved",
                "strategy_route": decision.strategy_route,
                "selection_rank": selection.get("selection_rank"),
                "model_probability": selection.get("model_probability") or selection.get("reversion_probability"),
                "selection_context": selection,
            }
            audit.append("signals", event, date.today(), deduplicate=True)
            results.append(
                {
                    "category": "signals",
                    "kind": "basket_selection",
                    "ticker": ticker,
                    "sector": selection.get("sector"),
                    "streak_direction": selection.get("streak_direction"),
                    "streak_length": selection.get("streak_length"),
                    "robust_z": selection.get("robust_z"),
                    "status": status,
                    "reason": reason,
                    "strategy_route": decision.strategy_route,
                    "model_probability": selection.get("model_probability") or selection.get("reversion_probability"),
                    "selection_context": selection,
                }
            )
            continue
        audit.append(
            "signals",
            {
                "kind": "basket_selection",
                "ticker": ticker,
                "status": "selected",
                "reason": "approved",
                "provider": "system",
                "sleeve": "core",
                "strategy_variant": "fast_ev" if fast_ev else "improved",
                "strategy_route": decision.strategy_route,
                "selection_rank": selection.get("selection_rank"),
                "model_probability": selection.get("model_probability") or selection.get("reversion_probability"),
                "selection_context": selection,
            },
            date.today(),
            deduplicate=True,
        )
        if prep_only:
            results.append(
                {
                    "category": "signals",
                    "kind": "basket_selection",
                    "ticker": ticker,
                    "status": "prep_only",
                    "reason": "opening_prep_candidate",
                    "strategy_route": decision.strategy_route,
                    "model_probability": selection.get("model_probability") or selection.get("reversion_probability"),
                    "selection_context": selection,
                }
            )
            continue
        try:
            results.append(
                runner(
                    ticker,
                    model,
                    expiration_gte,
                    expiration_lte,
                    timeframe,
                    selection_context=selection,
                    review_phase=review_phase,
                    fast_ev=fast_ev,
                    min_ev=min_ev,
                )
            )
        except Exception as exc:
            event = {
                "category": "signals",
                "kind": "basket_selection",
                "ticker": ticker,
                "sector": selection.get("sector"),
                "streak_direction": selection.get("streak_direction"),
                "streak_length": selection.get("streak_length"),
                "robust_z": selection.get("robust_z"),
                "status": "candidate_reviewed",
                "reason": f"reversion prob {prob:.1%} (options chain unavailable)",
                "provider": "system",
                "model_probability": prob,
                "selection_context": selection,
            }
            audit.append("signals", event, date.today(), deduplicate=True)
            results.append(
                {
                    "category": "signals",
                    "kind": "basket_selection",
                    "ticker": ticker,
                    "sector": selection.get("sector"),
                    "streak_direction": selection.get("streak_direction"),
                    "streak_length": selection.get("streak_length"),
                    "robust_z": selection.get("robust_z"),
                    "status": "candidate_reviewed",
                    "reason": f"reversion prob {prob:.1%} (options chain unavailable)",
                    "model_probability": prob,
                    "selection_context": selection,
                }
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run active paper trading cycle across tradable basket")
    parser.add_argument("--basket", required=True, help="Path to tradable basket CSV")
    parser.add_argument("--model", default=None, help="Path to model (deprecated, defaults to Bayesian EV engine)")
    parser.add_argument("--expiration-gte", required=True, help="Minimum option expiration YYYY-MM-DD")
    parser.add_argument("--expiration-lte", default=None, help="Maximum option expiration YYYY-MM-DD")
    parser.add_argument("--timeframe", default="1Day")
    parser.add_argument("--max-candidates", type=int, default=10)
    parser.add_argument("--z-threshold", type=float, default=-2.0)
    parser.add_argument("--review-phase", choices=("opening_prep", "entry"), default="entry")
    parser.add_argument("--fast-ev", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--prep-only", action="store_true", help="Prepare candidates without submitting paper orders")
    parser.add_argument("--min-ev", type=float, default=10.0, help="Minimum net expected value in dollars")
    args = parser.parse_args()

    results = run_basket(
        args.basket,
        args.model,
        args.expiration_gte,
        args.expiration_lte,
        timeframe=args.timeframe,
        max_candidates=args.max_candidates,
        z_threshold=args.z_threshold,
        review_phase=args.review_phase,
        fast_ev=args.fast_ev,
        prep_only=args.prep_only,
        min_ev=args.min_ev,
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
