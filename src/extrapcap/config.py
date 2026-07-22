from enum import StrEnum
import os
from pydantic import BaseModel, Field


class OperatingMode(StrEnum):
    END_OF_DAY = "end_of_day"
    HYBRID = "hybrid"
    INTRADAY_LOOP = "intraday_loop"


class RiskConfig(BaseModel):
    max_core_open_risk_pct: float = Field(0.10, gt=0, le=1)
    max_asymmetric_open_risk_pct: float = Field(0.03, gt=0, le=1)
    max_daily_loss_pct: float = Field(0.02, gt=0, le=1)
    max_drawdown_brake_pct: float = Field(0.10, gt=0, le=1)
    max_sector_concentration_pct: float = Field(0.25, gt=0, le=1)
    max_ticker_concentration_pct: float = Field(0.10, gt=0, le=1)
    max_asymmetric_trades: int = Field(3, gt=0)
    max_orders_per_symbol_per_day: int = Field(3, gt=0)
    intraday_cooldown_minutes: int = Field(15, ge=0)
    max_fill_deviation_pct: float = Field(0.25, ge=0, le=1)
    min_asymmetric_reward_multiple: float = Field(2.0, ge=1)
    asymmetric_time_stop_days: int = Field(10, gt=0)
    asymmetric_max_decay_pct: float = Field(0.50, gt=0, le=1)
    pause_asymmetric_core_drawdown_pct: float = Field(0.05, gt=0, le=1)
    core_profit_target_pct: float = Field(0.50, gt=0, lt=1)
    core_stop_loss_multiple: float = Field(2.0, ge=1)
    core_time_stop_days: int = Field(5, gt=0)


class StrategyConfig(BaseModel):
    z_window: int = Field(20, ge=5)
    z_threshold: float = Field(-2.0, le=-0.1)
    improved_delta_min: float = Field(0.15, gt=0, lt=1)
    improved_delta_max: float = Field(0.20, gt=0, lt=1)
    spread_width: float = Field(5.0, gt=0)
    min_credit_pct_width: float = Field(0.20, gt=0, lt=1)
    premium_funding_pct: float = Field(0.15, gt=0, le=0.20)
    trap_low: float = Field(0.50, ge=0, le=1)
    trap_high: float = Field(0.65, ge=0, le=1)


class AppConfig(BaseModel):
    mode: OperatingMode = OperatingMode.END_OF_DAY
    benchmark: str = "SPY"
    paper_only: bool = True
    risk: RiskConfig = RiskConfig()
    strategy: StrategyConfig = StrategyConfig()

    @classmethod
    def from_env(cls) -> "AppConfig":
        mode = os.getenv("EXTRAPCAP_MODE", OperatingMode.END_OF_DAY)
        return cls(mode=mode, paper_only=os.getenv("ALPACA_PAPER", "true").lower() == "true")
