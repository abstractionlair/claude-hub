Loaded cached credentials.
(node:985392) MaxListenersExceededWarning: Possible EventTarget memory leak detected. 11 abort listeners added to [AbortSignal]. MaxListeners is 10. Use events.setMaxListeners() to increase limit
(Use `node --trace-warnings ...` to show where the warning was created)
Here is a structured review of Draft 2 of the Personal AI Infrastructure technical specification.

## Overall Assessment
The specification is highly detailed, well-structured, and clearly maps the original requirements into a realistic, phased implementation plan. The decision to use FastAPI, pgvector, and a direct HNSW index fits perfectly within the memory constraints of a 4GB VPS.

However, **the spec needs one more revision before implementation.** There are critical flaws regarding how model CLIs are invoked (creating shell injection vulnerabilities) and how the connector embeddings are processed (they are currently stranded without a background worker). Additionally, several API endpoints required by the bash hooks are missing from the server spec.

---

## 🛑 Critical Findings
*These issues block implementation and require redesign.*

### 1. Shell Injection Vulnerability in Review Invocation
* **Location**: Section 6 (Review Model Registry)
* **Issue**: The `invoke` templates use `"claude -p \"$(cat {prompt_file})\" --input-file {file}"`. The spec claims writing to a temp file avoids shell escaping issues, but interpolating `$(cat ...)` inside double quotes in a shell command string does *not* protect against shell injection. If the prompt file contains a double quote (`"`), it will prematurely terminate the quoted string, causing bash syntax errors or potentially executing arbitrary shell commands.
* **Suggestion**: Avoid `shell=True` in Python. Use `subprocess.run()` with an array of arguments (e.g., `["claude", "-p", prompt_content, "--input-file", file_path]`). If the CLI wrappers require shell strings, use environment variables to pass the prompt securely (e.g., `PROMPT=$(cat {prompt_file}) opencode ...`), or if the CLI supports it, pass the prompt file path directly.

### 2. Connector Index Embeddings are Stranded
* **Location**: Section 2.5 (`connector_index`), Section 3.3 (Retry Queue), Section 5.3 (`FilesystemConnector`)
* **Issue**: `FilesystemConnector.index()` writes to `connector_index` with `embedding_status='pending'` and relies on "queued embedding generation." However, the embedding pipeline in Section 3 (both the async task and the retry loop) is hardcoded exclusively to the `artifacts` and `artifact_embeddings` tables. There is no worker designed to process pending embeddings in the `connector_index` table.
* **Suggestion**: Expand `embedding_retry_loop` to also sweep the `connector_index` table for pending items, or refactor vector storage into a polymorphic `embeddings_queue` table so the background worker can handle vectors for any entity type.

---

## ⚠️ Important Findings
*These are significant gaps or logical contradictions that will cause bugs.*

### 3. Missing API Endpoints for Bash Hooks
* **Location**: Section 7 (Hook Integration) vs Section 4 (API Surface)
* **Issue**: The bash scripts in Section 7 rely on three HTTP endpoints: `/log_unsummarized_count`, `/log_recent`, and `/workflow_active_items`. None of these endpoints are defined in the API Surface (Section 4) or the Module Architecture (Section 8). 
* **Suggestion**: Add these endpoints explicitly to the server API specification in Sections 4.3 and 4.6. 

### 4. Review Job ID Conflation
* **Location**: Section 4.2 (`review_dispatch` and `review_status`)
* **Issue**: `review_dispatch` states: "The `job_id` is the `artifact_id` of the reviewed artifact." If a user updates an artifact and runs a second review on it later, the new job will have the exact same `job_id` as the old job. `review_status` will have no way to distinguish the progress of the new multi-model review from the previously completed one.
* **Suggestion**: Generate a unique UUID for the review *run* (e.g., the `id` of the newly created `review_syntheses` row) and return that as the `job_id`.

### 5. Missing Mechanism for Pattern Similarity
* **Location**: Section 4.5 (`pattern_detect`) & Section 2.6 (`patterns` table)
* **Issue**: The spec states `pattern_detect` will "check if it already exists in the patterns table (by description similarity)." However, the `patterns` table lacks an `embedding` column, and there is no vector index. Passing all historically detected patterns to an LLM via text to check for similarity will eventually blow out the context window.
* **Suggestion**: Add an `embedding vector(768)` column to the `patterns` table and use pgvector to perform the similarity check before creating a new candidate pattern.

### 6. Connector Registry Startup Loading
* **Location**: Section 4.7 (`connector_register`) & Section 8.7 (Architecture)
* **Issue**: When a connector is registered, it saves to the `connectors` DB table. However, there is no documented mechanism for loading these stored connectors back into the in-memory `ConnectorRegistry` when the FastAPI server reboots. Active connectors would silently disappear from federated searches after a restart.
* **Suggestion**: Add an initialization step to the FastAPI lifespan handler in `server.py` that queries the `connectors` table and instantiates all `status = 'active'` connectors.

---

## 🔍 Minor Findings
*Edge cases, optimizations, and clarifications.*

### 7. Native asyncpg pgvector Support
* **Location**: Section 11 (Open Decisions)
* **Issue**: The spec mentions: "asyncpg requires manual vector serialization, while psycopg3 handles it natively."
* **Suggestion**: This is outdated. The `pgvector` python package natively supports asyncpg (`import pgvector.asyncpg; await pgvector.asyncpg.register_vector(pool)`). You can safely use `asyncpg` without manual serialization.

### 8. Deduplication Ignores New Metadata
* **Location**: Section 4.1 (`artifact_store`)
* **Issue**: The dedup logic returns the existing artifact ID if a content hash matches. If a user uploads duplicate content but passes *new* tags or metadata, those tags are silently discarded.
* **Suggestion**: Specify whether deduplication should perform a JSONB merge of new metadata/tags into the existing artifact, or explicitly document that incoming metadata is ignored on duplicate content.

### 9. Missing Implementation Artifact Column
* **Location**: Section 2.4 (`workflow_projects`)
* **Issue**: The table specifically tracks `vision_artifact_id`, `requirements_artifact_id`, and `spec_artifact_id`, but omits a column for the final deliverable.
* **Suggestion**: Add an `implementation_artifact_id UUID REFERENCES artifacts(id)` column to maintain structural symmetry for the final stage of the workflow.
