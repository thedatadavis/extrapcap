import pandas as pd
import pytest

from extrapcap.config import AppConfig, RiskConfig
from extrapcap.execution.orders import OrderEnvelope
from extrapcap.fills import debit_expiration_pnl
from extrapcap.options import DebitSpread, VerticalSpread
from extrapcap.portfolio import SleeveLedger
from extrapcap.risk import PortfolioRiskState, approve_asymmetric, dte_risk_fraction
from extrapcap.signals import robust_zscore


def test_constant_window_has_neutral_zscore():
    assert robust_zscore(pd.Series([1, 1, 1, 1, 1]), window=3).iloc[-1] == 0


def test_defined_risk_spreads():
    credit = VerticalSpread("ABC", 100, 95, 1.0)
    assert credit.max_loss == 400
    assert credit.max_profit == 100
    debit = DebitSpread("ABC", 100, 90, 1.0, direction="bearish")
    assert debit_expiration_pnl(debit, 85) == pytest.approx(900)


def test_premium_funding_is_bounded():
    ledger = SleeveLedger()
    assert ledger.realize_premium(100, AppConfig().strategy.premium_funding_pct) == 15


def test_paper_risk_is_tighter_for_expiring_options():
    assert dte_risk_fraction(0, RiskConfig()) == pytest.approx(0.25)
    assert dte_risk_fraction(1, RiskConfig()) == pytest.approx(0.50)
    assert dte_risk_fraction(2, RiskConfig()) == 1.0


def test_asymmetric_admission_is_defined_risk():
    spread = DebitSpread("ABC", 100, 90, 1.0, direction="bearish")
    assert approve_asymmetric(spread, PortfolioRiskState(nav=100_000), RiskConfig()).allowed


def test_order_id_is_deterministic():
    legs = ({"symbol": "ABC240119P00100000", "asset_class": "us_option", "side": "sell", "position_intent": "sell_to_open", "ratio_qty": 1},)
    a = OrderEnvelope("2026-07-22", "ABC", "sell_to_open", legs, "core", limit_price=1.0)
    b = OrderEnvelope("2026-07-22", "ABC", "sell_to_open", legs, "core", limit_price=1.0)
    assert a.client_order_id == b.client_order_id
