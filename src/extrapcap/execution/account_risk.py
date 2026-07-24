from __future__ import annotations

import json
import math
from pathlib import Path

from ..options_data import parse_occ_option_symbol
from ..risk import PortfolioRiskState


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _required_number(account: dict, key: str) -> float:
    if key not in account:
        raise RuntimeError(f"paper account is missing {key}")
    value = _number(account.get(key), float("nan"))
    if not math.isfinite(value):
        raise RuntimeError(f"paper account has invalid {key}")
    return value


def _registry_rows(path: str | Path) -> list[dict]:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _historical_equities(root: str | Path) -> list[float]:
    report_root = Path(root)
    if not report_root.exists():
        return []
    values = []
    for path in sorted(report_root.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            account = record.get("account")
            if isinstance(account, dict):
                equity = _number(account.get("equity"), -1)
                if equity > 0:
                    values.append(equity)
    return values


def _looks_like_option(position: dict) -> bool:
    if position.get("asset_class") == "us_option":
        return True
    symbol = str(position.get("symbol", ""))
    try:
        parse_occ_option_symbol(symbol)
    except ValueError:
        return False
    return True


def _open_order_option_symbols(order: dict) -> set[str]:
    symbols: set[str] = set()
    candidates = [order, *(order.get("legs") or [])]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        symbol = str(candidate.get("symbol", "")).upper()
        if not symbol:
            continue
        if candidate.get("asset_class") == "us_option":
            symbols.add(symbol)
            continue
        try:
            parse_occ_option_symbol(symbol)
        except ValueError:
            continue
        symbols.add(symbol)
    return symbols


def build_portfolio_risk_state(
    account: dict,
    positions: list[dict],
    open_orders: list[dict],
    *,
    registry_path: str | Path = "logs/orders/ids.jsonl",
    report_root: str | Path = "logs/reports",
    sector_by_ticker: dict[str, str] | None = None,
) -> PortfolioRiskState:
    """Rebuild hard risk state from Alpaca truth plus submitted order envelopes.

    Unknown option positions fail closed because their bounded loss and sleeve
    cannot be proven from the repository ledger.
    """
    equity = _number(account.get("equity") or account.get("portfolio_value"))
    options_buying_power = _required_number(account, "options_buying_power")
    options_trading_level = int(_required_number(account, "options_trading_level"))
    trading_blocked = (
        str(account.get("status", "")).upper() != "ACTIVE"
        or bool(account.get("trading_blocked"))
        or bool(account.get("account_blocked"))
        or bool(account.get("trade_suspended_by_user"))
    )
    last_equity = _number(account.get("last_equity"), equity)
    daily_pnl = equity - last_equity
    peak = max([equity, *_historical_equities(report_root)]) if equity > 0 else 0.0
    drawdown = (equity - peak) / peak if peak > 0 else 0.0

    held_option_symbols = {
        str(position.get("symbol", "")).upper()
        for position in positions
        if _number(position.get("qty")) != 0 and _looks_like_option(position)
    }
    open_client_ids = {
        str(order.get("client_order_id"))
        for order in open_orders
        if order.get("client_order_id")
    }

    core_open_risk = 0.0
    asymmetric_open_risk = 0.0
    open_asymmetric_trades = 0
    ticker_open_risk: dict[str, float] = {}
    sector_open_risk: dict[str, float] = {}
    tracked_active_contracts: set[str] = set()
    tracked_active_order_ids: set[str] = set()

    for record in _registry_rows(registry_path):
        if record.get("execution_status", "submitted") != "submitted":
            continue
        payload = record.get("payload") or {}
        contract_ids = {
            str(symbol).upper()
            for symbol in (
                record.get("contract_ids")
                or [leg.get("symbol") for leg in payload.get("legs", []) if leg.get("symbol")]
            )
            if symbol
        }
        client_order_id = str(record.get("client_order_id", ""))
        is_active = client_order_id in open_client_ids or (
            bool(contract_ids) and contract_ids.issubset(held_option_symbols)
        )
        if not is_active:
            continue
        if client_order_id in open_client_ids:
            tracked_active_order_ids.add(client_order_id)
        metadata = record.get("metadata") or {}
        width = _number(metadata.get("spread_width"), -1)
        entry_debit = _number(metadata.get("entry_debit"), -1)
        credit = _number(metadata.get("entry_credit", record.get("limit_price")), -1)
        quantity = int(_number(record.get("quantity", payload.get("qty", 1)), 1))
        if width <= 0 or quantity < 1 or (entry_debit <= 0 and (credit <= 0 or credit >= width)) or (entry_debit > 0 and entry_debit >= width):
            raise RuntimeError("active paper position is missing valid bounded-risk metadata")
        max_loss = (entry_debit if entry_debit > 0 else width - credit) * 100 * quantity
        sleeve = str(record.get("sleeve") or metadata.get("sleeve") or "core")
        ticker = str(record.get("ticker") or record.get("underlying") or "UNKNOWN").upper()
        ticker_open_risk[ticker] = ticker_open_risk.get(ticker, 0.0) + max_loss
        if sector_by_ticker is not None:
            sector = sector_by_ticker.get(ticker)
            if not sector:
                raise RuntimeError(f"active paper position is missing sector metadata: {ticker}")
            sector_open_risk[sector] = sector_open_risk.get(sector, 0.0) + max_loss
        tracked_active_contracts.update(contract_ids)
        if sleeve == "asymmetric":
            asymmetric_open_risk += max_loss
            open_asymmetric_trades += 1
        else:
            core_open_risk += max_loss

    untracked = held_option_symbols - tracked_active_contracts
    if untracked:
        raise RuntimeError(
            "untracked paper option positions prevent safe sizing: " + ", ".join(sorted(untracked))
        )
    untracked_open_orders = {
        str(order.get("client_order_id") or order.get("id") or "unknown")
        for order in open_orders
        if (_open_order_option_symbols(order) or order.get("order_class") == "mleg")
        and str(order.get("client_order_id", "")) not in tracked_active_order_ids
    }
    if untracked_open_orders:
        raise RuntimeError(
            "untracked paper option orders prevent safe sizing: "
            + ", ".join(sorted(untracked_open_orders))
        )

    return PortfolioRiskState(
        nav=equity,
        core_open_risk=core_open_risk,
        asymmetric_open_risk=asymmetric_open_risk,
        daily_pnl=daily_pnl,
        drawdown=drawdown,
        open_asymmetric_trades=open_asymmetric_trades,
        ticker_open_risk=ticker_open_risk,
        sector_open_risk=sector_open_risk,
        options_buying_power=options_buying_power,
        options_trading_level=options_trading_level,
        trading_blocked=trading_blocked,
    )
