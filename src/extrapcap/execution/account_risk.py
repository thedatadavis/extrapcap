from __future__ import annotations

import math

from ..options_data import parse_occ_option_symbol
from ..risk import PortfolioRiskState


def _required_number(account: dict, key: str) -> float:
    if key not in account:
        raise RuntimeError(f"paper account is missing {key}")
    try:
        value = float(account[key])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"paper account has invalid {key}") from exc
    if not math.isfinite(value):
        raise RuntimeError(f"paper account has invalid {key}")
    return value


def build_portfolio_risk_state(account: dict, positions: list[dict], open_orders: list[dict], *, sector_by_ticker: dict[str, str] | None = None) -> PortfolioRiskState:
    equity = _required_number(account, "equity") if account.get("equity") is not None else _required_number(account, "portfolio_value")
    last_equity = float(account.get("last_equity") or equity)
    buying_power = _required_number(account, "options_buying_power")
    level = int(_required_number(account, "options_trading_level"))
    held_options = [position for position in positions if float(position.get("qty", 0) or 0) and (position.get("asset_class") == "us_option" or _is_option(position.get("symbol")))]
    open_option_orders = [order for order in open_orders if any(_is_option(leg.get("symbol")) for leg in order.get("legs", []))]
    if held_options or open_option_orders:
        raise RuntimeError("active paper option positions/orders require broker-linked entry metadata")
    blocked = any(bool(account.get(key)) for key in ("trading_blocked", "account_blocked", "trade_suspended_by_user")) or str(account.get("status", "ACTIVE")).upper() != "ACTIVE"
    return PortfolioRiskState(nav=equity, daily_pnl=equity - last_equity, options_buying_power=buying_power, options_trading_level=level, trading_blocked=blocked)


def _is_option(symbol) -> bool:
    try:
        parse_occ_option_symbol(str(symbol))
    except ValueError:
        return False
    return True
