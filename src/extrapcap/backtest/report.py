from __future__ import annotations

import json
from pathlib import Path


def write_comparison_report(results: list[dict], output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Extrapolation Capital strategy comparison",
        "",
        "> This is an automated research artifact. It is not a performance claim. Confirm the data tier, option-chain source, slippage, and out-of-sample period before using any result.",
        "",
        "| Variant | Trades | Win rate | Premium | Expectancy | Return on capital | Utilization | Avg duration | Skew | Portfolio return | Portfolio Sharpe | Portfolio Sortino | Portfolio drawdown | P05 tail | Profit factor |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in results:
        lines.append(
            f"| {row['variant']} | {row['trades']} | {row['win_rate']:.1%} | "
            f"{row['premium_collected']:.2f} | {row['expectancy']:.4f} | "
            f"{row['return_on_capital']:.2%} | {row['average_open_risk_utilization']:.2%} | "
            f"{row['average_trade_duration_days']:.1f} | {row['trade_skewness']:.3f} | "
            f"{row['portfolio_total_return']:.2%} | {row['portfolio_sharpe_annualized']:.2f} | "
            f"{row['portfolio_sortino_annualized']:.2f} | {row['portfolio_max_drawdown']:.2%} | "
            f"{row['tail_loss_p05']:.4f} | {row['profit_factor']} |"
        )
    lines.extend(["", "## Machine-readable results", "", "```json", json.dumps(results, indent=2), "```", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
