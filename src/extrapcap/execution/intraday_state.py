from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path

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


def _registry_records(path: str | Path) -> list[dict]:
    target = Path(path)
    if not target.exists():
        return []
    records = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError("order registry contains invalid JSON") from exc
    return records


def build_intraday_risk_state(
    symbol: str,
    now: datetime,
    broker_orders: list[dict],
    *,
    registry_path: str | Path = "logs/orders/ids.jsonl",
    market_is_open: bool | None = None,
) -> IntradayRiskState:
    """Reconstruct per-symbol submissions from Alpaca and the append-only registry."""
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

    for record in _registry_records(registry_path):
        if record.get("execution_status", "submitted") != "submitted":
            continue
        try:
            record_day = date.fromisoformat(str(record.get("trading_day")))
        except ValueError as exc:
            raise RuntimeError("submitted order registry row has invalid trading_day") from exc
        record_ticker = str(record.get("ticker") or record.get("underlying") or "").upper()
        if record_day != trading_day or record_ticker != ticker:
            continue
        identity = str(record.get("client_order_id") or "").strip()
        if not identity:
            raise RuntimeError("submitted order registry row is missing client_order_id")
        timestamp = _timestamp(record.get("recorded_at"))
        # A same-day legacy submission without a timestamp must conservatively
        # keep the cooldown active, even when Alpaca history is unavailable.
        submissions.setdefault(identity, timestamp or now)

    observed = [value for value in submissions.values() if value is not None]
    return IntradayRiskState(
        symbol=ticker,
        market_is_open=market_is_open,
        orders_today=len(submissions),
        last_order_at=max(observed) if observed else None,
        now=now,
    )
