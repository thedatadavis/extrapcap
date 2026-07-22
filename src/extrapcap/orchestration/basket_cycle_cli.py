from __future__ import annotations

import argparse
import csv
from datetime import date
import json
import os
from pathlib import Path

from ..ledger import AuditLedger
from .live_cycle import run_live_cycle


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
                "streak_length": int(float(row["streak_length"])) if row.get("streak_length") else None,
                "streak_direction": row.get("streak_direction") or None,
                "signed_streak": int(float(row["signed_streak"])) if row.get("signed_streak") else None,
                "relative_return": float(row["relative_return"]) if row.get("relative_return") else None,
                "robust_z": float(row["robust_z"]) if row.get("robust_z") else None,
                "selection_source": str(path),
            }
        )
    return selected


def run_basket(
    basket: str | Path,
    model: str,
    expiration_gte: str,
    expiration_lte: str | None,
    *,
    execution_mode: str = "dry-run",
    timeframe: str = "1Day",
    runner=run_live_cycle,
) -> list[dict]:
    results = []
    for selection in basket_rows(basket):
        ticker = selection["ticker"]
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
            AuditLedger().append("exceptions", failure, date.today())
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
    )
    print(json.dumps(results, indent=2))
    if not basket_run_succeeded(results):
        raise SystemExit("basket cycle failed for every ticker")


if __name__ == "__main__":
    main()
