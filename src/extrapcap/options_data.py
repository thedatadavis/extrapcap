from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from .data.pagination import merge_pages
from .options import DebitSpread, VerticalSpread

class DataTier(StrEnum):
    INDICATIVE = "indicative"
    OPRA = "opra"
    RECONSTRUCTED = "reconstructed"
    PROVIDER_DEFAULT = "provider_default"


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


def select_put_vertical(underlying: str, contracts: list[OptionContract], quotes: list[OptionQuote], underlying_price: float, delta_min: float = 0.15, delta_max: float = 0.20, width: float = 5.0) -> SelectedVertical:
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
    delta_min: float = 0.30,
    delta_max: float = 0.50,
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
class FastEVSolution:
    spread: VerticalSpread | DebitSpread
    selected: SelectedVertical | SelectedDebitVertical
    expected_value: float
    max_profit: float
    max_risk: float
    bucket: str = "fast_ev_candidate"


def select_highest_ev_vertical(
    underlying: str,
    contracts: list[OptionContract],
    quotes: list[OptionQuote],
    underlying_price: float,
    win_probability: float,
    min_ev: float = 10.0,
    widths: tuple[float, ...] = (5.0, 10.0),
    streak_direction: str = "negative",
) -> FastEVSolution:
    """Scan directional vertical spreads in option chain and return the one with the highest EV >= min_ev."""
    quote_map = {quote.symbol: quote for quote in quotes}
    valid_contracts = [c for c in contracts if c.symbol in quote_map and c.underlying == underlying]

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
                strike_diff = c2.strike - c1.strike
                if not any(abs(strike_diff - w) < 1e-5 for w in widths):
                    continue
                width = strike_diff

                # Determine direction of debit / credit spreads
                # Call Debit (c1=long lower, c2=short higher) -> Bullish
                # Put Debit (c2=long higher, c1=short lower) -> Bearish
                # Put Credit (c2=short higher, c1=long lower) -> Bullish
                # Call Credit (c1=short lower, c2=long higher) -> Bearish
                if opt_type == "call":
                    debit_dir = "bullish"
                    credit_dir = "bearish"
                    long_debit, short_debit = c1, c2
                    q_long_debit, q_short_debit = q1, q2
                    short_credit, long_credit = c1, c2
                    q_short_credit, q_long_credit = q1, q2
                else:  # put
                    debit_dir = "bearish"
                    credit_dir = "bullish"
                    long_debit, short_debit = c2, c1
                    q_long_debit, q_short_debit = q2, q1
                    short_credit, long_credit = c2, c1
                    q_short_credit, q_long_credit = q2, q1

                # Debit Spread
                if debit_dir == target_direction and q_long_debit.ask is not None and q_short_debit.bid is not None and q_long_debit.ask > q_short_debit.bid:
                    debit = q_long_debit.ask - q_short_debit.bid
                    if 0 < debit < width:
                        max_profit = (width - debit) * 100
                        max_risk = debit * 100
                        ev = (win_probability * max_profit) - ((1 - win_probability) * max_risk)
                        if ev >= min_ev:
                            selected_debit = SelectedDebitVertical(underlying, long_debit, short_debit, debit, q_long_debit.delta)
                            spread_debit = DebitSpread(
                                underlying,
                                long_debit.strike,
                                short_debit.strike,
                                debit,
                                sleeve="asymmetric",
                                direction=debit_dir,
                            )
                            solutions.append((ev, max_profit, max_risk, spread_debit, selected_debit))

                # Credit Spread
                if credit_dir == target_direction and q_short_credit.bid is not None and q_long_credit.ask is not None and q_short_credit.bid > q_long_credit.ask:
                    credit = q_short_credit.bid - q_long_credit.ask
                    if 0 < credit < width:
                        max_profit = credit * 100
                        max_risk = (width - credit) * 100
                        ev = (win_probability * max_profit) - ((1 - win_probability) * max_risk)
                        if ev >= min_ev:
                            selected_credit = SelectedVertical(underlying, short_credit, long_credit, credit, q_short_credit.delta)
                            spread_credit = VerticalSpread(underlying, short_credit.strike, long_credit.strike, credit)
                            solutions.append((ev, max_profit, max_risk, spread_credit, selected_credit))

    if not solutions:
        raise ValueError(f"no {target_direction} vertical spread meets expected value threshold of ${min_ev:.2f}")

    best_ev, max_profit, max_risk, best_spread, best_selected = max(solutions, key=lambda item: item[0])
    return FastEVSolution(best_spread, best_selected, best_ev, max_profit, max_risk)


class AlpacaOptionsData:
    """Contracts from paper trading API; option market data from data API."""

    def __init__(self, api_key: str | None = None, secret_key: str | None = None, trading_url: str = "https://paper-api.alpaca.markets", data_url: str = "https://data.alpaca.markets"):
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")
        self.trading_url = trading_url.rstrip("/")
        self.data_url = data_url.rstrip("/")

    def _get(self, base: str, path: str, params: dict) -> dict:
        if not self.api_key or not self.secret_key:
            raise RuntimeError("missing Alpaca credentials for option data")
        query = urlencode({k: v for k, v in params.items() if v is not None})
        request = Request(f"{base}{path}?{query}", headers={"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.secret_key})
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read())

    def contracts(self, underlying: str, expiration_gte: str, expiration_lte: str | None = None, option_type: str = "put") -> dict:
        return self._get(self.trading_url, "/v2/options/contracts", {"underlying_symbols": underlying, "expiration_date_gte": expiration_gte, "expiration_date_lte": expiration_lte, "type": option_type, "status": "active", "show_deliverables": "false", "limit": 10000})

    def contracts_all(self, underlying: str, expiration_gte: str, expiration_lte: str | None = None, option_type: str = "put") -> dict:
        pages, token = [], None
        while True:
            page = self._get(self.trading_url, "/v2/options/contracts", {"underlying_symbols": underlying, "expiration_date_gte": expiration_gte, "expiration_date_lte": expiration_lte, "type": option_type, "status": "active", "show_deliverables": "false", "limit": 10000, "page_token": token})
            pages.append(page)
            token = page.get("next_page_token")
            if not token:
                return merge_pages(pages, "option_contracts")

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
    selected: SelectedVertical,
    quotes: list[OptionQuote],
    observed_at: datetime,
    *,
    max_age_seconds: int = 1800,
    max_spread_pct: float = 0.25,
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
        if quote.bid is None or quote.ask is None or quote.bid <= 0 or quote.ask <= quote.bid:
            return "option_quote_invalid", details
        midpoint = (quote.bid + quote.ask) / 2
        spread_pct = (quote.ask - quote.bid) / midpoint
        leg["spread_pct"] = spread_pct
        if spread_pct > max_spread_pct:
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
