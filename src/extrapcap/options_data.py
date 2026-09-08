from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from .data.pagination import merge_pages
from .options import DebitSpread, VerticalSpread

class DataTier(StrEnum):
    INDICATIVE = "indicative"
    OPRA = "opra"
    RECONSTRUCTED = "reconstructed"
    PROVIDER_DEFAULT = "provider_default"


class AlpacaOptionsRequestError(RuntimeError):
    """A safe, diagnostic option-data provider failure."""


@dataclass(frozen=True)
class OptionContract:
    symbol: str
    underlying: str
    expiration: str
    strike: float
    option_type: str
    style: str = "american"
    penny_program: bool | None = None


@dataclass(frozen=True)
class OptionQuote:
    symbol: str
    timestamp: str | None
    bid: float | None
    ask: float | None
    last: float | None
    implied_volatility: float | None = None
    delta: float | None = None

    @property
    def midpoint(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2


@dataclass(frozen=True)
class ParsedOptionSymbol:
    symbol: str
    underlying: str
    expiration: date
    option_type: str
    strike: float


def parse_occ_option_symbol(symbol: str) -> ParsedOptionSymbol:
    """Parse a standard 21-character OCC option symbol without guessing."""
    value = str(symbol).strip().upper()
    if len(value) < 16:
        raise ValueError(f"not an OCC option symbol: {symbol}")
    suffix = value[-15:]
    root = value[:-15].rstrip()
    if not root or suffix[6] not in {"P", "C"} or not suffix[7:].isdigit():
        raise ValueError(f"not an OCC option symbol: {symbol}")
    try:
        expiration = date(2000 + int(suffix[0:2]), int(suffix[2:4]), int(suffix[4:6]))
    except ValueError as exc:
        raise ValueError(f"invalid OCC expiration: {symbol}") from exc
    return ParsedOptionSymbol(value, root, expiration, suffix[6], int(suffix[7:]) / 1000)


@dataclass(frozen=True)
class SelectedVertical:
    underlying: str
    short: OptionContract
    long: OptionContract
    credit: float
    delta: float | None

    def order_legs(self) -> tuple[dict, dict]:
        return (
            {"symbol": self.short.symbol, "asset_class": "us_option", "side": "sell", "position_intent": "sell_to_open", "ratio_qty": 1},
            {"symbol": self.long.symbol, "asset_class": "us_option", "side": "buy", "position_intent": "buy_to_open", "ratio_qty": 1},
        )


@dataclass(frozen=True)
class SelectedDebitVertical:
    """A bearish put debit spread: buy the higher-strike put, sell the lower."""

    underlying: str
    long: OptionContract
    short: OptionContract
    debit: float
    delta: float | None

    def order_legs(self) -> tuple[dict, dict]:
        return (
            {"symbol": self.long.symbol, "asset_class": "us_option", "side": "buy", "position_intent": "buy_to_open", "ratio_qty": 1},
            {"symbol": self.short.symbol, "asset_class": "us_option", "side": "sell", "position_intent": "sell_to_open", "ratio_qty": 1},
        )


def contracts_from_payload(payload: dict) -> list[OptionContract]:
    rows = payload.get("option_contracts", payload.get("contracts", []))
    return [OptionContract(row.get("symbol") or row.get("contract_symbol"), row.get("underlying_symbol") or row.get("underlying"), row["expiration_date"], float(row["strike_price"]), row["type"], row.get("style", "american"), row.get("ppind")) for row in rows]


def select_put_vertical(underlying: str, contracts: list[OptionContract], quotes: list[OptionQuote], underlying_price: float, delta_min: float = 0.10, delta_max: float = 0.35, width: float = 5.0) -> SelectedVertical:
    quote_map = {quote.symbol: quote for quote in quotes}
    puts = [contract for contract in contracts if contract.underlying == underlying and contract.option_type == "put" and contract.symbol in quote_map]
    candidates = []
    for contract in puts:
        quote = quote_map[contract.symbol]
        if quote.delta is None or not delta_min <= abs(quote.delta) <= delta_max or quote.bid is None:
            continue
        candidates.append((abs(abs(quote.delta) - (delta_min + delta_max) / 2), contract, quote))
    if not candidates:
        raise ValueError("no put contract meets delta band")
    _, short, short_quote = min(candidates, key=lambda item: (item[0], item[1].expiration, item[1].strike))
    longs = [contract for contract in puts if contract.expiration == short.expiration and abs(contract.strike - (short.strike - width)) < 1e-9 and contract.symbol in quote_map]
    if not longs:
        raise ValueError("no long put contract matches requested width")
    long = longs[0]
    long_quote = quote_map[long.symbol]
    if long_quote.ask is None or short_quote.bid <= long_quote.ask:
        raise ValueError("quotes do not produce positive vertical credit")
    return SelectedVertical(underlying, short, long, short_quote.bid - long_quote.ask, short_quote.delta)


def select_bearish_put_debit_vertical(
    underlying: str,
    contracts: list[OptionContract],
    quotes: list[OptionQuote],
    underlying_price: float,
    delta_min: float = 0.25,
    delta_max: float = 0.60,
    width: float = 10.0,
) -> SelectedDebitVertical:
    """Select a quoted bearish put debit spread from the live option chain."""
    quote_map = {quote.symbol: quote for quote in quotes}
    puts = [contract for contract in contracts if contract.underlying == underlying and contract.option_type == "put" and contract.symbol in quote_map]
    candidates = []
    for contract in puts:
        quote = quote_map[contract.symbol]
        if quote.delta is None or not delta_min <= abs(quote.delta) <= delta_max or quote.ask is None:
            continue
        if contract.strike <= underlying_price:
            continue
        candidates.append((abs(abs(quote.delta) - (delta_min + delta_max) / 2), contract, quote))
    if not candidates:
        raise ValueError("no bearish debit long put meets delta band")
    _, long, long_quote = min(candidates, key=lambda item: (item[0], item[1].expiration, item[1].strike))
    shorts = [contract for contract in puts if contract.expiration == long.expiration and abs(contract.strike - (long.strike - width)) < 1e-9 and contract.symbol in quote_map]
    if not shorts:
        raise ValueError("no short put contract matches requested bearish debit width")
    short = shorts[0]
    short_quote = quote_map[short.symbol]
    if short_quote.bid is None or long_quote.ask <= short_quote.bid:
        raise ValueError("quotes do not produce positive bearish debit")
    return SelectedDebitVertical(underlying, long, short, long_quote.ask - short_quote.bid, long_quote.delta)


@dataclass(frozen=True)
class ExpectedValueSolution:
    spread: VerticalSpread | DebitSpread
    selected: SelectedVertical | SelectedDebitVertical
    expected_value: float
    max_profit: float
    max_risk: float
    expiration: str
    dte: int


def select_candidate_verticals(
    underlying: str,
    contracts: list[OptionContract],
    quotes: list[OptionQuote],
    underlying_price: float,
    win_probability: float,
    min_ev: float = 0.0,
    widths: tuple[float, ...] | None = None,
    streak_direction: str = "negative",
    trading_day: date | None = None,
    dte_min: int = 0,
    dte_max: int = 21,
    preferred_dte: int = 10,
    min_width_pct: float = 0.005,
    max_width_pct: float = 0.05,
    spread_types: tuple[str, ...] = ("credit", "debit"),
    limit: int | None = None,
) -> list[ExpectedValueSolution]:
    """Scan directional vertical spreads in option chain and return viable ones sorted by EV descending."""
    if underlying_price <= 0:
        raise ValueError(f"invalid real underlying price ${underlying_price}")

    min_allowed_width = max(0.50, round(underlying_price * min_width_pct, 2))
    max_allowed_width = max(min_allowed_width + 0.50, round(underlying_price * max_width_pct, 2))

    quote_map = {quote.symbol: quote for quote in quotes}
    # Filter contracts within 25% of real underlying price to focus on ATM/NTM spreads
    if dte_min < 0 or dte_max < dte_min:
        raise ValueError("invalid DTE range")
    if trading_day is None:
        raise ValueError("trading_day is required for DTE selection")
    valid_contracts = [
        c for c in contracts
        if c.symbol in quote_map
        and c.underlying == underlying
        and abs(c.strike - underlying_price) <= 0.25 * underlying_price
        and dte_min <= (date.fromisoformat(c.expiration) - trading_day).days <= dte_max
    ]

    solutions = []
    by_group: dict[tuple[str, str], list[OptionContract]] = {}
    for c in valid_contracts:
        by_group.setdefault((c.expiration, c.option_type), []).append(c)

    # Bullish reversion target for negative streak; Bearish reversion target for positive streak
    target_direction = "bullish" if streak_direction == "negative" else "bearish"

    for (exp, opt_type), group in by_group.items():
        group_sorted = sorted(group, key=lambda c: c.strike)
        for i, c1 in enumerate(group_sorted):
            q1 = quote_map[c1.symbol]
            for c2 in group_sorted[i + 1 :]:
                q2 = quote_map[c2.symbol]
                strike_diff = round(c2.strike - c1.strike, 4)
                if strike_diff <= 0:
                    continue
                if widths is not None:
                    if not any(abs(strike_diff - w) < 1e-5 for w in widths):
                        continue
                else:
                    if not (min_allowed_width - 1e-5 <= strike_diff <= max_allowed_width + 1e-5):
                        continue
                width = strike_diff

                # Credit Spreads (Core mean-reversion)
                if "credit" in spread_types:
                    if target_direction == "bullish" and opt_type == "put":
                        # Put Credit Spread: c2 is short (higher strike), c1 is long (lower strike)
                        # Short strike must be OTM or ATM: c2.strike <= underlying_price * 1.01
                        if c2.strike <= underlying_price * 1.01:
                            delta_ok = q2.delta is None or (0.05 <= abs(q2.delta) <= 0.60)
                            if (
                                delta_ok
                                and q2.bid is not None
                                and q2.bid > 0
                                and q1.ask is not None
                                and q1.ask > 0
                                and q2.bid > q1.ask
                            ):
                                credit = round(q2.bid - q1.ask, 2)
                                if 0.05 <= credit < width:
                                    max_profit = round(credit * 100, 2)
                                    max_risk = round((width - credit) * 100, 2)
                                    stop_risk = min(max_risk, round(2.0 * credit * 100, 2))
                                    ev = round((win_probability * max_profit) - ((1.0 - win_probability) * stop_risk), 2)
                                    if ev >= min_ev:
                                        selected_credit = SelectedVertical(underlying, c2, c1, credit, q2.delta)
                                        spread_credit = VerticalSpread(underlying, c2.strike, c1.strike, credit, direction="bullish")
                                        solutions.append((ev, max_profit, max_risk, spread_credit, selected_credit))
                    elif target_direction == "bearish" and opt_type == "call":
                        # Call Credit Spread: c1 is short (lower strike), c2 is long (higher strike)
                        # Short strike must be OTM or ATM: c1.strike >= underlying_price * 0.99
                        if c1.strike >= underlying_price * 0.99:
                            delta_ok = q1.delta is None or (0.05 <= abs(q1.delta) <= 0.60)
                            if (
                                delta_ok
                                and q1.bid is not None
                                and q1.bid > 0
                                and q2.ask is not None
                                and q2.ask > 0
                                and q1.bid > q2.ask
                            ):
                                credit = round(q1.bid - q2.ask, 2)
                                if 0.05 <= credit < width:
                                    max_profit = round(credit * 100, 2)
                                    max_risk = round((width - credit) * 100, 2)
                                    stop_risk = min(max_risk, round(2.0 * credit * 100, 2))
                                    ev = round((win_probability * max_profit) - ((1.0 - win_probability) * stop_risk), 2)
                                    if ev >= min_ev:
                                        selected_credit = SelectedVertical(underlying, c1, c2, credit, q1.delta)
                                        spread_credit = VerticalSpread(underlying, c1.strike, c2.strike, credit, direction="bearish")
                                        solutions.append((ev, max_profit, max_risk, spread_credit, selected_credit))

                # Debit Spreads (Asymmetric momentum)
                if "debit" in spread_types:
                    if target_direction == "bullish" and opt_type == "call":
                        # Call Debit Spread: c1 is long (lower strike), c2 is short (higher strike)
                        if (
                            q1.ask is not None
                            and q1.ask >= 0.05
                            and q2.bid is not None
                            and q2.bid >= 0.05
                            and q1.ask > q2.bid
                        ):
                            debit = round(q1.ask - q2.bid, 2)
                            if 0.05 <= debit < width:
                                max_profit = round((width - debit) * 100, 2)
                                max_risk = round(debit * 100, 2)
                                ev = round((win_probability * max_profit) - ((1.0 - win_probability) * max_risk), 2)
                                if ev >= min_ev:
                                    selected_debit = SelectedDebitVertical(underlying, c1, c2, debit, q1.delta)
                                    spread_debit = DebitSpread(
                                        underlying,
                                        c1.strike,
                                        c2.strike,
                                        debit,
                                        sleeve="asymmetric",
                                        direction="bullish",
                                    )
                                    solutions.append((ev, max_profit, max_risk, spread_debit, selected_debit))
                    elif target_direction == "bearish" and opt_type == "put":
                        # Put Debit Spread: c2 is long (higher strike), c1 is short (lower strike)
                        if (
                            q2.ask is not None
                            and q2.ask >= 0.05
                            and q1.bid is not None
                            and q1.bid >= 0.05
                            and q2.ask > q1.bid
                        ):
                            debit = round(q2.ask - q1.bid, 2)
                            if 0.05 <= debit < width:
                                max_profit = round((width - debit) * 100, 2)
                                max_risk = round(debit * 100, 2)
                                ev = round((win_probability * max_profit) - ((1.0 - win_probability) * max_risk), 2)
                                if ev >= min_ev:
                                    selected_debit = SelectedDebitVertical(underlying, c2, c1, debit, q2.delta)
                                    spread_debit = DebitSpread(
                                        underlying,
                                        c2.strike,
                                        c1.strike,
                                        debit,
                                        sleeve="asymmetric",
                                        direction="bearish",
                                    )
                                    solutions.append((ev, max_profit, max_risk, spread_debit, selected_debit))

    if not solutions:
        return []

    # Sort descending by EV, tie-breaking by closeness to preferred DTE
    def _rank_key(item):
        ev = item[0]
        selected_obj = item[4]
        exp_str = (
            selected_obj.short.expiration
            if isinstance(selected_obj, SelectedVertical)
            else selected_obj.long.expiration
        )
        dte_diff = abs((date.fromisoformat(exp_str) - trading_day).days - preferred_dte)
        return (ev, -dte_diff)

    sorted_solutions = sorted(solutions, key=_rank_key, reverse=True)
    if limit is not None and limit > 0:
        sorted_solutions = sorted_solutions[:limit]

    results = []
    for ev, max_profit, max_risk, spread, selected in sorted_solutions:
        exp_str = (
            selected.short.expiration
            if isinstance(selected, SelectedVertical)
            else selected.long.expiration
        )
        dte = (date.fromisoformat(exp_str) - trading_day).days
        results.append(
            ExpectedValueSolution(spread, selected, ev, max_profit, max_risk, exp_str, dte)
        )
    return results


def select_highest_ev_vertical(
    underlying: str,
    contracts: list[OptionContract],
    quotes: list[OptionQuote],
    underlying_price: float,
    win_probability: float,
    min_ev: float = 0.0,
    widths: tuple[float, ...] | None = None,
    streak_direction: str = "negative",
    trading_day: date | None = None,
    dte_min: int = 0,
    dte_max: int = 21,
    preferred_dte: int = 10,
    min_width_pct: float = 0.005,
    max_width_pct: float = 0.05,
    spread_types: tuple[str, ...] = ("credit", "debit"),
) -> ExpectedValueSolution:
    """Scan directional vertical spreads in option chain and return the one with the highest EV >= min_ev."""
    candidates = select_candidate_verticals(
        underlying=underlying,
        contracts=contracts,
        quotes=quotes,
        underlying_price=underlying_price,
        win_probability=win_probability,
        min_ev=min_ev,
        widths=widths,
        streak_direction=streak_direction,
        trading_day=trading_day,
        dte_min=dte_min,
        dte_max=dte_max,
        preferred_dte=preferred_dte,
        min_width_pct=min_width_pct,
        max_width_pct=max_width_pct,
        spread_types=spread_types,
        limit=1,
    )
    if not candidates:
        target_direction = "bullish" if streak_direction == "negative" else "bearish"
        raise ValueError(
            f"no {target_direction} vertical spread meets expected value threshold of ${min_ev:.2f}"
        )
    return candidates[0]



# Kept as a narrow import alias for external callers while the old strategy name is removed.
select_expected_value_vertical = select_highest_ev_vertical


class AlpacaOptionsData:
    """Contracts from paper trading API; option market data from data API."""

    def __init__(self, api_key: str | None = None, secret_key: str | None = None, trading_url: str = "https://paper-api.alpaca.markets", data_url: str = "https://data.alpaca.markets"):
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")
        self.trading_url = trading_url.rstrip("/")
        self.data_url = data_url.rstrip("/")
    @classmethod
    def from_env(cls) -> AlpacaOptionsData:
        return cls()

    def _get(self, base: str, path: str, params: dict) -> dict:
        if not self.api_key or not self.secret_key:
            raise RuntimeError("missing Alpaca credentials for option data")
        query = urlencode({k: v for k, v in params.items() if v is not None})
        request = Request(f"{base}{path}?{query}", headers={"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.secret_key})
        for attempt in range(3):
            try:
                with urlopen(request, timeout=30) as response:
                    return json.loads(response.read())
            except HTTPError as exc:
                if exc.code == 429 and attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                detail = ""
                try:
                    body = exc.read().decode("utf-8", errors="replace").strip()
                    payload = json.loads(body)
                    detail = str(payload.get("message") or payload.get("error") or body)
                except (AttributeError, json.JSONDecodeError, OSError, UnicodeError):
                    detail = str(exc.reason or exc)
                raise AlpacaOptionsRequestError(f"Alpaca option data request failed ({path}, HTTP {exc.code}): {detail}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise AlpacaOptionsRequestError(f"Alpaca option data request failed ({path}): {exc}") from exc

    @staticmethod
    def _normalize_contract_underlying(payload: dict, underlying: str) -> dict:
        result = dict(payload)
        rows = payload.get("option_contracts")
        if isinstance(rows, list):
            result["option_contracts"] = [{**row, "underlying_symbol": underlying.strip().upper()} if isinstance(row, dict) else row for row in rows]
        return result

    def contracts(self, underlying: str, expiration_gte: str, expiration_lte: str | None = None, option_type: str = "put", *, strategy_underlying: str | None = None) -> dict:
        payload = self._get(self.trading_url, "/v2/options/contracts", {"underlying_symbols": underlying, "expiration_date_gte": expiration_gte, "expiration_date_lte": expiration_lte, "type": option_type, "status": "active", "show_deliverables": "false", "limit": 10000})
        return self._normalize_contract_underlying(payload, strategy_underlying or underlying)

    def contracts_all(self, underlying: str, expiration_gte: str, expiration_lte: str | None = None, option_type: str = "put", *, strategy_underlying: str | None = None) -> dict:
        pages, token = [], None
        while True:
            page = self._get(self.trading_url, "/v2/options/contracts", {"underlying_symbols": underlying, "expiration_date_gte": expiration_gte, "expiration_date_lte": expiration_lte, "type": option_type, "status": "active", "show_deliverables": "false", "limit": 10000, "page_token": token})
            pages.append(page)
            token = page.get("next_page_token")
            if not token:
                return self._normalize_contract_underlying(merge_pages(pages, "option_contracts"), strategy_underlying or underlying)

    def chain(self, underlying: str, *, expiration_gte: str | None = None, expiration_lte: str | None = None, option_type: str | None = None, feed: str = "indicative", tier: DataTier | None = None) -> tuple[dict, DataTier]:
        selected_tier = tier or DataTier(feed)
        payload = self._get(self.data_url, f"/v1beta1/options/snapshots/{underlying}", {"expiration_date_gte": expiration_gte, "expiration_date_lte": expiration_lte, "type": option_type, "feed": feed, "limit": 1000})
        payload["_data_tier"] = selected_tier.value
        return payload, selected_tier

    def chain_all(self, underlying: str, *, expiration_gte: str | None = None, expiration_lte: str | None = None, option_type: str | None = None, feed: str = "indicative", tier: DataTier | None = None) -> tuple[dict, DataTier]:
        selected_tier = tier or DataTier(feed)
        pages, token = [], None
        while True:
            page = self._get(self.data_url, f"/v1beta1/options/snapshots/{underlying}", {"expiration_date_gte": expiration_gte, "expiration_date_lte": expiration_lte, "type": option_type, "feed": feed, "limit": 1000, "page_token": token})
            pages.append(page)
            token = page.get("next_page_token")
            if not token:
                result = merge_pages(pages, "snapshots")
                result["_data_tier"] = selected_tier.value
                return result, selected_tier

    def historical_trades(self, symbols: list[str], start: str, end: str, feed: str | None = None) -> tuple[dict, DataTier]:
        """Fetch historical trades using Alpaca's provider-selected feed.

        Alpaca's historical-trades endpoint does not accept a ``feed`` query
        parameter. Feed selection follows the account's data agreement, so a
        caller must not label the returned data OPRA or indicative without a
        provider-side entitlement check.
        """
        payload = self._get(self.data_url, "/v1beta1/options/trades", {"symbols": ",".join(symbols), "start": start, "end": end, "limit": 10000})
        payload["_data_tier"] = DataTier.PROVIDER_DEFAULT.value
        if feed:
            payload["_requested_feed"] = feed
        return payload, DataTier.PROVIDER_DEFAULT

    def historical_trades_all(self, symbols: list[str], start: str, end: str, feed: str | None = None) -> tuple[dict, DataTier]:
        tier, pages, token = DataTier.PROVIDER_DEFAULT, [], None
        while True:
            page = self._get(self.data_url, "/v1beta1/options/trades", {"symbols": ",".join(symbols), "start": start, "end": end, "limit": 10000, "page_token": token})
            pages.append(page)
            token = page.get("next_page_token")
            if not token:
                payload = merge_pages(pages, "trades")
                payload["_data_tier"] = tier.value
                if feed:
                    payload["_requested_feed"] = feed
                return payload, tier


def normalize_chain(payload: dict) -> list[OptionQuote]:
    result = []
    for symbol, snapshot in payload.get("snapshots", {}).items():
        quote = snapshot.get("latestQuote", {}) or {}
        trade = snapshot.get("latestTrade", {}) or {}
        greeks = snapshot.get("greeks", {}) or {}
        result.append(OptionQuote(symbol, quote.get("t"), quote.get("bp"), quote.get("ap"), trade.get("p"), snapshot.get("impliedVolatility"), greeks.get("delta")))
    return result


def selected_vertical_quote_quality(
    selected: SelectedVertical | SelectedDebitVertical,
    quotes: list[OptionQuote],
    observed_at: datetime,
    *,
    max_age_seconds: int = 1800,
    max_spread_pct: float = 0.40,
    max_absolute_spread: float = 0.15,
) -> tuple[str | None, dict]:
    quote_map = {quote.symbol: quote for quote in quotes}
    details = {"observed_at": observed_at.astimezone(timezone.utc).isoformat(), "legs": []}
    for role, contract in (("short", selected.short), ("long", selected.long)):
        quote = quote_map.get(contract.symbol)
        if quote is None:
            return "option_quote_missing", details
        leg = {
            "role": role,
            "contract_id": contract.symbol,
            "ticker": contract.underlying,
            "bid": quote.bid,
            "ask": quote.ask,
            "timestamp": quote.timestamp,
        }
        details["legs"].append(leg)
        if quote.bid is None or quote.ask is None:
            return "option_quote_invalid", details
        if role == "short":
            if quote.bid <= 0 or quote.ask <= quote.bid:
                return "option_quote_invalid", details
        else:
            if quote.bid < 0 or quote.ask <= 0 or quote.ask <= quote.bid:
                return "option_quote_invalid", details
        midpoint = (quote.bid + quote.ask) / 2
        spread = quote.ask - quote.bid
        spread_pct = (spread / midpoint) if midpoint > 0 else 0.0
        leg["spread"] = spread
        leg["spread_pct"] = spread_pct
        if spread_pct > max_spread_pct and spread > max_absolute_spread:
            return "option_quote_spread_too_wide", details
        if not quote.timestamp:
            return "option_quote_timestamp_missing", details
        try:
            timestamp = datetime.fromisoformat(str(quote.timestamp).replace("Z", "+00:00"))
        except ValueError:
            return "option_quote_timestamp_invalid", details
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age_seconds = (
            observed_at.astimezone(timezone.utc) - timestamp.astimezone(timezone.utc)
        ).total_seconds()
        leg["age_seconds"] = age_seconds
        if age_seconds < -5 or age_seconds > max_age_seconds:
            return "option_quote_stale", details
    return None, details

