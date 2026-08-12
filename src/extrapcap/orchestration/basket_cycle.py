"""Fail-closed basket qualification and paper-order orchestration."""

from __future__ import annotations

import csv
import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.error import URLError

from ..ledger import AuditLedger
from ..selection import core_streak_gate, streak_priority_key
from .live_cycle import run_live_cycle


def _number(value, cast):
    if value in (None, ""):
        return None
    return cast(float(value))


def basket_rows(path_or_rows: str | Path | list[dict]) -> list[dict]:
    if isinstance(path_or_rows, list):
        rows = path_or_rows
    else:
        path = Path(path_or_rows)
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    result = []
    for raw in rows:
        row = dict(raw)
        features = row.get("features")
        if isinstance(features, str):
            try:
                row = {**json.loads(features), **row}
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid features JSON for {row.get('ticker') or row.get('symbol')}"
                ) from exc
        row.pop("features", None)
        ticker = str(row.get("ticker") or row.get("symbol") or "").strip().upper()
        if not ticker:
            raise ValueError("basket row missing ticker")
        row.update(
            {
                "ticker": ticker,
                "sector": str(row.get("sector") or "").strip(),
                "formation_date": row.get("formation_date") or row.get("date"),
                "streak_length": _number(row.get("streak_length"), int),
                "streak_direction": str(row.get("streak_direction") or "").strip().lower(),
                "robust_z": _number(row.get("robust_z"), float),
                "relative_return": _number(row.get("relative_return"), float),
                "reversion_probability": _number(row.get("reversion_probability"), float),
                "underlying_price": _number(
                    row.get("underlying_price") or row.get("close") or row.get("price"), float
                ),
            }
        )
        result.append(row)
    return sorted(result, key=streak_priority_key)


def run_basket(
    basket: str | Path | list[dict],
    *,
    audit: AuditLedger | None = None,
    runner=run_live_cycle,
    trading_day: date | None = None,
    dte_min: int = 0,
    dte_max: int = 21,
    preferred_dte: int = 10,
    max_candidates: int = 25,
    max_submissions: int = 1,
) -> list[dict]:
    """Evaluate a ranked, bounded set while recording signal and provider vetoes."""
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")
    if max_submissions < 1:
        raise ValueError("max_submissions must be positive")
    audit = audit or AuditLedger()
    day = trading_day or datetime.now(UTC).date()
    rows = basket_rows(basket)
    results = []
    evaluated = 0
    deferred = 0
    submissions = 0
    for rank, selection in enumerate(rows, start=1):
        decision = core_streak_gate(selection)
        probability = selection.get("reversion_probability")
        if probability is None:
            raise ValueError(
                f"basket row {selection['ticker']} is missing ticker-specific Bayesian probability"
            )
        context = {
            **selection,
            "selection_rank": rank,
            "strategy_route": decision.strategy_route,
            "signal_gate": decision.as_dict(),
        }
        if not decision.allowed:
            result = {
                "category": "signals",
                "kind": "basket_selection",
                "ticker": selection["ticker"],
                "status": "vetoed",
                "reason": decision.reason,
                "model_probability": probability,
                "selection_context": context,
            }
        else:
            if evaluated >= max_candidates or submissions >= max_submissions:
                deferred += 1
                continue
            evaluated += 1
            try:
                result = runner(
                    symbol=selection["ticker"],
                    trading_day=day,
                    expiration_gte=day.isoformat(),
                    expiration_lte=None,
                    selection_context=context,
                    dte_min=dte_min,
                    dte_max=dte_max,
                    preferred_dte=preferred_dte,
                )
            except ValueError as exc:
                result = {
                    "category": "signals",
                    "kind": "basket_selection",
                    "ticker": selection["ticker"],
                    "status": "vetoed",
                    "reason": str(exc),
                    "model_probability": probability,
                    "selection_context": context,
                }
            except (RuntimeError, URLError, TimeoutError) as exc:
                result = {
                    "category": "signals",
                    "kind": "basket_selection",
                    "ticker": selection["ticker"],
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "model_probability": probability,
                    "selection_context": context,
                }
            if str(result.get("status") or "").lower() in {
                "accepted",
                "new",
                "pending_new",
                "filled",
                "submitted",
                "partially_filled",
            }:
                submissions += 1
        audit.append(
            "signals",
            {
                "ticker": selection["ticker"],
                "status": result.get("status"),
                "reason": result.get("reason", "submitted"),
                "model_probability": probability,
                "selection_context": context,
            },
            day,
            deduplicate=True,
        )
        results.append(result)
    if deferred:
        summary = {
            "category": "signals",
            "kind": "basket_selection_summary",
            "status": "deferred",
            "reason": "candidate_limit",
            "eligible": evaluated + deferred,
            "evaluated": evaluated,
            "deferred": deferred,
        }
        audit.append("signals", summary, day, deduplicate=True)
        results.append(summary)
    return results
