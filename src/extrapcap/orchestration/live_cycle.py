"""Single-ticker option entry path used by the Modal basket cycle."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from ..config import RiskConfig
from ..events import event_decision_for_ticker
from ..execution.account_risk import build_portfolio_risk_state
from ..execution.alpaca import AlpacaPaperClient
from ..execution.intraday_state import build_intraday_risk_state
from ..options_data import AlpacaOptionsData
from ..risk import approve_intraday_order
from .paper_run import PaperRunCoordinator, build_candidate, build_candidates


def _account_risk(client):
    return build_portfolio_risk_state(client.account(), client.positions(), client.open_orders())


def run_live_cycle(
    *,
    symbol: str,
    trading_day: date | None = None,
    expiration_gte: str | None = None,
    expiration_lte: str | None = None,
    timeframe: str = "1Day",
    selection_context: dict | None = None,
    dte_min: int = 0,
    dte_max: int = 21,
    preferred_dte: int = 10,
    max_quote_spread_pct: float = 0.40,
    max_absolute_spread: float = 0.15,
    max_strike_attempts: int = 3,
    poll_timeout: float = 15.0,
    natural_poll_timeout: float = 10.0,
) -> dict:
    day = trading_day or datetime.now(UTC).date()
    context = dict(selection_context or {})
    probability = float(context["reversion_probability"])
    dte = context.get("dte")
    client = AlpacaPaperClient.from_env()
    clock = client.clock()
    now = datetime.now(UTC)
    eastern_day = now.astimezone(ZoneInfo("America/New_York")).date()
    history_start = datetime.combine(eastern_day, time.min, ZoneInfo("America/New_York"))
    intraday_state = build_intraday_risk_state(
        symbol, now, client.orders_after(history_start), market_is_open=clock["is_open"]
    )
    intraday_state = intraday_state.__class__(
        **{**intraday_state.__dict__, "dte": int(dte) if dte is not None else None}
    )
    intraday = approve_intraday_order(intraday_state, RiskConfig())
    if not intraday.allowed:
        return {
            "ticker": symbol.upper(),
            "status": "vetoed",
            "reason": intraday.reason,
            "selection_context": context,
        }
    data = AlpacaOptionsData.from_env()
    start = expiration_gte or day.isoformat()
    provider_symbol = str(context.get("alpaca_symbol") or symbol).strip().upper()
    contracts = data.contracts_all(
        provider_symbol, start, expiration_lte, "call", strategy_underlying=symbol.upper()
    )
    put_contracts = data.contracts_all(
        provider_symbol, start, expiration_lte, "put", strategy_underlying=symbol.upper()
    )
    contracts["option_contracts"] = contracts.get("option_contracts", []) + put_contracts.get(
        "option_contracts", []
    )
    snapshot, tier = data.chain_all(
        provider_symbol, expiration_gte=start, expiration_lte=expiration_lte, feed="indicative"
    )
    underlying = float(context.get("underlying_price") or 0)
    if underlying <= 0:
        raise ValueError(f"{symbol} missing current underlying price")
    event = event_decision_for_ticker(symbol, day)
    candidates = build_candidates(
        underlying=symbol.upper(),
        trading_day=day,
        underlying_price=underlying,
        contracts_payload=contracts,
        snapshot_payload=snapshot,
        model_probability=probability,
        risk_state=_account_risk(client),
        risk_config=RiskConfig(),
        event_decision=event,
        selection_context=context,
        observed_at=datetime.now(UTC),
        dte_min=dte_min,
        dte_max=dte_max,
        preferred_dte=preferred_dte,
        max_quote_spread_pct=max_quote_spread_pct,
        max_absolute_spread=max_absolute_spread,
        limit=5,
    )
    if not candidates:
        return {
            "ticker": symbol.upper(),
            "status": "vetoed",
            "reason": "no_viable_vertical_spreads",
            "selection_context": context,
            "data_tier": tier.value,
        }

    # Filter to approved candidates (quote quality and risk gates pass)
    approved_candidates = [
        c for c in candidates if c.risk_decision.allowed and c.event_decision.allowed
    ]
    if not approved_candidates:
        best = candidates[0]
        reason = (
            best.event_decision.reason
            if not best.event_decision.allowed
            else best.risk_decision.reason
        )
        return {
            "ticker": symbol.upper(),
            "status": "vetoed",
            "reason": reason,
            "selection_context": context,
            "data_tier": tier.value,
            "market_data": best.market_data_details,
        }

    coordinator = PaperRunCoordinator(client)
    last_result = None
    for candidate in approved_candidates[:max_strike_attempts]:
        result = coordinator.execute_with_fill_loop(
            candidate,
            poll_timeout=poll_timeout,
            natural_poll_timeout=natural_poll_timeout,
        )
        result["data_tier"] = tier.value
        status = str(result.get("status") or "").lower()
        if status in {"filled", "partially_filled", "submitted", "new", "accepted"}:
            return result
        last_result = result

    return {
        **(last_result or {}),
        "status": "unfilled",
        "reason": "exhausted_strike_attempts",
        "data_tier": tier.value,
    }
