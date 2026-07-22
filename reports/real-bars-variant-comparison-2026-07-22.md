# Extrapolation Capital strategy comparison

> This is an automated research artifact. It is not a performance claim. Confirm the data tier, option-chain source, slippage, and out-of-sample period before using any result.

| Variant | Trades | Win rate | Premium | Expectancy | Return on capital | Utilization | Avg duration | Skew | P05/P50/P95 | Portfolio return | Portfolio Sharpe | Portfolio Sortino | Portfolio drawdown | Profit factor |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 810 | 91.7% | 121500.00 | 0.3342 | 76.54% | 0.24% | 1.5 | -3.383 | -0.481/0.429/0.429 | 114.52% | 6.65 | 17.73 | -1.41% | 7.659426402361873 |
| improved | 810 | 99.0% | 89100.00 | 0.2721 | 72.65% | 0.26% | 1.5 | -11.454 | 0.282/0.282/0.282 | 106.52% | 8.66 | 28.81 | -0.47% | 41.579792256846034 |

## Machine-readable results

```json
[
  {
    "variant": "baseline",
    "trades": 810,
    "wins": 743,
    "premium_collected": 121500.0,
    "asymmetric_budget": 25.0,
    "rejected_trap": 0,
    "total_pnl": 270.6771428571428,
    "max_drawdown": -1.0,
    "expectancy": 0.3341693121693121,
    "profit_factor": 7.659426402361873,
    "asymmetric_deployed": 18200.0,
    "win_rate": 0.917283950617284,
    "total_return": -1.0,
    "sharpe_annualized": 17.589660383578217,
    "sortino_annualized": 26.81962838217548,
    "cagr": null,
    "tail_loss_p05": -0.4808571428571411,
    "worst_return": -1.0,
    "data_scope": "modeled_option_proxy",
    "initial_nav": 100000.0,
    "portfolio_total_return": 1.1451851701286855,
    "portfolio_max_drawdown": -0.014146879359744347,
    "portfolio_sharpe_annualized": 6.6463450473600565,
    "portfolio_sortino_annualized": 17.731885144101632,
    "portfolio_cagr": 0.46579557449731857,
    "classifier_used": false,
    "news_filter_used": false,
    "news_vetoes": 0,
    "turn_of_month_only": false,
    "crash_protocol_enabled": false,
    "crash_trades": 0,
    "crash_pnl": 0.0,
    "asymmetric_rejected": 0,
    "asymmetric_enabled": true,
    "mode": "end_of_day",
    "return_on_capital": 0.76537,
    "average_trade_duration_days": 1.4790123456790123,
    "average_open_risk_utilization": 0.0024077844311377245,
    "trade_skewness": -3.382886260910919,
    "trade_return_quantiles": {
      "p05": -0.4808571428571411,
      "p25": 0.42857142857142855,
      "p50": 0.42857142857142855,
      "p75": 0.42857142857142855,
      "p95": 0.42857142857142855
    },
    "regime_decomposition": {
      "positive": {
        "trades": 500.0,
        "win_rate": 0.92,
        "expectancy": 0.33710285714285704,
        "profit_factor": 8.084544253632759,
        "max_drawdown": -1.0,
        "total_return": -1.0,
        "sharpe_annualized": 18.061313772216625,
        "sortino_annualized": 27.4757379230294,
        "cagr": null,
        "tail_loss_p05": -0.4318571428571403,
        "worst_return": -1.0,
        "skewness": -3.5118587799091827,
        "quantiles": {
          "p05": -0.4318571428571403,
          "p25": 0.42857142857142855,
          "p50": 0.42857142857142855,
          "p75": 0.42857142857142855,
          "p95": 0.42857142857142855
        }
      },
      "negative": {
        "trades": 310.0,
        "win_rate": 0.9129032258064517,
        "expectancy": 0.32943778801843315,
        "profit_factor": 7.059332090184781,
        "max_drawdown": -1.0,
        "total_return": -1.0,
        "sharpe_annualized": 16.85009764192496,
        "sortino_annualized": 25.8148490323466,
        "cagr": null,
        "tail_loss_p05": -0.5707142857142863,
        "worst_return": -1.0,
        "skewness": -3.193276841249661,
        "quantiles": {
          "p05": -0.5707142857142863,
          "p25": 0.42857142857142855,
          "p50": 0.42857142857142855,
          "p75": 0.42857142857142855,
          "p95": 0.42857142857142855
        }
      },
      "neutral": {
        "trades": 0.0,
        "win_rate": 0.0,
        "expectancy": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 0.0,
        "total_return": 0.0,
        "sharpe_annualized": 0.0,
        "sortino_annualized": 0.0,
        "cagr": null,
        "tail_loss_p05": 0.0,
        "worst_return": 0.0,
        "skewness": 0.0,
        "quantiles": {
          "p05": 0.0,
          "p25": 0.0,
          "p50": 0.0,
          "p75": 0.0,
          "p95": 0.0
        }
      }
    },
    "sector_concentration": "unavailable_without_sector_metadata",
    "intraday_vetoes": 0
  },
  {
    "variant": "improved",
    "trades": 810,
    "wins": 802,
    "premium_collected": 89100.00000000001,
    "asymmetric_budget": 65.0,
    "rejected_trap": 0,
    "total_pnl": 220.37948717948723,
    "max_drawdown": -1.0,
    "expectancy": 0.2720734409623298,
    "profit_factor": 41.579792256846034,
    "asymmetric_deployed": 13300.0,
    "win_rate": 0.9901234567901235,
    "total_return": -1.0,
    "sharpe_annualized": 41.5779560179703,
    "sortino_annualized": 54.79985153679943,
    "cagr": null,
    "tail_loss_p05": 0.2820512820512821,
    "worst_return": -1.0,
    "data_scope": "modeled_option_proxy",
    "initial_nav": 100000.0,
    "portfolio_total_return": 1.0651939232734704,
    "portfolio_max_drawdown": -0.004686309999999971,
    "portfolio_sharpe_annualized": 8.664247936704852,
    "portfolio_sortino_annualized": 28.80525183853586,
    "portfolio_cagr": 0.43815088553935366,
    "classifier_used": false,
    "news_filter_used": false,
    "news_vetoes": 0,
    "turn_of_month_only": false,
    "crash_protocol_enabled": false,
    "crash_trades": 0,
    "crash_pnl": 0.0,
    "asymmetric_rejected": 0,
    "asymmetric_enabled": true,
    "mode": "end_of_day",
    "return_on_capital": 0.7264800000000001,
    "average_trade_duration_days": 1.4790123456790123,
    "average_open_risk_utilization": 0.002626626746506986,
    "trade_skewness": -11.453551457293882,
    "trade_return_quantiles": {
      "p05": 0.2820512820512821,
      "p25": 0.2820512820512821,
      "p50": 0.2820512820512821,
      "p75": 0.2820512820512821,
      "p95": 0.2820512820512821
    },
    "regime_decomposition": {
      "positive": {
        "trades": 500.0,
        "win_rate": 0.99,
        "expectancy": 0.2726205128205128,
        "profit_factor": 44.57459016393447,
        "max_drawdown": -1.0,
        "total_return": -1.0,
        "sharpe_annualized": 42.56444688078935,
        "sortino_annualized": 55.7843350530957,
        "cagr": null,
        "tail_loss_p05": 0.2820512820512821,
        "worst_return": -1.0,
        "skewness": -11.956904569163267,
        "quantiles": {
          "p05": 0.2820512820512821,
          "p25": 0.2820512820512821,
          "p50": 0.2820512820512821,
          "p75": 0.2820512820512821,
          "p95": 0.2820512820512821
        }
      },
      "negative": {
        "trades": 310.0,
        "win_rate": 0.9903225806451613,
        "expectancy": 0.27119106699751855,
        "profit_factor": 37.5111358574609,
        "max_drawdown": -1.0,
        "total_return": -1.0,
        "sharpe_annualized": 40.04767175880722,
        "sortino_annualized": 53.3016491017153,
        "cagr": null,
        "tail_loss_p05": 0.2820512820512821,
        "worst_return": -1.0,
        "skewness": -10.73488982585015,
        "quantiles": {
          "p05": 0.2820512820512821,
          "p25": 0.2820512820512821,
          "p50": 0.2820512820512821,
          "p75": 0.2820512820512821,
          "p95": 0.2820512820512821
        }
      },
      "neutral": {
        "trades": 0.0,
        "win_rate": 0.0,
        "expectancy": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 0.0,
        "total_return": 0.0,
        "sharpe_annualized": 0.0,
        "sortino_annualized": 0.0,
        "cagr": null,
        "tail_loss_p05": 0.0,
        "worst_return": 0.0,
        "skewness": 0.0,
        "quantiles": {
          "p05": 0.0,
          "p25": 0.0,
          "p50": 0.0,
          "p75": 0.0,
          "p95": 0.0
        }
      }
    },
    "sector_concentration": "unavailable_without_sector_metadata",
    "intraday_vetoes": 0
  }
]
```
