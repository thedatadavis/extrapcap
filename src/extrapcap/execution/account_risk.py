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


def build_portfolio_risk_state(
    account: dict,
    positions: list[dict],
    open_orders: list[dict],
    *,
    sector_by_ticker: dict[str, str] | None = None,
    durable_positions: list[dict] | None = None,
) -> PortfolioRiskState:
    equity = _required_number(account, "equity") if account.get("equity") is not None else _required_number(account, "portfolio_value")
    last_equity = float(account.get("last_equity") or equity)
    buying_power = _required_number(account, "options_buying_power")
    level = int(_required_number(account, "options_trading_level"))
    blocked = any(bool(account.get(key)) for key in ("trading_blocked", "account_blocked", "trade_suspended_by_user")) or str(account.get("status", "ACTIVE")).upper() != "ACTIVE"

    core_open_risk = 0.0
    asymmetric_open_risk = 0.0
    open_asymmetric_trades = 0
    ticker_open_risk: dict[str, float] = {}
    sector_open_risk: dict[str, float] = {}

    def _add_risk(ticker: str, amount: float, sleeve: str = "core"):
        nonlocal core_open_risk, asymmetric_open_risk, open_asymmetric_trades
        if amount <= 0:
            return
        ticker_upper = ticker.upper()
        ticker_open_risk[ticker_upper] = round(ticker_open_risk.get(ticker_upper, 0.0) + amount, 2)
        if sector_by_ticker and ticker_upper in sector_by_ticker:
            sec = sector_by_ticker[ticker_upper]
            sector_open_risk[sec] = round(sector_open_risk.get(sec, 0.0) + amount, 2)
        if sleeve == "asymmetric":
            asymmetric_open_risk += amount
            open_asymmetric_trades += 1
        else:
            core_open_risk += amount

    # 1. First, aggregate known durable positions if provided
    durable_leg_symbols = set()
    for row in (durable_positions or []):
        ticker = str(row.get("ticker") or "").upper()
        width = float(row.get("spread_width") or 0.0)
        qty = int(float(row.get("quantity") or 1))
        credit = row.get("entry_credit")
        debit = row.get("entry_debit")
        sleeve = str(row.get("sleeve") or "core").lower()
        if credit is not None and float(credit) > 0:
            risk = max(0.0, (width - float(credit)) * 100.0 * qty)
        elif debit is not None and float(debit) > 0:
            risk = float(debit) * 100.0 * qty
        else:
            risk = width * 100.0 * qty
        _add_risk(ticker, risk, sleeve)
        legs = row.get("legs") or []
        if isinstance(legs, list):
            for leg in legs:
                if isinstance(leg, dict) and leg.get("symbol"):
                    durable_leg_symbols.add(str(leg["symbol"]))

    # 2. Broker held option positions not already accounted for in durable positions
    unaccounted_positions = [
        pos for pos in positions
        if float(pos.get("qty", 0) or 0)
        and (pos.get("asset_class") == "us_option" or _is_option(pos.get("symbol")))
        and str(pos.get("symbol") or "") not in durable_leg_symbols
    ]

    # Group unaccounted option positions by ticker and expiration to identify spreads
    grouped: dict[tuple[str, str], list[dict]] = {}
    for pos in unaccounted_positions:
        sym = str(pos.get("symbol") or "")
        try:
            parsed = parse_occ_option_symbol(sym)
            grouped.setdefault((parsed.underlying.upper(), str(parsed.expiration)), []).append(pos)
        except ValueError:
            val = abs(float(pos.get("market_value") or pos.get("cost_basis") or 0.0))
            _add_risk(sym, val, "core")

    for (ticker, _exp), legs in grouped.items():
        long_legs = [p for p in legs if float(p.get("qty", 0) or 0) > 0]
        short_legs = [p for p in legs if float(p.get("qty", 0) or 0) < 0]
        while long_legs and short_legs:
            long_pos = long_legs.pop(0)
            short_pos = short_legs.pop(0)
            long_qty = abs(float(long_pos.get("qty", 0) or 0))
            short_qty = abs(float(short_pos.get("qty", 0) or 0))
            spread_qty = min(long_qty, short_qty)
            long_parsed = parse_occ_option_symbol(str(long_pos["symbol"]))
            short_parsed = parse_occ_option_symbol(str(short_pos["symbol"]))
            width = abs(long_parsed.strike - short_parsed.strike)
            risk = width * 100.0 * spread_qty
            _add_risk(ticker, risk, "core")
            remaining_long = long_qty - spread_qty
            remaining_short = short_qty - spread_qty
            if remaining_long > 0:
                long_legs.insert(0, {**long_pos, "qty": remaining_long})
            if remaining_short > 0:
                short_legs.insert(0, {**short_pos, "qty": -remaining_short})

        for p in long_legs:
            cost = abs(float(p.get("cost_basis") or p.get("market_value") or 0.0))
            _add_risk(ticker, cost, "core")
        for p in short_legs:
            try:
                parsed = parse_occ_option_symbol(str(p["symbol"]))
                _add_risk(ticker, parsed.strike * 100.0 * abs(float(p.get("qty", 0) or 0)), "core")
            except ValueError:
                _add_risk(ticker, abs(float(p.get("market_value") or 0.0)), "core")

    # 3. Open option orders
    for order in open_orders:
        legs = order.get("legs") or []
        qty = int(float(order.get("qty") or 1))
        order_sleeve = str(order.get("sleeve") or "core").lower()
        if len(legs) >= 2:
            strikes = []
            order_ticker = str(order.get("ticker") or "")
            for leg in legs:
                sym = str(leg.get("symbol") or "")
                if _is_option(sym):
                    parsed = parse_occ_option_symbol(sym)
                    strikes.append(parsed.strike)
                    if not order_ticker:
                        order_ticker = parsed.underlying.upper()
            if len(strikes) >= 2 and order_ticker:
                width = abs(strikes[0] - strikes[1])
                limit_price = float(order.get("limit_price") or 0.0)
                side = str(order.get("side") or "").lower()
                if "sell" in side:
                    risk = max(0.0, (width - limit_price) * 100.0 * qty)
                else:
                    risk = limit_price * 100.0 * qty if limit_price > 0 else width * 100.0 * qty
                _add_risk(order_ticker, risk, order_sleeve)
        elif len(legs) == 1 or not legs:
            sym = str(order.get("symbol") or (legs[0].get("symbol") if legs else ""))
            if _is_option(sym):
                parsed = parse_occ_option_symbol(sym)
                limit_price = float(order.get("limit_price") or 0.0)
                risk = limit_price * 100.0 * qty if limit_price > 0 else 100.0 * qty
                _add_risk(parsed.underlying.upper(), risk, order_sleeve)

    return PortfolioRiskState(
        nav=equity,
        core_open_risk=round(core_open_risk, 2),
        asymmetric_open_risk=round(asymmetric_open_risk, 2),
        daily_pnl=equity - last_equity,
        drawdown=0.0,
        open_asymmetric_trades=open_asymmetric_trades,
        ticker_open_risk=ticker_open_risk,
        sector_open_risk=sector_open_risk,
        options_buying_power=buying_power,
        options_trading_level=level,
        trading_blocked=blocked,
    )


def _is_option(symbol) -> bool:
    try:
        parse_occ_option_symbol(str(symbol))
    except ValueError:
        return False
    return True
