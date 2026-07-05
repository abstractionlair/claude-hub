"""Gemini embedding client and async retry loop for artifact embeddings.

Wraps the google-genai SDK's synchronous embed_content() call in asyncio.to_thread()
and provides a background retry loop for pending/failed embeddings stored in the
artifact_embeddings table.
"""

import asyncio
import logging
import os
from typing import Optional

import asyncpg
from google import genai

logger = logging.getLogger(__name__)

_configured: bool = False
_client: Optional[genai.Client] = None

_MODEL = "gemini-embedding-2-preview"
_EMBEDDING_DIM = 768

# Retry loop constants
_POLL_INTERVAL_SECONDS = 60
_MAX_RETRY_COUNT = 5
_SWEEP_BATCH_SIZE = 10

# Batch embed constants
_BATCH_SIZE = 20
_BATCH_DELAY_SECONDS = 0.1


def configure_gemini() -> None:
    """Configure the Gemini API client with an API key env var.

    Checks GEMINI_EMBEDDING_API_KEY first (preferred, avoids conflict with
    Gemini CLI's OAuth auth), then falls back to GEMINI_API_KEY for
    backwards compatibility.

    Should be called once at startup.  If no key is found, embedding
    generation is disabled for the lifetime of the process (a warning is
    logged and the module-level ``_configured`` flag stays ``False``).
    """
    global _configured, _client

    api_key = (os.environ.get("GEMINI_EMBEDDING_API_KEY")
               or os.environ.get("GEMINI_API_KEY"))
    if not api_key:
        logger.warning(
            "GEMINI_EMBEDDING_API_KEY is not set — embedding generation is disabled"
        )
        _configured = False
        _client = None
        return

    _client = genai.Client(api_key=api_key)
    _configured = True
    logger.info("Gemini embedding client configured (model=%s)", _MODEL)


async def generate_embedding(text: str) -> list[float]:
    """Generate a document embedding for *text*.

    Uses ``task_type="retrieval_document"`` so the resulting vector is
    optimised for being *searched* rather than for searching.

    Returns:
        A list of 768 floats.

    Raises:
        RuntimeError: If :func:`configure_gemini` was not called or the API
            key was missing.
        google.api_core.exceptions.GoogleAPIError: On transient/permanent API
            errors (callers should handle retries).
    """
    if not _configured or _client is None:
        raise RuntimeError(
            "Gemini is not configured — call configure_gemini() first"
        )

    result = await asyncio.to_thread(
        _client.models.embed_content,
        model=_MODEL,
        contents=text,
        config={
            "task_type": "RETRIEVAL_DOCUMENT",
            "output_dimensionality": _EMBEDDING_DIM,
        },
    )
    return result.embeddings[0].values


async def generate_query_embedding(text: str) -> list[float]:
    """Generate a query embedding for *text*.

    Uses ``task_type="RETRIEVAL_QUERY"`` so the resulting vector is
    optimised for cosine-similarity search against document embeddings.

    Returns:
        A list of 768 floats.

    Raises:
        RuntimeError: If :func:`configure_gemini` was not called or the API
            key was missing.
        google.api_core.exceptions.GoogleAPIError: On transient/permanent API
            errors.
    """
    if not _configured or _client is None:
        raise RuntimeError(
            "Gemini is not configured — call configure_gemini() first"
        )

    result = await asyncio.to_thread(
        _client.models.embed_content,
        model=_MODEL,
        contents=text,
        config={
            "task_type": "RETRIEVAL_QUERY",
            "output_dimensionality": _EMBEDDING_DIM,
        },
    )
    return result.embeddings[0].values


async def embed_artifact(
    pool: asyncpg.Pool,
    artifact_id: str,
    content: str,
    sensitive: bool,
) -> None:
    """Generate an embedding for a single artifact and persist it.

    If *sensitive* is ``True`` the call is a no-op (sensitive content must
    never be sent to an external embedding API).

    On success the ``artifact_embeddings`` row is updated with the vector
    and ``status='complete'``.  On failure the row is updated with
    ``status='failed'``, the error message, and an incremented
    ``retry_count``.

    Args:
        pool: asyncpg connection pool.
        artifact_id: UUID of the artifact (string form).
        content: The text to embed.
        sensitive: Whether the artifact contains sensitive data.
    """
    if sensitive:
        logger.debug(
            "Skipping embedding for sensitive artifact %s", artifact_id
        )
        return

    if not _configured:
        logger.debug(
            "Skipping embedding for artifact %s — Gemini is not configured",
            artifact_id,
        )
        return

    try:
        embedding = await generate_embedding(content)

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE artifact_embeddings
                SET embedding = $1,
                    model = $2,
                    status = 'complete',
                    error_message = NULL,
                    updated_at = NOW()
                WHERE artifact_id = $3::uuid
                """,
                embedding,
                _MODEL,
                artifact_id,
            )
        logger.debug("Embedded artifact %s successfully", artifact_id)

    except Exception as exc:
        logger.warning(
            "Failed to embed artifact %s: %s", artifact_id, exc
        )
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE artifact_embeddings
                SET status = 'failed',
                    error_message = $1,
                    retry_count = retry_count + 1,
                    updated_at = NOW()
                WHERE artifact_id = $2::uuid
                """,
                str(exc),
                artifact_id,
            )


async def _sweep_pending(pool: asyncpg.Pool) -> int:
    """Run one sweep of pending/failed embeddings.

    Fetches up to ``_SWEEP_BATCH_SIZE`` rows that are eligible for
    (re-)embedding and processes them one at a time.  Sensitive artifacts
    are excluded at the query level.

    Returns:
        The number of rows successfully embedded in this sweep.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ae.artifact_id, a.content
            FROM artifact_embeddings ae
            JOIN artifacts a ON a.id = ae.artifact_id
            WHERE ae.status IN ('pending', 'failed')
              AND ae.retry_count < $1
              AND a.sensitive = FALSE
            ORDER BY ae.updated_at ASC
            LIMIT $2
            """,
            _MAX_RETRY_COUNT,
            _SWEEP_BATCH_SIZE,
        )

    if not rows:
        return 0

    success_count = 0
    for row in rows:
        artifact_id = str(row["artifact_id"])
        content: str = row["content"]
        try:
            await embed_artifact(
                pool,
                artifact_id,
                content,
                sensitive=False,  # Already filtered by query
            )
            success_count += 1
        except Exception:
            # embed_artifact already handles its own error logging and
            # row update, but guard against truly unexpected errors here.
            logger.exception(
                "Unexpected error in sweep for artifact %s", artifact_id
            )

    return success_count


async def sweep_connector_index(pool: asyncpg.Pool) -> int:
    """Sweep connector_index rows with pending/failed embedding status.

    Fetches up to ``_SWEEP_BATCH_SIZE`` rows from the ``connector_index``
    table that need embedding.  Reads the full file content from disk
    (via the connector's ``root_path`` + ``source_path``) so that retry
    embeddings are the same quality as initial ones.  Falls back to
    ``content_preview`` if the file cannot be read.

    Returns:
        The number of rows successfully embedded in this sweep.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ci.id, ci.content_preview, ci.source_path,
                   c.config
            FROM connector_index ci
            JOIN connectors c ON c.id = ci.connector_id
            WHERE ci.embedding_status IN ('pending', 'failed')
              AND ci.retry_count < $1
            ORDER BY ci.indexed_at ASC
            LIMIT $2
            """,
            _MAX_RETRY_COUNT,
            _SWEEP_BATCH_SIZE,
        )

    if not rows:
        return 0

    success_count = 0
    for row in rows:
        row_id = str(row["id"])
        # Try to read full file content from disk for better embedding quality
        content = None
        try:
            import json
            config = row["config"] if isinstance(row["config"], dict) else json.loads(row["config"])
            root_path = config.get("root_path")
            if root_path and row["source_path"]:
                from pathlib import Path
                file_path = (Path(root_path) / row["source_path"]).resolve()
                root_resolved = Path(root_path).resolve()
                if file_path.is_relative_to(root_resolved) and file_path.is_file():
                    content = file_path.read_text(encoding="utf-8")
        except Exception:
            pass  # Fall back to content_preview
        if content is None:
            content = row["content_preview"] or ""
        if not content.strip():
            # No content to embed — mark failed and increment retry_count
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE connector_index
                    SET embedding_status = 'failed',
                        retry_count = retry_count + 1
                    WHERE id = $1::uuid
                    """,
                    row_id,
                )
            continue

        try:
            embedding = await generate_embedding(content)
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE connector_index
                    SET embedding = $1,
                        embedding_status = 'complete'
                    WHERE id = $2::uuid
                    """,
                    embedding,
                    row_id,
                )
            success_count += 1
        except Exception as exc:
            logger.warning(
                "Failed to embed connector_index row %s: %s", row_id, exc
            )
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE connector_index
                    SET embedding_status = 'failed',
                        retry_count = retry_count + 1
                    WHERE id = $1::uuid
                    """,
                    row_id,
                )

    return success_count


async def embedding_retry_loop(pool: asyncpg.Pool) -> None:
    """Long-running asyncio task that retries pending/failed embeddings.

    Behaviour:
    - On startup: immediate sweep of all eligible rows.
    - Then polls every ``_POLL_INTERVAL_SECONDS`` (60 s).
    - Handles ``asyncio.CancelledError`` for graceful shutdown.

    Intended usage::

        task = asyncio.create_task(embedding_retry_loop(pool))
        # ... at shutdown ...
        task.cancel()
        await task
    """
    if not _configured:
        logger.info(
            "Embedding retry loop not starting — Gemini is not configured"
        )
        return

    logger.info("Embedding retry loop started")

    try:
        # Immediate sweep on startup
        count = await _sweep_pending(pool)
        if count:
            logger.info(
                "Embedding startup sweep: embedded %d artifacts", count
            )
        ci_count = await sweep_connector_index(pool)
        if ci_count:
            logger.info(
                "Connector index startup sweep: embedded %d entries", ci_count
            )

        while True:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            try:
                count = await _sweep_pending(pool)
                if count:
                    logger.info(
                        "Embedding sweep: embedded %d artifacts", count
                    )
                ci_count = await sweep_connector_index(pool)
                if ci_count:
                    logger.info(
                        "Connector index sweep: embedded %d entries", ci_count
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error during embedding sweep")

    except asyncio.CancelledError:
        logger.info("Embedding retry loop cancelled — shutting down")


async def batch_embed(
    artifact_ids: list[str],
    pool: asyncpg.Pool,
) -> dict[str, int]:
    """Embed a list of artifacts in batches for bulk ingestion.

    Processes artifacts in batches of ``_BATCH_SIZE`` (20) with a
    ``_BATCH_DELAY_SECONDS`` (100 ms) pause between batches to avoid
    hitting rate limits.

    Sensitive artifacts are skipped.  Each artifact is processed
    independently so one failure does not stop the batch.

    Args:
        artifact_ids: List of artifact UUID strings to embed.
        pool: asyncpg connection pool.

    Returns:
        A dict with keys ``"succeeded"`` and ``"failed"`` containing counts.
    """
    if not _configured:
        logger.warning(
            "batch_embed called but Gemini is not configured — skipping"
        )
        return {"succeeded": 0, "failed": len(artifact_ids)}

    succeeded = 0
    failed = 0

    for batch_start in range(0, len(artifact_ids), _BATCH_SIZE):
        batch = artifact_ids[batch_start : batch_start + _BATCH_SIZE]

        # Fetch content and sensitivity for the batch in one query
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, content, sensitive
                FROM artifacts
                WHERE id = ANY($1::uuid[])
                """,
                batch,
            )

        row_map = {str(row["id"]): row for row in rows}

        for aid in batch:
            row = row_map.get(aid)
            if row is None:
                logger.warning(
                    "batch_embed: artifact %s not found, skipping", aid
                )
                failed += 1
                continue

            try:
                await embed_artifact(
                    pool,
                    aid,
                    row["content"],
                    sensitive=row["sensitive"],
                )
                if not row["sensitive"]:
                    succeeded += 1
                # Sensitive artifacts are silently skipped (not counted as failed)
            except Exception:
                logger.exception(
                    "batch_embed: unexpected error for artifact %s", aid
                )
                failed += 1

        # Delay between batches (skip after the last batch)
        if batch_start + _BATCH_SIZE < len(artifact_ids):
            await asyncio.sleep(_BATCH_DELAY_SECONDS)

    logger.info(
        "batch_embed complete: %d succeeded, %d failed out of %d requested",
        succeeded,
        failed,
        len(artifact_ids),
    )
    return {"succeeded": succeeded, "failed": failed}
