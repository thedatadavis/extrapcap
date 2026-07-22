from dataclasses import asdict, dataclass, field
from datetime import timedelta
import pandas as pd
from ..config import AppConfig
from ..fills import debit_expiration_pnl, vertical_expiration_pnl
from ..options import build_asymmetric_debit_spread, build_credit_spread
from ..portfolio import SleeveLedger
from ..risk import PortfolioRiskState, approve_asymmetric, approve_candidate
from ..reporting.metrics import summarize_returns
from ..signals import SNIPER_FEATURES, relative_features
from ..orchestration.windows import execution_window


@dataclass
class BacktestResult:
    variant: str
    trades: int
    wins: int
    premium_collected: float
    asymmetric_budget: float
    rejected_trap: int
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    expectancy: float = 0.0
    profit_factor: float | None = 0.0
    asymmetric_deployed: float = 0.0
    win_rate: float = 0.0
    total_return: float = 0.0
    sharpe_annualized: float = 0.0
    sortino_annualized: float = 0.0
    cagr: float | None = None
    tail_loss_p05: float = 0.0
    worst_return: float = 0.0
    data_scope: str = "modeled_option_proxy"
    initial_nav: float = 100_000.0
    portfolio_total_return: float = 0.0
    portfolio_max_drawdown: float = 0.0
    portfolio_sharpe_annualized: float = 0.0
    portfolio_sortino_annualized: float = 0.0
    portfolio_cagr: float | None = None
    classifier_used: bool = False
    news_filter_used: bool = False
    news_vetoes: int = 0
    turn_of_month_only: bool = False
    crash_protocol_enabled: bool = False
    crash_trades: int = 0
    crash_pnl: float = 0.0
    asymmetric_rejected: int = 0
    asymmetric_enabled: bool = True
    mode: str = "end_of_day"
    return_on_capital: float = 0.0
    average_trade_duration_days: float = 0.0
    average_open_risk_utilization: float = 0.0
    trade_skewness: float = 0.0
    regime_decomposition: dict = field(default_factory=dict)
    sector_concentration: dict | str = "unavailable_without_sector_metadata"
    intraday_vetoes: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def run_backtest(
    bars: pd.DataFrame,
    benchmark: pd.Series,
    variant: str,
    cfg: AppConfig,
    sniper=None,
    *,
    include_asymmetric: bool = True,
    include_crash_protocol: bool = False,
    turn_of_month_only: bool = False,
    news_events: pd.DataFrame | None = None,
    mode: str = "end_of_day",
    eligible_symbols: set[str] | None = None,
    sector_by_symbol: dict[str, str] | None = None,
) -> BacktestResult:
    if mode not in {"end_of_day", "hybrid", "intraday_loop"}:
        raise ValueError("mode must be end_of_day, hybrid, or intraday_loop")
    frame = relative_features(bars, benchmark, cfg.strategy.z_window)
    if eligible_symbols is not None:
        allowed = {symbol.upper() for symbol in eligible_symbols}
        frame = frame[frame["symbol"].str.upper().isin(allowed)].copy()
    ledger = SleeveLedger()
    frame["next_close"] = frame.groupby("symbol")["close"].shift(-1)
    frame["next_date"] = frame.groupby("symbol")["date"].shift(-1)
    frame = frame.sort_values(["date", "symbol"]).reset_index(drop=True)
    trades = wins = trap = 0
    open_risk = 0.0
    releases: dict[pd.Timestamp, list[tuple[str, str | None, float]]] = {}
    crash_open_risk = 0.0
    crash_releases: dict[pd.Timestamp, float] = {}
    asymmetric_open_risk = 0.0
    asymmetric_open_trades = 0
    asymmetric_releases: dict[pd.Timestamp, tuple[float, int]] = {}
    pnl = []
    pnl_events: list[tuple[pd.Timestamp, float]] = []
    realized_by_date: dict[pd.Timestamp, float] = {}
    ticker_open_risk: dict[str, float] = {}
    sector_open_risk: dict[str, float] = {}
    sector_map = {str(key).upper(): str(value) for key, value in (sector_by_symbol or {}).items()}
    peak_nav = 100_000.0
    max_sector_risk = 0.0
    crash_trades = 0
    crash_pnl = 0.0
    asymmetric_rejected = 0
    trade_durations: list[int] = []
    utilization_samples: list[float] = []
    regime_returns: dict[str, list[float]] = {"positive": [], "negative": [], "neutral": []}
    intraday_available = bool(
        not frame.empty
        and frame.assign(_session=frame["date"].dt.date).groupby(["symbol", "_session"]).size().max() > 1
    )
    intraday_entries: set[tuple[str, object]] = set()
    last_intraday_entry: dict[str, pd.Timestamp] = {}
    intraday_vetoes = 0

    def allows_intraday_entry(symbol: str, timestamp: pd.Timestamp) -> bool:
        nonlocal intraday_vetoes
        if mode == "end_of_day" or not intraday_available:
            return True
        window = execution_window(timestamp.to_pydatetime())
        allowed_windows = {"close_positioning"} if mode == "hybrid" else {"open_liquidity", "close_positioning"}
        if window not in allowed_windows:
            intraday_vetoes += 1
            return False
        session = timestamp.date()
        key = (symbol.upper(), session)
        if key in intraday_entries:
            intraday_vetoes += 1
            return False
        previous = last_intraday_entry.get(symbol.upper())
        if previous is not None and timestamp - previous < timedelta(minutes=cfg.intraday_cooldown_minutes):
            intraday_vetoes += 1
            return False
        intraday_entries.add(key)
        last_intraday_entry[symbol.upper()] = timestamp
        return True
    news_vetoes = 0
    structural_news = set()
    if news_events is not None:
        required = {"date", "symbol", "structural_risk"}
        missing = required - set(news_events.columns)
        if missing:
            raise ValueError(f"news events missing required columns: {sorted(missing)}")
        structural_news = {
            (pd.Timestamp(row.date).normalize(), str(row.symbol).upper())
            for row in news_events.itertuples()
            if bool(row.structural_risk)
        }
    for row in frame.itertuples():
        current_date = pd.Timestamp(row.date)
        for release_date, records in list(releases.items()):
            if release_date <= current_date:
                for symbol, sector, amount in records:
                    open_risk = max(0.0, open_risk - amount)
                    ticker_open_risk[symbol] = max(0.0, ticker_open_risk.get(symbol, 0.0) - amount)
                    if sector is not None:
                        sector_open_risk[sector] = max(0.0, sector_open_risk.get(sector, 0.0) - amount)
                del releases[release_date]
        crash_released = sum(amount for date, amount in crash_releases.items() if date <= current_date)
        if crash_released:
            crash_open_risk = max(0.0, crash_open_risk - crash_released)
            crash_releases = {date: amount for date, amount in crash_releases.items() if date > current_date}
        for release_date, (risk_amount, trade_count) in list(asymmetric_releases.items()):
            if release_date <= current_date:
                asymmetric_open_risk = max(0.0, asymmetric_open_risk - risk_amount)
                asymmetric_open_trades = max(0, asymmetric_open_trades - trade_count)
                del asymmetric_releases[release_date]
        utilization_samples.append((open_risk + crash_open_risk + asymmetric_open_risk) / 100_000)
        current_equity = 100_000.0 + sum(value for day, value in realized_by_date.items() if day <= current_date.normalize())
        peak_nav = max(peak_nav, current_equity)
        drawdown = current_equity / peak_nav - 1.0 if peak_nav else -1.0
        daily_pnl = realized_by_date.get(current_date.normalize(), 0.0)
        max_sector_risk = max(max_sector_risk, max(sector_open_risk.values(), default=0.0))
        if pd.isna(row.next_close):
            continue
        if turn_of_month_only and not bool(row.turn_of_month):
            continue
        if (current_date.normalize(), str(row.symbol).upper()) in structural_news:
            news_vetoes += 1
            continue
        if row.robust_z > cfg.strategy.z_threshold:
            continue
        if sniper is None:
            # Explicit fallback for fixture-only research. Paper mode must pass a
            # trained model into this function before enabling autonomous submit.
            probability = 0.72 if row.robust_z <= cfg.strategy.z_threshold else 0.62
        else:
            feature_row = pd.DataFrame([{name: getattr(row, name) for name in SNIPER_FEATURES}])
            probability = float(sniper.predict_probability(feature_row)[0])
        if probability < cfg.strategy.trap_low:
            if include_crash_protocol:
                crash = build_asymmetric_debit_spread(row.symbol, row.close, "bearish")
                if crash_open_risk + crash.max_loss <= 100_000 * cfg.risk.max_asymmetric_open_risk_pct and allows_intraday_entry(row.symbol, current_date):
                    crash_result = debit_expiration_pnl(crash, float(row.next_close))
                    crash_trades += 1
                    crash_pnl += crash_result
                    pnl_events.append((pd.Timestamp(row.next_date), crash_result))
                    crash_open_risk += crash.max_loss
                    crash_exit_date = pd.Timestamp(row.next_date)
                    crash_releases[crash_exit_date] = crash_releases.get(crash_exit_date, 0.0) + crash.max_loss
            continue
        if cfg.strategy.trap_low <= probability < cfg.strategy.trap_high:
            trap += 1
            continue
        spread = build_credit_spread(row.symbol, row.close, variant, cfg.strategy.spread_width)
        sector = sector_map.get(str(row.symbol).upper())
        decision = approve_candidate(
            spread,
            PortfolioRiskState(
                nav=100_000,
                core_open_risk=open_risk,
                daily_pnl=daily_pnl,
                drawdown=drawdown,
                ticker_open_risk=ticker_open_risk,
            ),
            cfg.risk,
            sector_open_risk=sector_open_risk.get(sector, 0.0) if sector is not None else 0.0,
        )
        if not decision.allowed:
            continue
        if not allows_intraday_entry(row.symbol, current_date):
            continue
        trades += 1
        next_price = float(row.next_close)
        trade_pnl = vertical_expiration_pnl(spread, next_price)
        pnl.append(trade_pnl / spread.max_loss)
        exit_date = pd.Timestamp(row.next_date).normalize()
        pnl_events.append((exit_date, trade_pnl))
        realized_by_date[exit_date] = realized_by_date.get(exit_date, 0.0) + trade_pnl
        trade_durations.append(max(0, (pd.Timestamp(row.next_date) - current_date).days))
        regime = "positive" if row.market_regime > 0 else "negative" if row.market_regime < 0 else "neutral"
        regime_returns[regime].append(trade_pnl / spread.max_loss)
        wins += int(trade_pnl > 0)
        ledger.realize_premium(spread.max_profit, cfg.strategy.premium_funding_pct)
        # One-bar holding period: release core risk and, when funded, deploy a
        # small continuation debit spread on the same signal for separate analysis.
        open_risk += spread.max_loss
        releases.setdefault(exit_date, []).append((str(row.symbol).upper(), sector, spread.max_loss))
        ticker_open_risk[str(row.symbol).upper()] = ticker_open_risk.get(str(row.symbol).upper(), 0.0) + spread.max_loss
        if sector is not None:
            sector_open_risk[sector] = sector_open_risk.get(sector, 0.0) + spread.max_loss
        if include_asymmetric and row.robust_z <= cfg.strategy.z_threshold and ledger.asymmetric_budget >= 100:
            asymmetric = build_asymmetric_debit_spread(row.symbol, row.close, "bearish")
            asymmetric_decision = approve_asymmetric(
                asymmetric,
                PortfolioRiskState(
                    nav=100_000,
                    asymmetric_open_risk=asymmetric_open_risk,
                    open_asymmetric_trades=asymmetric_open_trades,
                ),
                cfg.risk,
            )
            if asymmetric_decision.allowed:
                ledger.deploy_asymmetric(asymmetric.max_loss)
                ledger.realize_asymmetric(-asymmetric.max_loss)
                pnl_events.append((current_date, -asymmetric.max_loss))
                asymmetric_open_risk += asymmetric.max_loss
                asymmetric_open_trades += 1
                asymmetric_releases[exit_date] = (
                    asymmetric_releases.get(exit_date, (0.0, 0))[0] + asymmetric.max_loss,
                    asymmetric_releases.get(exit_date, (0.0, 0))[1] + 1,
                )
            else:
                asymmetric_rejected += 1
    elapsed_years = None
    if not frame.empty:
        elapsed_days = (frame["date"].max() - frame["date"].min()).days
        elapsed_years = elapsed_days / 365.25 if elapsed_days > 0 else None
    metrics = summarize_returns(pnl, elapsed_years=elapsed_years)
    initial_nav = 100_000.0
    event_dates = [event_date for event_date, _ in pnl_events]
    dates = pd.DatetimeIndex(
        sorted(set(frame["date"].dropna().tolist()) | set(event_dates))
    )
    daily_pnl = pd.Series(0.0, index=dates)
    for event_date, event_pnl in pnl_events:
        daily_pnl.loc[event_date] += event_pnl
    portfolio_metrics = summarize_returns(daily_pnl / initial_nav, elapsed_years=elapsed_years)
    return BacktestResult(
        variant=variant,
        trades=trades,
        wins=wins,
        premium_collected=ledger.premium_collected,
        asymmetric_budget=ledger.asymmetric_budget,
        rejected_trap=trap,
        total_pnl=sum(pnl),
        max_drawdown=metrics["max_drawdown"],
        expectancy=metrics["expectancy"],
        profit_factor=metrics["profit_factor"],
        asymmetric_deployed=ledger.asymmetric_deployed,
        win_rate=metrics["win_rate"],
        total_return=metrics["total_return"],
        sharpe_annualized=metrics["sharpe_annualized"],
        sortino_annualized=metrics["sortino_annualized"],
        cagr=metrics["cagr"],
        tail_loss_p05=metrics["tail_loss_p05"],
        worst_return=metrics["worst_return"],
        data_scope="modeled_option_proxy",
        initial_nav=initial_nav,
        portfolio_total_return=portfolio_metrics["total_return"],
        portfolio_max_drawdown=portfolio_metrics["max_drawdown"],
        portfolio_sharpe_annualized=portfolio_metrics["sharpe_annualized"],
        portfolio_sortino_annualized=portfolio_metrics["sortino_annualized"],
        portfolio_cagr=portfolio_metrics["cagr"],
        classifier_used=sniper is not None,
        news_filter_used=news_events is not None,
        news_vetoes=news_vetoes,
        turn_of_month_only=turn_of_month_only,
        crash_protocol_enabled=include_crash_protocol,
        crash_trades=crash_trades,
        crash_pnl=crash_pnl,
        asymmetric_rejected=asymmetric_rejected,
        asymmetric_enabled=include_asymmetric,
        mode=mode,
        return_on_capital=float(daily_pnl.sum() / initial_nav),
        average_trade_duration_days=float(sum(trade_durations) / len(trade_durations)) if trade_durations else 0.0,
        average_open_risk_utilization=float(sum(utilization_samples) / len(utilization_samples)) if utilization_samples else 0.0,
        trade_skewness=float(metrics["skewness"]),
        regime_decomposition={regime: summarize_returns(values) for regime, values in regime_returns.items()},
        sector_concentration=(
            {
                "metadata_available": True,
                "max_open_risk_pct": float(max_sector_risk / initial_nav),
                "by_sector": {
                    sector: float(value / initial_nav)
                    for sector, value in sorted(sector_open_risk.items())
                    if value > 0
                },
            }
            if sector_map
            else "unavailable_without_sector_metadata"
        ),
        intraday_vetoes=intraday_vetoes,
    )
