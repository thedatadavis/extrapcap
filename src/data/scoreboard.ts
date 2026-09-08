export type ScoreboardTrade = {
  id: number;
  ticker: string;
  companyName: string;
  strategy: string;
  sleeve: string;
  direction: 'Bullish' | 'Bearish' | 'Neutral';
  quantity: number;
  openedAt: string;
  closedAt: string;
  holdingDays: number;
  entryCredit: number;
  spreadWidth: number;
  upfrontPremium: number;
  maxRisk: number;
  exitPrice: number | null;
  costToClose: number | null;
  realizedPnl: number | null;
  returnPct: number | null;
  isWin: boolean;
  capitalPreserved: number | null;
  closeReason: string;
  closeReasonDisplay: string;
  robustZ?: number;
  streakLength?: number;
  streakDirection?: string;
  reversionProbability?: number;
  phase: string;
  feasibilityRatio?: number;
  journalUrl: string;
};

export type ScoreboardSummary = {
  totalTrades: number;
  wins: number;
  losses: number;
  pushes: number;
  winRatePct: number;
  netPnl: number;
  totalUpfrontPremium: number;
  totalMaxRisk: number;
  grossProfit: number;
  grossLoss: number;
  profitFactor: number | null;
  avgWin: number;
  avgLoss: number;
  avgReturnPct: number;
  totalCapitalPreserved: number;
  avgHoldingDays: number;
};

export type StreakPerformanceMetric = {
  streakLength: number;
  totalTrades: number;
  wins: number;
  losses: number;
  winRatePct: number;
  netPnl: number;
};

export type DirectionPerformanceMetric = {
  direction: string;
  totalTrades: number;
  wins: number;
  losses: number;
  winRatePct: number;
  netPnl: number;
};

export type ScoreboardData = {
  summary: ScoreboardSummary;
  streakMetrics: StreakPerformanceMetric[];
  directionMetrics: DirectionPerformanceMetric[];
  trades: ScoreboardTrade[];
  availablePhases: string[];
  activePhase: string;
};

function parseJson(str: unknown): Record<string, any> {
  if (typeof str === 'object' && str !== null) return str as Record<string, any>;
  if (typeof str === 'string') {
    try {
      return JSON.parse(str);
    } catch {
      return {};
    }
  }
  return {};
}

export function formatCloseReason(rawReason: string): string {
  if (!rawReason) return 'Closed';
  const reason = rawReason.toLowerCase();
  if (reason.includes('profit_target_80') || reason.includes('standard_80')) return 'Profit Target (80%)';
  if (reason.includes('early_profit') || reason.includes('early_35')) return 'Early Profit (35%)';
  if (reason.includes('feasibility')) return 'Stop Loss (Feasibility)';
  if (reason.includes('long_wing')) return 'Stop Loss (Wing Breach)';
  if (reason.includes('catastrophic')) return 'Stop Loss (Width Cap)';
  if (reason.includes('stop_loss')) return 'Stop Loss';
  if (reason.includes('max_holding')) {
    const match = reason.match(/\d+/);
    return match ? `Max Holding (${match[0]} sessions)` : 'Max Holding Time';
  }
  if (reason.includes('forced_exit_dte')) {
    const match = reason.match(/\d+/);
    return match ? `Horizon Exit (${match[0]} DTE)` : 'Horizon Exit';
  }
  return rawReason.replaceAll('_', ' ');
}

export async function getScoreboardData(db: any, selectedPhase?: string): Promise<ScoreboardData> {
  if (!db) {
    return {
      summary: {
        totalTrades: 0,
        wins: 0,
        losses: 0,
        pushes: 0,
        winRatePct: 0,
        netPnl: 0,
        totalUpfrontPremium: 0,
        totalMaxRisk: 0,
        grossProfit: 0,
        grossLoss: 0,
        profitFactor: null,
        avgWin: 0,
        avgLoss: 0,
        avgReturnPct: 0,
        totalCapitalPreserved: 0,
        avgHoldingDays: 0,
      },
      streakMetrics: [],
      directionMetrics: [],
      trades: [],
      availablePhases: ['testing'],
      activePhase: selectedPhase || 'all',
    };
  }

  // 1. Fetch all closed positions
  const posResult = await db.prepare(
    'SELECT * FROM positions WHERE is_active = 0 OR closed_at IS NOT NULL ORDER BY closed_at DESC, id DESC'
  ).all();
  const rows = posResult.results || [];

  // 2. Fetch all position management events to resolve realized PnL and exit prices
  const eventResult = await db.prepare(
    "SELECT * FROM events WHERE kind = 'position_management' OR category = 'positions' ORDER BY recorded_at DESC"
  ).all();
  const exitMap = new Map<number, { exitPrice: number; realizedPnl?: number; reason?: string }>();

  for (const evt of eventResult.results || []) {
    const payload = parseJson(evt.payload);
    const posId = Number(
      payload.position_id ?? (typeof evt.event_id === 'string' ? evt.event_id.replace(/^pos-/, '') : 0)
    );
    if (posId && !exitMap.has(posId)) {
      const exitP =
        typeof payload.exit_price === 'number'
          ? Math.abs(payload.exit_price)
          : typeof payload.current_debit === 'number'
          ? Math.abs(payload.current_debit)
          : undefined;

      if (exitP !== undefined) {
        exitMap.set(posId, {
          exitPrice: exitP,
          realizedPnl: typeof payload.realized_pnl === 'number' ? payload.realized_pnl : undefined,
          reason: payload.reason,
        });
      }
    }
  }

  // 3. Map into ScoreboardTrade objects
  const allTrades: ScoreboardTrade[] = rows.map((row: any) => {
    const id = Number(row.id);
    const ticker = String(row.ticker || '').toUpperCase();
    const companyName = String(row.company_name || '');
    const quantity = Math.max(1, Number(row.quantity || 1));
    const entryCredit = Math.abs(Number(row.entry_credit ?? row.entry_debit ?? 0));
    const shortStrike = Number(row.short_strike || 0);
    const longStrike = Number(row.long_strike || 0);
    const spreadWidth = Math.abs(Number(row.spread_width || Math.abs(shortStrike - longStrike) || 0));
    const upfrontPremium = Math.round(entryCredit * 100 * quantity * 100) / 100;
    const maxRisk = Math.max(0, Math.round((spreadWidth - entryCredit) * 100 * quantity * 100) / 100);

    const exitInfo = exitMap.get(id);
    const exitPrice = exitInfo?.exitPrice ?? null;
    let costToClose: number | null = null;
    let realizedPnl: number | null = null;
    let capitalPreserved: number | null = null;

    if (exitPrice !== null && exitPrice !== undefined) {
      costToClose = Math.round(exitPrice * 100 * quantity * 100) / 100;
      realizedPnl =
        exitInfo?.realizedPnl ?? Math.round((entryCredit - exitPrice) * 100 * quantity * 100) / 100;
      if (realizedPnl < 0 && maxRisk > 0) {
        capitalPreserved = Math.max(0, Math.round((maxRisk - Math.abs(realizedPnl)) * 100) / 100);
      }
    }

    const returnPct =
      realizedPnl !== null && maxRisk > 0
        ? Math.round((realizedPnl / maxRisk) * 1000) / 10
        : null;

    const metrics = parseJson(row.selection_metrics);
    const meta = parseJson(row.metadata);
    const fc = meta.feasibility_context || {};

    const phase = String(meta.phase || 'testing').toLowerCase();
    const openedAt = String(row.opened_at || '').slice(0, 10);
    const closedAt = String(row.closed_at || openedAt).slice(0, 10);

    let holdingDays = 0;
    if (openedAt && closedAt) {
      const openTs = new Date(openedAt + 'T00:00:00Z').getTime();
      const closeTs = new Date(closedAt + 'T00:00:00Z').getTime();
      holdingDays = Math.max(0, Math.round((closeTs - openTs) / (1000 * 60 * 60 * 24)));
    }

    const direction: 'Bullish' | 'Bearish' = shortStrike > longStrike ? 'Bullish' : 'Bearish';
    const strategy = `${direction} Put Credit Spread`;
    const sleeve = String(row.sleeve || meta.sleeve || 'core_mean_reversion').replaceAll('_', ' ');

    const rawReason = exitInfo?.reason || row.close_reason || '';
    const closeReasonDisplay = formatCloseReason(rawReason);

    return {
      id,
      ticker,
      companyName,
      strategy,
      sleeve,
      direction,
      quantity,
      openedAt,
      closedAt,
      holdingDays,
      entryCredit,
      spreadWidth,
      upfrontPremium,
      maxRisk,
      exitPrice,
      costToClose,
      realizedPnl,
      returnPct,
      isWin: (realizedPnl ?? 0) > 0.01,
      capitalPreserved,
      closeReason: rawReason,
      closeReasonDisplay,
      robustZ: typeof metrics.robust_z === 'number' ? metrics.robust_z : undefined,
      streakLength: typeof metrics.streak_length === 'number' ? metrics.streak_length : undefined,
      streakDirection: metrics.streak_direction,
      reversionProbability: typeof metrics.reversion_probability === 'number' ? metrics.reversion_probability : undefined,
      phase,
      feasibilityRatio: typeof fc.feasibility_ratio === 'number' ? fc.feasibility_ratio : undefined,
      journalUrl: `/journal/${openedAt}/${ticker}`,
    };
  });

  const availablePhases = [...new Set(allTrades.map((t) => t.phase))].filter(Boolean);
  if (!availablePhases.includes('testing')) availablePhases.push('testing');

  // 4. Filter by phase if specified (and not 'all')
  const filteredTrades =
    selectedPhase && selectedPhase !== 'all'
      ? allTrades.filter((t) => t.phase === selectedPhase.toLowerCase())
      : allTrades;

  // 5. Compute summary statistics
  let totalUpfrontPremium = 0;
  let totalMaxRisk = 0;
  let netPnl = 0;
  let grossProfit = 0;
  let grossLoss = 0;
  let wins = 0;
  let losses = 0;
  let pushes = 0;
  let totalReturnPct = 0;
  let returnsCount = 0;
  let totalCapitalPreserved = 0;
  let totalHoldingDays = 0;

  for (const trade of filteredTrades) {
    totalUpfrontPremium += trade.upfrontPremium;
    totalMaxRisk += trade.maxRisk;
    totalHoldingDays += trade.holdingDays;
    if (trade.capitalPreserved) totalCapitalPreserved += trade.capitalPreserved;

    if (trade.realizedPnl !== null) {
      netPnl += trade.realizedPnl;
      if (trade.realizedPnl > 0.01) {
        wins += 1;
        grossProfit += trade.realizedPnl;
      } else if (trade.realizedPnl < -0.01) {
        losses += 1;
        grossLoss += Math.abs(trade.realizedPnl);
      } else {
        pushes += 1;
      }
    }

    if (trade.returnPct !== null) {
      totalReturnPct += trade.returnPct;
      returnsCount += 1;
    }
  }

  const totalTrades = filteredTrades.length;
  const winRatePct = totalTrades > 0 ? Math.round((wins / totalTrades) * 1000) / 10 : 0;
  const profitFactor = grossLoss > 0 ? Math.round((grossProfit / grossLoss) * 100) / 100 : grossProfit > 0 ? 999.0 : null;
  const avgWin = wins > 0 ? Math.round((grossProfit / wins) * 100) / 100 : 0;
  const avgLoss = losses > 0 ? Math.round((grossLoss / losses) * 100) / 100 : 0;
  const avgReturnPct = returnsCount > 0 ? Math.round((totalReturnPct / returnsCount) * 10) / 10 : 0;
  const avgHoldingDays = totalTrades > 0 ? Math.round((totalHoldingDays / totalTrades) * 10) / 10 : 0;

  const summary: ScoreboardSummary = {
    totalTrades,
    wins,
    losses,
    pushes,
    winRatePct,
    netPnl: Math.round(netPnl * 100) / 100,
    totalUpfrontPremium: Math.round(totalUpfrontPremium * 100) / 100,
    totalMaxRisk: Math.round(totalMaxRisk * 100) / 100,
    grossProfit: Math.round(grossProfit * 100) / 100,
    grossLoss: Math.round(grossLoss * 100) / 100,
    profitFactor,
    avgWin,
    avgLoss,
    avgReturnPct,
    totalCapitalPreserved: Math.round(totalCapitalPreserved * 100) / 100,
    avgHoldingDays,
  };

  // 6. Compute streak length metrics
  const streakMap = new Map<number, { total: number; wins: number; losses: number; netPnl: number }>();
  for (const trade of filteredTrades) {
    const len = trade.streakLength ?? 0;
    if (!len) continue;
    const curr = streakMap.get(len) ?? { total: 0, wins: 0, losses: 0, netPnl: 0 };
    curr.total += 1;
    if (trade.isWin) curr.wins += 1;
    else if ((trade.realizedPnl ?? 0) < -0.01) curr.losses += 1;
    curr.netPnl += trade.realizedPnl ?? 0;
    streakMap.set(len, curr);
  }

  const streakMetrics: StreakPerformanceMetric[] = [...streakMap.entries()]
    .sort(([a], [b]) => a - b)
    .map(([streakLength, data]) => ({
      streakLength,
      totalTrades: data.total,
      wins: data.wins,
      losses: data.losses,
      winRatePct: data.total > 0 ? Math.round((data.wins / data.total) * 1000) / 10 : 0,
      netPnl: Math.round(data.netPnl * 100) / 100,
    }));

  // 7. Compute direction metrics
  const dirMap = new Map<string, { total: number; wins: number; losses: number; netPnl: number }>();
  for (const trade of filteredTrades) {
    const dir = trade.direction === 'Bullish' ? 'Bullish (Oversold Rebound)' : 'Bearish (Overbought Reversion)';
    const curr = dirMap.get(dir) ?? { total: 0, wins: 0, losses: 0, netPnl: 0 };
    curr.total += 1;
    if (trade.isWin) curr.wins += 1;
    else if ((trade.realizedPnl ?? 0) < -0.01) curr.losses += 1;
    curr.netPnl += trade.realizedPnl ?? 0;
    dirMap.set(dir, curr);
  }

  const directionMetrics: DirectionPerformanceMetric[] = [...dirMap.entries()].map(([direction, data]) => ({
    direction,
    totalTrades: data.total,
    wins: data.wins,
    losses: data.losses,
    winRatePct: data.total > 0 ? Math.round((data.wins / data.total) * 1000) / 10 : 0,
    netPnl: Math.round(data.netPnl * 100) / 100,
  }));

  return {
    summary,
    streakMetrics,
    directionMetrics,
    trades: filteredTrades,
    availablePhases,
    activePhase: selectedPhase || 'all',
  };
}
