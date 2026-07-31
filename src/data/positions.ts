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
    // Short Put payout at expiration: -max(0, shortStrike - S)
    const shortPayout = -Math.max(0, shortStrike - targetSpotPrice);
    // Long Put payout at expiration: +max(0, longStrike - S)
    const longPayout = Math.max(0, longStrike - targetSpotPrice);
    pnlPerShare = entryCredit + shortPayout + longPayout;
  } else {
    pnlPerShare = entryCredit;
  }

  return pnlPerShare * 100 * quantity;
}

export function generatePayoffCurve(position: ActivePosition, steps: number = 100): PayoffPoint[] {
  const { longStrike, shortStrike, currentSpotPrice } = position;
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

export const ACTIVE_POSITIONS: ActivePosition[] = [
  {
    id: 'pos-t-001',
    ticker: 'T',
    companyName: 'AT&T Inc.',
    strategy: 'Bull Put Spread',
    sleeve: 'Core Mean Reversion',
    entryDate: '2026-07-28',
    expirationDate: '2026-08-15',
    dte: 15,
    shortStrike: 18.5,
    longStrike: 17.5,
    spreadWidth: 1.0,
    quantity: 10,
    entryCredit: 0.35,
    netCreditTotal: 350,
    maxProfit: 350,
    maxRisk: 650,
    breakEven: 18.15,
    currentSpotPrice: 19.24,
    unrealizedPnL: 210,
    unrealizedPnLPct: 60.0,
    status: 'profit',
    selectionRank: 1,
    reversionProbability: 0.5325,
    robustZ: -2.45,
    legs: [
      {
        contractId: 'T260815P00018500',
        symbol: 'T 08/15/26 P18.5',
        side: 'sell',
        type: 'put',
        strike: 18.5,
        expiration: '2026-08-15',
        qty: 10,
        entryPrice: 0.52,
        currentPrice: 0.21,
      },
      {
        contractId: 'T260815P00017500',
        symbol: 'T 08/15/26 P17.5',
        side: 'buy',
        type: 'put',
        strike: 17.5,
        expiration: '2026-08-15',
        qty: 10,
        entryPrice: 0.17,
        currentPrice: 0.07,
      },
    ],
  },
  {
    id: 'pos-vrt-002',
    ticker: 'VRT',
    companyName: 'Vertiv Holdings Co',
    strategy: 'Bull Put Spread',
    sleeve: 'Crash Protocol',
    entryDate: '2026-07-29',
    expirationDate: '2026-08-21',
    dte: 21,
    shortStrike: 75.0,
    longStrike: 70.0,
    spreadWidth: 5.0,
    quantity: 4,
    entryCredit: 1.45,
    netCreditTotal: 580,
    maxProfit: 580,
    maxRisk: 1420,
    breakEven: 73.55,
    currentSpotPrice: 79.10,
    unrealizedPnL: 180,
    unrealizedPnLPct: 31.03,
    status: 'profit',
    selectionRank: 2,
    reversionProbability: 0.5104,
    robustZ: -4.30,
    legs: [
      {
        contractId: 'VRT260821P00075000',
        symbol: 'VRT 08/21/26 P75.0',
        side: 'sell',
        type: 'put',
        strike: 75.0,
        expiration: '2026-08-21',
        qty: 4,
        entryPrice: 2.10,
        currentPrice: 1.45,
      },
      {
        contractId: 'VRT260821P00070000',
        symbol: 'VRT 08/21/26 P70.0',
        side: 'buy',
        type: 'put',
        strike: 70.0,
        expiration: '2026-08-21',
        qty: 4,
        entryPrice: 0.65,
        currentPrice: 0.45,
      },
    ],
  },
  {
    id: 'pos-bg-003',
    ticker: 'BG',
    companyName: 'Bunge Global SA',
    strategy: 'Bull Put Spread',
    sleeve: 'Core Mean Reversion',
    entryDate: '2026-07-30',
    expirationDate: '2026-08-28',
    dte: 28,
    shortStrike: 90.0,
    longStrike: 85.0,
    spreadWidth: 5.0,
    quantity: 3,
    entryCredit: 1.20,
    netCreditTotal: 360,
    maxProfit: 360,
    maxRisk: 1140,
    breakEven: 88.8,
    currentSpotPrice: 91.45,
    unrealizedPnL: 45,
    unrealizedPnLPct: 12.5,
    status: 'neutral',
    selectionRank: 1,
    reversionProbability: 0.5923,
    robustZ: -3.03,
    legs: [
      {
        contractId: 'BG260828P00090000',
        symbol: 'BG 08/28/26 P90.0',
        side: 'sell',
        type: 'put',
        strike: 90.0,
        expiration: '2026-08-28',
        qty: 3,
        entryPrice: 1.85,
        currentPrice: 1.60,
      },
      {
        contractId: 'BG260828P00085000',
        symbol: 'BG 08/28/26 P85.0',
        side: 'buy',
        type: 'put',
        strike: 85.0,
        expiration: '2026-08-28',
        qty: 3,
        entryPrice: 0.65,
        currentPrice: 0.55,
      },
    ],
  },
  {
    id: 'pos-mod-004',
    ticker: 'MOD',
    companyName: 'Modine Manufacturing Co',
    strategy: 'Bull Put Spread',
    sleeve: 'Core Mean Reversion',
    entryDate: '2026-07-30',
    expirationDate: '2026-08-21',
    dte: 21,
    shortStrike: 110.0,
    longStrike: 105.0,
    spreadWidth: 5.0,
    quantity: 2,
    entryCredit: 1.60,
    netCreditTotal: 320,
    maxProfit: 320,
    maxRisk: 680,
    breakEven: 108.4,
    currentSpotPrice: 109.10,
    unrealizedPnL: -30,
    unrealizedPnLPct: -9.38,
    status: 'at_risk',
    selectionRank: 3,
    reversionProbability: 0.5556,
    robustZ: -2.78,
    legs: [
      {
        contractId: 'MOD260821P00110000',
        symbol: 'MOD 08/21/26 P110.0',
        side: 'sell',
        type: 'put',
        strike: 110.0,
        expiration: '2026-08-21',
        qty: 2,
        entryPrice: 2.30,
        currentPrice: 2.55,
      },
      {
        contractId: 'MOD260821P00105000',
        symbol: 'MOD 08/21/26 P105.0',
        side: 'buy',
        type: 'put',
        strike: 105.0,
        expiration: '2026-08-21',
        qty: 2,
        entryPrice: 0.70,
        currentPrice: 0.80,
      },
    ],
  },
];
