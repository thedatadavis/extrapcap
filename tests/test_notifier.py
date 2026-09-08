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
