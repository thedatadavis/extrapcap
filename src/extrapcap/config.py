import os

from pydantic import BaseModel, Field


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
    early_profit_target_pct: float = Field(0.35, gt=0, lt=1)
    early_profit_target_days: int = Field(2, gt=0)
    core_stop_loss_multiple: float = Field(2.0, ge=1)
    core_time_stop_days: int = Field(4, gt=0)
    max_holding_sessions: int = Field(3, ge=1)
    forced_exit_dte: int = Field(3, ge=0)
    zero_dte_entry_cutoff_minutes: int = Field(30, ge=1)
    zero_dte_risk_fraction: float = Field(0.25, gt=0, le=1)
    one_dte_risk_fraction: float = Field(0.50, gt=0, le=1)


class StrategyConfig(BaseModel):
    z_window: int = Field(20, ge=5)
    z_threshold: float = Field(-0.5, le=-0.1)
    improved_delta_min: float = Field(0.15, gt=0, lt=1)
    improved_delta_max: float = Field(0.20, gt=0, lt=1)
    spread_width: float = Field(5.0, gt=0)
    min_credit_pct_width: float = Field(0.05, gt=0, lt=1)
    max_option_quote_age_seconds: int = Field(1800, gt=0)
    max_option_spread_pct: float = Field(0.40, gt=0, le=1)
    premium_funding_pct: float = Field(0.15, gt=0, le=0.20)
    dte_min: int = Field(0, ge=0)
    dte_max: int = Field(21, ge=1)
    preferred_dte: int = Field(10, ge=0)


class AppConfig(BaseModel):
    benchmark: str = "SPY"
    paper_only: bool = True
    risk: RiskConfig = RiskConfig()
    strategy: StrategyConfig = StrategyConfig()

    @classmethod
    def from_env(cls) -> "AppConfig":
        if os.getenv("ALPACA_PAPER", "true").lower() != "true":
            raise RuntimeError("extrapcap only supports Alpaca paper trading")
        return cls(paper_only=True)
