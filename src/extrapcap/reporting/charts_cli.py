from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path


def _results(report: str) -> list[dict]:
    marker = "## Machine-readable results"
    payload = report[report.index(marker):]
    start = payload.index("[")
    end = payload.rindex("]")
    return json.loads(payload[start : end + 1])


def write_variant_chart(report_path: str | Path, output: str | Path) -> Path:
    rows = _results(Path(report_path).read_text(encoding="utf-8"))
    width, height = 760, 300
    chart_left, chart_width = 190, 500
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" role="img" aria-label="Variant comparison">',
        '<rect width="100%" height="100%" fill="#10151c"/>',
        '<text x="24" y="30" fill="#f4f7fb" font-family="sans-serif" font-size="18">Modeled variant diagnostics</text>',
        '<text x="24" y="50" fill="#9aa7b4" font-family="sans-serif" font-size="11">Real daily bars; modeled option proxy, not realized performance</text>',
    ]
    metrics = [("win_rate", "Win rate", 1.0), ("return_on_capital", "Return on capital", 1.2)]
    y = 90
    colors = ["#75d6a1", "#77b7ff"]
    for index, row in enumerate(rows[:2]):
        label = escape(str(row.get("variant", "variant")))
        lines.append(f'<text x="24" y="{y + 14}" fill="#f4f7fb" font-family="sans-serif" font-size="13">{label}</text>')
        for metric_index, (key, metric_label, scale) in enumerate(metrics):
            value = float(row.get(key, 0.0))
            bar_y = y + metric_index * 36
            bar_width = max(0.0, min(chart_width, value / scale * chart_width))
            lines.append(f'<text x="{chart_left - 8}" y="{bar_y + 12}" text-anchor="end" fill="#9aa7b4" font-family="sans-serif" font-size="10">{metric_label}</text>')
            lines.append(f'<rect x="{chart_left}" y="{bar_y}" width="{chart_width}" height="18" fill="#202b36" rx="3"/>')
            lines.append(f'<rect x="{chart_left}" y="{bar_y}" width="{bar_width:.1f}" height="18" fill="{colors[index]}" rx="3"/>')
            lines.append(f'<text x="{chart_left + bar_width + 6:.1f}" y="{bar_y + 13}" fill="#f4f7fb" font-family="sans-serif" font-size="10">{value:.1%}</text>')
        y += 92
    lines.append("</svg>")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a dependency-free variant comparison SVG")
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", default="reports/assets/variant-comparison.svg")
    args = parser.parse_args()
    print(write_variant_chart(args.report, args.output))


if __name__ == "__main__":
    main()
