import os
import httpx


def send_resend_email(subject: str, text: str) -> bool:
    """Send a plain text / markdown email via Resend API."""
    api_key = os.environ.get("RESEND_API_KEY")
    recipient = os.environ.get("RECIPIENT_EMAIL", "christophergdavis@gmail.com")
    sender = os.environ.get("SENDER_EMAIL", "reports@mail.qry.thedatadavis.com")

    if not api_key:
        print("Warning: RESEND_API_KEY missing, skipping email notification.")
        return False

    payload = {
        "from": f"Extrapolation Capital <{sender}>",
        "to": [recipient],
        "subject": subject,
        "text": text,
    }

    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
        if response.status_code in (200, 201):
            print(f"Successfully sent snapshot email '{subject}' to {recipient}.")
            return True
        else:
            print(f"Warning: Failed to send Resend email ({response.status_code}): {response.text}")
            return False
    except Exception as e:
        print(f"Warning: Resend API request failed: {e}")
        return False


def format_reconciliation_text(snapshot: dict) -> str:
    as_of = snapshot.get("as_of", "Today")
    equity = snapshot.get("equity", 0.0)
    cash = snapshot.get("cash", 0.0)
    buying_power = snapshot.get("buying_power", 0.0)
    daily_pnl = snapshot.get("daily_pnl", 0.0)

    pnl_str = f"+${daily_pnl:,.2f}" if daily_pnl >= 0 else f"-${abs(daily_pnl):,.2f}"

    return f"""==================================================
EXTRAPOLATION CAPITAL · DAILY RECONCILIATION
Date: {as_of}
==================================================

ACCOUNT PORTFOLIO SNAPSHOT
--------------------------------------------------
Total Equity:        ${equity:,.2f}
Cash Balance:        ${cash:,.2f}
Options Buying Pwr:  ${buying_power:,.2f}
Daily Session P&L:   {pnl_str}

Web Dashboard: https://extrapcap.pages.dev
Admin Console: https://extrapcap.pages.dev/admin
--------------------------------------------------
System status: Reconciled with Alpaca Paper Trading
"""


def format_daily_report_text(as_of: str, summary: dict, events: list) -> str:
    evaluated = summary.get("evaluated", 0)
    passed_gate = summary.get("passed_gate", 0)
    passed_prob = summary.get("passed_prob", 0)
    submitted = summary.get("submitted", 0)
    filled = summary.get("filled", 0)
    wsj = summary.get("wsj_summary", "No market commentary recorded.")

    return f"""==================================================
EXTRAPOLATION CAPITAL · DAILY EXECUTIVE REPORT
Date: {as_of}
==================================================

EVALUATION FUNNEL SUMMARY
--------------------------------------------------
Candidates Evaluated: {evaluated}
Signal Passed:        {passed_gate}
Model Approved (>50%):{passed_prob}
Orders Submitted:     {submitted}
Confirmed Fills:      {filled}

WSJ DAILY COMMENTARY & MARKET NOTE
--------------------------------------------------
{wsj}

Interactive Journal: https://extrapcap.pages.dev/journal/{as_of}
--------------------------------------------------
Extrapolation Capital Automated Research System
"""


def _parse_occ_symbol(symbol: str) -> dict | None:
    value = str(symbol).strip().upper()
    if len(value) < 16:
        return None
    suffix = value[-15:]
    if suffix[6] not in {"P", "C"} or not suffix[7:].isdigit():
        return None
    try:
        exp = f"20{suffix[0:2]}-{suffix[2:4]}-{suffix[4:6]}"
        opt_type = "Put" if suffix[6] == "P" else "Call"
        strike = int(suffix[7:]) / 1000.0
        return {"expiration": exp, "type": opt_type, "strike": strike}
    except Exception:
        return None


_REASON_MAP = {
    "credit_profit_target": "Profit Target Hit (50% max gain captured)",
    "credit_stop_loss": "Stop Loss Triggered (2x credit limit reached)",
    "max_dte_reached": "Max DTE / Target Holding Period Reached",
    "debit_take_profit": "Take Profit Target Hit",
    "debit_stop_loss": "Stop Loss Triggered",
    "debit_time_decay": "Time Decay Threshold Reached",
    "broker_position_closed": "Position Closed by Broker",
}


def format_candidate_orders_text(as_of: str, orders: list) -> str:
    lines = [
        "==================================================",
        "EXTRAPOLATION CAPITAL · PAPER ORDERS SUBMITTED",
        f"Date: {as_of}",
        "==================================================",
        "",
        f"Total Orders Submitted: {len(orders)}",
        "--------------------------------------------------",
    ]

    for order in orders:
        ticker = order.get("ticker") or order.get("journal", {}).get("ticker", "N/A")
        client_id = order.get("client_order_id", "N/A")
        prob = order.get("model_probability")
        if prob is None:
            prob = order.get("selection_context", {}).get("model_probability")
        prob_str = f"{float(prob) * 100:.1f}%" if prob is not None else "N/A"

        quantity = int(order.get("filled_qty") or order.get("quantity") or 1)
        raw_price = order.get("filled_avg_price")
        if raw_price is None:
            raw_price = order.get("limit_price", 0.0)
        price = abs(float(raw_price or 0.0))

        side = str(order.get("side") or "").lower()
        is_credit = "sell" in side or side == "sell_to_open"

        # Parse legs
        legs = order.get("legs") or []
        short_leg = None
        long_leg = None
        spread_type = "Credit Spread" if is_credit else "Debit Spread"
        exp_date = ""

        for leg in legs:
            occ = _parse_occ_symbol(leg.get("symbol", ""))
            leg_side = str(leg.get("side") or leg.get("position_intent") or "").lower()
            if occ:
                exp_date = occ["expiration"]
                spread_type = f"{occ['type']} {'Credit' if is_credit else 'Debit'} Spread"
                if "sell" in leg_side:
                    short_leg = occ
                else:
                    long_leg = occ

        total_premium = round(price * quantity * 100, 2)

        lines.append(f"• {ticker} · {quantity}x {spread_type}")
        if short_leg and long_leg:
            s_strike = f"${short_leg['strike']:.2f}".rstrip("0").rstrip(".")
            l_strike = f"${long_leg['strike']:.2f}".rstrip("0").rstrip(".")
            lines.append(f"  Strikes:       Short {s_strike} / Long {l_strike} (Exp: {exp_date})")
        elif exp_date:
            lines.append(f"  Expiration:    {exp_date}")

        fill_label = "Net Credit" if is_credit else "Net Debit"
        status_label = str(order.get("status") or "submitted").capitalize()
        lines.append(f"  Execution:     ${price:.2f} {fill_label} ({status_label}: {quantity} contracts)")
        lines.append(f"  Total Premium: ${total_premium:,.2f} {'collected' if is_credit else 'paid'}")
        lines.append(f"  Model P(rev):  {prob_str}")
        lines.append(f"  Order ID:      {client_id}")
        lines.append("")

    lines.extend([
        "--------------------------------------------------",
        "View Active Spreads: https://extrapcap.pages.dev/positions/active",
    ])

    return "\n".join(lines)


def format_position_exits_text(as_of: str, exits: list) -> str:
    lines = [
        "==================================================",
        "EXTRAPOLATION CAPITAL · POSITION EXITS TRIGGERED",
        f"Date: {as_of}",
        "==================================================",
        "",
        f"Positions Closed: {len(exits)}",
        "--------------------------------------------------",
    ]

    for exit_evt in exits:
        ticker = exit_evt.get("ticker") or exit_evt.get("journal", {}).get("ticker", "N/A")
        raw_reason = (
            exit_evt.get("reason")
            or exit_evt.get("metadata", {}).get("close_reason")
            or exit_evt.get("journal", {}).get("reason")
            or "Exit rule triggered"
        )
        friendly_reason = _REASON_MAP.get(raw_reason, raw_reason)
        qty = int(exit_evt.get("quantity") or 1)

        lines.append(f"• {ticker} · {qty} contract(s)")
        lines.append(f"  Exit Trigger:  {friendly_reason}")

        # Legs info
        legs = exit_evt.get("legs") or []
        short_leg = None
        long_leg = None
        exp_date = ""
        for leg in legs:
            occ = _parse_occ_symbol(leg.get("symbol", ""))
            leg_side = str(leg.get("side") or leg.get("position_intent") or "").lower()
            if occ:
                exp_date = occ["expiration"]
                if "sell" in leg_side:
                    short_leg = occ
                else:
                    long_leg = occ
        if short_leg and long_leg:
            s_strike = f"${short_leg['strike']:.2f}".rstrip("0").rstrip(".")
            l_strike = f"${long_leg['strike']:.2f}".rstrip("0").rstrip(".")
            lines.append(f"  Spread:        Short {s_strike} / Long {l_strike} (Exp: {exp_date})")

        entry_credit = exit_evt.get("entry_credit")
        entry_debit = exit_evt.get("entry_debit")
        exit_price = exit_evt.get("exit_price")
        realized_pnl = exit_evt.get("realized_pnl")

        if entry_credit is not None:
            ec = abs(float(entry_credit))
            lines.append(f"  Entry Credit:  ${ec:.2f} / share (${ec * qty * 100:,.2f} collected)")
            if exit_price is not None:
                ep = abs(float(exit_price))
                lines.append(f"  Exit Debit:    ${ep:.2f} / share (${ep * qty * 100:,.2f} to close)")
        elif entry_debit is not None:
            ed = abs(float(entry_debit))
            lines.append(f"  Entry Debit:   ${ed:.2f} / share (${ed * qty * 100:,.2f} paid)")
            if exit_price is not None:
                ep = abs(float(exit_price))
                lines.append(f"  Exit Credit:   ${ep:.2f} / share (${ep * qty * 100:,.2f} proceeds)")

        if realized_pnl is not None:
            pnl_val = float(realized_pnl)
            pnl_str = f"+${pnl_val:,.2f}" if pnl_val >= 0 else f"-${abs(pnl_val):,.2f}"
            ret_str = ""
            if entry_credit and float(entry_credit) > 0:
                ret_pct = (pnl_val / (float(entry_credit) * qty * 100)) * 100
                ret_str = f" ({ret_pct:+.1f}% on credit)"
            elif entry_debit and float(entry_debit) > 0:
                ret_pct = (pnl_val / (float(entry_debit) * qty * 100)) * 100
                ret_str = f" ({ret_pct:+.1f}% on debit)"
            lines.append(f"  Realized P&L:  {pnl_str}{ret_str}")

        lines.append("")

    lines.extend([
        "--------------------------------------------------",
        "View Active Positions: https://extrapcap.pages.dev/positions/active",
    ])

    return "\n".join(lines)


def format_error_alert_text(workflow: str, error: str) -> str:
    return f"""==================================================
⚠️ EXTRAPOLATION CAPITAL · WORKFLOW FAILURE ALERT
Workflow: {workflow}
==================================================

ERROR DETAILS
--------------------------------------------------
{error}

--------------------------------------------------
Inspect Logs: https://extrapcap.pages.dev/admin
"""
