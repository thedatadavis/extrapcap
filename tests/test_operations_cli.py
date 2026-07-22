import json

import pandas as pd

from extrapcap.data.features_cli import build_features
from extrapcap.reporting.daily_cli import render_daily_report


def test_feature_generation_reads_normalized_csv(tmp_path):
    rows = []
    for day in pd.date_range("2026-01-01", periods=25, tz="UTC"):
        rows.extend([
            {"date": day, "symbol": "SPY", "close": 100.0},
            {"date": day, "symbol": "ABC", "close": 100.0 + day.day / 100},
        ])
    source = tmp_path / "bars.csv"
    output = tmp_path / "features.csv"
    pd.DataFrame(rows).to_csv(source, index=False)
    build_features(source, output)
    result = pd.read_csv(output)
    assert {"robust_z", "relative_return", "turn_of_month", "seasonality_sin", "market_regime", "ticker_identity"}.issubset(result.columns)


def test_daily_report_is_machine_readable(tmp_path):
    root = tmp_path / "logs"
    path = root / "orders" / "2026-07-22.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"status":"dry_run","client_order_id":"xpc-1"}\n', encoding="utf-8")
    output = tmp_path / "report.json"
    render_daily_report(root, "2026-07-22", output)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["event_count"] == 1
    assert report["categories"] == {"orders": 1}
