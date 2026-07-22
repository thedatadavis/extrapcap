from __future__ import annotations

from dataclasses import asdict, dataclass
import pandas as pd

from ..fills import FillAssumptions, credit_fill, vertical_expiration_pnl
from ..options import VerticalSpread
from ..options_data import DataTier
from ..reporting.metrics import summarize_returns


@dataclass
class ChainBacktestResult:
    data_tier: str
    trades: int
    wins: int
    rejected_bad_fill: int
    premium_collected: float
    total_pnl: float
    expectancy: float
    max_drawdown: float
    profit_factor: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def run_chain_backtest(observations: pd.DataFrame, assumptions: FillAssumptions | None = None, allow_reconstructed: bool = False) -> ChainBacktestResult:
    assumptions = assumptions or FillAssumptions()
    tiers = {str(value) for value in observations.get("data_tier", pd.Series(dtype=str)).dropna().unique()}
    if not tiers:
        raise ValueError("chain observations must include data_tier")
    if not allow_reconstructed and DataTier.RECONSTRUCTED.value in tiers:
        raise ValueError("reconstructed observations require allow_reconstructed=True")
    returns, pnl_values, premium, trades, wins, rejected = [], [], 0.0, 0, 0, 0
    for row in observations.sort_values("entry_date").itertuples():
        try:
            dollars = credit_fill(float(row.short_bid), float(row.long_ask), 1, assumptions)
        except ValueError:
            rejected += 1
            continue
        credit = dollars / 100
        if credit <= 0:
            rejected += 1
            continue
        spread = VerticalSpread(row.underlying, float(row.short_strike), float(row.long_strike), credit)
        pnl = vertical_expiration_pnl(spread, float(row.expiry_underlying_close), assumptions.commission_per_contract * 2)
        trades += 1
        wins += int(pnl > 0)
        premium += spread.max_profit
        pnl_values.append(pnl)
        returns.append(pnl / spread.max_loss)
    metrics = summarize_returns(returns)
    return ChainBacktestResult("+".join(sorted(tiers)), trades, wins, rejected, premium, float(sum(pnl_values)), metrics["expectancy"], metrics["max_drawdown"], metrics["profit_factor"])
