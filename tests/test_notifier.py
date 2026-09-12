from modal_app.notifier import format_candidate_orders_text, format_position_exits_text


def test_format_candidate_orders_text_credit_spread():
    orders = [
        {
            "ticker": "UPS",
            "client_order_id": "test-order-1",
            "model_probability": 0.625,
            "quantity": 25,
            "side": "sell_to_open",
            "filled_avg_price": -1.48,
            "status": "filled",
            "legs": [
                {
                    "symbol": "UPS260925P00102000",
                    "side": "sell",
                    "position_intent": "sell_to_open",
                    "ratio_qty": 1,
                },
                {
                    "symbol": "UPS260925P00098000",
                    "side": "buy",
                    "position_intent": "buy_to_open",
                    "ratio_qty": 1,
                },
            ],
        }
    ]

    text = format_candidate_orders_text("2026-09-08", orders)
    assert "EXTRAPOLATION CAPITAL · PAPER ORDERS SUBMITTED" in text
    assert "Date: 2026-09-08" in text
    assert "• UPS · 25x Put Credit Spread" in text
    assert "Short $102 / Long $98" in text
    assert "Exp: 2026-09-25" in text
    assert "$1.48 Net Credit (Filled: 25 contracts)" in text
    assert "$3,700.00 collected" in text
    assert "62.5%" in text
    assert "test-order-1" in text


def test_format_position_exits_text_profit_target():
    exits = [
        {
            "ticker": "UPS",
            "reason": "credit_profit_target",
            "quantity": 25,
            "entry_credit": 1.48,
            "exit_price": 0.70,
            "realized_pnl": 1950.0,
            "legs": [
                {
                    "symbol": "UPS260925P00102000",
                    "side": "sell",
                },
                {
                    "symbol": "UPS260925P00098000",
                    "side": "buy",
                },
            ],
        }
    ]

    text = format_position_exits_text("2026-09-08", exits)
    assert "EXTRAPOLATION CAPITAL · POSITION EXITS TRIGGERED" in text
    assert "Positions Closed: 1" in text
    assert "• UPS · 25 contract(s)" in text
    assert "Exit Trigger:  Profit Target Hit (80% max gain captured)" in text
    assert "Spread:        Short $102 / Long $98 (Exp: 2026-09-25)" in text
    assert "Entry Credit:  $1.48 / share ($3,700.00 collected)" in text
    assert "Exit Debit:    $0.70 / share ($1,750.00 to close)" in text
    assert "Realized P&L:  +$1,950.00 (+52.7% on credit)" in text


def test_format_daily_report_text():
    from modal_app.notifier import format_daily_report_text

    summary = {
        "evaluated": 754,
        "passed_gate": 228,
        "passed_prob": 224,
        "submitted": 1,
        "filled": 1,
        "wsj_summary": "Markets on Sept. 11, 2026, saw quantitative screening evaluate 754 candidates...",
    }
    account = {
        "equity": 66578.21,
        "cash": 86234.21,
        "buying_power": 148936.84,
        "daily_pnl": 8036.34,
    }
    orders = [
        {
            "ticker": "ADBE",
            "quantity": 15,
            "side": "sell_to_open",
            "limit_price": 4.94,
            "filled_avg_price": -3.55,
            "execution_status": "filled",
            "legs": [
                {"symbol": "ADBE260918P00247500", "side": "sell"},
                {"symbol": "ADBE260918P00237500", "side": "buy"},
            ],
            "metadata": {
                "feasibility_context": {
                    "underlying_price": 253.95,
                }
            },
        }
    ]
    positions = [
        {
            "ticker": "ADBE",
            "quantity": 15,
            "short_strike": 247.5,
            "long_strike": 237.5,
            "expiration": "2026-09-18",
            "entry_credit": 3.55,
            "is_active": 1,
        }
    ]

    text = format_daily_report_text(
        as_of="2026-09-11",
        summary=summary,
        orders=orders,
        positions=positions,
        account=account,
    )

    assert "EXTRAPOLATION CAPITAL · DAILY EXECUTIVE REPORT" in text
    assert "Date: 2026-09-11" in text
    assert "ACCOUNT & PORTFOLIO SNAPSHOT" in text
    assert "Total Equity:        $66,578.21" in text
    assert "Cash Balance:        $86,234.21" in text
    assert "EVALUATION FUNNEL SUMMARY" in text
    assert "Candidates Evaluated: 754" in text
    assert "Signal Passed:        228" in text
    assert "Model Approved (>50%):224" in text
    assert "Orders Submitted:     1" in text
    assert "Confirmed Fills:      1" in text
    assert "EXECUTED TRADES & TRADE ECONOMICS" in text
    assert "• ADBE · 15x Put Credit Spread" in text
    assert "Short $247.5 / Long $237.5 (Exp: 2026-09-18)" in text
    assert "$3.55 Net Credit (Filled: 15 contracts)" in text
    assert "$5,325.00 collected upfront" in text
    assert "ACTIVE POSITIONS IN BOOK (1)" in text
    assert "WSJ DAILY COMMENTARY & MARKET NOTE" in text
    assert "https://extrapcap.pages.dev/journal/2026-09-11" in text
    assert "https://extrapcap.pages.dev/scoreboard" in text

