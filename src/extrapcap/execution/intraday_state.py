from __future__ import annotations

from datetime import date, datetime, timezone

from ..options_data import parse_occ_option_symbol
from ..orchestration.windows import EASTERN
from ..risk import IntradayRiskState


def _timestamp(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _ticker_from_symbol(value) -> str | None:
    symbol = str(value or "").strip().upper()
    if not symbol:
        return None
    try:
        return parse_occ_option_symbol(symbol).underlying
    except ValueError:
        return symbol


def _order_tickers(order: dict) -> set[str]:
    tickers = set()
    for candidate in (order, *(order.get("legs") or [])):
        if not isinstance(candidate, dict):
            continue
        ticker = _ticker_from_symbol(candidate.get("underlying") or candidate.get("symbol"))
        if ticker:
            tickers.add(ticker)
    return tickers


def build_intraday_risk_state(
    symbol: str,
    now: datetime,
    broker_orders: list[dict],
    *,
    market_is_open: bool | None = None,
) -> IntradayRiskState:
    """Reconstruct per-symbol submissions from Alpaca order history."""
    ticker = symbol.upper()
    trading_day = now.astimezone(EASTERN).date()
    submissions: dict[str, datetime | None] = {}

    for order in broker_orders:
        timestamp = _timestamp(order.get("submitted_at") or order.get("created_at"))
        order_day = timestamp.astimezone(EASTERN).date() if timestamp else None
        if order_day != trading_day or ticker not in _order_tickers(order):
            continue
        identity = str(order.get("client_order_id") or order.get("id") or "").strip()
        if not identity:
            raise RuntimeError("broker order is missing an identifier")
        submissions[identity] = timestamp

    observed = [value for value in submissions.values() if value is not None]
    return IntradayRiskState(
        symbol=ticker,
        market_is_open=market_is_open,
        orders_today=len(submissions),
        last_order_at=max(observed) if observed else None,
        now=now,
    )
