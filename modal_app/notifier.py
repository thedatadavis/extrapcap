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
        prob = order.get("model_probability", 0.0)
        lines.append(f"• TICKER: {ticker} (P(rev): {prob*100:.1f}%) | Order ID: {client_id}")

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
        ticker = exit_evt.get("ticker", exit_evt.get("journal", {}).get("ticker", "N/A"))
        reason = exit_evt.get("journal", {}).get("reason", "Exit rule triggered")
        lines.append(f"• CLOSED: {ticker} | Reason: {reason}")

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
