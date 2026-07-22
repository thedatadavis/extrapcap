from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

import pandas as pd

from ..backtest.engine import run_backtest
from ..config import AppConfig


@dataclass(frozen=True)
class Scenario:
    name: str
    variant: str
    classifier: bool = False
    news_filter: bool = False
    turn_of_month_only: bool = False
    crash_protocol: bool = False
    asymmetric: bool = True
    mode: str = "end_of_day"


@dataclass
class ScenarioResult:
    scenario: str
    status: str
    reason: str | None
    configuration: dict
    result: dict | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def default_scenarios() -> list[Scenario]:
    return [
        Scenario("baseline_no_classifier_eod", "baseline"),
        Scenario("improved_no_classifier_eod", "improved"),
        Scenario("baseline_classifier_eod", "baseline", classifier=True),
        Scenario("improved_classifier_eod", "improved", classifier=True),
        Scenario("improved_turn_of_month", "improved", turn_of_month_only=True),
        Scenario("improved_news_filter", "improved", news_filter=True),
        Scenario("improved_crash_protocol", "improved", classifier=True, crash_protocol=True),
        Scenario("improved_premium_only", "improved", asymmetric=False),
        Scenario("improved_plus_asymmetric", "improved", asymmetric=True),
        Scenario("improved_hybrid", "improved", mode="hybrid"),
        Scenario("improved_intraday_loop", "improved", mode="intraday_loop"),
    ]


def _has_intraday_observations(bars: pd.DataFrame) -> bool:
    if not pd.api.types.is_datetime64_any_dtype(bars["date"]):
        dates = pd.to_datetime(bars["date"], utc=True)
    else:
        dates = bars["date"]
    grouped = bars.assign(_session=dates.dt.date).groupby(["symbol", "_session"]).size()
    return bool(not grouped.empty and grouped.max() > 1)


def run_matrix(
    bars: pd.DataFrame,
    benchmark: pd.Series,
    cfg: AppConfig,
    *,
    scenarios: list[Scenario] | None = None,
    sniper=None,
    news_events: pd.DataFrame | None = None,
    eligible_symbols: set[str] | None = None,
) -> list[ScenarioResult]:
    scenarios = scenarios or default_scenarios()
    intraday_available = _has_intraday_observations(bars)
    results = []
    for scenario in scenarios:
        configuration = asdict(scenario)
        if scenario.classifier and sniper is None:
            results.append(ScenarioResult(scenario.name, "not_run", "classifier_model_required", configuration))
            continue
        if scenario.news_filter and news_events is None:
            results.append(ScenarioResult(scenario.name, "not_run", "news_event_input_required", configuration))
            continue
        if scenario.mode == "intraday_loop" and not intraday_available:
            results.append(ScenarioResult(scenario.name, "not_run", "intraday_bars_required", configuration))
            continue
        result = run_backtest(
            bars,
            benchmark,
            scenario.variant,
            cfg,
            sniper if scenario.classifier else None,
            include_asymmetric=scenario.asymmetric,
            include_crash_protocol=scenario.crash_protocol,
            turn_of_month_only=scenario.turn_of_month_only,
            news_events=news_events if scenario.news_filter else None,
            mode=scenario.mode,
            eligible_symbols=eligible_symbols,
        )
        results.append(ScenarioResult(scenario.name, "completed", None, configuration, result.as_dict()))
    return results


def write_matrix_report(results: list[ScenarioResult], output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Extrapolation Capital research matrix",
        "",
        "> Results are proxy research unless the result explicitly identifies observed option-chain data. `not_run` rows are evidence of a missing dependency, not a favorable result.",
        "",
        "| Scenario | Status | Trades | Win rate | Portfolio return | Drawdown | Crash trades | News vetoes |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in results:
        result = row.result or {}
        lines.append(
            f"| {row.scenario} | {row.status} | {result.get('trades', '')} | "
            f"{result.get('win_rate', 0):.1%} | "
            f"{result.get('portfolio_total_return', 0):.2%} | "
            f"{result.get('portfolio_max_drawdown', 0):.2%} | "
            f"{result.get('crash_trades', '')} | {result.get('news_vetoes', '')} |"
        )
    lines.extend(["", "## Machine-readable results", "", "```json", json.dumps([row.as_dict() for row in results], indent=2), "```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
