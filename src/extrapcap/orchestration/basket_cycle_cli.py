from __future__ import annotations

import argparse
import csv
from datetime import date
import json
import os
from pathlib import Path

from ..ledger import AuditLedger
from ..selection import core_streak_gate, streak_priority_key
from .live_cycle import run_live_cycle


def _optional_float(value) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _optional_int(value) -> int | None:
    if value in (None, ""):
        return None
    return int(float(value))


def basket_rows(path: str | Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    symbol_key = "symbol" if rows and "symbol" in rows[0] else "ticker"
    selected = []
    for row in rows:
        symbol = str(row.get(symbol_key, "")).strip().upper()
        if not symbol:
            continue
        selected.append(
            {
                "ticker": symbol,
                "formation_date": row.get("date") or None,
                "streak_length": _optional_int(row.get("streak_length")),
                "streak_direction": row.get("streak_direction") or None,
                "signed_streak": _optional_int(row.get("signed_streak")),
                "relative_return": _optional_float(row.get("relative_return")),
                "robust_z": _optional_float(row.get("robust_z")),
                "dollar_volume": _optional_float(row.get("dollar_volume")),
                "liquidity_context": _optional_float(row.get("liquidity_context")),
                "volatility_context": _optional_float(row.get("volatility_context")),
                "market_regime": _optional_float(row.get("market_regime")),
                "intraday_range_pct": _optional_float(row.get("intraday_range_pct")),
                "selection_source": str(path),
            }
        )
    return sorted(selected, key=streak_priority_key)


def run_basket(
    basket: str | Path,
    model: str,
    expiration_gte: str,
    expiration_lte: str | None = None,
    *,
    execution_mode: str = "dry-run",
    timeframe: str = "1Day",
    z_threshold: float = -2.0,
    max_candidates: int = 3,
    runner=run_live_cycle,
    ledger: AuditLedger | None = None,
) -> list[dict]:
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1")
    audit = ledger or AuditLedger()
    results = []
    approved_count = 0
    for rank, selection in enumerate(basket_rows(basket), start=1):
        ticker = selection["ticker"]
        decision = core_streak_gate(selection, z_threshold)
        selection = {
            **selection,
            "selection_rank": rank,
            "strategy_route": decision.strategy_route,
            "signal_gate": decision.as_dict(),
        }
        if not decision.allowed or approved_count >= max_candidates:
            reason = decision.reason if not decision.allowed else "candidate_limit"
            status = "vetoed" if not decision.allowed else "deferred"
            event = {
                "kind": "basket_selection",
                "ticker": ticker,
                "status": status,
                "reason": reason,
                "provider": "system",
                "sleeve": "core",
                "strategy_variant": "improved",
                "strategy_route": decision.strategy_route,
                "selection_rank": rank,
                "selection_context": selection,
            }
            audit.append("signals", event, date.today(), deduplicate=True)
            results.append(
                {
                    "ticker": ticker,
                    "status": status,
                    "reason": reason,
                    "strategy_route": decision.strategy_route,
                    "selection_context": selection,
                }
            )
            continue
        approved_count += 1
        audit.append(
            "signals",
            {
                "kind": "basket_selection",
                "ticker": ticker,
                "status": "selected",
                "reason": "approved",
                "provider": "system",
                "sleeve": "core",
                "strategy_variant": "improved",
                "strategy_route": decision.strategy_route,
                "selection_rank": rank,
                "selection_context": selection,
            },
            date.today(),
            deduplicate=True,
        )
        try:
            results.append(
                runner(
                    ticker,
                    model,
                    expiration_gte,
                    expiration_lte,
                    execution_mode,
                    timeframe,
                    selection_context=selection,
                )
            )
        except Exception as exc:
            failure = {
                "ticker": ticker,
                "status": "error",
                "reason": f"{type(exc).__name__}: {exc}",
                "selection_context": selection,
            }
            audit.append("exceptions", failure, date.today())
            results.append(failure)
    return results


def basket_run_succeeded(results: list[dict]) -> bool:
    """Require at least one ticker to reach a non-provider-error outcome."""
    return any(result.get("status") != "error" for result in results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the provider-backed cycle over the streak-screen basket")
    parser.add_argument("--basket", default="data/universe/tradable-basket.csv")
    parser.add_argument("--model", default=os.getenv("SNIPER_MODEL_PATH"))
    parser.add_argument("--expiration-gte", required=True)
    parser.add_argument("--expiration-lte")
    parser.add_argument("--execution-mode", choices=("dry-run", "paper-submit"), default="dry-run")
    parser.add_argument("--timeframe", choices=("1Day", "1Min", "5Min", "15Min", "1Hour"), default="1Day")
    parser.add_argument("--z-threshold", type=float, default=-2.0)
    parser.add_argument("--max-candidates", type=int, default=3)
    args = parser.parse_args()
    if not args.model:
        parser.error("--model or SNIPER_MODEL_PATH is required")
    results = run_basket(
        args.basket,
        args.model,
        args.expiration_gte,
        args.expiration_lte,
        execution_mode=args.execution_mode,
        timeframe=args.timeframe,
        z_threshold=args.z_threshold,
        max_candidates=args.max_candidates,
    )
    print(json.dumps(results, indent=2))
    if not basket_run_succeeded(results):
        raise SystemExit("basket cycle failed for every ticker")


if __name__ == "__main__":
    main()
