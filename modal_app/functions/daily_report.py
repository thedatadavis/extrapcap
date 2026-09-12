import json
import time
from datetime import datetime, timezone
import modal
from modal_app.base import app, image, secrets, state_mount
from modal_app.cf_client import CloudflareAPIClient
from modal_app.notifier import format_daily_report_text, format_error_alert_text, send_resend_email
from extrapcap.llm.nebius import NebiusReviewer
from extrapcap.reporting.daily_note import deterministic_wsj_summary


@app.function(
    image=image,
    secrets=secrets,
    volumes=state_mount,
    timeout=600,
)
def daily_report():
    """Daily EOD Operations Report Cron (8:45 PM UTC / 4:45 PM EDT)."""
    try:
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now_et = datetime.now(timezone.utc)
    today = now_et.date()
    if today.weekday() >= 5:
        return {"status": "skipped", "reason": "weekend_market_closed"}

    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("daily_report")

    try:
        today_str = now_et.strftime("%Y-%m-%d")
        basket = cf.get_basket(as_of=today_str) or cf.get_basket()
        all_orders = cf.get_orders()
        today_orders = [
            order
            for order in all_orders
            if str(order.get("created_at") or order.get("submitted_at") or "")[:10] == today_str
        ]
        filled_orders = [
            o
            for o in today_orders
            if str(o.get("execution_status") or o.get("status") or "").lower() == "filled"
        ]

        all_positions = cf.get_positions()
        active_positions = [p for p in all_positions if p.get("is_active") or not p.get("closed_at")]
        today_exits = [p for p in all_positions if str(p.get("closed_at") or "")[:10] == today_str]

        # Calculate deduplicated funnel counts
        evaluated_tickers = set()
        gate_tickers = set()
        model_approved_tickers = set()
        submitted_tickers = set()
        filled_tickers = set()

        for b in basket:
            sym = str(b.get("symbol") or b.get("ticker") or "").upper()
            if not sym:
                continue
            evaluated_tickers.add(sym)
            feat = b.get("features")
            if isinstance(feat, str):
                try:
                    feat = json.loads(feat)
                except Exception:
                    feat = {}
            elif not isinstance(feat, dict):
                feat = {}

            prob = b.get("reversion_probability")
            if prob is None:
                prob = feat.get("reversion_probability")

            rz = b.get("robust_z")
            sd = b.get("streak_direction")
            if sd == "negative" and rz is not None and float(rz) <= -0.5:
                gate_tickers.add(sym)
                if prob is not None and float(prob) >= 0.50:
                    model_approved_tickers.add(sym)

        for o in today_orders:
            ticker = str(o.get("ticker") or "").upper()
            if ticker:
                evaluated_tickers.add(ticker)
                gate_tickers.add(ticker)
                model_approved_tickers.add(ticker)
                submitted_tickers.add(ticker)
                st = str(o.get("execution_status") or o.get("status") or "").lower()
                if st == "filled":
                    filled_tickers.add(ticker)

        for p in active_positions:
            ticker = str(p.get("ticker") or "").upper()
            if ticker and str(p.get("opened_at") or "")[:10] == today_str:
                evaluated_tickers.add(ticker)
                gate_tickers.add(ticker)
                model_approved_tickers.add(ticker)
                submitted_tickers.add(ticker)
                filled_tickers.add(ticker)

        evaluated_count = len(evaluated_tickers)
        passed_gate_count = len(gate_tickers)
        passed_prob_count = len(model_approved_tickers)
        submitted_count = len(submitted_tickers)
        filled_count = len(filled_tickers)

        # Account snapshot
        account_snapshot = {}
        try:
            account_res = cf.client.get("/api/account")
            if account_res.status_code == 200:
                acc_rows = account_res.json()
                if acc_rows:
                    account_snapshot = acc_rows[-1]
        except Exception as err:
            print(f"Warning: Failed to fetch account snapshot: {err}")

        # Construct summary facts for WSJ commentary
        summary_for_note = {
            "trading_day": today_str,
            "evaluated_basket_count": evaluated_count,
            "streak_gate_passed_count": passed_gate_count,
            "reversion_prob_passed_count": passed_prob_count,
            "orders_submitted_count": submitted_count,
            "orders_filled_count": filled_count,
            "portfolio": account_snapshot,
        }

        # Generate WSJ narrative (via Nebius LLM or deterministic fallback)
        wsj_text = None
        try:
            reviewer = NebiusReviewer()
            judgment = reviewer.daily_note(summary_for_note)
            if judgment.get("wsj_summary"):
                wsj_text = judgment["wsj_summary"]
        except Exception as err:
            print(f"Warning: Nebius daily note failed: {err}")

        if not wsj_text:
            wsj_text = deterministic_wsj_summary(summary_for_note)

        report = {
            "summary": f"{evaluated_count} current opportunities evaluated, {submitted_count} orders submitted ({filled_count} filled)",
            "evaluated_count": evaluated_count,
            "passed_gate_count": passed_gate_count,
            "passed_prob_count": passed_prob_count,
            "submitted_count": submitted_count,
            "filled_count": filled_count,
            "portfolio_note": {
                "wsj_summary": wsj_text,
            },
        }

        event = {
            "journal": {
                "event_id": f"evt-report-{today_str}",
                "trading_day": today_str,
                "category": "reports",
                "kind": "daily_report",
                "title": f"Daily Operations Report · {today_str}",
                "status": "completed",
                "reason": report.get("summary", "Daily report generated."),
            },
            "report": report,
            "marketData": {
                "wsj_summary": wsj_text,
            },
        }

        cf.append_events([event])
        cf.complete_run(
            run_id,
            summary={
                "report_date": today_str,
                "evaluated": evaluated_count,
                "submitted": submitted_count,
                "filled": filled_count,
            },
            start_time=start_time,
        )

        # Send daily executive report email
        summary_info = {
            "evaluated": evaluated_count,
            "passed_gate": passed_gate_count,
            "passed_prob": passed_prob_count,
            "submitted": submitted_count,
            "filled": filled_count,
            "wsj_summary": wsj_text,
        }

        email_text = format_daily_report_text(
            as_of=today_str,
            summary=summary_info,
            orders=filled_orders,
            positions=active_positions,
            account=account_snapshot,
            exits=today_exits,
        )

        send_resend_email(
            subject=f"[Extrapcap] Daily Executive Report · {today_str}",
            text=email_text,
        )

        return {"status": "success", "report_date": today_str}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        send_resend_email(
            subject="[Extrapcap] ⚠️ Daily Report Failure Alert",
            text=format_error_alert_text("daily_report", str(e)),
        )
        raise
