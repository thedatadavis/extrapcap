# Extrapcap Quantitative Strategy Improvement Backlog

This backlog catalogs quantitative research and algorithm refinement tickets compiled from live paper trading observations (including the ADBE streak reversion cycle). These tickets serve as the research agenda for the year-end strategy tune-up.

---

## Ticket Overview

| Ticket ID | Title | Focus Area | Expected Impact | Complexity |
| :--- | :--- | :--- | :--- | :--- |
| [**TICKET-01**](#ticket-01-mfemae-curve-analysis--dynamic-profit-target-calibration) | MFE/MAE Curve Analysis & Dynamic Profit Target Calibration | Exit Optimization | +15-25% Annualized ROC, reduced tail duration risk | Medium |
| [**TICKET-02**](#ticket-02-contextual-feasibility-stop-loss-threshold-tuning) | Contextual Feasibility Stop-Loss Threshold Tuning | Risk Management | Reduces false stop-out whipsaws by 30-40% | Medium |
| [**TICKET-03**](#ticket-03-spread-width-5-vs-10-and-delta-offset-roc-efficiency) | Spread Width ($5 vs $10) and Delta-Offset ROC Efficiency | Trade Structuring | +8-12% Net yield via reduced bid-ask friction | Low |
| [**TICKET-04**](#ticket-04-execution-slippage-telemetry--limit-order-polling-dynamics) | Execution Slippage Telemetry & Limit-Order Polling Dynamics | Execution Quality | Minimizes spread drag; tracks adverse selection | Low |
| [**TICKET-05**](#ticket-05-counterfactual-shadow-book-for-risk-vetoed-setups) | Counterfactual "Shadow Book" for Risk-Vetoed Setups | Portfolio Construction | Identifies opportunity cost of sector/margin caps | High |
| [**TICKET-06**](#ticket-06-sector-specific-bayesian-prior-recalibration) | Sector-Specific Bayesian Prior Recalibration | Alpha Engine | Improves true-positive reversion accuracy in Tech/Cyclicals | Medium |

---

## TICKET-01: MFE/MAE Curve Analysis & Dynamic Profit Target Calibration

### Context & Problem Statement
Currently, Extrapcap uses a static **80% max profit target** ($0.80 on a $1.00 credit) or holds to expiration. In the ADBE March 2026 trade, the position collected $1.08 in net credit. Within 48 hours of entry, the underlying bounced and the spread showed an unrealized gain of +$0.19 (+17.6% of max profit). However, securing the remaining 62.4% required keeping capital locked and exposed to gamma/gap risk across 20+ trading days.

In credit spread selling, the **Maximum Favorable Excursion (MFE)** typically decelerates dramatically after the initial delta reversion, leaving the trader collecting small theta crumbs while maintaining full tail risk.

### Hypothesis
Closing credit spreads at **50% of max profit** (or a dynamic threshold based on elapsed DTE) will:
1. Capture ~70-80% of total strategy PnL while reducing average market exposure duration by 40-50%.
2. Greatly improve **Annualized Return on Capital (ROC)** and portfolio Sharpe ratio.
3. Rapidly recycle collateral back into cash to fund new high-conviction streak setups.

### Telemetry & Data Required
- Ingest 30-minute position snapshots from the Cloudflare D1 `events` table:
  - Underlying spot price $S_t$
  - Spread mark $C_t = \text{bid-ask midpoint}$
  - Elapsed Days Since Open ($t - t_{\text{entry}}$) and remaining DTE.
- Calculate:
  $$\text{MFE}_t = \max_{0 \le \tau \le t} \left( \frac{\text{Credit}_{\text{open}} - C_\tau}{\text{Credit}_{\text{open}}} \right)$$
  $$\text{MAE}_t = \max_{0 \le \tau \le t} \left( \frac{C_\tau - \text{Credit}_{\text{open}}}{\text{Width} - \text{Credit}_{\text{open}}} \right)$$

### Research Tasks
1. Plot cumulative MFE distribution curves across all closed trades vs holding time.
2. Run counterfactual backtests testing profit-take targets at: `[40%, 50%, 60%, 70%, 80%]`.
3. Test a **time-decaying profit target curve**:
   - Days 1–3: Take profit at 50%
   - Days 4–10: Take profit at 65%
   - Days >10: Take profit at 80%

### Acceptance Criteria
- Backtest demonstrates higher Sharpe ratio and lower max drawdown compared to flat 80% baseline.
- Capital turnover rate increases by at least 1.5x without degrading total net return.

---

## TICKET-02: Contextual Feasibility Stop-Loss Threshold Tuning

### Context & Problem Statement
Extrapcap currently uses a feasibility ratio stop-loss:
$$\text{Feasibility Ratio} = \frac{|\text{Short Strike} - S_t|}{\text{Expected Move}_{\text{remaining}}} \le 1.25$$
When underlying spot price drops sharply towards the short strike, the feasibility ratio breaches 1.25, triggering a defensive exit to prevent max loss. However, high-beta streak stocks frequently experience brief intraday "knife" dips before reversing sharply back above the short strike, triggering false stop-outs at the worst possible price.

### Hypothesis
A contextual stop-loss mechanism—incorporating market regime (VIX level), time-of-day filtering, and a multi-snapshot persistence check (e.g. breach must persist across two consecutive 30-minute evaluations)—will significantly cut whipsaw stop-outs while maintaining catastrophic drawdown defense.

### Telemetry & Data Required
- Log all stop-loss triggers in `events` with:
  - Exact feasibility ratio at trigger
  - Spot price relative to short strike
  - Realized volatility (HV20) vs Implied Volatility (IV)
- Post-stop recovery telemetry: Track underlying spot price for 5 trading days post-stop. Record whether the stock recovered above the short strike before original expiration.

### Research Tasks
1. Quantify the "Whipsaw Rate": `% of stopped-out trades that would have expired worthless (full profit) if held`.
2. Model threshold variants:
   - Dynamic Feasibility: $1.25 \times (1 + 0.5 \times \frac{\text{DTE}}{30})$ (allowing wider tolerance early in the trade).
   - Persistence Gate: Require ratio $\le 1.25$ on two consecutive 30-minute intervals before triggering order submission.

### Acceptance Criteria
- Reduction of false stop-out rate by $\ge 30\%$.
- Strategy worst-case single-trade loss remains capped at $< 2.5\times$ original credit collected.

---

## TICKET-03: Spread Width ($5 vs $10) and Delta-Offset ROC Efficiency

### Context & Problem Statement
In higher-priced underlyings ($S_t > \$300$, e.g., ADBE at \$340, MSFT at \$400), a \$5-wide vertical spread requires taking high short deltas (e.g., 25-30 delta) to collect an acceptable premium (\$0.90–\$1.10). Furthermore:
- Bid-ask friction on options is often \$0.08–\$0.15 per leg. On a \$5-wide spread collecting \$1.00, friction accounts for 15–20% of gross credit.
- On a \$10-wide spread, credit collected is often \$2.20–\$2.60 against \$7.40 max risk, offering similar or higher return on collateral (30–35% ROC) while friction accounts for only 8–10% of gross credit.

### Hypothesis
Scaling spread width dynamically with the underlying share price:
- $S_t < \$100 \implies \$2.50\text{ or }\$5.00\text{ width}$
- $\$100 \le S_t < \$300 \implies \$5.00\text{ width}$
- $S_t \ge \$300 \implies \$10.00\text{ width}$
will improve net return on risk-adjusted capital by reducing transaction drag and allowing further out-of-the-money (lower delta, higher probability of profit) short strike placement.

### Research Tasks
1. Extract historical option chains for greenlisted mega-cap tickers.
2. Compare 20-delta short put performance on \$5 vs \$10 spreads across identical entry dates.
3. Compute net ROC after subtracting realistic Alpaca execution friction (\$0.05/leg).

### Acceptance Criteria
- Demonstrated improvement in probability of profit (POP) from ~72% to >80% at equal or superior ROC.
- Bid-ask spread slippage as a percentage of total credit collected drops below 10%.

---

## TICKET-04: Execution Slippage Telemetry & Limit-Order Polling Dynamics

### Context & Problem Statement
Orders are submitted via Alpaca paper trading using limit orders pegged to the NBBO midpoint or bid. Currently, we record the `filled_avg_price` upon fill, but we do not persistently log:
- The exact NBBO (`bid`, `ask`, `midpoint`) at the millisecond the order was routed.
- The duration from order creation to fill.
- The cancellation / replacement count during stale quote stepping.

Without this telemetry, it is difficult to determine whether we are suffering from adverse selection (only getting filled when the market is moving against us) or overpaying to get filled.

### Hypothesis
Implementing continuous execution telemetry and an adaptive limit-order pegging ladder (e.g., submit at `midpoint`, wait 60s, step down by \$0.02, up to 3 steps) will optimize fill rate while keeping execution slippage within \$0.03 of true fair value.

### Implementation Tasks
1. Extend `orders` schema in `schema.sql` to include:
   - `quoted_bid_at_route`: REAL
   - `quoted_ask_at_route`: REAL
   - `quoted_mid_at_route`: REAL
   - `fill_latency_ms`: INTEGER
   - `slippage_vs_mid`: REAL (`filled_avg_price - quoted_mid_at_route`)
2. Update `modal_app/functions/executor.py` / `src/extrapcap/execution.py` to record these fields upon order placement and fill.
3. Add a "Slippage & Fill Quality" card to the `/scoreboard` dashboard.

### Acceptance Criteria
- 100% of live/paper orders record quote snapshot at routing time.
- Slippage metric is reported in the Daily Executive Report email.

---

## TICKET-05: Counterfactual "Shadow Book" for Risk-Vetoed Setups

### Context & Problem Statement
Extrapcap enforces strict risk limits:
- Maximum portfolio margin utilization (e.g., 50%).
- Maximum ticker and sector concentration (e.g., max 2 Tech positions).
- Minimum Bayesian reversion probability threshold ($P_{\text{revert}} \ge 0.65$).

When multiple attractive candidates appear on the same morning (e.g. 4 tech tickers on consecutive down-days), the algorithm selects the top 2 and vetoes the remaining 2. Today, those vetoed setups are discarded, creating a blind spot: **Did our portfolio filters eliminate bad trades, or did they choke off our most profitable winners?**

### Hypothesis
Maintaining an automated "Shadow Book" that tracks virtual executions of all candidates that passed the streak screener but were vetoed by risk caps will quantify the true opportunity cost of our portfolio constraints.

### Architecture & Implementation
1. Add a `shadow_positions` table or record virtual orders with `phase='shadow'` in D1.
2. In the 30-minute position management cron, update shadow positions mark-to-market alongside live positions.
3. In the Weekly Review, compute:
   - Shadow Portfolio PnL vs Live Portfolio PnL
   - Risk Filter Precision: `True Rejections` (shadow trade lost money) vs `False Rejections` (shadow trade hit 80% TP).

### Acceptance Criteria
- Shadow book operates fully autonomously with zero impact on live trading capital.
- Dashboard provides an interactive comparison of "What If We Took All Signals" vs "Risk-Constrained Live Book".

---

## TICKET-06: Sector-Specific Bayesian Prior Recalibration

### Context & Problem Statement
The Bayesian Relative Streak Model ([`bayesian_reversion.py`](file:///Users/chris/Documents/GitHub/extrapcap/src/extrapcap/models/bayesian_reversion.py)) currently uses unified global priors across all greenlisted tickers. In practice:
- Mega-cap enterprise tech (ADBE, MSFT, ORCL) exhibits strong institutional dip-buying and high mean-reversion speed after 3-day relative drawdowns.
- Cyclicals, energy, and biotech frequently develop long momentum drift where streaks persist for 5–7 days before reversing.

Using identical prior parameters across all sectors causes the model to either underestimate tech recovery odds or prematurely trigger entries on drifting cyclicals.

### Hypothesis
Segmenting the Bayesian prior parameters $(\alpha, \beta)$ by GICS sector will increase the Brier score accuracy of the predicted reversion probabilities by $\ge 15\%$.

### Research Tasks
1. Partition historical daily bars (10-year dataset) by GICS sector.
2. Fit empirical Beta distributions for streak recovery probabilities per sector:
   $$\text{Prior}_{\text{Tech}} \sim \text{Beta}(\alpha_{\text{tech}}, \beta_{\text{tech}})$$
   $$\text{Prior}_{\text{Health}} \sim \text{Beta}(\alpha_{\text{health}}, \beta_{\text{health}})$$
3. Backtest sector-specific priors vs the unified global prior over 2020–2026.

### Acceptance Criteria
- Statistically significant improvement in ROC and win rate on out-of-sample data.
- Reduced drawdown during sector-specific rotation regimes.
