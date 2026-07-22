from __future__ import annotations

from .engine import run_backtest


def compare_variants(bars, benchmark, cfg) -> list[dict]:
    return [run_backtest(bars, benchmark, variant, cfg).as_dict() for variant in ("baseline", "improved")]
