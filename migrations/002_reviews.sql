-- Phase 2: Multi-Model Review System
-- Creates review and synthesis tables on the artifact_data tablespace

-- Individual model reviews (R2.1)
CREATE TABLE reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL,
    artifact_id UUID REFERENCES artifacts(id) ON DELETE CASCADE,
    review_artifact_id UUID REFERENCES artifacts(id),
    raw_content TEXT,
    model TEXT NOT NULL,
    prompt TEXT NOT NULL,
    findings JSONB NOT NULL DEFAULT '[]',
    clean_room BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'complete', 'failed', 'timeout')),
    invocation_mode TEXT NOT NULL DEFAULT 'agentic',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) TABLESPACE artifact_data;

-- Synthesized review results (R2.2)
CREATE TABLE review_syntheses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL,
    artifact_id UUID REFERENCES artifacts(id) ON DELETE CASCADE,
    synthesis_artifact_id UUID REFERENCES artifacts(id),
    review_ids UUID[] NOT NULL,
    consensus JSONB NOT NULL DEFAULT '[]',
    unique_findings JSONB NOT NULL DEFAULT '{}',
    contradictions JSONB NOT NULL DEFAULT '[]',
    models_requested TEXT[] NOT NULL,
    models_responded TEXT[] NOT NULL,
    review_modes JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(job_id)
) TABLESPACE artifact_data;

-- Indexes
CREATE INDEX idx_reviews_artifact ON reviews(artifact_id);
CREATE INDEX idx_reviews_job_id ON reviews(job_id);
CREATE INDEX idx_reviews_status ON reviews(status)
    WHERE status IN ('pending', 'running');
CREATE INDEX idx_review_syntheses_job_id ON review_syntheses(job_id);
