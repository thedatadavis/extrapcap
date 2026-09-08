export type ContractDetail = {
  contractId: string;
  ticker?: string;
  expiration?: string;
  optionType?: string;
  strike?: number;
  role?: string;
};

export type JournalItem = {
  eventId: string;
  category: string;
  kind: string;
  title: string;
  timestamp?: string;
  ticker?: string;
  contractIds: string[];
  contracts: ContractDetail[];
  clientOrderId?: string;
  status: string;
  decision: string;
  provider: string;
  reason: string;
  sleeve?: string;
  strategyVariant?: string;
  strategyRoute?: string;
  selectionRank?: number;
  modelProbability?: number;
  modelBucket?: string;
  dataTier?: string;
  selectionContext?: JsonRecord;
  signalId?: string;
  riskSnapshot?: JsonRecord;
  eventDecision?: JsonRecord;
  marketData?: JsonRecord;
  marketPrice?: number;
  marketPriceDate?: string;
  positions?: JsonRecord[];
  openOrders?: JsonRecord[];
  quantity?: number;
  limitPrice?: number;
  fillPrice?: number;
  side?: string;
};

export type JournalEntry = {
  date: string;
  entries: JournalItem[];
};

export type PublicReadout = {
  label: string;
  status: string;
  headline: string;
  body: string;
};

export type AccountSnapshot = {
  date: string;
  balance: number;
  cash: number;
  buyingPower: number;
};

export type PublicTrade = {
  action: string;
  ticker: string;
  description: string;
  context: string;
  status: string;
};

type JsonRecord = Record<string, any>;

function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function parseJson(str: unknown): JsonRecord {
  if (typeof str === 'object' && str !== null) return str as JsonRecord;
  if (typeof str === 'string') {
    try { return JSON.parse(str); } catch { return {}; }
  }
  return {};
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

function contractDetails(record: JsonRecord, metadata: JsonRecord): ContractDetail[] {
  const rawRows = Array.isArray(record.contracts)
    ? record.contracts
    : Array.isArray(metadata.contract_details)
      ? metadata.contract_details
      : Array.isArray(record.legs)
        ? record.legs
        : Array.isArray(metadata.legs)
          ? metadata.legs
          : [];

  if (rawRows.length > 0) {
    return rawRows.map((row: JsonRecord) => {
      const contractId = String(row.contract_id ?? row.symbol ?? '');
      const occ = parseOcc(contractId);
      const rawType = String(row.option_type ?? row.type ?? '').toLowerCase().trim();
      const optionType = rawType === 'p' || rawType === 'put' ? 'put' : rawType === 'c' || rawType === 'call' ? 'call' : occ?.type;
      return {
        contractId,
        ticker: asString(row.ticker ?? row.underlying),
        expiration: asString(row.expiration ?? occ?.expiration),
        optionType,
        strike: typeof row.strike === 'number' ? row.strike : occ?.strike,
        role: asString(row.role ?? row.side ?? row.position_intent),
      };
    }).filter((row: ContractDetail) => row.contractId);
  }

  const ids = Array.isArray(record.contract_ids)
    ? record.contract_ids
    : Array.isArray(metadata.contract_ids)
      ? metadata.contract_ids
      : [];
  return ids.map((id: unknown) => {
    const contractId = String(id ?? '');
    const occ = parseOcc(contractId);
    return {
      contractId,
      expiration: occ?.expiration,
      optionType: occ?.type,
      strike: occ?.strike,
    };
  }).filter((row: ContractDetail) => row.contractId);
}

function contractIds(record: JsonRecord, metadata: JsonRecord, contracts: ContractDetail[]): string[] {
  const explicit = Array.isArray(record.contract_ids)
    ? record.contract_ids
    : Array.isArray(metadata.contract_ids)
      ? metadata.contract_ids
      : contracts.map((contract) => contract.contractId);
  return [...new Set(explicit.map((value: unknown) => String(value).toUpperCase()).filter(Boolean))];
}

export async function getAccountHistory(db?: any): Promise<AccountSnapshot[]> {
  if (!db) return [];
  try {
    const result = await db.prepare(
      'SELECT as_of as date, equity as balance, cash, buying_power as buyingPower FROM account_snapshots ORDER BY as_of ASC'
    ).all();
    return (result.results || []).map((row: any) => ({
      date: row.date,
      balance: Number(row.balance || 0),
      cash: Number(row.cash || 0),
      buyingPower: Number(row.buyingPower || 0),
    }));
  } catch (err) {
    console.error('Error in getAccountHistory:', err);
    return [];
  }
}

export async function getJournalDates(db?: any): Promise<string[]> {
  if (!db) return [];
  try {
    const result = await db.prepare(
      'SELECT DISTINCT trading_day FROM events ORDER BY trading_day DESC'
    ).all();
    return (result.results || []).map((r: any) => String(r.trading_day)).filter(Boolean);
  } catch (err) {
    console.error('Error in getJournalDates:', err);
    return [];
  }
}

export type PositionEconomics = {
  id: number;
  ticker: string;
  strategy: string;
  direction: string;
  quantity: number;
  openedAt: string;
  closedAt: string | null;
  isActive: boolean;
  closeReason: string | null;
  shortStrike: number;
  longStrike: number;
  spreadWidth: number;
  expiration: string;
  entryCredit: number;
  upfrontPremium: number;
  grossMargin: number;
  maxRisk: number;
  maxRocPct: number;
  exitPrice: number | null;
  costToClose: number | null;
  realizedPnl: number | null;
  capitalPreserved: number | null;
  robustZ?: number;
  streakLength?: number;
  streakDirection?: string;
  reversionProbability?: number;
  underlyingPrice?: number;
  legs: any[];
  metadata?: any;
};

export async function getSessionPositions(db?: any, date?: string): Promise<PositionEconomics[]> {
  if (!db) return [];
  try {
    const posQuery = date
      ? await db.prepare('SELECT * FROM positions WHERE opened_at = ? OR closed_at = ? ORDER BY id DESC').bind(date, date).all()
      : await db.prepare('SELECT * FROM positions ORDER BY opened_at DESC, id DESC').all();

    const eventQuery = date
      ? await db.prepare("SELECT * FROM events WHERE trading_day = ? AND (kind = 'position_management' OR category = 'positions')").bind(date).all()
      : await db.prepare("SELECT * FROM events WHERE kind = 'position_management' OR category = 'positions'").all();

    const exitMap = new Map<number, { exitPrice: number; realizedPnl?: number; reason?: string }>();
    for (const evt of eventQuery.results || []) {
      const payload = parseJson(evt.payload);
      const posId = Number(payload.position_id ?? (typeof evt.event_id === 'string' ? evt.event_id.replace(/^pos-/, '') : 0));
      if (posId) {
        const exitP = typeof payload.exit_price === 'number'
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

    const rows = posQuery.results || [];
    return rows.map((row: any) => {
      const id = Number(row.id);
      const ticker = String(row.ticker || '').toUpperCase();
      const quantity = Math.max(1, Number(row.quantity || 1));
      const entryCredit = Math.abs(Number(row.entry_credit ?? row.entry_debit ?? 0));
      const shortStrike = Number(row.short_strike || 0);
      const longStrike = Number(row.long_strike || 0);
      const spreadWidth = Math.abs(Number(row.spread_width || Math.abs(shortStrike - longStrike) || 0));
      const upfrontPremium = Math.round(entryCredit * 100 * quantity * 100) / 100;
      const grossMargin = Math.round(spreadWidth * 100 * quantity * 100) / 100;
      const maxRisk = Math.max(0, Math.round((spreadWidth - entryCredit) * 100 * quantity * 100) / 100);
      const maxRocPct = maxRisk > 0 ? Math.round((upfrontPremium / maxRisk) * 1000) / 10 : 0;

      const exitInfo = exitMap.get(id);
      const exitPrice = exitInfo?.exitPrice ?? null;
      let costToClose: number | null = null;
      let realizedPnl: number | null = null;
      let capitalPreserved: number | null = null;

      if (exitPrice !== null && exitPrice !== undefined) {
        costToClose = Math.round(exitPrice * 100 * quantity * 100) / 100;
        realizedPnl = exitInfo?.realizedPnl ?? Math.round((entryCredit - exitPrice) * 100 * quantity * 100) / 100;
        if (realizedPnl < 0) {
          capitalPreserved = Math.max(0, Math.round((maxRisk - Math.abs(realizedPnl)) * 100) / 100);
        }
      }

      const metrics = parseJson(row.selection_metrics);
      const meta = parseJson(row.metadata);
      const legs = Array.isArray(row.legs) ? row.legs : parseJson(row.legs);

      const direction = shortStrike > longStrike ? 'Bullish' : 'Bearish';
      const strategy = `${direction} Put Credit Spread`;

      return {
        id,
        ticker,
        strategy,
        direction,
        quantity,
        openedAt: String(row.opened_at || ''),
        closedAt: row.closed_at ? String(row.closed_at) : null,
        isActive: Boolean(row.is_active),
        closeReason: exitInfo?.reason || row.close_reason,
        shortStrike,
        longStrike,
        spreadWidth,
        expiration: String(row.expiration || '').slice(0, 10),
        entryCredit,
        upfrontPremium,
        grossMargin,
        maxRisk,
        maxRocPct,
        exitPrice,
        costToClose,
        realizedPnl,
        capitalPreserved,
        robustZ: typeof metrics.robust_z === 'number' ? metrics.robust_z : undefined,
        streakLength: typeof metrics.streak_length === 'number' ? metrics.streak_length : undefined,
        streakDirection: metrics.streak_direction,
        reversionProbability: typeof metrics.reversion_probability === 'number' ? metrics.reversion_probability : undefined,
        underlyingPrice: typeof metrics.underlying_price === 'number' ? metrics.underlying_price : undefined,
        legs: Array.isArray(legs) ? legs : [],
        metadata: meta,
      };
    });
  } catch (err) {
    console.error('Error in getSessionPositions:', err);
    return [];
  }
}

export async function getSessionOrders(db?: any, date?: string): Promise<any[]> {
  if (!db) return [];
  try {
    const result = date
      ? await db.prepare("SELECT * FROM orders WHERE submitted_at LIKE ? OR created_at LIKE ? ORDER BY id DESC").bind(`${date}%`, `${date}%`).all()
      : await db.prepare("SELECT * FROM orders ORDER BY id DESC LIMIT 100").all();
    return result.results || [];
  } catch (err) {
    console.error('Error in getSessionOrders:', err);
    return [];
  }
}

export async function getJournal(db?: any, tradingDay?: string): Promise<JournalEntry[]> {
  if (!db) return [];
  try {
    const result = tradingDay
      ? await db.prepare(
          'SELECT * FROM events WHERE trading_day = ? ORDER BY trading_day DESC, recorded_at DESC'
        ).bind(tradingDay).all()
      : await db.prepare(
          'SELECT * FROM events ORDER BY trading_day DESC, recorded_at DESC'
        ).all();

    const rows = result.results || [];
    const byDate = new Map<string, JournalItem[]>();

    for (const row of rows) {
      const date = row.trading_day;
      const rawPayload = parseJson(row.payload);
      const metadata = parseJson(rawPayload.journal ?? {});
      const judgment = parseJson(rawPayload.judgment ?? rawPayload.output ?? {});

      const contracts = contractDetails(rawPayload, metadata);
      const ids = contractIds(rawPayload, metadata, contracts);
      const ticker = asString(row.ticker ?? rawPayload.ticker ?? rawPayload.underlying ?? metadata.ticker ?? contracts[0]?.ticker);
      const status = String(row.status ?? metadata.status ?? judgment.decision ?? 'recorded');
      const decision = String(judgment.decision ?? rawPayload.decision ?? status);
      const kind = String(row.kind ?? metadata.kind ?? row.category);
      const eventId = String(row.event_id ?? metadata.event_id ?? rawPayload.client_order_id ?? rawPayload.order_id);

      const quantity = typeof rawPayload.quantity === 'number'
        ? rawPayload.quantity
        : typeof rawPayload.filled_qty === 'number'
          ? rawPayload.filled_qty
          : typeof metadata.quantity === 'number'
            ? metadata.quantity
            : undefined;

      const fillPrice = rawPayload.filled_avg_price !== undefined && rawPayload.filled_avg_price !== null
        ? Math.abs(Number(rawPayload.filled_avg_price))
        : rawPayload.response?.filled_avg_price !== undefined && rawPayload.response?.filled_avg_price !== null
          ? Math.abs(Number(rawPayload.response.filled_avg_price))
          : typeof rawPayload.exit_price === 'number'
            ? Math.abs(rawPayload.exit_price)
            : undefined;

      const limitPrice = typeof rawPayload.limit_price === 'number'
        ? Math.abs(rawPayload.limit_price)
        : typeof rawPayload.price === 'number'
          ? Math.abs(rawPayload.price)
          : undefined;

      const side = asString(rawPayload.side ?? rawPayload.position_intent ?? metadata.side);

      const events = byDate.get(date) ?? [];
      events.push({
        eventId,
        category: row.category,
        kind,
        title: String(metadata.title ?? [ticker, kind.replaceAll('_', ' '), status.replaceAll('_', ' ')].filter(Boolean).join(' · ')),
        timestamp: asString(row.recorded_at ?? metadata.recorded_at ?? rawPayload.timestamp),
        ticker,
        contractIds: ids,
        contracts,
        clientOrderId: asString(rawPayload.client_order_id ?? metadata.client_order_id),
        status,
        decision,
        provider: String(judgment.provider ?? metadata.provider ?? rawPayload.provider ?? 'system'),
        reason: String(row.reason ?? judgment.reason ?? metadata.reason ?? 'No rationale recorded.'),
        sleeve: asString(row.sleeve ?? metadata.sleeve),
        strategyVariant: asString(row.strategy_variant ?? metadata.strategy_variant),
        strategyRoute: asString(row.strategy_route ?? metadata.strategy_route ?? rawPayload.selection_context?.strategy_route),
        selectionRank: typeof (rawPayload.selection_rank ?? metadata.selection_rank ?? rawPayload.selection_context?.selection_rank) === 'number'
          ? Number(rawPayload.selection_rank ?? metadata.selection_rank ?? rawPayload.selection_context?.selection_rank)
          : undefined,
        modelProbability: typeof (row.model_probability ?? rawPayload.model_probability ?? metadata.model_probability) === 'number'
          ? Number(row.model_probability ?? rawPayload.model_probability ?? metadata.model_probability)
          : undefined,
        modelBucket: asString(rawPayload.model_bucket ?? metadata.model_bucket),
        dataTier: asString(rawPayload.data_tier ?? metadata.data_tier),
        selectionContext: rawPayload.selection_context ?? metadata.selection_context,
        signalId: asString(rawPayload.signal_id),
        riskSnapshot: rawPayload.risk_snapshot,
        eventDecision: rawPayload.event_decision,
        marketData: rawPayload.market_data,
        marketPrice: typeof rawPayload.underlying_price === 'number' ? rawPayload.underlying_price : undefined,
        positions: Array.isArray(rawPayload.positions) ? rawPayload.positions : undefined,
        openOrders: Array.isArray(rawPayload.open_orders) ? rawPayload.open_orders : undefined,
        quantity,
        limitPrice,
        fillPrice,
        side,
      });
      byDate.set(date, events);
    }

    return [...byDate.entries()]
      .map(([date, entries]) => ({
        date,
        entries: entries.sort((left, right) => (left.timestamp ?? '').localeCompare(right.timestamp ?? '') || left.category.localeCompare(right.category)),
      }))
      .sort((left, right) => right.date.localeCompare(left.date));
  } catch (err) {
    console.error('Error in getJournal:', err);
    return [];
  }
}

export function isExecutedTrade(item: JournalItem) {
  const status = (item.status ?? '').toLowerCase();
  const decision = (item.decision ?? '').toLowerCase();
  const kind = (item.kind ?? '').toLowerCase();
  const category = (item.category ?? '').toLowerCase();

  if (
    status === 'vetoed' ||
    status === 'deferred' ||
    status === 'recorded' ||
    status === 'prepared' ||
    status === 'pending' ||
    status === 'pending_new' ||
    status === 'submitted' ||
    status === 'accepted' ||
    decision === 'vetoed' ||
    decision === 'no-go' ||
    category === 'signals' ||
    kind === 'entry_signal_gate' ||
    kind === 'data_integrity_gate' ||
    kind === 'event_gate'
  ) {
    return false;
  }

  return (
    status === 'filled' ||
    status === 'partially_filled' ||
    status === 'executed' ||
    status === 'broker_closed' ||
    status === 'closed' ||
    kind === 'fill' ||
    kind === 'execution' ||
    kind.includes('exit') ||
    kind.includes('close')
  );
}

export async function getExecutedTrades(dbOrJournal?: any) {
  const journal = Array.isArray(dbOrJournal) ? dbOrJournal : await getJournal(dbOrJournal);
  return journal
    .flatMap((entry) => entry.entries.map((item) => ({ date: entry.date, item, trade: tradeFor(item) })))
    .filter(({ item }) => isExecutedTrade(item));
}

function displayName(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function spreadDescription(item: JournalItem) {
  const expiration = item.contracts.find((contract) => contract.expiration)?.expiration;
  const strikes = item.contracts.map((contract) => contract.strike).filter((strike): strike is number => strike !== undefined);
  const optionTypes = [...new Set(item.contracts.map((contract) => contract.optionType).filter(Boolean))];
  const width = strikes.length > 1 ? Math.abs(Math.max(...strikes) - Math.min(...strikes)) : undefined;
  const instrument = optionTypes.length === 1 ? `${optionTypes[0]} spread` : 'options spread';
  const details = [
    width ? `${instrument} covering a ${width}-point price range with a capped loss` : `${instrument} with a capped loss`,
    expiration ? `expiring ${formatDate(expiration)}` : undefined,
  ].filter(Boolean);
  return details.join(' ');
}

function marketContext(item: JournalItem) {
  if (item.marketPrice === undefined) return '';
  const strikes = [...new Set(item.contracts.map((contract) => contract.strike).filter((strike): strike is number => strike !== undefined))].sort((left, right) => right - left);
  const price = `$${item.marketPrice.toFixed(2)}`;
  if (strikes.length > 0) {
    return ` At the time, ${item.ticker ?? 'the underlying'} was trading near ${price}; the option strikes were ${strikes.map((strike) => `$${strike.toFixed(0)}`).join(' and ')}.`;
  }
  return ` At the time, ${item.ticker ?? 'the underlying'} was trading near ${price}.`;
}

export function readoutFor(item: JournalItem): PublicReadout {
  const ticker = item.ticker ?? 'The underlying market';
  const context = item.selectionContext ?? {};
  const direction = context.streak_direction === 'positive' ? 'outperformed' : 'underperformed';
  const streakLength = Number(context.streak_length ?? 0);
  const streak = streakLength ? `${streakLength} consecutive sessions` : 'a recent run of sessions';
  const signalReason = String(context.signal_gate?.reason ?? item.reason);
  const isVetoed = ['vetoed', 'blocked', 'rejected'].includes(item.status);

  if (item.kind === 'basket_selection') {
    if (signalReason === 'core_requires_negative_relative_streak') {
      return {
        label: 'Market screen',
        status: 'pass',
        headline: `${ticker} was left out of the rebound screen`,
        body: `${ticker} outperformed the broader market for ${streak}. This part of the strategy looks for potential rebounds after a stock falls behind the market, so the move was passed over.`,
      };
    }
    if (isVetoed) {
      return {
        label: 'Market screen',
        status: 'pass',
        headline: `${ticker} did not move far enough to qualify`,
        body: `${ticker} ${direction} the broader market for ${streak}, but the difference was not large enough to meet the system's threshold for a potential rebound. No trade was proposed.`,
      };
    }
    return {
      label: 'Market screen',
      status: 'advance',
      headline: `${ticker} advanced for further review`,
      body: `${ticker} ${direction} the broader market for ${streak}. The move was large enough to continue into the next stage of review, where the system checks price, events, liquidity, and portfolio risk.`,
    };
  }

  if (item.kind === 'model_decision') {
    const confidence = item.modelProbability !== undefined ? ` The model estimated a ${(item.modelProbability * 100).toFixed(0)}% chance that the setup would succeed.` : '';
    return {
      label: 'Risk review',
      status: isVetoed ? 'block' : 'advance',
      headline: isVetoed ? `${ticker} was held back by the risk review` : `${ticker} passed the risk review`,
      body: isVetoed
        ? `The system reviewed ${ticker} and decided that conditions were not suitable for selling options to collect a payment.${confidence} No order was sent.`
        : `The system reviewed ${ticker} and found the conditions suitable for the next step.${confidence}`,
    };
  }

  if (item.kind === 'llm_review') {
    return {
      label: 'Trade review',
      status: item.decision === 'go' ? 'entry approved' : 'entry declined',
      headline: item.decision === 'go' ? `${ticker} received approval for an entry` : `${ticker} was declined after review`,
      body: item.decision === 'go'
        ? `A second review approved a ${spreadDescription(item)}.${marketContext(item)}`
        : `A second review did not approve a trade in ${ticker}. The setup was not sent to the order queue.${marketContext(item)}`,
    };
  }

  if (item.kind === 'paper_order') {
    return {
      label: 'Order',
      status: 'entry prepared',
      headline: `An entry was prepared for ${ticker}`,
      body: `The system prepared one ${spreadDescription(item)} for ${ticker}.${marketContext(item)}`,
    };
  }

  return {
    label: displayName(item.category),
    status: item.kind.includes('exit') || item.kind.includes('close') ? 'exit' : displayName(item.status),
    headline: `${ticker} was recorded in the journal`,
    body: `The system recorded a ${displayName(item.kind).toLowerCase()} involving ${ticker}. This entry documents the research process and does not represent a live trade.`,
  };
}

export function tradeFor(item: JournalItem): PublicTrade {
  const strikes = [...new Set(item.contracts.map((contract) => contract.strike).filter((strike): strike is number => strike !== undefined))].sort((left, right) => right - left);
  const optionTypes = [...new Set(item.contracts.map((contract) => contract.optionType).filter(Boolean))];
  const side = (item.side ?? '').toLowerCase();
  const isCredit = side.includes('sell') || side === 'sell_to_open';
  const isDebit = side.includes('buy') || side === 'buy_to_open';

  let spreadType = 'Options spread';
  if (optionTypes.length === 1) {
    const optName = optionTypes[0][0].toUpperCase() + optionTypes[0].slice(1);
    if (isCredit) {
      spreadType = `${optName} Credit Spread`;
    } else if (isDebit) {
      spreadType = `${optName} Debit Spread`;
    } else {
      spreadType = `${optName} spread`;
    }
  } else if (isCredit) {
    spreadType = 'Credit Spread';
  } else if (isDebit) {
    spreadType = 'Debit Spread';
  }

  const qtyPrefix = item.quantity ? `${item.quantity}x ` : '';
  const price = item.fillPrice ?? item.limitPrice;
  const priceStr = price !== undefined ? ` @ $${price.toFixed(2)}` : '';
  const strikesStr = strikes.map((s) => `$${s % 1 === 0 ? s : s.toFixed(2)}`).join(' / ');

  const description = strikes.length > 1
    ? `${qtyPrefix}${spreadType} · ${strikesStr}${priceStr}`
    : `${qtyPrefix}${displayName(item.kind)}${priceStr}`;

  return {
    action: /exit|close/.test(item.kind) || /close/.test(item.status) ? 'Exit' : 'Entry',
    ticker: item.ticker ?? '—',
    description,
    context: item.marketPrice !== undefined ? `Underlying near $${item.marketPrice.toFixed(2)}` : 'Price not recorded',
    status: displayName(item.status),
  };
}

export function formatDate(dateString: string) {
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(dateString + 'T12:00:00Z'));
}

export function formatMonth(month: string) {
  return new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(month + '-01T12:00:00Z'));
}
