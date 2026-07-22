from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os

from ..config import AppConfig
from ..data.alpaca_market import AlpacaMarketData
from ..data.normalize import normalize_stock_bars
from ..events import EventDecision, decision_from_csv
from ..execution.account_risk import build_portfolio_risk_state
from ..execution.alpaca import AlpacaPaperClient
from ..ledger import AuditLedger
from ..fills import FillAssumptions
from ..llm.nebius import NebiusReviewer
from ..models.sniper import SniperModel
from ..options_data import AlpacaOptionsData
from ..orchestration.paper_run import PaperRunCoordinator, build_candidate
from ..risk import IntradayRiskState, approve_intraday_order
from ..selection import core_streak_gate
from ..signals import SNIPER_FEATURES, relative_features


def run_live_cycle(
    symbol: str,
    model_path: str,
    expiration_gte: str,
    expiration_lte: str | None = None,
    execution_mode: str = "dry-run",
    timeframe: str = "1Day",
    selection_context: dict | None = None,
) -> dict:
    config = AppConfig.from_env()
    os.environ["EXTRAPCAP_EXECUTION_MODE"] = execution_mode
    client = AlpacaPaperClient.from_env()
    if not client.api_key or not client.secret_key:
        raise RuntimeError("live cycle requires Alpaca credentials for market and option data")
    market = AlpacaMarketData(client.api_key, client.secret_key)
    options = AlpacaOptionsData(client.api_key, client.secret_key)
    end = datetime.now(timezone.utc)
    if timeframe != "1Day":
        intraday_gate = approve_intraday_order(IntradayRiskState(symbol=symbol, now=end), config.risk)
        if not intraday_gate.allowed:
            result = {
                "ticker": symbol.upper(),
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "status": "vetoed",
                "reason": intraday_gate.reason,
                "selection_context": selection_context or {},
            }
            AuditLedger().append("risk", result, end.date())
            return result
    lookback_days = max(45, config.strategy.z_window * 3)
    if timeframe != "1Day":
        lookback_days = min(lookback_days, 5)
    start = end - timedelta(days=lookback_days)
    bars = normalize_stock_bars(market.stock_bars([symbol, config.benchmark], start.isoformat(), end.isoformat(), timeframe))
    benchmark = bars.loc[bars.symbol == config.benchmark].set_index("date")["close"]
    features = relative_features(bars[bars.symbol == symbol], benchmark, config.strategy.z_window)
    latest = features.dropna(subset=SNIPER_FEATURES).tail(1)
    if latest.empty:
        raise RuntimeError("not enough bars to produce Sniper features")
    latest_row = latest.iloc[0]
    live_features = {
        "as_of": latest_row["date"].isoformat(),
        "streak_length": int(latest_row["streak_length"]),
        "streak_direction": str(latest_row["streak_direction"]),
        "signed_streak": int(latest_row["signed_streak"]),
        "relative_return": float(latest_row["relative_return"]),
        "robust_z": float(latest_row["robust_z"]),
    }
    context = dict(selection_context or {})
    context["live_features"] = live_features
    formation_keys = {"streak_length", "streak_direction", "robust_z"}
    has_completed_formation = all(context.get(key) is not None for key in formation_keys)
    gate_context = context if has_completed_formation else live_features
    context["formation_source"] = "completed_basket" if gate_context is context else "latest_provider_bar"
    signal_gate = core_streak_gate(gate_context, config.strategy.z_threshold)
    context["signal_gate"] = signal_gate.as_dict()
    if not signal_gate.allowed:
        result = {
            "kind": "entry_signal_gate",
            "ticker": symbol.upper(),
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "status": "vetoed",
            "reason": signal_gate.reason,
            "provider": "system",
            "sleeve": "core",
            "strategy_variant": "improved",
            "selection_context": context,
        }
        AuditLedger().append("signals", result, end.date(), deduplicate=True)
        return {
            "ticker": symbol.upper(),
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "status": "vetoed",
            "reason": signal_gate.reason,
            "result": result,
        }
    model = SniperModel.load(model_path, SNIPER_FEATURES)
    probability = float(model.predict_probability(latest[SNIPER_FEATURES].astype(float))[0])
    account = client.account()
    risk_state = build_portfolio_risk_state(account, client.positions(), client.open_orders())
    contracts_payload = options.contracts_all(symbol, expiration_gte, expiration_lte)
    snapshot_payload, _ = options.chain_all(symbol, expiration_gte=expiration_gte, expiration_lte=expiration_lte, option_type="put", feed=os.getenv("ALPACA_OPTIONS_FEED", "indicative"))
    reviewer = NebiusReviewer()
    event_path = os.getenv("EXTRAPCAP_NEWS_EVENTS")
    event_reviewer = reviewer if os.getenv("EXTRAPCAP_NEWS_LLM", "false").lower() == "true" else None
    event_decision = decision_from_csv(event_path, symbol, end.date(), event_reviewer) if event_path else EventDecision("noise_or_opinion", True, "news adapter not configured")
    candidate = build_candidate(
        underlying=symbol,
        trading_day=end.date(),
        underlying_price=float(latest_row["close"]),
        contracts_payload=contracts_payload,
        snapshot_payload=snapshot_payload,
        model_probability=probability,
        risk_state=risk_state,
        risk_config=config.risk,
        event_decision=event_decision,
        fill_assumptions=FillAssumptions(),
        selection_context=context,
    )
    result = PaperRunCoordinator(client, reviewer).execute(candidate)
    return {"ticker": symbol.upper(), "symbol": symbol.upper(), "timeframe": timeframe, "probability": probability, "model": model.version, "result": result}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one provider-backed Extrapcap cycle")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--model", default=os.getenv("SNIPER_MODEL_PATH"))
    parser.add_argument("--expiration-gte", required=True)
    parser.add_argument("--expiration-lte")
    parser.add_argument("--execution-mode", choices=("dry-run", "paper-submit"), default="dry-run")
    parser.add_argument("--timeframe", choices=("1Day", "1Min", "5Min", "15Min", "1Hour"), default="1Day")
    args = parser.parse_args()
    if not args.model:
        parser.error("--model or SNIPER_MODEL_PATH is required")
    print(json.dumps(run_live_cycle(args.symbol, args.model, args.expiration_gte, args.expiration_lte or None, args.execution_mode, args.timeframe), indent=2))


if __name__ == "__main__":
    main()
