-- Phase 1: Foundation + Artifact Store
-- Creates core artifact tables on the artifact_data tablespace

-- Enable pgvector extension (required for vector(768) type)
CREATE EXTENSION IF NOT EXISTS vector;

-- Migration tracking
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Core artifact storage (R1.1)
CREATE TABLE artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    tags TEXT[],
    source_ref TEXT,
    derives_from UUID[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sensitive BOOLEAN NOT NULL DEFAULT FALSE,
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}'
) TABLESPACE artifact_data;

-- Immutable version chain (R1.1)
CREATE TABLE artifact_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(artifact_id, version)
) TABLESPACE artifact_data;

-- Vector storage (R1.2)
CREATE TABLE artifact_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    embedding vector(768),
    model TEXT NOT NULL DEFAULT 'models/gemini-embedding-001',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'complete', 'failed')),
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(artifact_id)
) TABLESPACE artifact_data;

-- Outcome tracking (R5)
CREATE TABLE artifact_outcomes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    rating TEXT NOT NULL
        CHECK (rating IN ('SUCCEEDED', 'PARTIAL_SUCCESS', 'PARTIAL_FAILURE', 'FAILED')),
    reasoning TEXT,
    rated_by TEXT NOT NULL DEFAULT 'human',
    rated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) TABLESPACE artifact_data;

-- Indexes
CREATE INDEX idx_artifacts_type ON artifacts(artifact_type);
CREATE INDEX idx_artifacts_created_at ON artifacts(created_at);
CREATE INDEX idx_artifacts_archived ON artifacts(archived);
CREATE INDEX idx_artifacts_content_hash ON artifacts(content_hash);
CREATE INDEX idx_artifacts_tags ON artifacts USING GIN(tags);
CREATE INDEX idx_artifacts_metadata ON artifacts USING GIN(metadata);
CREATE INDEX idx_artifacts_derives_from ON artifacts USING GIN(derives_from);
CREATE UNIQUE INDEX idx_artifacts_dedup ON artifacts(content_hash, COALESCE(source_ref, ''))
    WHERE archived = FALSE;

CREATE INDEX idx_artifact_embeddings_vector ON artifact_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_artifact_embeddings_pending ON artifact_embeddings(status)
    WHERE status IN ('pending', 'failed');

CREATE INDEX idx_artifact_outcomes_artifact ON artifact_outcomes(artifact_id);
