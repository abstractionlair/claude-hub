"""Artifact CRUD and semantic search operations.

Provides module-level async functions for storing, retrieving, updating,
searching, and exporting artifacts.  All functions take an asyncpg pool as
their first argument and use parameterized queries with positional ``$N``
placeholders.

Depends on:
    - ``database.py`` -- ``get_pool()`` for asyncpg pool access
    - ``embedding.py`` -- ``embed_artifact()``, ``generate_query_embedding()``, ``batch_embed()``
    - ``artifact_models.py`` -- Pydantic response models
"""

import asyncio
import hashlib
import json
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

from claude_hub.embedding import batch_embed, embed_artifact, generate_query_embedding

logger = logging.getLogger(__name__)


class ArtifactNotFoundError(Exception):
    """Raised when an artifact is not found by ID."""
    pass


_BACKUP_DIR = Path(
    os.environ.get(
        "ARTIFACT_BACKUP_DIR",
        "/mnt/HC_Volume_104288266/data/backups/artifacts",
    )
)

# Quality-weighted scoring boosts are hardcoded in the SQL CTE within
# search_artifacts() for query-planner efficiency.
# Confidence boosts: HIGH +0.1, MEDIUM 0, LOW -0.1, SUPERSEDED -0.2
# Utility boost: (utility_score - 0.5) * 0.4  (range: -0.2 to +0.2)
# Age decay: max(-0.1 * years_old, -0.2)  (caps at -0.2)


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of raw UTF-8 bytes, hex-encoded.

    Args:
        content: The text content to hash.

    Returns:
        A 64-character lowercase hex string.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_uuid(s: str) -> bool:
    """Return True if *s* is a valid UUID string."""
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError):
        return False


async def store_artifact(
    pool: asyncpg.Pool,
    content: str,
    artifact_type: str,
    tags: list[str] | None = None,
    source_ref: str | None = None,
    derives_from: list[str] | None = None,
    sensitive: bool = False,
    metadata: dict | None = None,
    confidence: str | None = None,
) -> dict:
    """Store a new artifact with its first version and a pending embedding row.

    Inserts into ``artifacts``, ``artifact_versions`` (version 1), and
    ``artifact_embeddings`` (status ``'pending'``) inside a single transaction.

    If the dedup index (``content_hash`` + ``source_ref``) catches a duplicate,
    the existing artifact's ID is returned instead.

    After commit, a fire-and-forget embedding task is spawned unless
    *sensitive* is ``True``.

    Args:
        pool: asyncpg connection pool.
        content: Artifact text content.  Must not be empty.
        artifact_type: Classification label (e.g. ``'learning'``, ``'plan'``).
        tags: Optional list of string tags.
        source_ref: Optional provenance reference (session ID, file path, etc.).
        derives_from: Optional list of parent artifact UUID strings.
        sensitive: If ``True``, skip embedding generation.
        metadata: Optional arbitrary key-value metadata.
        confidence: Optional confidence level (``'HIGH'``, ``'MEDIUM'``, ``'LOW'``).
            Defaults to ``'MEDIUM'`` if not specified (per R5.2).

    Returns:
        A dict with keys ``artifact_id``, ``version``, and ``embedding_status``.

    Raises:
        ValueError: If *content* is empty or *derives_from* contains invalid UUIDs.
    """
    if not content:
        raise ValueError("Artifact content must not be empty")

    if derives_from:
        for df_id in derives_from:
            if not _validate_uuid(df_id):
                raise ValueError(f"Invalid UUID in derives_from: {df_id}")

    _VALID_CONFIDENCE_LEVELS = {"HIGH", "MEDIUM", "LOW"}
    if confidence is not None and confidence not in _VALID_CONFIDENCE_LEVELS:
        raise ValueError(
            f"Invalid confidence: {confidence!r}. "
            f"Must be one of {_VALID_CONFIDENCE_LEVELS}"
        )
    confidence_val = confidence or "MEDIUM"

    content_hash = compute_content_hash(content)
    tags_val = tags or []
    derives_from_uuids = (
        [uuid.UUID(d) for d in derives_from] if derives_from else []
    )
    metadata_val = json.dumps(metadata or {})

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Insert the artifact row
                artifact_id = await conn.fetchval(
                    """
                    INSERT INTO artifacts (
                        content, content_hash, artifact_type, tags,
                        source_ref, derives_from, sensitive, metadata,
                        confidence
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
                    RETURNING id
                    """,
                    content,
                    content_hash,
                    artifact_type,
                    tags_val,
                    source_ref,
                    derives_from_uuids,
                    sensitive,
                    metadata_val,
                    confidence_val,
                )

                artifact_id_str = str(artifact_id)

                # Insert version 1
                await conn.execute(
                    """
                    INSERT INTO artifact_versions (
                        artifact_id, version, content, content_hash
                    )
                    VALUES ($1, 1, $2, $3)
                    """,
                    artifact_id,
                    content,
                    content_hash,
                )

                # Insert pending embedding row
                await conn.execute(
                    """
                    INSERT INTO artifact_embeddings (artifact_id, status)
                    VALUES ($1, 'pending')
                    """,
                    artifact_id,
                )

        # Fire-and-forget embedding generation
        if not sensitive:
            asyncio.create_task(
                embed_artifact(pool, artifact_id_str, content, sensitive=False)
            )

        logger.info(
            "Stored artifact %s (type=%s, sensitive=%s)",
            artifact_id_str,
            artifact_type,
            sensitive,
        )

        return {
            "artifact_id": artifact_id_str,
            "version": 1,
            "embedding_status": "pending",
        }

    except asyncpg.UniqueViolationError:
        # Dedup index caught a duplicate -- return the existing artifact
        async with pool.acquire() as conn:
            existing_id = await conn.fetchval(
                """
                SELECT id FROM artifacts
                WHERE content_hash = $1
                  AND COALESCE(source_ref, '') = COALESCE($2, '')
                  AND archived = FALSE
                """,
                content_hash,
                source_ref,
            )

        if existing_id is None:
            raise RuntimeError(
                "UniqueViolationError on content_hash but lookup returned no rows; "
                "possible race condition — retry the operation"
            )
        existing_id_str = str(existing_id)
        logger.info(
            "Duplicate artifact detected, returning existing %s",
            existing_id_str,
        )
        return {
            "artifact_id": existing_id_str,
            "version": 1,
            "embedding_status": "existing",
        }


async def get_artifact(
    pool: asyncpg.Pool,
    artifact_id: str,
    include_versions: bool = False,
    include_feedback: bool = True,
    include_outcomes: bool | None = None,
) -> dict | None:
    """Retrieve a single artifact by ID.

    Args:
        pool: asyncpg connection pool.
        artifact_id: UUID string of the artifact.
        include_versions: Whether to include the full version history.
        include_feedback: Whether to include usage feedback records.
        include_outcomes: Deprecated alias for *include_feedback*.  If
            explicitly set, it overrides *include_feedback* for backward
            compatibility.

    Returns:
        A dict representing the artifact, or ``None`` if not found.
    """
    # Backward compatibility: if caller explicitly passes include_outcomes,
    # use that value for include_feedback.
    if include_outcomes is not None:
        include_feedback = include_outcomes

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, content, content_hash, artifact_type, tags,
                   source_ref, derives_from, created_at, sensitive,
                   archived, metadata, confidence, utility_score
            FROM artifacts
            WHERE id = $1::uuid
            """,
            artifact_id,
        )

        if row is None:
            return None

        result = {
            "id": str(row["id"]),
            "content": row["content"],
            "content_hash": row["content_hash"],
            "artifact_type": row["artifact_type"],
            "tags": list(row["tags"]) if row["tags"] else [],
            "source_ref": row["source_ref"],
            "derives_from": (
                [str(d) for d in row["derives_from"]]
                if row["derives_from"]
                else []
            ),
            "created_at": row["created_at"].isoformat(),
            "sensitive": row["sensitive"],
            "archived": row["archived"],
            "metadata": (
                json.loads(row["metadata"])
                if isinstance(row["metadata"], str)
                else dict(row["metadata"])
            ),
            "confidence": row["confidence"],
            "utility_score": float(row["utility_score"]) if row["utility_score"] is not None else None,
        }

        if include_versions:
            version_rows = await conn.fetch(
                """
                SELECT version, content, content_hash, created_at
                FROM artifact_versions
                WHERE artifact_id = $1::uuid
                ORDER BY version ASC
                """,
                artifact_id,
            )
            result["versions"] = [
                {
                    "version": vr["version"],
                    "content": vr["content"],
                    "content_hash": vr["content_hash"],
                    "created_at": vr["created_at"].isoformat(),
                }
                for vr in version_rows
            ]
        else:
            result["versions"] = None

        if include_feedback:
            feedback_rows = await conn.fetch(
                """
                SELECT useful, note, agent_id, content_version, created_at
                FROM artifact_feedback
                WHERE artifact_id = $1::uuid
                ORDER BY created_at DESC
                """,
                artifact_id,
            )
            result["feedback"] = [
                {
                    "useful": frow["useful"],
                    "note": frow["note"],
                    "agent_id": frow["agent_id"],
                    "content_version": frow["content_version"],
                    "created_at": frow["created_at"].isoformat(),
                }
                for frow in feedback_rows
            ]
            # Backward-compatible alias
            result["outcomes"] = None
        else:
            result["feedback"] = None
            result["outcomes"] = None

    return result


async def search_artifacts(
    pool: asyncpg.Pool,
    query: str,
    artifact_type: str | None = None,
    tags: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_archived: bool = False,
    confidence: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Semantic search over artifacts with quality-weighted scoring.

    Generates a query embedding, then searches ``artifact_embeddings`` using
    cosine distance.  The base similarity score is boosted by three quality
    signals via a CTE:

    - **confidence_boost**: HIGH +0.1, MEDIUM 0, LOW -0.1, SUPERSEDED -0.2
    - **utility_boost**: ``(utility_score - 0.5) * 0.4`` (range -0.2 to +0.2)
    - **age_boost**: ``max(-0.1 * years_old, -0.2)`` (caps at -0.2)

    SUPERSEDED artifacts are excluded by default unless *include_archived* is
    True.  After results are returned, ``last_retrieved`` is batch-updated on
    the matching artifact IDs.

    Args:
        pool: asyncpg connection pool.
        query: Natural-language search query.
        artifact_type: Optional filter by artifact type.
        tags: Optional tags filter (AND semantics via ``@>``).
        date_from: Optional ISO 8601 lower bound on ``created_at``.
        date_to: Optional ISO 8601 upper bound on ``created_at``.
        include_archived: Whether to include archived artifacts.
        confidence: Optional minimum confidence filter (e.g. ``'HIGH'``
            excludes MEDIUM/LOW/SUPERSEDED).
        limit: Maximum number of results (default 10).

    Returns:
        A list of dicts matching :class:`ArtifactSearchResult` fields.
    """
    # Confidence levels ordered from highest to lowest for >= filtering
    _CONFIDENCE_LEVELS = ["HIGH", "MEDIUM", "LOW", "SUPERSEDED"]

    try:
        query_embedding = await generate_query_embedding(query)
    except RuntimeError:
        logger.error(
            "Embedding generation failed for query: %s",
            query[:100],
        )
        raise

    # Build dynamic WHERE clauses
    conditions: list[str] = [
        "ae.status = 'complete'",
        "ae.embedding IS NOT NULL",
    ]
    params: list = [query_embedding]  # $1 is the query vector
    param_idx = 2  # next positional param

    if not include_archived:
        conditions.append("a.archived = FALSE")
        # Also exclude SUPERSEDED unless include_archived
        conditions.append("a.confidence != 'SUPERSEDED'")

    if artifact_type is not None:
        conditions.append(f"a.artifact_type = ${param_idx}")
        params.append(artifact_type)
        param_idx += 1

    if tags:
        conditions.append(f"a.tags @> ${param_idx}")
        params.append(tags)
        param_idx += 1

    if date_from is not None:
        conditions.append(f"a.created_at >= ${param_idx}::timestamptz")
        params.append(date_from)
        param_idx += 1

    if date_to is not None:
        conditions.append(f"a.created_at <= ${param_idx}::timestamptz")
        params.append(date_to)
        param_idx += 1

    # Confidence minimum filter -- include only levels at or above the specified level
    if confidence is not None and confidence in _CONFIDENCE_LEVELS:
        allowed = _CONFIDENCE_LEVELS[: _CONFIDENCE_LEVELS.index(confidence) + 1]
        conditions.append(f"a.confidence = ANY(${param_idx})")
        params.append(allowed)
        param_idx += 1

    where_clause = " AND ".join(conditions)

    # Limit param
    limit_param = f"${param_idx}"
    params.append(limit)

    sql = f"""
        WITH scored AS (
            SELECT
                a.id AS artifact_id,
                LEFT(a.content, 200) AS content_preview,
                a.artifact_type,
                a.tags,
                a.created_at,
                a.utility_score,
                a.confidence,
                1 - (ae.embedding <=> $1::vector) AS base_score,
                CASE a.confidence
                    WHEN 'HIGH' THEN 0.1
                    WHEN 'MEDIUM' THEN 0.0
                    WHEN 'LOW' THEN -0.1
                    WHEN 'SUPERSEDED' THEN -0.2
                    ELSE 0.0
                END AS confidence_boost,
                (COALESCE(a.utility_score, 0.5) - 0.5) * 0.4 AS utility_boost,
                GREATEST(
                    -0.1 * EXTRACT(EPOCH FROM (NOW() - a.created_at)) / (365.0 * 86400),
                    -0.2
                ) AS age_boost
            FROM artifact_embeddings ae
            JOIN artifacts a ON a.id = ae.artifact_id
            WHERE {where_clause}
        )
        SELECT *,
               base_score + confidence_boost + utility_boost + age_boost AS final_score
        FROM scored
        ORDER BY final_score DESC
        LIMIT {limit_param}
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    results = [
        {
            "artifact_id": str(row["artifact_id"]),
            "content_preview": row["content_preview"],
            "artifact_type": row["artifact_type"],
            "tags": list(row["tags"]) if row["tags"] else [],
            "score": float(row["final_score"]),
            "utility_score": float(row["utility_score"]) if row["utility_score"] is not None else 0.5,
            "confidence": row["confidence"] or "MEDIUM",
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]

    # Batch update last_retrieved on all returned artifacts
    if results:
        artifact_ids = [uuid.UUID(r["artifact_id"]) for r in results]
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE artifacts SET last_retrieved = NOW() WHERE id = ANY($1::uuid[])",
                artifact_ids,
            )

    return results


async def list_artifacts(
    pool: asyncpg.Pool,
    artifact_type: str | None = None,
    tags: list[str] | None = None,
    include_archived: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List artifacts with optional filters and pagination.

    Uses ``COUNT(*) OVER()`` to return the total count alongside the
    paginated results in a single query.

    Args:
        pool: asyncpg connection pool.
        artifact_type: Optional filter by artifact type.
        tags: Optional tags filter (AND semantics via ``@>``).
        include_archived: Whether to include archived artifacts.
        limit: Maximum number of results per page (default 20).
        offset: Pagination offset (default 0).

    Returns:
        A dict with ``results`` (list of artifact dicts) and ``total_count``.
    """
    conditions: list[str] = []
    params: list = []
    param_idx = 1

    if not include_archived:
        conditions.append("archived = FALSE")

    if artifact_type is not None:
        conditions.append(f"artifact_type = ${param_idx}")
        params.append(artifact_type)
        param_idx += 1

    if tags:
        conditions.append(f"tags @> ${param_idx}")
        params.append(tags)
        param_idx += 1

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    limit_param = f"${param_idx}"
    params.append(limit)
    param_idx += 1

    offset_param = f"${param_idx}"
    params.append(offset)

    sql = f"""
        SELECT id, artifact_type, tags, LEFT(content, 200) AS content_preview,
               created_at, archived, COUNT(*) OVER() AS total_count
        FROM artifacts
        {where_clause}
        ORDER BY created_at DESC
        LIMIT {limit_param} OFFSET {offset_param}
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    total_count = rows[0]["total_count"] if rows else 0

    results = [
        {
            "artifact_id": str(row["id"]),
            "artifact_type": row["artifact_type"],
            "tags": list(row["tags"]) if row["tags"] else [],
            "content_preview": row["content_preview"],
            "created_at": row["created_at"].isoformat(),
            "archived": row["archived"],
        }
        for row in rows
    ]

    return {"results": results, "total_count": total_count}


async def archive_artifact(pool: asyncpg.Pool, artifact_id: str) -> bool:
    """Archive an artifact by setting ``archived = TRUE``.

    Idempotent: archiving an already-archived artifact is a no-op that
    still returns ``True``.

    Args:
        pool: asyncpg connection pool.
        artifact_id: UUID string of the artifact.

    Returns:
        ``True`` if the artifact was found, ``False`` otherwise.
    """
    async with pool.acquire() as conn:
        # Check existence first so already-archived artifacts return True
        exists = await conn.fetchval(
            "SELECT 1 FROM artifacts WHERE id = $1::uuid",
            artifact_id,
        )
        if not exists:
            return False

        await conn.execute(
            """
            UPDATE artifacts SET archived = TRUE WHERE id = $1::uuid
            """,
            artifact_id,
        )

    return True


async def update_artifact(
    pool: asyncpg.Pool,
    artifact_id: str,
    content: str,
    metadata: dict | None = None,
) -> dict | None:
    """Update an artifact's content, creating a new version.

    In a transaction:
    1. Validate the artifact exists.
    2. Determine the next version number (``max(version) + 1``).
    3. Insert a new ``artifact_versions`` row.
    4. Update the ``artifacts`` row with new content, content_hash, and
       optionally merge metadata.
    5. Reset the embedding to ``status='pending'`` and clear the vector.

    After commit, a fire-and-forget embedding task is spawned.

    Args:
        pool: asyncpg connection pool.
        artifact_id: UUID string of the artifact.
        content: The new content for the artifact.
        metadata: Optional metadata to JSONB-merge into existing metadata.

    Returns:
        A dict with ``artifact_id``, ``version``, and ``embedding_status``,
        or ``None`` if the artifact was not found.

    Raises:
        ValueError: If *content* is empty or None.
    """
    if not content:
        raise ValueError("Artifact content must not be empty")

    content_hash = compute_content_hash(content)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Validate artifact exists
            existing = await conn.fetchrow(
                "SELECT id, sensitive FROM artifacts WHERE id = $1::uuid",
                artifact_id,
            )
            if existing is None:
                return None

            sensitive = existing["sensitive"]

            # Get next version number
            max_version = await conn.fetchval(
                """
                SELECT COALESCE(MAX(version), 0)
                FROM artifact_versions
                WHERE artifact_id = $1::uuid
                """,
                artifact_id,
            )
            next_version = max_version + 1

            # Insert new version row
            await conn.execute(
                """
                INSERT INTO artifact_versions (
                    artifact_id, version, content, content_hash
                )
                VALUES ($1::uuid, $2, $3, $4)
                """,
                artifact_id,
                next_version,
                content,
                content_hash,
            )

            # Update the main artifacts row
            if metadata:
                metadata_json = json.dumps(metadata)
                await conn.execute(
                    """
                    UPDATE artifacts
                    SET content = $1,
                        content_hash = $2,
                        metadata = metadata || $3::jsonb
                    WHERE id = $4::uuid
                    """,
                    content,
                    content_hash,
                    metadata_json,
                    artifact_id,
                )
            else:
                await conn.execute(
                    """
                    UPDATE artifacts
                    SET content = $1,
                        content_hash = $2
                    WHERE id = $3::uuid
                    """,
                    content,
                    content_hash,
                    artifact_id,
                )

            # Reset embedding to pending and clear vector
            await conn.execute(
                """
                UPDATE artifact_embeddings
                SET embedding = NULL,
                    status = 'pending',
                    error_message = NULL,
                    retry_count = 0,
                    updated_at = NOW()
                WHERE artifact_id = $1::uuid
                """,
                artifact_id,
            )

    # Fire-and-forget embedding generation
    if not sensitive:
        asyncio.create_task(
            embed_artifact(pool, artifact_id, content, sensitive=False)
        )

    logger.info(
        "Updated artifact %s to version %d", artifact_id, next_version
    )

    return {
        "artifact_id": artifact_id,
        "version": next_version,
        "embedding_status": "pending",
    }


async def update_metadata(
    pool: asyncpg.Pool,
    artifact_id: str,
    metadata: dict,
    tags: list[str] | None = None,
    archived: bool | None = None,
) -> bool:
    """Update an artifact's metadata, tags, and/or archived status.

    Metadata is JSONB-merged (existing keys preserved unless overridden).
    Tags are replaced wholesale if provided.  Archived status is updated
    only if explicitly passed.

    Args:
        pool: asyncpg connection pool.
        artifact_id: UUID string of the artifact.
        metadata: Metadata fields to merge into existing metadata.
        tags: If provided, replace the artifact's tags with this list.
        archived: If provided, set the artifact's archived status.

    Returns:
        ``True`` if the artifact was found, ``False`` otherwise.
    """
    set_clauses: list[str] = ["metadata = metadata || $2::jsonb"]
    params: list = [artifact_id, json.dumps(metadata)]
    param_idx = 3

    if tags is not None:
        set_clauses.append(f"tags = ${param_idx}")
        params.append(tags)
        param_idx += 1

    if archived is not None:
        set_clauses.append(f"archived = ${param_idx}")
        params.append(archived)
        param_idx += 1

    set_clause = ", ".join(set_clauses)

    sql = f"""
        UPDATE artifacts
        SET {set_clause}
        WHERE id = $1::uuid
    """

    async with pool.acquire() as conn:
        result = await conn.execute(sql, *params)

    return result == "UPDATE 1"


_VALID_CONFIDENCE = frozenset(("HIGH", "MEDIUM", "LOW", "SUPERSEDED"))


async def record_feedback(
    pool: asyncpg.Pool,
    artifact_id: str,
    useful: bool,
    note: str | None = None,
    agent_id: str = "main",
) -> dict:
    """Record usage feedback on an artifact and recompute its utility score.

    Inserts a row into ``artifact_feedback`` with the current max content
    version, then recomputes the Bayesian-average utility score using
    ``(count_useful + 1) / (count_total + 2)`` and updates the artifact.

    Args:
        pool: asyncpg connection pool.
        artifact_id: UUID string of the artifact.
        useful: Whether the artifact was useful.
        note: Optional free-text note.
        agent_id: Identifier of the agent giving feedback (default ``'main'``).

    Returns:
        A dict with ``success``, ``feedback_id``, and ``utility_score``.

    Raises:
        ArtifactNotFoundError: If the artifact does not exist.
    """
    async with pool.acquire() as conn:
        # Validate artifact exists
        exists = await conn.fetchval(
            "SELECT 1 FROM artifacts WHERE id = $1::uuid",
            artifact_id,
        )
        if not exists:
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_id}")

        # Get current max version
        max_version = await conn.fetchval(
            """
            SELECT COALESCE(MAX(version), 1)
            FROM artifact_versions
            WHERE artifact_id = $1::uuid
            """,
            artifact_id,
        )

        # Insert feedback
        feedback_id = await conn.fetchval(
            """
            INSERT INTO artifact_feedback (
                artifact_id, useful, note, agent_id, content_version
            )
            VALUES ($1::uuid, $2, $3, $4, $5)
            RETURNING id
            """,
            artifact_id,
            useful,
            note,
            agent_id,
            max_version,
        )

        # Recompute utility score: Bayesian average (count_useful + 1) / (count_total + 2)
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) FILTER (WHERE useful = TRUE) AS count_useful,
                   COUNT(*) AS count_total
            FROM artifact_feedback
            WHERE artifact_id = $1::uuid
            """,
            artifact_id,
        )
        count_useful = row["count_useful"]
        count_total = row["count_total"]
        utility_score = (count_useful + 1) / (count_total + 2)

        # Update artifact's utility_score
        await conn.execute(
            "UPDATE artifacts SET utility_score = $1 WHERE id = $2::uuid",
            utility_score,
            artifact_id,
        )

    logger.info(
        "Recorded feedback for artifact %s (useful=%s, score=%.3f)",
        artifact_id,
        useful,
        utility_score,
    )

    return {
        "success": True,
        "feedback_id": str(feedback_id),
        "utility_score": utility_score,
    }


async def set_confidence(
    pool: asyncpg.Pool,
    artifact_id: str,
    confidence: str,
    reason: str | None = None,
) -> dict:
    """Set an artifact's confidence level.

    Args:
        pool: asyncpg connection pool.
        artifact_id: UUID string of the artifact.
        confidence: One of ``'HIGH'``, ``'MEDIUM'``, ``'LOW'``, ``'SUPERSEDED'``.
        reason: Optional reason for the confidence level (stored in metadata).

    Returns:
        A dict with ``success: True``.

    Raises:
        ValueError: If confidence is invalid.
        ArtifactNotFoundError: If the artifact does not exist.
    """
    if confidence not in _VALID_CONFIDENCE:
        raise ValueError(
            f"Invalid confidence value: {confidence!r}. "
            f"Must be one of {sorted(_VALID_CONFIDENCE)}"
        )

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM artifacts WHERE id = $1::uuid",
            artifact_id,
        )
        if not exists:
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_id}")

        if reason:
            reason_json = json.dumps({"confidence_reason": reason})
            await conn.execute(
                """
                UPDATE artifacts
                SET confidence = $1,
                    metadata = metadata || $2::jsonb
                WHERE id = $3::uuid
                """,
                confidence,
                reason_json,
                artifact_id,
            )
        else:
            await conn.execute(
                "UPDATE artifacts SET confidence = $1 WHERE id = $2::uuid",
                confidence,
                artifact_id,
            )

    logger.info(
        "Set confidence for artifact %s to %s", artifact_id, confidence
    )

    return {"success": True}


async def get_retirement_candidates(
    pool: asyncpg.Pool,
    min_age_days: int = 30,
    max_utility: float = 0.3,
    limit: int = 20,
) -> dict:
    """Find artifacts that are candidates for retirement.

    Returns artifacts that are either:
    - Low utility (``utility_score < max_utility``) and older than *min_age_days*, or
    - LOW or SUPERSEDED confidence and older than *min_age_days*, or
    - Never retrieved (``last_retrieved IS NULL``) and older than 90 days.

    Excludes archived artifacts.

    Args:
        pool: asyncpg connection pool.
        min_age_days: Minimum artifact age in days, evaluated against
            ``created_at`` (not ``last_retrieved``). Default 30.
        max_utility: Maximum utility score threshold (default 0.3).
        limit: Maximum number of candidates to return (default 20).

    Returns:
        A dict with ``candidates`` list.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, artifact_type, LEFT(content, 200) AS content_preview,
                   utility_score, confidence, last_retrieved, created_at
            FROM artifacts
            WHERE archived = FALSE
              AND created_at < NOW() - ($1 || ' days')::interval
              AND (
                  COALESCE(utility_score, 0.5) < $2
                  OR confidence IN ('LOW', 'SUPERSEDED')
                  OR (last_retrieved IS NULL AND created_at < NOW() - interval '90 days')
              )
            ORDER BY utility_score ASC, created_at ASC
            LIMIT $3
            """,
            str(min_age_days),
            max_utility,
            limit,
        )

    candidates = [
        {
            "id": str(row["id"]),
            "artifact_type": row["artifact_type"],
            "content_preview": row["content_preview"],
            "utility_score": float(row["utility_score"]) if row["utility_score"] is not None else 0.5,
            "confidence": row["confidence"],
            "last_retrieved": row["last_retrieved"].isoformat() if row["last_retrieved"] else None,
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]

    logger.info(
        "Found %d retirement candidates (min_age=%d, max_utility=%.2f)",
        len(candidates),
        min_age_days,
        max_utility,
    )

    return {"candidates": candidates}


async def export_artifacts(
    pool: asyncpg.Pool,
    format: str = "json",
    artifact_type: str | None = None,
) -> dict:
    """Export artifacts to a backup file.

    Supports two formats:
    - ``"json"``: Full artifact export with versions and feedback as JSON.
    - ``"pg_dump"``: Raw ``pg_dump`` of the artifact tables.

    Args:
        pool: asyncpg connection pool.
        format: Export format (``"json"`` or ``"pg_dump"``).
        artifact_type: Optional filter to a specific artifact type (JSON only).

    Returns:
        A dict with ``export_path`` and optionally ``artifact_count``.
    """
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if format == "pg_dump":
        export_path = _BACKUP_DIR / f"export-{timestamp}.sql"
        # Extract DSN from the pool for pg_dump
        dsn = os.environ.get("CLAUDE_HUB_PG_DSN")
        if dsn is None:
            # Fall back to the pool's internal DSN attribute
            dsn = getattr(pool, "_dsn", None)
        if dsn is None:
            raise RuntimeError(
                "Cannot determine database DSN for pg_dump. "
                "Set CLAUDE_HUB_PG_DSN environment variable."
            )
        result = subprocess.run(
            [
                "pg_dump",
                f"-d{dsn}",
                "--table=artifacts",
                "--table=artifact_versions",
                "--table=artifact_embeddings",
                "--table=artifact_feedback",
                f"--file={export_path}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("pg_dump failed: %s", result.stderr)
            raise RuntimeError(f"pg_dump failed: {result.stderr}")

        logger.info("Exported artifacts via pg_dump to %s", export_path)
        return {"export_path": str(export_path)}

    # JSON export
    export_path = _BACKUP_DIR / f"export-{timestamp}.json"

    conditions: list[str] = []
    params: list = []
    param_idx = 1

    if artifact_type is not None:
        conditions.append(f"artifact_type = ${param_idx}")
        params.append(artifact_type)
        param_idx += 1

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with pool.acquire() as conn:
        artifact_rows = await conn.fetch(
            f"""
            SELECT id, content, content_hash, artifact_type, tags,
                   source_ref, derives_from, created_at, sensitive,
                   archived, metadata, confidence, utility_score
            FROM artifacts
            {where_clause}
            ORDER BY created_at ASC
            """,
            *params,
        )

        artifacts_data = []
        for arow in artifact_rows:
            artifact_id = str(arow["id"])

            # Fetch versions
            version_rows = await conn.fetch(
                """
                SELECT version, content, content_hash, created_at
                FROM artifact_versions
                WHERE artifact_id = $1::uuid
                ORDER BY version ASC
                """,
                artifact_id,
            )

            # Fetch feedback
            feedback_rows = await conn.fetch(
                """
                SELECT useful, note, agent_id, content_version, created_at
                FROM artifact_feedback
                WHERE artifact_id = $1::uuid
                ORDER BY created_at DESC
                """,
                artifact_id,
            )

            # Fetch embedding metadata (status, model, dimensions — NOT the vector)
            embedding_row = await conn.fetchrow(
                """
                SELECT status, model,
                       CASE WHEN embedding IS NOT NULL
                            THEN vector_dims(embedding)
                            ELSE NULL
                       END AS dimensions
                FROM artifact_embeddings
                WHERE artifact_id = $1::uuid
                """,
                artifact_id,
            )
            embedding_info = None
            if embedding_row:
                embedding_info = {
                    "status": embedding_row["status"],
                    "model": embedding_row["model"],
                    "dimensions": embedding_row["dimensions"],
                }

            artifacts_data.append(
                {
                    "id": artifact_id,
                    "content": arow["content"],
                    "content_hash": arow["content_hash"],
                    "artifact_type": arow["artifact_type"],
                    "tags": list(arow["tags"]) if arow["tags"] else [],
                    "source_ref": arow["source_ref"],
                    "derives_from": (
                        [str(d) for d in arow["derives_from"]]
                        if arow["derives_from"]
                        else []
                    ),
                    "created_at": arow["created_at"].isoformat(),
                    "sensitive": arow["sensitive"],
                    "archived": arow["archived"],
                    "metadata": (
                        json.loads(arow["metadata"])
                        if isinstance(arow["metadata"], str)
                        else dict(arow["metadata"])
                    ),
                    "confidence": arow["confidence"],
                    "utility_score": float(arow["utility_score"]) if arow["utility_score"] is not None else None,
                    "embedding": embedding_info,
                    "versions": [
                        {
                            "version": vr["version"],
                            "content": vr["content"],
                            "content_hash": vr["content_hash"],
                            "created_at": vr["created_at"].isoformat(),
                        }
                        for vr in version_rows
                    ],
                    "feedback": [
                        {
                            "useful": frow["useful"],
                            "note": frow["note"],
                            "agent_id": frow["agent_id"],
                            "content_version": frow["content_version"],
                            "created_at": frow["created_at"].isoformat(),
                        }
                        for frow in feedback_rows
                    ],
                }
            )

    export_payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "artifact_count": len(artifacts_data),
        "artifacts": artifacts_data,
    }

    export_path.write_text(
        json.dumps(export_payload, indent=2, default=str),
        encoding="utf-8",
    )

    logger.info(
        "Exported %d artifacts to %s", len(artifacts_data), export_path
    )

    return {
        "export_path": str(export_path),
        "artifact_count": len(artifacts_data),
    }


async def import_artifacts(
    pool: asyncpg.Pool,
    path: str,
    dry_run: bool = False,
) -> dict:
    """Import artifacts from a JSON export file.

    For each artifact in the file:
    1. Check for duplicates via ``content_hash`` + ``source_ref``.
    2. Skip if already exists.
    3. Otherwise insert the artifact, its versions, and its feedback.
    4. Queue embedding generation for non-sensitive artifacts.

    Args:
        pool: asyncpg connection pool.
        path: Path to the JSON export file.
        dry_run: If ``True``, validate and count without actually inserting.

    Returns:
        A dict with ``imported``, ``skipped``, and ``errors`` counts/messages.
    """
    import_path = Path(path)
    if not import_path.exists():
        raise FileNotFoundError(f"Import file not found: {path}")

    try:
        data = json.loads(import_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON format: {exc}") from exc
    artifacts = data.get("artifacts", [])

    imported = 0
    skipped = 0
    errors: list[str] = []
    embedding_queue: list[str] = []

    for artifact in artifacts:
        content_hash = artifact.get("content_hash", "")
        source_ref = artifact.get("source_ref")

        try:
            # Check for existing duplicate (match partial unique index semantics)
            async with pool.acquire() as conn:
                existing = await conn.fetchval(
                    """
                    SELECT id FROM artifacts
                    WHERE content_hash = $1
                      AND COALESCE(source_ref, '') = COALESCE($2, '')
                      AND archived = FALSE
                    """,
                    content_hash,
                    source_ref,
                )

            if existing is not None:
                skipped += 1
                continue

            if dry_run:
                imported += 1
                continue

            # Insert artifact and related rows in a transaction
            tags_val = artifact.get("tags", [])
            derives_from_raw = artifact.get("derives_from", [])
            derives_from_uuids = []
            for d in derives_from_raw:
                try:
                    derives_from_uuids.append(uuid.UUID(d))
                except (ValueError, AttributeError):
                    logger.warning(
                        "Skipping invalid UUID in derives_from during import: %s", d
                    )
            metadata_val = json.dumps(artifact.get("metadata", {}))

            # Recompute content_hash from actual content (don't trust exported hash)
            content = artifact.get("content", "")
            recomputed_hash = compute_content_hash(content) if content else ""
            exported_hash = artifact.get("content_hash", "")
            if recomputed_hash and exported_hash and recomputed_hash != exported_hash:
                logger.warning(
                    "content_hash mismatch for artifact %s: "
                    "exported=%s, recomputed=%s — using recomputed",
                    artifact.get("id", "unknown"),
                    exported_hash[:16],
                    recomputed_hash[:16],
                )
            content_hash = recomputed_hash or exported_hash

            # Preserve the exported ID if present and valid
            exported_id = artifact.get("id")
            artifact_uuid = None
            if exported_id:
                try:
                    artifact_uuid = uuid.UUID(exported_id)
                except (ValueError, AttributeError):
                    logger.warning(
                        "Invalid exported artifact ID %s, will generate new UUID",
                        exported_id,
                    )
                    artifact_uuid = None

            # Parse exported timestamps
            created_at = None
            if artifact.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(artifact["created_at"])
                except (ValueError, TypeError):
                    logger.warning(
                        "Invalid created_at timestamp for artifact %s, using NOW()",
                        exported_id or "unknown",
                    )

            async with pool.acquire() as conn:
                async with conn.transaction():
                    if artifact_uuid and created_at:
                        # Preserve both ID and timestamp from export
                        artifact_id = await conn.fetchval(
                            """
                            INSERT INTO artifacts (
                                id, content, content_hash, artifact_type, tags,
                                source_ref, derives_from, sensitive, archived,
                                metadata, created_at
                            )
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
                            RETURNING id
                            """,
                            artifact_uuid,
                            content,
                            content_hash,
                            artifact.get("artifact_type", "unknown"),
                            tags_val,
                            source_ref,
                            derives_from_uuids,
                            artifact.get("sensitive", False),
                            artifact.get("archived", False),
                            metadata_val,
                            created_at,
                        )
                    elif artifact_uuid:
                        # Preserve ID, use default timestamp
                        artifact_id = await conn.fetchval(
                            """
                            INSERT INTO artifacts (
                                id, content, content_hash, artifact_type, tags,
                                source_ref, derives_from, sensitive, archived,
                                metadata
                            )
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
                            RETURNING id
                            """,
                            artifact_uuid,
                            content,
                            content_hash,
                            artifact.get("artifact_type", "unknown"),
                            tags_val,
                            source_ref,
                            derives_from_uuids,
                            artifact.get("sensitive", False),
                            artifact.get("archived", False),
                            metadata_val,
                        )
                    else:
                        # Generate new ID (no valid exported ID)
                        artifact_id = await conn.fetchval(
                            """
                            INSERT INTO artifacts (
                                content, content_hash, artifact_type, tags,
                                source_ref, derives_from, sensitive, archived,
                                metadata
                            )
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                            RETURNING id
                            """,
                            content,
                            content_hash,
                            artifact.get("artifact_type", "unknown"),
                            tags_val,
                            source_ref,
                            derives_from_uuids,
                            artifact.get("sensitive", False),
                            artifact.get("archived", False),
                            metadata_val,
                        )

                    artifact_id_str = str(artifact_id)

                    # Insert versions (preserve version timestamps if available)
                    for version in artifact.get("versions", []):
                        v_created_at = None
                        if version.get("created_at"):
                            try:
                                v_created_at = datetime.fromisoformat(version["created_at"])
                            except (ValueError, TypeError):
                                pass

                        if v_created_at:
                            await conn.execute(
                                """
                                INSERT INTO artifact_versions (
                                    artifact_id, version, content, content_hash,
                                    created_at
                                )
                                VALUES ($1, $2, $3, $4, $5)
                                """,
                                artifact_id,
                                version["version"],
                                version["content"],
                                version["content_hash"],
                                v_created_at,
                            )
                        else:
                            await conn.execute(
                                """
                                INSERT INTO artifact_versions (
                                    artifact_id, version, content, content_hash
                                )
                                VALUES ($1, $2, $3, $4)
                                """,
                                artifact_id,
                                version["version"],
                                version["content"],
                                version["content_hash"],
                            )

                    # Insert feedback (preserve created_at timestamps)
                    for fb_item in artifact.get("feedback", []):
                        fb_created_at = None
                        if fb_item.get("created_at"):
                            try:
                                fb_created_at = datetime.fromisoformat(fb_item["created_at"])
                            except (ValueError, TypeError):
                                pass

                        if fb_created_at:
                            await conn.execute(
                                """
                                INSERT INTO artifact_feedback (
                                    artifact_id, useful, note, agent_id,
                                    content_version, created_at
                                )
                                VALUES ($1, $2, $3, $4, $5, $6)
                                """,
                                artifact_id,
                                fb_item["useful"],
                                fb_item.get("note"),
                                fb_item.get("agent_id", "import"),
                                fb_item.get("content_version"),
                                fb_created_at,
                            )
                        else:
                            await conn.execute(
                                """
                                INSERT INTO artifact_feedback (
                                    artifact_id, useful, note, agent_id,
                                    content_version
                                )
                                VALUES ($1, $2, $3, $4, $5)
                                """,
                                artifact_id,
                                fb_item["useful"],
                                fb_item.get("note"),
                                fb_item.get("agent_id", "import"),
                                fb_item.get("content_version"),
                            )

                    # Insert pending embedding row
                    await conn.execute(
                        """
                        INSERT INTO artifact_embeddings (artifact_id, status)
                        VALUES ($1, 'pending')
                        """,
                        artifact_id,
                    )

            # Queue for embedding if not sensitive
            if not artifact.get("sensitive", False):
                embedding_queue.append(artifact_id_str)

            imported += 1

        except Exception as exc:
            error_msg = f"Error importing artifact (hash={content_hash[:12]}...): {exc}"
            logger.warning(error_msg)
            errors.append(error_msg)

    # Batch-embed all imported non-sensitive artifacts
    if embedding_queue and not dry_run:
        asyncio.create_task(batch_embed(embedding_queue, pool))

    logger.info(
        "Import complete: %d imported, %d skipped, %d errors",
        imported,
        skipped,
        len(errors),
    )

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }
