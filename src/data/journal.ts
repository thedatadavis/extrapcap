import fs from 'node:fs';
import path from 'node:path';

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

type JsonRecord = Record<string, any>;

const logsDir = path.join(process.cwd(), 'logs');
const reportDir = path.join(process.cwd(), 'reports');
const datedLog = /^\d{4}-\d{2}-\d{2}\.jsonl$/;

function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
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

function readLedger(): JournalEntry[] {
  if (!fs.existsSync(logsDir)) return [];
  const byDate = new Map<string, JournalItem[]>();
  const categories = fs.readdirSync(logsDir)
    .filter((name) => fs.statSync(path.join(logsDir, name)).isDirectory())
    .sort();

  for (const category of categories) {
    const categoryDir = path.join(logsDir, category);
    for (const fileName of fs.readdirSync(categoryDir).filter((name) => datedLog.test(name)).sort()) {
      const date = fileName.replace('.jsonl', '');
      const lines = fs.readFileSync(path.join(categoryDir, fileName), 'utf8').split('\n').filter(Boolean);
      const events = byDate.get(date) ?? [];
      lines.forEach((line, index) => {
        const record: JsonRecord = JSON.parse(line);
        const metadata: JsonRecord = record.journal ?? {};
        const judgment: JsonRecord = record.judgment ?? record.output ?? {};
        const contracts = contractDetails(record, metadata);
        const ids = contractIds(record, metadata, contracts);
        const ticker = asString(record.ticker ?? record.underlying ?? metadata.ticker ?? contracts[0]?.ticker);
        const status = String(record.status ?? metadata.status ?? judgment.decision ?? 'recorded');
        const decision = String(judgment.decision ?? record.decision ?? status);
        const kind = String(record.kind ?? metadata.kind ?? category.replace(/s$/, ''));
        const eventId = String(metadata.event_id ?? record.client_order_id ?? record.order_id ?? (category + '-' + String(index + 1)));
        events.push({
          eventId,
          category,
          kind,
          title: String(metadata.title ?? [ticker, kind.replaceAll('_', ' '), status.replaceAll('_', ' ')].filter(Boolean).join(' · ')),
          timestamp: asString(metadata.recorded_at ?? record.timestamp),
          ticker,
          contractIds: ids,
          contracts,
          clientOrderId: asString(record.client_order_id ?? metadata.client_order_id),
          status,
          decision,
          provider: String(judgment.provider ?? metadata.provider ?? record.provider ?? 'system'),
          reason: String(record.reason ?? judgment.reason ?? metadata.reason ?? 'No rationale recorded.'),
          sleeve: asString(record.sleeve ?? metadata.sleeve),
          strategyVariant: asString(record.strategy_variant ?? metadata.strategy_variant),
          strategyRoute: asString(record.strategy_route ?? metadata.strategy_route ?? record.selection_context?.strategy_route),
          selectionRank: typeof (record.selection_rank ?? metadata.selection_rank ?? record.selection_context?.selection_rank) === 'number'
            ? Number(record.selection_rank ?? metadata.selection_rank ?? record.selection_context?.selection_rank)
            : undefined,
          modelProbability: typeof (record.model_probability ?? metadata.model_probability) === 'number'
            ? Number(record.model_probability ?? metadata.model_probability)
            : undefined,
          modelBucket: asString(record.model_bucket ?? metadata.model_bucket),
          dataTier: asString(record.data_tier ?? metadata.data_tier),
          selectionContext: record.selection_context ?? metadata.selection_context,
          signalId: asString(record.signal_id),
          riskSnapshot: record.risk_snapshot,
          eventDecision: record.event_decision,
          marketData: record.market_data,
        });
      });
      byDate.set(date, events);
    }
  }
  return [...byDate.entries()]
    .map(([date, entries]) => ({
      date,
      entries: entries.sort((left, right) => (left.timestamp ?? '').localeCompare(right.timestamp ?? '') || left.category.localeCompare(right.category)),
    }))
    .sort((left, right) => right.date.localeCompare(left.date));
}

function latestPerformance() {
  const fallback = {
    variant: 'Unavailable',
    trades: 0,
    wins: 0,
    winRate: 0,
    returnOnCapital: 0,
    expectancy: 0,
    maxDrawdown: 0,
    portfolioReturn: 0,
    dataScope: 'no report found',
    quantiles: { p05: 0, p50: 0, p95: 0 },
    source: 'none',
  };
  if (!fs.existsSync(reportDir)) return fallback;
  const reports = fs.readdirSync(reportDir)
    .filter((name) => /^real-bars-variant-comparison-.*\.md$/.test(name))
    .sort()
    .reverse();
  if (!reports.length) return fallback;
  const source = path.join('reports', reports[0]);
  const text = fs.readFileSync(path.join(process.cwd(), source), 'utf8');
  const marker = '## Machine-readable results';
  if (!text.includes(marker)) return { ...fallback, source };
  const payload = text.slice(text.indexOf(marker));
  const rows = JSON.parse(payload.slice(payload.indexOf('['), payload.lastIndexOf(']') + 1));
  const row = rows.find((candidate: JsonRecord) => candidate.variant === 'improved') ?? rows[0];
  if (!row) return { ...fallback, source };
  const quantiles = row.trade_return_quantiles ?? {};
  return {
    variant: String(row.variant ?? 'unknown'),
    trades: Number(row.trades ?? 0),
    wins: Number(row.wins ?? 0),
    winRate: Number(row.win_rate ?? 0),
    returnOnCapital: Number(row.return_on_capital ?? 0),
    expectancy: Number(row.expectancy ?? 0),
    maxDrawdown: Number(row.portfolio_max_drawdown ?? 0),
    portfolioReturn: Number(row.portfolio_total_return ?? 0),
    dataScope: String(row.data_scope ?? 'unknown'),
    quantiles: {
      p05: Number(quantiles.p05 ?? row.tail_loss_p05 ?? 0),
      p50: Number(quantiles.p50 ?? 0),
      p95: Number(quantiles.p95 ?? 0),
    },
    source,
  };
}

export const journal = readLedger();

export const months = journal.reduce<Record<string, JournalEntry[]>>((groups, entry) => {
  const month = entry.date.slice(0, 7);
  (groups[month] ??= []).push(entry);
  return groups;
}, {});

export const performance = latestPerformance();
export const totalJournalEvents = journal.reduce((total, entry) => total + entry.entries.length, 0);
export const latestJournalDate = journal[0]?.date;

function displayName(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function spreadDescription(item: JournalItem) {
  const expiration = item.contracts.find((contract) => contract.expiration)?.expiration;
  const strikes = item.contracts.map((contract) => contract.strike).filter((strike): strike is number => strike !== undefined);
  const width = strikes.length > 1 ? Math.abs(Math.max(...strikes) - Math.min(...strikes)) : undefined;
  const details = [
    width ? `put spread covering a ${width}-point price range with a capped loss` : 'put spread with a capped loss',
    expiration ? `expiring ${formatDate(expiration)}` : undefined,
  ].filter(Boolean);
  return details.join(' ');
}

export function readoutFor(item: JournalItem): PublicReadout {
  const ticker = item.ticker ?? 'The underlying market';
  const status = item.status === 'dry_run' ? 'paper order' : displayName(item.status);
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
        status: 'not selected',
        headline: `${ticker} was left out of the rebound screen`,
        body: `${ticker} outperformed the broader market for ${streak}. This part of the strategy looks for potential rebounds after a stock falls behind the market, so the move was not considered for a trade.`,
      };
    }
    if (isVetoed) {
      return {
        label: 'Market screen',
        status: 'not selected',
        headline: `${ticker} did not move far enough to qualify`,
        body: `${ticker} ${direction} the broader market for ${streak}, but the difference was not large enough to meet the system's threshold for a potential rebound. No trade was proposed.`,
      };
    }
    return {
      label: 'Market screen',
      status: 'advanced',
      headline: `${ticker} advanced for further review`,
      body: `${ticker} ${direction} the broader market for ${streak}. The move was large enough to continue into the next stage of review, where the system checks price, events, liquidity, and portfolio risk.`,
    };
  }

  if (item.kind === 'model_decision') {
    const confidence = item.modelProbability !== undefined ? ` The model estimated a ${(item.modelProbability * 100).toFixed(0)}% chance that the setup would succeed.` : '';
    return {
      label: 'Risk review',
      status: isVetoed ? 'held back' : 'approved',
      headline: isVetoed ? `${ticker} was held back by the risk review` : `${ticker} passed the risk review`,
      body: isVetoed
        ? `The system reviewed ${ticker} and decided that conditions were not suitable for selling options to collect a payment.${confidence} No order was sent.`
        : `The system reviewed ${ticker} and found the conditions suitable for the next step.${confidence}`,
    };
  }

  if (item.kind === 'llm_review') {
    return {
      label: 'Trade review',
      status: item.decision === 'go' ? 'approved' : 'declined',
      headline: item.decision === 'go' ? `${ticker} received approval for a paper trade` : `${ticker} was declined after review`,
      body: item.decision === 'go'
        ? `A second review approved a ${spreadDescription(item)}. The trade was prepared for the paper account only; no real capital was committed.`
        : `A second review did not approve a trade in ${ticker}. The decision kept the setup out of the paper account.`,
    };
  }

  if (item.kind === 'paper_order') {
    return {
      label: 'Paper execution',
      status: 'paper only',
      headline: `A paper order was prepared for ${ticker}`,
      body: `The system prepared one ${spreadDescription(item)} for ${ticker}. This was a dry run for testing the process, not a live order, so no real trade or capital was involved.`,
    };
  }

  return {
    label: displayName(item.category),
    status: displayName(item.status),
    headline: `${ticker} was recorded in the journal`,
    body: `The system recorded a ${displayName(item.kind).toLowerCase()} involving ${ticker}. This entry documents the research process and does not represent a live trade.`,
  };
}

export const eventsByCategory = journal
  .flatMap((entry) => entry.entries)
  .reduce<Record<string, number>>((counts, event) => {
    counts[event.category] = (counts[event.category] ?? 0) + 1;
    return counts;
  }, {});

export function formatDate(dateString: string) {
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(dateString + 'T12:00:00Z'));
}

export function formatMonth(month: string) {
  return new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(month + '-01T12:00:00Z'));
}
