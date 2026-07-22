import fs from 'node:fs';
import path from 'node:path';

export type JournalEntry = {
  date: string;
  entries: Array<{
    id: string;
    decision: string;
    provider: string;
    reason: string;
  }>;
};

const rationaleDir = path.join(process.cwd(), 'logs', 'rationales');

function readEntries(fileName: string): JournalEntry {
  const date = fileName.replace('.jsonl', '');
  const lines = fs.readFileSync(path.join(rationaleDir, fileName), 'utf8').trim().split('\n').filter(Boolean);
  return {
    date,
    entries: lines.map((line, index) => {
      const record = JSON.parse(line);
      const judgment = record.judgment ?? {};
      return {
        id: record.client_order_id ?? record.candidate ?? `entry-${index + 1}`,
        decision: judgment.decision ?? 'unknown',
        provider: judgment.provider ?? 'system',
        reason: judgment.reason ?? 'No rationale recorded.',
      };
    }),
  };
}

export const journal = fs.existsSync(rationaleDir)
  ? fs.readdirSync(rationaleDir).filter((file) => file.endsWith('.jsonl')).sort().reverse().map(readEntries)
  : [];

export const months = journal.reduce<Record<string, JournalEntry[]>>((groups, entry) => {
  const month = entry.date.slice(0, 7);
  (groups[month] ??= []).push(entry);
  return groups;
}, {});

export const performance = {
  variant: 'Improved',
  trades: 1,
  wins: 1,
  totalPnl: 0.2820512820512821,
  expectancy: 0.2820512820512821,
  maxDrawdown: 0,
  source: 'reports/sample-backtest.json',
};

export const totalJournalEvents = journal.reduce((total, entry) => total + entry.entries.length, 0);

export function formatDate(dateString: string) {
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${dateString}T12:00:00Z`));
}

export function formatMonth(month: string) {
  return new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${month}-01T12:00:00Z`));
}
