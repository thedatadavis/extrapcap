from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os

from ..config import AppConfig
from ..data.alpaca_market import AlpacaMarketData
from ..data.normalize import completed_daily_bars, completed_formation_reason, normalize_stock_bars
from ..events import EventDecision, decision_from_csv, earnings_decision_from_csv
from ..execution.account_risk import build_portfolio_risk_state
from ..execution.alpaca import AlpacaPaperClient
from ..execution.intraday_state import build_intraday_risk_state
from ..secrets import paper_crash_protocol_enabled
from ..ledger import AuditLedger
from ..fills import FillAssumptions
from ..llm.nebius import NebiusReviewer
from ..models.sniper import SniperModel
from ..options_data import AlpacaOptionsData
from ..orchestration.paper_run import PaperRunCoordinator, build_candidate, build_crash_candidate
from ..risk import approve_intraday_order
from ..selection import completed_signal_alignment_reason, core_streak_gate
from ..signals import SNIPER_FEATURES, relative_features
from ..universe.greenlist import load_sector_map
from .windows import EASTERN


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
    context = dict(selection_context or {})
    sector_map = load_sector_map(os.getenv("EXTRAPCAP_GREENLIST") or None)
    context.setdefault("sector", sector_map.get(symbol.upper()))
    session_start = end.astimezone(EASTERN).replace(hour=0, minute=0, second=0, microsecond=0)
    market_clock = client.clock()
    intraday_state = build_intraday_risk_state(
        symbol,
        end,
        client.orders_after(session_start),
        market_is_open=market_clock["is_open"],
    )
    intraday_gate = approve_intraday_order(intraday_state, config.risk)
    context["intraday_risk"] = {
        "orders_today": intraday_state.orders_today,
        "last_order_at": intraday_state.last_order_at.isoformat()
        if intraday_state.last_order_at
        else None,
        "allowed": intraday_gate.allowed,
        "reason": intraday_gate.reason,
        "market_is_open": market_clock["is_open"],
        "market_timestamp": market_clock.get("timestamp"),
        "next_open": market_clock.get("next_open"),
        "next_close": market_clock.get("next_close"),
    }
    if not intraday_gate.allowed:
        result = {
            "kind": "intraday_risk_gate",
            "ticker": symbol.upper(),
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "status": "vetoed",
            "reason": intraday_gate.reason,
            "selection_context": context,
        }
        AuditLedger().append("risk", result, end.date(), deduplicate=True)
        return result
    lookback_days = max(45, config.strategy.z_window * 3)
    if timeframe != "1Day":
        lookback_days = min(lookback_days, 5)
    start = end - timedelta(days=lookback_days)
    observed_bars = normalize_stock_bars(
        market.stock_bars([symbol, config.benchmark], start.isoformat(), end.isoformat(), timeframe)
    )
    signal_bars = completed_daily_bars(observed_bars, end) if timeframe == "1Day" else observed_bars
    if signal_bars.empty:
        raise RuntimeError("provider returned no completed signal bars")
    benchmark = signal_bars.loc[signal_bars.symbol == config.benchmark].set_index("date")["close"]
    features = relative_features(
        signal_bars[signal_bars.symbol == symbol], benchmark, config.strategy.z_window
    )
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
    context["live_features"] = live_features
    if timeframe == "1Day":
        max_age_days = int(os.getenv("EXTRAPCAP_MAX_DAILY_BAR_AGE_DAYS", "4"))
        freshness_reason = completed_formation_reason(
            latest_row["date"],
            context.get("formation_date"),
            now=end,
            max_age_days=max_age_days,
        )
        context["data_freshness"] = {
            "allowed": freshness_reason is None,
            "reason": freshness_reason or "completed_formation_aligned",
            "latest_completed_as_of": latest_row["date"].isoformat(),
            "max_age_days": max_age_days,
        }
        if freshness_reason is not None:
            result = {
                "kind": "data_freshness_gate",
                "ticker": symbol.upper(),
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "status": "vetoed",
                "reason": freshness_reason,
                "provider": "system",
                "sleeve": "core",
                "strategy_variant": "improved",
                "selection_context": context,
            }
            AuditLedger().append("risk", result, end.date(), deduplicate=True)
            return {
                "ticker": symbol.upper(),
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "status": "vetoed",
                "reason": freshness_reason,
                "result": result,
            }
    formation_keys = {"streak_length", "streak_direction", "robust_z"}
    has_completed_formation = all(context.get(key) is not None for key in formation_keys)
    if has_completed_formation:
        alignment_reason = completed_signal_alignment_reason(context, live_features)
        context["formation_comparison"] = {
            "allowed": alignment_reason is None,
            "reason": alignment_reason or "completed_signal_values_aligned",
            "basket": {key: context.get(key) for key in (*formation_keys, "relative_return")},
            "provider": live_features,
        }
        if alignment_reason is not None:
            result = {
                "kind": "data_integrity_gate",
                "ticker": symbol.upper(),
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "status": "vetoed",
                "reason": alignment_reason,
                "provider": "system",
                "sleeve": "core",
                "strategy_variant": "improved",
                "selection_context": context,
            }
            AuditLedger().append("risk", result, end.date(), deduplicate=True)
            return {
                "ticker": symbol.upper(),
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "status": "vetoed",
                "reason": alignment_reason,
                "result": result,
            }
    context["formation_source"] = (
        "completed_basket_verified_against_provider"
        if has_completed_formation
        else "latest_provider_bar"
    )
    signal_gate = core_streak_gate(live_features, config.strategy.z_threshold)
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
    reviewer = NebiusReviewer()
    earnings_path = os.getenv("EXTRAPCAP_EARNINGS_CALENDAR", "data/events/earnings.csv")
    earnings_decision = earnings_decision_from_csv(
        earnings_path,
        symbol,
        end.date(),
        max_age_hours=float(os.getenv("EXTRAPCAP_EARNINGS_MAX_AGE_HOURS", "36")),
        now=end,
    )
    event_path = os.getenv("EXTRAPCAP_NEWS_EVENTS")
    event_reviewer = reviewer if os.getenv("EXTRAPCAP_NEWS_LLM", "false").lower() == "true" else None
    news_decision = (
        decision_from_csv(event_path, symbol, end.date(), event_reviewer)
        if event_path
        else EventDecision("noise_or_opinion", True, "news adapter not configured")
    )
    context["event_checks"] = {
        "earnings": earnings_decision.__dict__,
        "news": news_decision.__dict__,
    }
    event_decision = earnings_decision if not earnings_decision.allowed else news_decision
    if not event_decision.allowed:
        result = {
            "kind": "event_gate",
            "ticker": symbol.upper(),
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "status": "vetoed",
            "reason": event_decision.reason,
            "provider": "system",
            "sleeve": "core",
            "strategy_variant": "improved",
            "selection_context": context,
            "event_decision": event_decision.__dict__,
        }
        AuditLedger().append("signals", result, end.date(), deduplicate=True)
        return {
            "ticker": symbol.upper(),
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "status": "vetoed",
            "reason": event_decision.reason,
            "result": result,
        }
    model = SniperModel.load(model_path, SNIPER_FEATURES)
    probability = float(model.predict_probability(latest[SNIPER_FEATURES].astype(float))[0])
    account = client.account()
    risk_state = build_portfolio_risk_state(
        account,
        client.positions(),
        client.open_orders(),
        sector_by_ticker=sector_map,
    )
    contracts_payload = options.contracts_all(symbol, expiration_gte, expiration_lte)
    snapshot_payload, data_tier = options.chain_all(symbol, expiration_gte=expiration_gte, expiration_lte=expiration_lte, option_type="put", feed=os.getenv("ALPACA_OPTIONS_FEED", "indicative"))
    context["data_tier"] = data_tier.value
    current_symbol_bars = observed_bars[observed_bars.symbol == symbol]
    current_underlying_price = float(
        current_symbol_bars.sort_values("date").iloc[-1]["close"]
    )
    context["market_price_as_of"] = current_symbol_bars.sort_values("date").iloc[-1]["date"].isoformat()
    context["crash_protocol_paper_enabled"] = paper_crash_protocol_enabled()
    if (
        execution_mode == "paper-submit"
        and context["crash_protocol_paper_enabled"]
        and probability < config.strategy.trap_low
    ):
        candidate = build_crash_candidate(
            underlying=symbol,
            trading_day=end.date(),
            underlying_price=current_underlying_price,
            contracts_payload=contracts_payload,
            snapshot_payload=snapshot_payload,
            model_probability=probability,
            risk_state=risk_state,
            risk_config=config.risk,
            event_decision=event_decision,
            fill_assumptions=FillAssumptions(),
            selection_context=context,
            observed_at=end,
            max_quote_age_seconds=config.strategy.max_option_quote_age_seconds,
            max_quote_spread_pct=config.strategy.max_option_spread_pct,
        )
    else:
        candidate = build_candidate(
            underlying=symbol,
            trading_day=end.date(),
            underlying_price=current_underlying_price,
            contracts_payload=contracts_payload,
            snapshot_payload=snapshot_payload,
            model_probability=probability,
            risk_state=risk_state,
            risk_config=config.risk,
            event_decision=event_decision,
            fill_assumptions=FillAssumptions(),
            selection_context=context,
            observed_at=end,
            max_quote_age_seconds=config.strategy.max_option_quote_age_seconds,
            max_quote_spread_pct=config.strategy.max_option_spread_pct,
            min_credit_pct_width=config.strategy.min_credit_pct_width,
        )
    result = PaperRunCoordinator(client, reviewer).execute(candidate)
    return {"ticker": symbol.upper(), "symbol": symbol.upper(), "timeframe": timeframe, "probability": probability, "model": model.version, "result": result}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one provider-backed Extrapcap cycle")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--model", default=os.getenv("SNIPER_MODEL_PATH"))
    parser.add_argument("--expiration-gte", required=True)
    parser.add_argument("--expiration-lte")
    parser.add_argument("--execution-mode", choices=("dry-run", "paper-submit", "live-submit"), default="dry-run")
    parser.add_argument("--timeframe", choices=("1Day", "1Min", "5Min", "15Min", "1Hour"), default="1Day")
    args = parser.parse_args()
    if not args.model:
        parser.error("--model or SNIPER_MODEL_PATH is required")
    print(json.dumps(run_live_cycle(args.symbol, args.model, args.expiration_gte, args.expiration_lte or None, args.execution_mode, args.timeframe), indent=2))


if __name__ == "__main__":
    main()
