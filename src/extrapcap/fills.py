from __future__ import annotations

from dataclasses import dataclass

from .options import DebitSpread, VerticalSpread


@dataclass(frozen=True)
class FillAssumptions:
    slippage_per_leg: float = 0.02
    max_bid_ask_pct: float = 0.25
    commission_per_contract: float = 0.0


def credit_fill(short_bid: float, long_ask: float, contracts: int, assumptions: FillAssumptions = FillAssumptions()) -> float:
    if short_bid < 0 or long_ask < 0 or short_bid <= long_ask:
        raise ValueError("credit spread quotes must produce positive credit")
    gross = short_bid - long_ask - 2 * assumptions.slippage_per_leg
    return max(0.0, gross) * 100 * contracts - assumptions.commission_per_contract * 2 * contracts


def debit_fill(long_ask: float, short_bid: float, contracts: int, assumptions: FillAssumptions = FillAssumptions()) -> float:
    if long_ask <= short_bid or long_ask < 0 or short_bid < 0:
        raise ValueError("debit spread quotes must produce a positive debit")
    gross = long_ask - short_bid + 2 * assumptions.slippage_per_leg
    return gross * 100 * contracts + assumptions.commission_per_contract * 2 * contracts


def vertical_expiration_pnl(spread: VerticalSpread, underlying_price: float, commissions: float = 0.0) -> float:
    intrinsic = min(spread.width, max(0.0, spread.short_strike - underlying_price))
    return (spread.credit - intrinsic) * 100 * spread.contracts - commissions


def debit_expiration_pnl(spread: DebitSpread, underlying_price: float, commissions: float = 0.0) -> float:
    """Expiration P&L for a defined-risk debit spread in either direction."""
    if spread.direction == "bearish":
        long_intrinsic = max(0.0, spread.long_strike - underlying_price)
        short_intrinsic = max(0.0, spread.short_strike - underlying_price)
    elif spread.direction == "bullish":
        long_intrinsic = max(0.0, underlying_price - spread.long_strike)
        short_intrinsic = max(0.0, underlying_price - spread.short_strike)
    else:
        raise ValueError(f"unsupported debit spread direction: {spread.direction}")
    intrinsic = min(spread.width, max(0.0, long_intrinsic - short_intrinsic))
    return (intrinsic - spread.debit) * 100 * spread.contracts - commissions


def early_assignment_exposure(spread: VerticalSpread, underlying_price: float, days_to_expiry: int) -> bool:
    """Conservative flag for an American short put that is ITM before expiry."""
    return days_to_expiry > 0 and underlying_price < spread.short_strike
