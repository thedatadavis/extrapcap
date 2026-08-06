-- Cloudflare D1 Database Schema for Extrapcap (Normalized & Run-Scoped)

-- 1. Workflow run tracking (Parent entity for execution runs)
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY NOT NULL,
    workflow    TEXT NOT NULL,
    status      TEXT DEFAULT 'running',
    started_at  TEXT DEFAULT (datetime('now')),
    finished_at TEXT,
    duration_s  REAL,
    summary     TEXT,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_workflow ON runs(workflow, started_at DESC);

-- 2. Core trading events (Run-scoped audit trail)
CREATE TABLE IF NOT EXISTS events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         TEXT UNIQUE NOT NULL,
    run_id           TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
    trading_day      TEXT NOT NULL,
    recorded_at      TEXT DEFAULT (datetime('now')),
    category         TEXT NOT NULL,
    kind             TEXT,
    ticker           TEXT,
    status           TEXT,
    reason           TEXT,
    sleeve           TEXT,
    strategy_variant TEXT,
    strategy_route   TEXT,
    model_probability REAL,
    payload          TEXT NOT NULL,
    CONSTRAINT unq_run_ticker_kind UNIQUE (run_id, ticker, kind, category)
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_day ON events(trading_day);
CREATE INDEX IF NOT EXISTS idx_events_ticker ON events(ticker);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category, trading_day);

-- 3. Tradable basket snapshots (Run-scoped candidate snapshots)
CREATE TABLE IF NOT EXISTS basket (
    as_of            TEXT NOT NULL,
    run_id           TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
    symbol           TEXT NOT NULL,
    sector           TEXT,
    robust_z         REAL,
    signed_streak    INTEGER,
    streak_length    INTEGER,
    streak_direction TEXT,
    features         TEXT,
    PRIMARY KEY (as_of, run_id, symbol)
);
CREATE INDEX IF NOT EXISTS idx_basket_as_of ON basket(as_of);
CREATE INDEX IF NOT EXISTS idx_basket_run ON basket(run_id);

-- 4. Order lifecycle (Run-scoped order records)
CREATE TABLE IF NOT EXISTS orders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    client_order_id  TEXT UNIQUE NOT NULL,
    run_id           TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
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
CREATE INDEX IF NOT EXISTS idx_orders_run ON orders(run_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(execution_status);

-- 5. Active and historical positions
CREATE TABLE IF NOT EXISTS positions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
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
CREATE INDEX IF NOT EXISTS idx_positions_run ON positions(run_id);

-- 6. Account snapshots (Reconciliation data)
CREATE TABLE IF NOT EXISTS account_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT REFERENCES runs(run_id) ON DELETE CASCADE,
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
CREATE INDEX IF NOT EXISTS idx_snapshots_run ON account_snapshots(run_id);

-- 7. Daily market bars (Shared market data)
CREATE TABLE IF NOT EXISTS bars (
    date   TEXT NOT NULL,
    symbol TEXT NOT NULL,
    open   REAL, high REAL, low REAL, close REAL,
    volume INTEGER, vwap REAL,
    PRIMARY KEY (date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_bars_symbol ON bars(symbol, date);

-- 8. Stock greenlist universe metadata
CREATE TABLE IF NOT EXISTS universe (
    symbol                TEXT PRIMARY KEY NOT NULL,
    sector                TEXT NOT NULL,
    avg_volume            INTEGER,
    market_cap            REAL,
    cap_tier              TEXT,
    exchange              TEXT,
    weekly_options        INTEGER DEFAULT 0,
    penny_pricing         INTEGER DEFAULT 0,
    options_volume        INTEGER,
    updated_at            TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_universe_sector ON universe(sector);

-- 9. Structural risk events (News & Earnings vetoes)
CREATE TABLE IF NOT EXISTS risk_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    event_type  TEXT NOT NULL, -- 'earnings' or 'news'
    event_date  TEXT NOT NULL,
    headline    TEXT,
    veto_reason TEXT,
    recorded_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_risk_events_symbol ON risk_events(symbol, event_date);

