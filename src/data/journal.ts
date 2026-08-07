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

function contractDetails(record: JsonRecord, metadata: JsonRecord): ContractDetail[] {
  const rows = Array.isArray(record.contracts)
    ? record.contracts
    : Array.isArray(metadata.contract_details)
      ? metadata.contract_details
      : [];
  return rows.map((row: JsonRecord) => ({
    contractId: String(row.contract_id ?? row.symbol ?? ''),
    ticker: asString(row.ticker ?? row.underlying),
    expiration: asString(row.expiration),
    optionType: asString(row.option_type),
    strike: typeof row.strike === 'number' ? row.strike : undefined,
    role: asString(row.role),
  })).filter((row: ContractDetail) => row.contractId);
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

export async function getJournal(db?: any): Promise<JournalEntry[]> {
  if (!db) return [];
  try {
    const result = await db.prepare(
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
    kind === 'fill' ||
    kind === 'execution' ||
    kind.includes('exit') ||
    kind.includes('close')
  );
}

export async function getExecutedTrades(db?: any) {
  const journal = await getJournal(db);
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
  const instrument = optionTypes.length === 1 ? `${optionTypes[0][0].toUpperCase()}${optionTypes[0].slice(1)} spread` : 'Options spread';
  const description = strikes.length > 1
    ? `${instrument} · ${strikes.map((strike) => `$${strike.toFixed(0)}`).join(' / ')}`
    : displayName(item.kind);
  return {
    action: /exit|close/.test(item.kind) ? 'Exit' : 'Entry',
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
