-- Phase 4: Knowledge Quality (R5)
-- Adds feedback tracking, review grading, and quality-weighted retrieval columns.

-- New columns on artifacts for quality-weighted scoring
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS confidence TEXT DEFAULT 'MEDIUM'
    CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW', 'SUPERSEDED'));
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS utility_score REAL DEFAULT 0.5;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS last_retrieved TIMESTAMPTZ;

-- Agent-driven usage feedback (R5.1)
CREATE TABLE IF NOT EXISTS artifact_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    useful BOOLEAN NOT NULL,
    note TEXT,
    agent_id TEXT NOT NULL DEFAULT 'main',
    content_version INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) TABLESPACE artifact_data;

-- Review quality grading (R5.5) — per-model signal
CREATE TABLE IF NOT EXISTS review_grades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL,
    model_name TEXT NOT NULL,
    review_type TEXT NOT NULL,
    grade TEXT NOT NULL CHECK (grade IN ('EXCELLENT', 'ADEQUATE', 'INADEQUATE', 'HARMFUL')),
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
) TABLESPACE artifact_data;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_artifact_feedback_artifact ON artifact_feedback(artifact_id);
CREATE INDEX IF NOT EXISTS idx_review_grades_model ON review_grades(model_name, review_type);

-- Migration version recorded by the migration runner in database.py
