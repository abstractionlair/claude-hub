-- Phase 2.1: Model-forward principle — deprecate structured parsing columns
-- These columns remain for backward compatibility but are no longer populated.
-- raw_content (reviews) and synthesis_artifact_id (review_syntheses) are canonical.

COMMENT ON COLUMN reviews.findings IS 'DEPRECATED: raw_content is the canonical source. Synthesis reads raw output directly.';
COMMENT ON COLUMN review_syntheses.consensus IS 'DEPRECATED: synthesis stored as prose artifact via synthesis_artifact_id.';
COMMENT ON COLUMN review_syntheses.unique_findings IS 'DEPRECATED: synthesis stored as prose artifact via synthesis_artifact_id.';
COMMENT ON COLUMN review_syntheses.contradictions IS 'DEPRECATED: synthesis stored as prose artifact via synthesis_artifact_id.';

-- Make findings nullable (no longer populated)
ALTER TABLE reviews ALTER COLUMN findings DROP NOT NULL;
ALTER TABLE reviews ALTER COLUMN findings DROP DEFAULT;

-- Drop files_accessed column (model-forward: audit trail lives in review prose)
ALTER TABLE reviews DROP COLUMN IF EXISTS files_accessed;
