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
  strategy: string;
  sleeve: string;
  direction: 'bullish' | 'bearish' | 'neutral';
  optionType: 'put' | 'call' | 'mixed';
  entryDate: string;
  expirationDate: string;
  dte: number;
  strikes: number[];
  quantity: number;
  entryValue: number;
  entryValuePerContract: number;
  maxProfit: number;
  maxRisk: number;
  breakEvenPoints: number[];
  currentSpotPrice: number | null;
  unrealizedPnL: number;
  unrealizedPnLPct: number | null;
  status: 'profit' | 'neutral' | 'at_risk';
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

const CONTRACT_MULTIPLIER = 100;
const EPSILON = 1e-8;

function numeric(value: unknown, field: string): number {
  if (value == null || (typeof value === 'string' && value.trim() === '')) {
    throw new Error(`positions: ${field} is required and must be numeric`);
  }
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`positions: ${field} is required and must be numeric`);
  return parsed;
}

function positive(value: unknown, field: string): number {
  const parsed = numeric(value, field);
  if (parsed <= 0) throw new Error(`positions: ${field} must be greater than zero`);
  return parsed;
}

function parseJson(value: unknown, field: string): Record<string, any> {
  if (value == null || value === '') return {};
  try {
    const parsed = typeof value === 'string' ? JSON.parse(value) : value;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('object expected');
    return parsed as Record<string, any>;
  } catch (error) {
    throw new Error(`positions: invalid ${field}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function parseOcc(symbol: string): { type: 'put' | 'call'; strike: number; expiration: string } | null {
  const value = symbol.trim().toUpperCase();
  if (value.length < 16) return null;
  const suffix = value.slice(-15);
  if (!/^[0-9]{6}[CP][0-9]{8}$/.test(suffix)) return null;
  const year = 2000 + Number(suffix.slice(0, 2));
  const month = Number(suffix.slice(2, 4));
  const day = Number(suffix.slice(4, 6));
  const expiration = `${year.toString().padStart(4, '0')}-${month.toString().padStart(2, '0')}-${day.toString().padStart(2, '0')}`;
  const date = new Date(`${expiration}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  return { type: suffix[6] === 'P' ? 'put' : 'call', strike: Number(suffix.slice(7)) / 1000, expiration };
}

function parseLeg(raw: any, rowExpiration: string, index: number): OptionLeg {
  if (!raw || typeof raw !== 'object') throw new Error(`positions: leg ${index} is invalid`);
  const symbol = String(raw.symbol ?? raw.contract_id ?? '').trim();
  if (!symbol) throw new Error(`positions: leg ${index} is missing its contract symbol`);
  const occ = parseOcc(symbol);
  const typeValue = String(raw.type ?? raw.option_type ?? occ?.type ?? '').toLowerCase();
  if (typeValue !== 'put' && typeValue !== 'call') throw new Error(`positions: leg ${symbol} is missing option type`);
  const strike = numeric(raw.strike ?? raw.strike_price ?? occ?.strike, `leg ${symbol} strike`);
  const expiration = String(raw.expiration ?? raw.expiration_date ?? occ?.expiration ?? rowExpiration).slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(expiration)) throw new Error(`positions: leg ${symbol} has invalid expiration`);
  const side = String(raw.side ?? '').toLowerCase();
  if (side !== 'buy' && side !== 'sell') throw new Error(`positions: leg ${symbol} must declare buy or sell`);
  const entryPrice = numeric(raw.entryPrice ?? raw.entry_price, `leg ${symbol} entry price`);
  const currentPrice = numeric(raw.currentPrice ?? raw.current_price ?? raw.mark ?? raw.midpoint, `leg ${symbol} current mark`);
  if (entryPrice < 0 || currentPrice < 0) throw new Error(`positions: leg ${symbol} prices cannot be negative`);
  return {
    contractId: String(raw.contractId ?? raw.contract_id ?? symbol),
    symbol,
    side: side as 'buy' | 'sell',
    type: typeValue as 'put' | 'call',
    strike,
    expiration,
    qty: positive(raw.qty ?? raw.ratio_qty ?? 1, `leg ${symbol} quantity`),
    entryPrice,
    currentPrice,
  };
}

function intrinsic(leg: OptionLeg, spotPrice: number): number {
  return leg.type === 'call' ? Math.max(0, spotPrice - leg.strike) : Math.max(0, leg.strike - spotPrice);
}

function sideSign(leg: OptionLeg): number {
  return leg.side === 'buy' ? 1 : -1;
}

function cashValue(position: ActivePosition, spotPrice: number, mark: 'expiration' | 'current'): number {
  return position.legs.reduce((total, leg) => {
    const units = position.quantity * leg.qty * CONTRACT_MULTIPLIER;
    const entryCash = -sideSign(leg) * leg.entryPrice * units;
    const exitValue = mark === 'expiration' ? intrinsic(leg, spotPrice) : leg.currentPrice;
    return total + entryCash + sideSign(leg) * exitValue * units;
  }, 0);
}

export function calculateSpreadPayoff(position: ActivePosition, targetSpotPrice: number): number {
  return cashValue(position, numeric(targetSpotPrice, 'target spot price'), 'expiration');
}

function uniqueSorted(values: number[]): number[] {
  return [...new Set(values.filter((value) => Number.isFinite(value)).map((value) => Number(value.toFixed(8))))].sort((a, b) => a - b);
}

function breakEvenPoints(position: ActivePosition, strikes: number[]): number[] {
  const upper = Math.max(...strikes, 1) * 2 + Math.max(...strikes, 1);
  const anchors = uniqueSorted([0, ...strikes, upper]);
  const points: number[] = [];
  for (let index = 0; index < anchors.length - 1; index += 1) {
    const left = anchors[index];
    const right = anchors[index + 1];
    const leftPnl = calculateSpreadPayoff(position, left);
    const rightPnl = calculateSpreadPayoff(position, right);
    if (Math.abs(leftPnl) < 0.01) points.push(left);
    if (leftPnl * rightPnl < 0) {
      points.push(left + ((0 - leftPnl) * (right - left)) / (rightPnl - leftPnl));
    }
    if (index === anchors.length - 2 && Math.abs(rightPnl) < 0.01) points.push(right);
  }
  return uniqueSorted(points);
}

function classifySpread(legs: OptionLeg[], entryValue: number): { strategy: string; direction: ActivePosition['direction']; optionType: ActivePosition['optionType'] } {
  const optionTypes = [...new Set(legs.map((leg) => leg.type))];
  const optionType = optionTypes.length === 1 ? optionTypes[0] : 'mixed';
  if (optionType === 'mixed') return { strategy: 'Iron Condor', direction: 'neutral', optionType };
  const buys = legs.filter((leg) => leg.side === 'buy');
  const sells = legs.filter((leg) => leg.side === 'sell');
  if (!buys.length || !sells.length) throw new Error('positions: a spread requires both bought and sold legs');
  let direction: ActivePosition['direction'] = 'neutral';
  if (optionType === 'put') direction = buys[0].strike > sells[0].strike ? 'bearish' : 'bullish';
  if (optionType === 'call') direction = buys[0].strike < sells[0].strike ? 'bullish' : 'bearish';
  const kind = entryValue > EPSILON ? 'Credit' : entryValue < -EPSILON ? 'Debit' : 'Flat';
  const directionLabel = direction[0].toUpperCase() + direction.slice(1);
  return { strategy: `${directionLabel} ${optionType[0].toUpperCase() + optionType.slice(1)} ${kind} Spread`, direction, optionType };
}

function mapSleeve(row: any): string {
  const value = String(row.sleeve ?? row.strategy_variant ?? '').toLowerCase();
  if (value.includes('asymmetric')) return 'Asymmetric Reversion';
  if (value.includes('core')) return 'Core Mean Reversion';
  return value ? value : 'Unclassified';
}

function dteFor(expiration: string): number {
  const exp = new Date(`${expiration}T23:59:59Z`);
  if (Number.isNaN(exp.getTime())) throw new Error(`positions: invalid expiration ${expiration}`);
  return Math.max(0, Math.ceil((exp.getTime() - Date.now()) / 86_400_000));
}

function deriveExtrema(position: ActivePosition): { maxProfit: number; maxRisk: number } {
  const strikes = position.legs.map((leg) => leg.strike);
  const upper = Math.max(...strikes, 1) * 2 + Math.max(...strikes, 1);
  const values = uniqueSorted([0, ...strikes, upper]).map((spot) => calculateSpreadPayoff(position, spot));
  return { maxProfit: Math.max(0, ...values), maxRisk: Math.max(0, ...values.map((value) => -value)) };
}

export function generatePayoffCurve(position: ActivePosition, steps = 100): PayoffPoint[] {
  if (!Number.isInteger(steps) || steps < 2) throw new Error('positions: payoff curve requires at least two steps');
  const strikes = position.legs.map((leg) => leg.strike);
  const minPrice = Math.max(0.01, Math.min(...strikes) - Math.max(...strikes, 1) * 0.5);
  const maxPrice = Math.max(...strikes) + Math.max(...strikes, 1) * 0.5;
  const stepSize = (maxPrice - minPrice) / (steps - 1);
  return Array.from({ length: steps }, (_, index) => {
    const spotPrice = Number((minPrice + index * stepSize).toFixed(2));
    const pnlTotal = calculateSpreadPayoff(position, spotPrice);
    return { spotPrice, pnlPerContract: pnlTotal / position.quantity, pnlTotal, isProfit: pnlTotal >= 0 };
  });
}

function parsePosition(row: any): ActivePosition {
  const id = String(row.id ?? '').trim();
  const ticker = String(row.ticker ?? '').trim().toUpperCase();
  const expirationDate = String(row.expiration ?? '').slice(0, 10);
  if (!id || !ticker || !/^\d{4}-\d{2}-\d{2}$/.test(expirationDate)) throw new Error('positions: id, ticker, and expiration are required');
  const quantity = positive(row.quantity, `position ${id} quantity`);
  let rawLegs = row.legs;
  if (typeof rawLegs === 'string') {
    try {
      rawLegs = JSON.parse(rawLegs);
    } catch (error) {
      throw new Error(`positions: invalid position ${id} legs: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  if (!Array.isArray(rawLegs) || rawLegs.length < 2) throw new Error(`positions: position ${id} has no complete option legs`);
  const legs = rawLegs.map((leg, index) => parseLeg(leg, expirationDate, index));
  if (legs.some((leg) => leg.expiration !== expirationDate)) throw new Error(`positions: position ${id} has mismatched leg expirations`);
  const entryValue = legs.reduce((total, leg) => total - sideSign(leg) * leg.entryPrice * leg.qty * quantity * CONTRACT_MULTIPLIER, 0);
  const currentPnl = legs.reduce((total, leg) => total - sideSign(leg) * leg.entryPrice * leg.qty * quantity * CONTRACT_MULTIPLIER + sideSign(leg) * leg.currentPrice * leg.qty * quantity * CONTRACT_MULTIPLIER, 0);
  const classification = classifySpread(legs, entryValue);
  const position: ActivePosition = {
    id,
    ticker,
    companyName: String(row.company_name ?? ''),
    ...classification,
    sleeve: mapSleeve(row),
    entryDate: String(row.opened_at ?? ''),
    expirationDate,
    dte: dteFor(expirationDate),
    strikes: uniqueSorted(legs.map((leg) => leg.strike)),
    quantity,
    entryValue,
    entryValuePerContract: entryValue / quantity,
    maxProfit: 0,
    maxRisk: 0,
    breakEvenPoints: [],
    currentSpotPrice: (() => {
      const meta = parseJson(row.metadata, `position ${id} metadata`);
      return meta.current_spot_price == null ? null : numeric(meta.current_spot_price, `position ${id} current spot`);
    })(),
    unrealizedPnL: currentPnl,
    unrealizedPnLPct: null,
    status: currentPnl > 0.01 ? 'profit' : currentPnl < -0.01 ? 'at_risk' : 'neutral',
    legs,
    selectionRank: (() => { const m = parseJson(row.selection_metrics, `position ${id} selection metrics`); return m.selection_rank == null ? undefined : numeric(m.selection_rank, `position ${id} selection rank`); })(),
    reversionProbability: (() => { const m = parseJson(row.selection_metrics, `position ${id} selection metrics`); return m.reversion_probability == null ? undefined : numeric(m.reversion_probability, `position ${id} reversion probability`); })(),
    robustZ: (() => { const m = parseJson(row.selection_metrics, `position ${id} selection metrics`); return m.robust_z == null ? undefined : numeric(m.robust_z, `position ${id} robust z`); })(),
  };
  const extrema = deriveExtrema(position);
  position.maxProfit = extrema.maxProfit;
  position.maxRisk = extrema.maxRisk;
  position.breakEvenPoints = breakEvenPoints(position, position.strikes);
  const denominator = entryValue >= 0 ? position.maxProfit : position.maxRisk;
  position.unrealizedPnLPct = denominator > 0 ? (currentPnl / denominator) * 100 : null;
  return position;
}

export async function getActivePositions(db: any): Promise<ActivePosition[]> {
  if (!db) throw new Error('positions: D1 database binding is required');
  const result = await db.prepare('SELECT * FROM positions WHERE is_active = 1 ORDER BY opened_at DESC').all();
  const rows = result?.results;
  if (!Array.isArray(rows)) throw new Error('positions: D1 returned an invalid result');
  return rows.map(parsePosition);
}
