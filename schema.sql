-- Cloudflare D1 Database Schema for Extrapcap

-- Core trading events (replaces all logs/*.jsonl files)
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT UNIQUE NOT NULL,
    trading_day     TEXT NOT NULL,
    recorded_at     TEXT DEFAULT (datetime('now')),
    category        TEXT NOT NULL,
    kind            TEXT,
    ticker          TEXT,
    status          TEXT,
    reason          TEXT,
    sleeve          TEXT,
    strategy_variant TEXT,
    strategy_route  TEXT,
    model_probability REAL,
    payload         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_day ON events(trading_day);
CREATE INDEX IF NOT EXISTS idx_events_ticker ON events(ticker);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category, trading_day);

-- Order lifecycle (replaces logs/orders/ids.jsonl)
CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    client_order_id  TEXT UNIQUE NOT NULL,
    signal_id        TEXT,
    broker_order_id  TEXT,
    ticker           TEXT NOT NULL,
    sleeve           TEXT NOT NULL,
    side             TEXT NOT NULL,
    strategy_variant TEXT,
    limit_price      REAL,
    quantity         INTEGER DEFAULT 1,
    legs             TEXT NOT NULL,
    metadata         TEXT,
    execution_status TEXT DEFAULT 'submitted',
    submitted_at     TEXT,
    filled_at        TEXT,
    created_at       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(execution_status);

-- Active and historical positions
CREATE TABLE IF NOT EXISTS positions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker            TEXT NOT NULL,
    company_name      TEXT,
    short_symbol      TEXT NOT NULL,
    long_symbol       TEXT NOT NULL,
    short_strike      REAL NOT NULL,
    long_strike       REAL NOT NULL,
    expiration        TEXT NOT NULL,
    spread_width      REAL NOT NULL,
    entry_credit      REAL,
    entry_debit       REAL,
    opened_at         TEXT NOT NULL,
    closed_at         TEXT,
    close_reason      TEXT,
    sleeve            TEXT DEFAULT 'core',
    strategy_variant  TEXT DEFAULT 'fast_ev',
    strategy_route    TEXT,
    quantity          INTEGER DEFAULT 1,
    is_active         INTEGER DEFAULT 1,
    legs              TEXT,
    selection_metrics TEXT,
    metadata          TEXT
);
CREATE INDEX IF NOT EXISTS idx_positions_active ON positions(is_active);

-- Daily market bars (replaces data/normalized/bars.csv)
CREATE TABLE IF NOT EXISTS bars (
    date   TEXT NOT NULL,
    symbol TEXT NOT NULL,
    open   REAL, high REAL, low REAL, close REAL,
    volume INTEGER, vwap REAL,
    PRIMARY KEY (date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_bars_symbol ON bars(symbol, date);

-- Tradable basket snapshots (replaces data/universe/tradable-basket.csv)
CREATE TABLE IF NOT EXISTS basket (
    as_of            TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    sector           TEXT,
    robust_z         REAL,
    signed_streak    INTEGER,
    streak_length    INTEGER,
    streak_direction TEXT,
    features         TEXT,
    PRIMARY KEY (as_of, symbol)
);

-- Workflow run tracking
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT UNIQUE NOT NULL,
    workflow    TEXT NOT NULL,
    status      TEXT DEFAULT 'running',
    started_at  TEXT DEFAULT (datetime('now')),
    finished_at TEXT,
    duration_s  REAL,
    summary     TEXT,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs(workflow, started_at DESC);

-- Account snapshots (replaces logs/reports reconciliation data)
CREATE TABLE IF NOT EXISTS account_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of           TEXT NOT NULL,
    equity          REAL,
    cash            REAL,
    buying_power    REAL,
    portfolio_value REAL,
    daily_pnl       REAL,
    payload         TEXT,
    recorded_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON account_snapshots(as_of);
