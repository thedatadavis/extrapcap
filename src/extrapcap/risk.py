from dataclasses import dataclass
from datetime import datetime
from .config import RiskConfig
from .options import DebitSpread, VerticalSpread
from .orchestration.windows import execution_window


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class PortfolioRiskState:
    nav: float
    core_open_risk: float = 0.0
    asymmetric_open_risk: float = 0.0
    daily_pnl: float = 0.0
    drawdown: float = 0.0
    open_asymmetric_trades: int = 0
    ticker_open_risk: dict[str, float] | None = None
    sector_open_risk: dict[str, float] | None = None
    options_buying_power: float | None = None
    options_trading_level: int | None = None
    trading_blocked: bool = False


@dataclass(frozen=True)
class IntradayRiskState:
    symbol: str
    market_is_open: bool | None = None
    orders_today: int = 0
    last_order_at: datetime | None = None
    now: datetime | None = None
    modeled_credit: float | None = None
    observed_credit: float | None = None


def approve_intraday_order(state: IntradayRiskState, cfg: RiskConfig, *, is_exit: bool = False) -> RiskDecision:
    """Apply non-overridable intraday window, duplicate, cooldown, and fill gates."""
    now = state.now or datetime.now().astimezone()
    if state.market_is_open is False:
        return RiskDecision(False, "broker market clock closed")
    window = execution_window(now)
    if window == "closed":
        return RiskDecision(False, "market closed")
    if not is_exit and window in {"market_open_guard", "near_close_guard"}:
        return RiskDecision(False, f"execution window: {window}")
    if not is_exit and state.orders_today >= cfg.max_orders_per_symbol_per_day:
        return RiskDecision(False, "symbol daily order cap")
    if not is_exit and state.last_order_at is not None:
        elapsed = (now - state.last_order_at).total_seconds() / 60
        if elapsed < cfg.intraday_cooldown_minutes:
            return RiskDecision(False, "symbol cooldown")
    if state.modeled_credit and state.observed_credit is not None:
        deviation = abs(state.observed_credit - state.modeled_credit) / abs(state.modeled_credit)
        if deviation > cfg.max_fill_deviation_pct:
            return RiskDecision(False, "fill-quality circuit breaker")
    return RiskDecision(True, "approved")


def approve_candidate(spread: VerticalSpread, state: PortfolioRiskState, cfg: RiskConfig, sector_open_risk: float = 0.0) -> RiskDecision:
    if state.trading_blocked:
        return RiskDecision(False, "account trading blocked")
    if state.options_trading_level is not None and state.options_trading_level < 3:
        return RiskDecision(False, "level 3 options approval required")
    if state.nav <= 0:
        return RiskDecision(False, "invalid NAV")
    if state.options_buying_power is not None:
        if state.options_buying_power < 0:
            return RiskDecision(False, "invalid options buying power")
        if spread.max_loss > state.options_buying_power:
            return RiskDecision(False, "insufficient options buying power")
    if state.drawdown <= -cfg.max_drawdown_brake_pct:
        return RiskDecision(False, "drawdown brake")
    if state.daily_pnl <= -state.nav * cfg.max_daily_loss_pct:
        return RiskDecision(False, "daily loss cap")
    if spread.sleeve == "core":
        if state.core_open_risk + spread.max_loss > state.nav * cfg.max_core_open_risk_pct:
            return RiskDecision(False, "core open-risk cap")
    else:
        if state.open_asymmetric_trades >= cfg.max_asymmetric_trades:
            return RiskDecision(False, "asymmetric trade-count cap")
        if state.asymmetric_open_risk + spread.max_loss > state.nav * cfg.max_asymmetric_open_risk_pct:
            return RiskDecision(False, "asymmetric open-risk cap")
    if sector_open_risk + spread.max_loss > state.nav * cfg.max_sector_concentration_pct:
        return RiskDecision(False, "sector concentration cap")
    if state.ticker_open_risk and state.ticker_open_risk.get(spread.symbol, 0.0) + spread.max_loss > state.nav * cfg.max_ticker_concentration_pct:
        return RiskDecision(False, "ticker concentration cap")
    return RiskDecision(True, "approved")


def approve_core(spread: VerticalSpread, nav: float, open_risk: float, cfg: RiskConfig) -> RiskDecision:
    if spread.sleeve != "core":
        return RiskDecision(False, "wrong sleeve")
    if open_risk + spread.max_loss > nav * cfg.max_core_open_risk_pct:
        return RiskDecision(False, "core open-risk cap")
    return RiskDecision(True, "approved")


def approve_asymmetric(
    spread: DebitSpread,
    state: PortfolioRiskState,
    cfg: RiskConfig,
    *,
    core_drawdown: float = 0.0,
) -> RiskDecision:
    if spread.sleeve != "asymmetric":
        return RiskDecision(False, "wrong sleeve")
    if spread.reward_multiple < cfg.min_asymmetric_reward_multiple:
        return RiskDecision(False, "asymmetric reward-to-risk below minimum")
    if core_drawdown <= -cfg.pause_asymmetric_core_drawdown_pct:
        return RiskDecision(False, "asymmetric deployment paused by core drawdown")
    if state.nav <= 0:
        return RiskDecision(False, "invalid NAV")
    if state.asymmetric_open_risk + spread.max_loss > state.nav * cfg.max_asymmetric_open_risk_pct:
        return RiskDecision(False, "asymmetric open-risk cap")
    if state.open_asymmetric_trades >= cfg.max_asymmetric_trades:
        return RiskDecision(False, "asymmetric trade-count cap")
    return RiskDecision(True, "approved")


def asymmetric_exit_reason(
    spread: DebitSpread,
    days_held: int,
    current_mark: float,
    cfg: RiskConfig,
) -> str | None:
    """Return a deterministic exit reason for a decaying long-premium position."""
    if days_held >= cfg.asymmetric_time_stop_days:
        return "asymmetric_time_stop"
    if current_mark < 0:
        return "invalid_negative_mark"
    decay = 1 - current_mark / spread.debit if spread.debit else 1.0
    if decay >= cfg.asymmetric_max_decay_pct:
        return "asymmetric_decay_stop"
    return None
