from extrapcap.reporting.case_studies_cli import write_case_studies
from extrapcap.reporting.charts_cli import write_variant_chart


def test_variant_chart_is_rendered_from_report_json(tmp_path):
    report = tmp_path / "comparison.md"
    report.write_text(
        "## Machine-readable results\n\n"
        "[{\"variant\":\"baseline\",\"win_rate\":0.9,\"return_on_capital\":0.2}]\n",
        encoding="utf-8",
    )
    output = write_variant_chart(report, tmp_path / "chart.svg")
    assert output.read_text(encoding="utf-8").startswith("<svg")


def test_case_study_report_preserves_streak_context(tmp_path):
    basket = tmp_path / "basket.csv"
    basket.write_text(
        "symbol,date,streak_direction,streak_length,relative_return,robust_z,"
        "volatility_context,liquidity_context\n"
        "ABC,2026-07-22,negative,3,-0.01,-2.1,0.2,1000000\n",
        encoding="utf-8",
    )
    output = write_case_studies(basket, tmp_path / "case-studies.md")
    text = output.read_text(encoding="utf-8")
    assert "ABC" in text
    assert "negative streak of 3" in text
