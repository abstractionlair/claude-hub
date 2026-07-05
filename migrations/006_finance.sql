-- Phase 6: Financial Holdings Tracking
-- Adds tables for brokerage account tracking, daily holdings snapshots,
-- balance history, transactions, and email cross-check events.

-- Brokerage accounts (one row per SnapTrade account or manual account)
CREATE TABLE IF NOT EXISTS finance_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connector_id UUID REFERENCES connectors(id) ON DELETE SET NULL,
    snaptrade_account_id TEXT UNIQUE,
    brokerage TEXT NOT NULL,
    account_name TEXT NOT NULL,
    account_type TEXT,
    account_number_masked TEXT,
    currency TEXT NOT NULL DEFAULT 'USD',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Daily position snapshots
CREATE TABLE IF NOT EXISTS finance_holdings (
    id BIGSERIAL PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES finance_accounts(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    description TEXT,
    shares NUMERIC(20,6) NOT NULL,
    price NUMERIC(20,6),
    market_value NUMERIC(20,2),
    cost_basis NUMERIC(20,2),
    average_purchase_price NUMERIC(20,6),
    currency TEXT NOT NULL DEFAULT 'USD',
    asset_class TEXT,
    source TEXT NOT NULL DEFAULT 'snaptrade',
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_id, snapshot_date, symbol)
);

-- Daily account balance snapshots
CREATE TABLE IF NOT EXISTS finance_balances (
    id BIGSERIAL PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES finance_accounts(id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    total_value NUMERIC(20,2),
    cash NUMERIC(20,2),
    buying_power NUMERIC(20,2),
    source TEXT NOT NULL DEFAULT 'snaptrade',
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(account_id, snapshot_date)
);

-- Transaction history
CREATE TABLE IF NOT EXISTS finance_transactions (
    id BIGSERIAL PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES finance_accounts(id) ON DELETE CASCADE,
    snaptrade_id TEXT,
    trade_date DATE NOT NULL,
    settlement_date DATE,
    type TEXT NOT NULL,
    symbol TEXT,
    description TEXT,
    shares NUMERIC(20,6),
    price NUMERIC(20,6),
    amount NUMERIC(20,2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    source TEXT NOT NULL DEFAULT 'snaptrade',
    raw_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_txn_dedup
    ON finance_transactions(account_id, snaptrade_id) WHERE snaptrade_id IS NOT NULL;

-- Email statement notification events (cross-check)
CREATE TABLE IF NOT EXISTS finance_email_events (
    id BIGSERIAL PRIMARY KEY,
    brokerage TEXT NOT NULL,
    event_type TEXT NOT NULL,
    subject TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    email_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Sync run audit trail
CREATE TABLE IF NOT EXISTS finance_sync_runs (
    id BIGSERIAL PRIMARY KEY,
    connector_id UUID REFERENCES connectors(id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'success', 'error')),
    accounts_synced INT DEFAULT 0,
    holdings_upserted INT DEFAULT 0,
    transactions_fetched INT DEFAULT 0,
    error_message TEXT,
    details JSONB
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_finance_holdings_date ON finance_holdings(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_finance_holdings_symbol ON finance_holdings(symbol);
CREATE INDEX IF NOT EXISTS idx_finance_holdings_account ON finance_holdings(account_id);
CREATE INDEX IF NOT EXISTS idx_finance_balances_date ON finance_balances(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_finance_txn_date ON finance_transactions(trade_date);
CREATE INDEX IF NOT EXISTS idx_finance_email_received ON finance_email_events(received_at);
CREATE INDEX IF NOT EXISTS idx_finance_sync_started ON finance_sync_runs(started_at);
