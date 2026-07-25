from datetime import datetime, timezone
import json

from extrapcap.data.alpaca_market import AlpacaMarketData
from extrapcap.events import decision_from_csv
from extrapcap.news import parse_article_rows, refresh_news_events


def test_alpaca_market_data_news_payload_formatting(monkeypatch):
    captured = {}

    def fake_get(path, params):
        captured["path"] = path
        captured["params"] = params
        return {"news": []}

    client = AlpacaMarketData(api_key="fake_key", secret_key="fake_secret")
    monkeypatch.setattr(client, "_get", fake_get)

    res = client.news(["AAPL", "GOOGL"], start="2026-07-20T00:00:00Z", limit=10)
    assert captured["path"] == "/v1beta1/news"
    assert captured["params"]["symbols"] == "AAPL,GOOGL"
    assert captured["params"]["start"] == "2026-07-20T00:00:00Z"
    assert captured["params"]["limit"] == 10
    assert res == {"news": []}


def test_parse_article_rows_classifies_structural_risk():
    articles = [
        {
            "headline": "Company faces DOJ investigation into accounting irregularities",
            "created_at": "2026-07-24T12:00:00Z",
            "symbols": ["ABC"],
        },
        {
            "headline": "Analyst increases price target following strong quarter",
            "created_at": "2026-07-24T13:00:00Z",
            "symbols": ["XYZ"],
        },
    ]
    rows = parse_article_rows(articles)
    assert len(rows) == 2
    abc_row = next(r for r in rows if r["symbol"] == "ABC")
    xyz_row = next(r for r in rows if r["symbol"] == "XYZ")

    assert abc_row["structural_risk"] == "true"
    assert xyz_row["structural_risk"] == "false"


def test_refresh_news_events_writes_csv_and_metadata(tmp_path):
    class FakeAlpaca:
        def news(self, symbols=None, start=None, end=None, limit=50):
            return {
                "news": [
                    {
                        "headline": "ABC Corp files for bankruptcy protection",
                        "created_at": "2026-07-24T10:00:00Z",
                        "symbols": ["ABC"],
                    }
                ]
            }

    csv_path = tmp_path / "news.csv"
    retrieved = datetime(2026, 7, 24, 15, tzinfo=timezone.utc)
    target, sidecar, metadata = refresh_news_events(
        output=csv_path,
        symbols=["ABC"],
        days=1,
        client=FakeAlpaca(),
        retrieved_at=retrieved,
    )

    assert target.exists()
    assert sidecar.exists()
    assert metadata["articles_fetched"] == 1
    assert metadata["structural_risk_vetoes"] == 1

    decision = decision_from_csv(target, "ABC", datetime(2026, 7, 24).date())
    assert decision.allowed is False
    assert decision.category == "structural_risk"
