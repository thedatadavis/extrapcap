from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class VerticalSpread:
    symbol: str
    short_strike: float
    long_strike: float
    credit: float
    contracts: int = 1
    sleeve: str = "core"
    direction: str = "bullish"

    def __post_init__(self) -> None:
        if self.short_strike == self.long_strike:
            raise ValueError("vertical spread strikes must differ")
        if self.credit <= 0 or self.credit >= self.width:
            raise ValueError("credit must be positive and less than spread width")
        if self.credit < 0.35 * self.width:
            raise ValueError(
                f"Credit {self.credit} is too low for width {self.width}; risk ratio violates safety policy (< 0.35)"
            )
        if self.contracts < 1:
            raise ValueError("contracts must be positive")

    @property
    def width(self) -> float:
        return abs(self.short_strike - self.long_strike)

    @property
    def max_loss(self) -> float:
        return (self.width - self.credit) * 100 * self.contracts

    @property
    def max_profit(self) -> float:
        return self.credit * 100 * self.contracts


CreditSpread = VerticalSpread


@dataclass(frozen=True)
class DebitSpread:
    symbol: str
    long_strike: float
    short_strike: float
    debit: float
    contracts: int = 1
    sleeve: str = "asymmetric"
    direction: str = "bullish"

    def __post_init__(self) -> None:
        if self.short_strike == self.long_strike:
            raise ValueError("debit spread strikes must differ")
        if self.debit <= 0 or self.debit >= self.width:
            raise ValueError("debit must be positive and less than spread width")
        if self.debit > 0.30 * self.width:
            raise ValueError(
                f"debit {self.debit} exceeds 30% of width {self.width}; violates 1:3 reward-to-risk policy"
            )

    @property
    def width(self) -> float:
        return abs(self.short_strike - self.long_strike)

    @property
    def max_loss(self) -> float:
        return self.debit * 100 * self.contracts

    @property
    def max_profit(self) -> float:
        return (self.width - self.debit) * 100 * self.contracts

    @property
    def reward_multiple(self) -> float:
        return self.max_profit / self.max_loss if self.max_loss > 0 else float("inf")


@dataclass(frozen=True)
class BrokenWingButterfly:
    symbol: str
    lower_strike: float   # Long 1
    middle_strike: float  # Short 2
    upper_strike: float   # Long 1 (broken wing)
    net_credit: float
    direction: str = "bullish"
    contracts: int = 1

    def __post_init__(self) -> None:
        if not (self.lower_strike < self.middle_strike < self.upper_strike):
            raise ValueError("broken wing butterfly strikes must satisfy lower < middle < upper")
        if self.net_credit < 0:
            raise ValueError("broken wing butterfly must be entered for flat or net credit (>= 0)")
        if self.contracts < 1:
            raise ValueError("contracts must be positive")

    @property
    def lower_width(self) -> float:
        return abs(self.middle_strike - self.lower_strike)

    @property
    def upper_width(self) -> float:
        return abs(self.upper_strike - self.middle_strike)

    @property
    def max_loss(self) -> float:
        """Downside risk if stock collapses through the broken wing."""
        embedded_risk = max(0.0, self.lower_width - self.upper_width)
        return max(0.0, (embedded_risk - self.net_credit) * 100 * self.contracts)

    @property
    def max_profit(self) -> float:
        """Max profit achieved if underlying pins the short middle strike at expiration."""
        body_width = (
            self.middle_strike - self.lower_strike
            if self.direction == "bearish"
            else self.upper_strike - self.middle_strike
        )
        return (body_width + self.net_credit) * 100 * self.contracts


def build_credit_spread(
    symbol: str, price: float, variant: str = "baseline", width: float = 5.0
) -> VerticalSpread:
    """Construct a compressed ATM/NTM credit spread collecting >= 40% of width.

    Eliminates far-OTM strikes (0.15 - 0.25 delta), targeting ATM/NTM strikes (Delta 0.40 - 0.50).
    """
    short = round(price / 5.0) * 5.0
    credit = round(width * (0.42 if variant == "baseline" else 0.40), 2)
    return VerticalSpread(
        symbol=symbol,
        short_strike=short,
        long_strike=short - width,
        credit=credit,
        sleeve="core",
        direction="bullish",
    )


def build_positive_skew_debit_spread(
    symbol: str,
    spot_price: float,
    direction: str,  # "bullish" or "bearish"
    width: float = 4.0,
    target_debit_ratio: float = 0.25,  # Pay <= 25% of width for 1:3 reward-to-risk
) -> DebitSpread:
    """Build asymmetric 1:3 positive-skew vertical debit spread.

    - Bullish Reversal (Oversold Z <= -2.0):
      Long Call ATM (0.40 - 0.50 Delta), Short Call OTM (0.15 - 0.25 Delta).
    - Bearish Reversal (Overbought Z >= +2.0):
      Long Put ATM (0.40 - 0.50 Delta), Short Put OTM (0.15 - 0.25 Delta).
    """
    if spot_price <= 0:
        raise ValueError(f"invalid spot_price {spot_price}")
    if width <= 0:
        raise ValueError(f"invalid spread width {width}")
    if not 0 < target_debit_ratio <= 0.30:
        raise ValueError(f"target_debit_ratio {target_debit_ratio} exceeds max allowable 0.30")

    debit = round(width * target_debit_ratio, 2)
    debit = max(0.01, min(debit, round(0.30 * width, 2)))

    strike_step = 1.0 if width <= 2.5 else (2.5 if width <= 5.0 else 5.0)
    long_strike = round(spot_price / strike_step) * strike_step

    if direction == "bullish":
        short_strike = long_strike + width
        return DebitSpread(
            symbol=symbol,
            long_strike=long_strike,
            short_strike=short_strike,
            debit=debit,
            sleeve="asymmetric",
            direction="bullish",
        )
    elif direction == "bearish":
        short_strike = long_strike - width
        return DebitSpread(
            symbol=symbol,
            long_strike=long_strike,
            short_strike=short_strike,
            debit=debit,
            sleeve="asymmetric",
            direction="bearish",
        )
    else:
        raise ValueError(f"invalid direction '{direction}', must be 'bullish' or 'bearish'")


def build_asymmetric_debit_spread(
    symbol: str,
    price: float,
    direction: str = "bearish",
    width: float = 4.0,
    target_debit_ratio: float = 0.25,
) -> DebitSpread:
    return build_positive_skew_debit_spread(
        symbol=symbol,
        spot_price=price,
        direction=direction,
        width=width,
        target_debit_ratio=target_debit_ratio,
    )


def build_broken_wing_butterfly(
    symbol: str,
    spot_price: float,
    direction: str = "bullish",
    implied_vol: float = 0.25,
    dte_days: int = 10,
    net_credit: float = 0.10,
) -> BrokenWingButterfly:
    """Construct a Broken Wing Butterfly structure for asymmetric low-risk reversal exposure.

    For bullish/oversold setups:
    - Buy 1 Put at Spot (upper strike)
    - Sell 2 Puts at Spot - 1.0 sigma (middle strike)
    - Buy 1 Put at Spot - 2.5 sigma (lower strike / broken wing)
    """
    sigma = max(1.0, spot_price * implied_vol * math.sqrt(dte_days / 365.0))
    strike_step = 1.0 if spot_price < 100 else 5.0

    if direction == "bullish":
        upper = round(spot_price / strike_step) * strike_step
        middle = round((spot_price - 1.0 * sigma) / strike_step) * strike_step
        lower = round((spot_price - 2.5 * sigma) / strike_step) * strike_step
        if middle >= upper:
            middle = upper - strike_step
        if lower >= middle:
            lower = middle - strike_step * 1.5
        return BrokenWingButterfly(
            symbol=symbol,
            lower_strike=lower,
            middle_strike=middle,
            upper_strike=upper,
            net_credit=net_credit,
            direction="bullish",
        )
    else:
        lower = round(spot_price / strike_step) * strike_step
        middle = round((spot_price + 1.0 * sigma) / strike_step) * strike_step
        upper = round((spot_price + 2.5 * sigma) / strike_step) * strike_step
        if middle <= lower:
            middle = lower + strike_step
        if upper <= middle:
            upper = middle + strike_step * 1.5
        return BrokenWingButterfly(
            symbol=symbol,
            lower_strike=lower,
            middle_strike=middle,
            upper_strike=upper,
            net_credit=net_credit,
            direction="bearish",
        )
