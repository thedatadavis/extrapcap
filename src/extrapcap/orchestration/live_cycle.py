"""Single-ticker option entry path used by the Modal basket cycle."""

from __future__ import annotations

from datetime import date, datetime, timezone

from ..events import event_decision_for_ticker
from ..config import RiskConfig
from ..execution.alpaca import AlpacaPaperClient
from ..options_data import AlpacaOptionsData
from ..risk import PortfolioRiskState, approve_intraday_order, IntradayRiskState
from .paper_run import PaperRunCoordinator, build_candidate


def _account_risk(client) -> PortfolioRiskState:
    account = client.account()
    nav = float(account.get("portfolio_value") or 0)
    buying_power = float(account["options_buying_power"]) if account.get("options_buying_power") is not None else None
    level = int(account["options_approved_level"]) if account.get("options_approved_level") is not None else None
    if nav <= 0:
        raise RuntimeError("Alpaca account returned non-positive portfolio value")
    return PortfolioRiskState(nav=nav, options_buying_power=buying_power, options_trading_level=level, trading_blocked=str(account.get("trading_blocked", "false")).lower() == "true")


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
) -> dict:
    day = trading_day or date.today()
    context = dict(selection_context or {})
    probability = float(context["reversion_probability"])
    dte = context.get("dte")
    client = AlpacaPaperClient.from_env()
    clock = client.clock()
    intraday = approve_intraday_order(IntradayRiskState(symbol=symbol.upper(), market_is_open=clock["is_open"], now=datetime.now(timezone.utc), dte=int(dte) if dte is not None else None), RiskConfig())
    if not intraday.allowed:
        return {"ticker": symbol.upper(), "status": "vetoed", "reason": intraday.reason, "selection_context": context}
    data = AlpacaOptionsData.from_env()
    start = expiration_gte or day.isoformat()
    contracts = data.contracts_all(symbol.upper(), start, expiration_lte, "call")
    put_contracts = data.contracts_all(symbol.upper(), start, expiration_lte, "put")
    contracts["option_contracts"] = contracts.get("option_contracts", []) + put_contracts.get("option_contracts", [])
    snapshot, tier = data.chain_all(symbol.upper(), expiration_gte=start, expiration_lte=expiration_lte, feed="indicative")
    underlying = float(context.get("underlying_price") or 0)
    if underlying <= 0:
        raise ValueError(f"{symbol} missing current underlying price")
    event = event_decision_for_ticker(symbol, day)
    candidate = build_candidate(
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
        observed_at=datetime.now(timezone.utc),
        dte_min=dte_min,
        dte_max=dte_max,
        preferred_dte=preferred_dte,
    )
    result = PaperRunCoordinator(client).execute(candidate)
    result["data_tier"] = tier.value
    return result
