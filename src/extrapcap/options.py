from dataclasses import dataclass


@dataclass(frozen=True)
class VerticalSpread:
    symbol: str
    short_strike: float
    long_strike: float
    credit: float
    contracts: int = 1
    sleeve: str = "core"

    def __post_init__(self) -> None:
        if self.long_strike >= self.short_strike:
            raise ValueError("put vertical requires long strike below short strike")
        if self.credit <= 0 or self.credit >= self.width:
            raise ValueError("credit must be positive and less than spread width")
        if self.contracts < 1:
            raise ValueError("contracts must be positive")

    @property
    def width(self) -> float:
        return self.short_strike - self.long_strike

    @property
    def max_loss(self) -> float:
        return (self.width - self.credit) * 100 * self.contracts

    @property
    def max_profit(self) -> float:
        return self.credit * 100 * self.contracts


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
        return self.max_profit / self.max_loss


def build_credit_spread(symbol: str, price: float, variant: str, width: float = 5.0) -> VerticalSpread:
    short = round(price * (0.98 if variant == "baseline" else 0.95) / 5) * 5
    credit = round(width * (0.30 if variant == "baseline" else 0.22), 2)
    return VerticalSpread(symbol, short, short - width, credit, sleeve="core")


def build_asymmetric_debit_spread(symbol: str, price: float, direction: str = "bearish", width: float = 10.0) -> DebitSpread:
    if direction == "bearish":
        long_strike = round(price * 1.02 / 5) * 5
        return DebitSpread(symbol, long_strike, long_strike - width, 1.0, sleeve="asymmetric", direction="bearish")
    long_strike = round(price * 1.02 / 5) * 5
    return DebitSpread(symbol, long_strike, long_strike + width, 1.0, sleeve="asymmetric", direction="bullish")
