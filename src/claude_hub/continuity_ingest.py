"""Bridge between window-file continuity and the artifact store.

Provides async functions to ingest window files as artifacts and search
across them semantically. Keeps continuity.py dependency-free (no asyncpg/
Postgres requirement) by living in a separate module.

Usage as CLI (via continuity.py subcommands):
    python3 -m claude_hub.continuity ingest --file <path>
    python3 -m claude_hub.continuity ingest-all [--harness <name>]
    python3 -m claude_hub.continuity search --topic "..." [--limit N]
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import asyncpg

from claude_hub.artifact_store import (
    search_artifacts,
    store_artifact,
    update_artifact,
)
from claude_hub.continuity import _parse_frontmatter, _windows_dir

logger = logging.getLogger(__name__)

ARTIFACT_TYPE = "window"
DEFAULT_TAGS = ["continuity", "window"]


async def ingest_window(pool: asyncpg.Pool, window_path: Path) -> dict:
    """Ingest a single window file into the artifact store.

    Reads the file, extracts frontmatter metadata, and stores it as an
    artifact with type "window". Uses source_ref for dedup — if an artifact
    with the same source_ref already exists, updates it instead.

    Args:
        pool: asyncpg connection pool.
        window_path: Path to the window file.

    Returns:
        Dict with artifact_id, version, embedding_status, action ("created"/"updated"/"skipped").
    """
    if not window_path.exists():
        return {"error": f"File not found: {window_path}"}

    raw_content = window_path.read_text(encoding="utf-8")
    if not raw_content.strip():
        return {"error": f"Empty file: {window_path}"}

    metadata_fm, body = _parse_frontmatter(raw_content)

    # Use body (without frontmatter) as artifact content for better
    # embeddings and search previews
    content = body.strip() if body.strip() else raw_content

    # Build a stable source_ref from the relative path
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path.cwd()))
    try:
        source_ref = str(window_path.resolve().relative_to(project_dir.resolve()))
    except ValueError:
        source_ref = str(window_path)

    # Check if an artifact with this source_ref already exists
    existing = await _find_by_source_ref(pool, source_ref)

    artifact_metadata = {
        "session_id": metadata_fm.get("session_id"),
        "harness": metadata_fm.get("harness"),
        "created": metadata_fm.get("created"),
        "updated": metadata_fm.get("updated"),
        "finalized": metadata_fm.get("finalized"),
        "parent": metadata_fm.get("parent"),
        "window_file": source_ref,
        "role": metadata_fm.get("role"),
        "projects": metadata_fm.get("projects"),
    }

    tags = list(DEFAULT_TAGS)
    harness = metadata_fm.get("harness")
    if harness and harness not in tags:
        tags.append(str(harness))

    # Preserve workstream, component, and service as prefixed tags
    # so they're queryable via artifact_search
    for tag_field in ("workstream", "component", "service"):
        value = metadata_fm.get(tag_field)
        if value and str(value).strip():
            tags.append(f"{tag_field}:{value}")

    if existing:
        # Update if content changed
        from claude_hub.artifact_store import compute_content_hash

        if compute_content_hash(content) == existing["content_hash"]:
            return {
                "artifact_id": existing["id"],
                "version": existing["version"],
                "embedding_status": "unchanged",
                "action": "skipped",
            }

        result = await update_artifact(
            pool,
            artifact_id=existing["id"],
            content=content,
            metadata=artifact_metadata,
        )
        if result:
            result["action"] = "updated"
            return result
        return {"error": f"Failed to update artifact {existing['id']}"}

    # Create new artifact
    result = await store_artifact(
        pool,
        content=content,
        artifact_type=ARTIFACT_TYPE,
        tags=tags,
        source_ref=source_ref,
        metadata=artifact_metadata,
    )
    result["action"] = "created"
    return result


async def ingest_all_windows(
    pool: asyncpg.Pool,
    harness: str = "claude-code",
) -> dict:
    """Bulk ingest all window files for a harness.

    Scans the windows directory and ingests each .md file.
    Idempotent — skips files whose content hasn't changed.

    Returns:
        Dict with counts: created, updated, skipped, errors.
    """
    directory = _windows_dir(harness)
    result = {"created": 0, "updated": 0, "skipped": 0, "errors": 0, "details": []}

    if not directory.exists():
        return result

    for md_file in sorted(directory.glob("*.md")):
        try:
            r = await ingest_window(pool, md_file)
            action = r.get("action", "error")
            if action in ("created", "updated", "skipped"):
                result[action] += 1
                result["details"].append(f"{action}: {md_file.name}")
            else:
                result["errors"] += 1
                result["details"].append(f"error: {md_file.name}: {r.get('error', 'unknown')}")
        except Exception as e:
            result["errors"] += 1
            result["details"].append(f"error: {md_file.name}: {e}")

    return result


async def search_windows(
    pool: asyncpg.Pool,
    topic: str,
    limit: int = 5,
) -> list[dict]:
    """Semantic search across window artifacts.

    Args:
        pool: asyncpg connection pool.
        topic: Natural-language search query.
        limit: Maximum results.

    Returns:
        List of search result dicts (artifact_id, content_preview, score, etc.).
    """
    return await search_artifacts(
        pool,
        query=topic,
        artifact_type=ARTIFACT_TYPE,
        limit=limit,
    )


async def get_semantic_context(
    pool: asyncpg.Pool,
    topic: str,
    limit: int = 3,
) -> str:
    """Get formatted semantic context for SessionStart hook injection.

    Searches for topic-relevant past windows and formats them as a
    concise string suitable for systemMessage.

    Args:
        pool: asyncpg connection pool.
        topic: Search topic (extracted from current window or project context).
        limit: Maximum number of past windows to include.

    Returns:
        Formatted context string, or empty string if no results.
    """
    results = await search_windows(pool, topic, limit=limit)

    if not results:
        return ""

    lines = ["--- Related past sessions ---"]
    for r in results:
        score = r.get("score", 0)
        preview = r.get("content_preview", "")
        # Strip frontmatter from preview if present
        if preview.startswith("---"):
            end = preview.find("\n---\n", 3)
            if end != -1:
                preview = preview[end + 5:]
        preview = preview.replace("\n", " ").strip()[:150]
        created = r.get("created_at", "unknown")[:10]
        lines.append(f"[{score:.2f}] {created}: {preview}")

    return "\n".join(lines)


async def _find_by_source_ref(pool: asyncpg.Pool, source_ref: str) -> dict | None:
    """Find an existing artifact by source_ref.

    Returns dict with id, content_hash, version, or None.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT a.id, a.content_hash,
                   (SELECT MAX(v.version) FROM artifact_versions v WHERE v.artifact_id = a.id) AS version
            FROM artifacts a
            WHERE a.source_ref = $1 AND a.archived = false
            LIMIT 1
            """,
            source_ref,
        )
    if row:
        return {"id": str(row["id"]), "content_hash": row["content_hash"], "version": row["version"]}
    return None
