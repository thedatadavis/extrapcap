export type OptionLeg = {
  contractId: string;
  symbol: string;
  side: 'buy' | 'sell';
  type: 'put' | 'call';
  strike: number;
  expiration: string;
  qty: number;
  entryPrice: number;
  currentPrice: number;
};

export type ActivePosition = {
  id: string;
  ticker: string;
  companyName: string;
  strategy: 'Bull Put Spread' | 'Bear Call Spread' | 'Iron Condor';
  sleeve: 'Core Mean Reversion' | 'Crash Protocol' | 'Fast EV';
  entryDate: string;
  expirationDate: string;
  dte: number;
  shortStrike: number;
  longStrike: number;
  spreadWidth: number;
  quantity: number;
  entryCredit: number; // per contract ($)
  netCreditTotal: number; // total credit ($)
  maxProfit: number; // total max profit ($)
  maxRisk: number; // total max risk ($)
  breakEven: number; // break-even underlying price
  currentSpotPrice: number; // current price of underlying
  unrealizedPnL: number; // current open P/L ($)
  unrealizedPnLPct: number; // current open P/L (%)
  status: 'profit' | 'neutral' | 'at_risk' | 'itm';
  legs: OptionLeg[];
  selectionRank?: number;
  reversionProbability?: number;
  robustZ?: number;
};

export type PayoffPoint = {
  spotPrice: number;
  pnlPerContract: number;
  pnlTotal: number;
  isProfit: boolean;
};

export function calculateSpreadPayoff(position: ActivePosition, targetSpotPrice: number): number {
  const { shortStrike, longStrike, entryCredit, quantity } = position;
  let pnlPerShare = 0;

  if (position.strategy === 'Bull Put Spread') {
    const shortPayout = -Math.max(0, shortStrike - targetSpotPrice);
    const longPayout = Math.max(0, longStrike - targetSpotPrice);
    pnlPerShare = entryCredit + shortPayout + longPayout;
  } else {
    pnlPerShare = entryCredit;
  }

  return pnlPerShare * 100 * quantity;
}

export function generatePayoffCurve(position: ActivePosition, steps: number = 100): PayoffPoint[] {
  const { longStrike, shortStrike } = position;
  const padding = (shortStrike - longStrike) * 2.5 || shortStrike * 0.15;
  const minPrice = Math.max(0.01, longStrike - padding);
  const maxPrice = shortStrike + padding;
  const stepSize = (maxPrice - minPrice) / (steps - 1);

  const points: PayoffPoint[] = [];
  for (let i = 0; i < steps; i++) {
    const spotPrice = Number((minPrice + i * stepSize).toFixed(2));
    const pnlTotal = calculateSpreadPayoff(position, spotPrice);
    points.push({
      spotPrice,
      pnlPerContract: pnlTotal / (position.quantity * 100),
      pnlTotal,
      isProfit: pnlTotal >= 0,
    });
  }

  return points;
}

export const FALLBACK_POSITIONS: ActivePosition[] = [
  {
    id: 'pos-t-001',
    ticker: 'T',
    companyName: 'AT&T Inc.',
    strategy: 'Bull Put Spread',
    sleeve: 'Core Mean Reversion',
    entryDate: '2026-07-31',
    expirationDate: '2026-08-14',
    dte: 9,
    shortStrike: 29.0,
    longStrike: 24.0,
    spreadWidth: 5.0,
    quantity: 1,
    entryCredit: 4.61,
    netCreditTotal: 461,
    maxProfit: 461,
    maxRisk: 39,
    breakEven: 24.39,
    currentSpotPrice: 23.06,
    unrealizedPnL: -39,
    unrealizedPnLPct: -100.0,
    status: 'itm',
    selectionRank: 1,
    reversionProbability: 0.512,
    robustZ: -2.35,
    legs: [
      {
        contractId: 'T260814P00029000',
        symbol: 'T 08/14/26 P29.0',
        side: 'sell',
        type: 'put',
        strike: 29.0,
        expiration: '2026-08-14',
        qty: 1,
        entryPrice: 5.55,
        currentPrice: 5.85,
      },
      {
        contractId: 'T260814P00024000',
        symbol: 'T 08/14/26 P24.0',
        side: 'buy',
        type: 'put',
        strike: 24.0,
        expiration: '2026-08-14',
        qty: 1,
        entryPrice: 0.94,
        currentPrice: 0.85,
      },
    ],
  },
];

export async function getActivePositions(db?: any): Promise<ActivePosition[]> {
  if (!db) return FALLBACK_POSITIONS;
  try {
    const result = await db.prepare('SELECT * FROM positions WHERE is_active = 1 ORDER BY opened_at DESC').all();
    const rows = result.results || [];
    if (rows.length === 0) return FALLBACK_POSITIONS;

    return rows.map((r: any) => {
      const legs = typeof r.legs === 'string' ? JSON.parse(r.legs) : (r.legs || []);
      const metrics = typeof r.selection_metrics === 'string' ? JSON.parse(r.selection_metrics) : (r.selection_metrics || {});
      const meta = typeof r.metadata === 'string' ? JSON.parse(r.metadata) : (r.metadata || {});

      const entryCredit = r.entry_credit ?? 0.50;
      const quantity = r.quantity ?? 1;
      const spreadWidth = r.spread_width ?? Math.abs(r.short_strike - r.long_strike);
      const maxProfit = entryCredit * 100 * quantity;
      const maxRisk = (spreadWidth - entryCredit) * 100 * quantity;
      const breakEven = r.short_strike - entryCredit;
      const currentSpotPrice = meta.current_spot_price ?? (r.short_strike * 1.02);
      const unrealizedPnL = meta.unrealized_pnl ?? (maxProfit * 0.4);
      const unrealizedPnLPct = maxProfit > 0 ? (unrealizedPnL / maxProfit) * 100 : 0;

      const today = new Date();
      const exp = new Date(r.expiration);
      const dte = Math.max(0, Math.ceil((exp.getTime() - today.getTime()) / (1000 * 60 * 60 * 24)));

      let status: 'profit' | 'neutral' | 'at_risk' | 'itm' = 'profit';
      if (currentSpotPrice <= r.short_strike && currentSpotPrice > r.long_strike) {
        status = 'at_risk';
      } else if (currentSpotPrice <= r.long_strike) {
        status = 'itm';
      } else if (unrealizedPnLPct < 10) {
        status = 'neutral';
      }

      return {
        id: String(r.id),
        ticker: r.ticker,
        companyName: r.company_name || r.ticker,
        strategy: r.strategy_route || 'Bull Put Spread',
        sleeve: r.sleeve === 'crash' ? 'Crash Protocol' : r.sleeve === 'fast_ev' ? 'Fast EV' : 'Core Mean Reversion',
        entryDate: r.opened_at,
        expirationDate: r.expiration,
        dte,
        shortStrike: r.short_strike,
        longStrike: r.long_strike,
        spreadWidth,
        quantity,
        entryCredit,
        netCreditTotal: maxProfit,
        maxProfit,
        maxRisk,
        breakEven,
        currentSpotPrice,
        unrealizedPnL,
        unrealizedPnLPct,
        status,
        legs,
        selectionRank: metrics.selection_rank,
        reversionProbability: metrics.reversion_probability,
        robustZ: metrics.robust_z,
      };
    });
  } catch (err) {
    console.error('Error fetching active positions from D1:', err);
    return FALLBACK_POSITIONS;
  }
}

export const ACTIVE_POSITIONS = FALLBACK_POSITIONS;
