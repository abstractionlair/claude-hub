-- Phase 5: Connector Interface (R7)
-- Adds connector registration and content indexing tables.

-- Registered data source connectors (R7)
CREATE TABLE IF NOT EXISTS connectors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    connector_type TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'indexing', 'error', 'disabled')),
    last_indexed TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Content indexed by connectors (R7.3, R7.4)
CREATE TABLE IF NOT EXISTS connector_index (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connector_id UUID NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
    source_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    title TEXT,
    content_preview TEXT,
    embedding vector(768),
    embedding_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (embedding_status IN ('pending', 'complete', 'failed')),
    retry_count INT NOT NULL DEFAULT 0,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(connector_id, source_path)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_connector_index_connector ON connector_index(connector_id);
CREATE INDEX IF NOT EXISTS idx_connector_index_embedding ON connector_index
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Migration version recorded by the migration runner in database.py
