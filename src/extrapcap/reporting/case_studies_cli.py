from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def write_case_studies(basket: str | Path, output: str | Path) -> Path:
    frame = pd.read_csv(basket)
    lines = [
        "# Tradable-basket case studies",
        "",
        "> These are formation-date examples from the free daily-bar streak screen. They describe what the system knew at selection time; they are not post-selection performance claims.",
        "",
    ]
    for row in frame.sort_values(["streak_direction", "streak_length", "symbol"]).itertuples():
        lines.extend(
            [
                f"## {row.symbol} — {row.streak_direction} streak of {int(row.streak_length)}",
                "",
                f"- Formation bar: {row.date}",
                f"- Signed relative return: {row.relative_return:.4%} versus SPY",
                f"- Robust Z-score: {row.robust_z:.3f}",
                f"- Volatility context: {row.volatility_context:.2%} annualized proxy",
                f"- Dollar liquidity context: USD {row.liquidity_context:,.0f} rolling median proxy",
                "",
            ]
        )
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Render streak-screen case studies")
    parser.add_argument("--basket", required=True)
    parser.add_argument("--output", default="reports/case-studies.md")
    args = parser.parse_args()
    print(write_case_studies(args.basket, args.output))


if __name__ == "__main__":
    main()
