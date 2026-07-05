"""Tests for artifact_store module — CRUD and semantic search operations."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_hub.artifact_store import (
    archive_artifact,
    compute_content_hash,
    export_artifacts,
    get_artifact,
    import_artifacts,
    list_artifacts,
    search_artifacts,
    store_artifact,
    update_artifact,
    update_metadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_pool():
    """Create a mock asyncpg pool with acquire() context manager.

    Returns both the pool and the connection object so tests can
    configure return values on conn.fetchval / conn.fetchrow / etc.
    """
    pool = MagicMock()
    conn = AsyncMock()

    # Make pool.acquire() work as async context manager
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx

    # Also support pool.fetch(), pool.fetchrow(), pool.execute() directly
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.execute = AsyncMock(return_value="UPDATE 1")

    # conn.transaction() is a sync call that returns an async context manager.
    # Use MagicMock so calling transaction() returns the ctx directly (not a coroutine).
    tx_ctx = MagicMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=None)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_ctx)

    return pool, conn


def _make_artifact_row(
    *,
    artifact_id: uuid.UUID | None = None,
    content: str = "some content",
    content_hash: str | None = None,
    artifact_type: str = "learning",
    tags: list[str] | None = None,
    source_ref: str | None = None,
    derives_from: list | None = None,
    created_at: datetime | None = None,
    sensitive: bool = False,
    archived: bool = False,
    metadata: str | dict | None = None,
    confidence: str = "MEDIUM",
    utility_score: float = 0.5,
) -> dict:
    """Build a dict mimicking an asyncpg Record for an artifact row."""
    aid = artifact_id or uuid.uuid4()
    return {
        "id": aid,
        "content": content,
        "content_hash": content_hash or compute_content_hash(content),
        "artifact_type": artifact_type,
        "tags": tags or [],
        "source_ref": source_ref,
        "derives_from": derives_from or [],
        "created_at": created_at or datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
        "sensitive": sensitive,
        "archived": archived,
        "metadata": metadata or "{}",
        "confidence": confidence,
        "utility_score": utility_score,
    }


# ---------------------------------------------------------------------------
# compute_content_hash
# ---------------------------------------------------------------------------


class TestComputeContentHash:
    def test_deterministic(self):
        """Same input always yields the same SHA-256 hex digest."""
        h1 = compute_content_hash("hello world")
        h2 = compute_content_hash("hello world")
        assert h1 == h2
        # Verify against known SHA-256 value
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert h1 == expected

    def test_different_content_different_hash(self):
        """Distinct inputs produce distinct hashes."""
        h1 = compute_content_hash("alpha")
        h2 = compute_content_hash("beta")
        assert h1 != h2

    def test_empty_string_produces_valid_hash(self):
        """Empty string is a valid input and produces a 64-char hex digest."""
        h = compute_content_hash("")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# store_artifact
# ---------------------------------------------------------------------------


class TestStoreArtifact:
    @pytest.mark.asyncio
    async def test_successful_store(self):
        """Successful store returns artifact_id, version=1, embedding_status='pending'."""
        pool, conn = _mock_pool()
        fake_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=fake_id)
        conn.execute = AsyncMock()

        with patch("claude_hub.artifact_store.embed_artifact", new_callable=AsyncMock):
            with patch("claude_hub.artifact_store.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                result = await store_artifact(
                    pool, "test content", "learning"
                )

        assert result["artifact_id"] == str(fake_id)
        assert result["version"] == 1
        assert result["embedding_status"] == "pending"

    @pytest.mark.asyncio
    async def test_empty_content_raises_value_error(self):
        """Empty content string raises ValueError."""
        pool, _ = _mock_pool()
        with pytest.raises(ValueError, match="content must not be empty"):
            await store_artifact(pool, "", "learning")

    @pytest.mark.asyncio
    async def test_invalid_derives_from_uuid_raises_value_error(self):
        """Invalid UUID string in derives_from raises ValueError."""
        pool, _ = _mock_pool()
        with pytest.raises(ValueError, match="Invalid UUID in derives_from"):
            await store_artifact(
                pool, "content", "learning", derives_from=["not-a-uuid"]
            )

    @pytest.mark.asyncio
    async def test_dedup_returns_existing(self):
        """UniqueViolationError triggers dedup path, returning existing artifact."""
        import asyncpg

        pool, conn = _mock_pool()

        # First acquire() raises UniqueViolationError during the transaction
        call_count = 0
        original_aenter = pool.acquire.return_value.__aenter__

        async def _acquire_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: inside the try block, conn.fetchval raises
                err_conn = AsyncMock()
                tx_ctx = MagicMock()
                tx_ctx.__aenter__ = AsyncMock(return_value=None)
                tx_ctx.__aexit__ = AsyncMock(return_value=False)
                err_conn.transaction = MagicMock(return_value=tx_ctx)
                err_conn.fetchval = AsyncMock(
                    side_effect=asyncpg.UniqueViolationError("")
                )
                return err_conn
            else:
                # Second call: the dedup lookup returns existing id
                dedup_conn = AsyncMock()
                existing_id = uuid.uuid4()
                dedup_conn.fetchval = AsyncMock(return_value=existing_id)
                return dedup_conn

        pool.acquire.return_value.__aenter__ = AsyncMock(
            side_effect=_acquire_side_effect
        )

        result = await store_artifact(pool, "duplicate content", "learning")
        assert result["embedding_status"] == "existing"
        assert result["version"] == 1

    @pytest.mark.asyncio
    async def test_tags_and_metadata_passed_through(self):
        """Tags and metadata arguments are forwarded to the INSERT."""
        pool, conn = _mock_pool()
        fake_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=fake_id)
        conn.execute = AsyncMock()

        with patch("claude_hub.artifact_store.embed_artifact", new_callable=AsyncMock):
            with patch("claude_hub.artifact_store.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                result = await store_artifact(
                    pool,
                    "tagged content",
                    "plan",
                    tags=["infra", "db"],
                    metadata={"priority": "high"},
                )

        assert result["artifact_id"] == str(fake_id)
        # Verify the INSERT was called with the right args
        insert_call = conn.fetchval.call_args
        args = insert_call[0]
        # args[0] is the SQL, args[3] (index 4) should be the tags list
        assert args[4] == ["infra", "db"]
        # args[8] should be the JSON metadata string
        assert json.loads(args[8]) == {"priority": "high"}

    @pytest.mark.asyncio
    async def test_sensitive_skips_embedding_task(self):
        """When sensitive=True, no embedding task is created."""
        pool, conn = _mock_pool()
        fake_id = uuid.uuid4()
        conn.fetchval = AsyncMock(return_value=fake_id)
        conn.execute = AsyncMock()

        with patch("claude_hub.artifact_store.asyncio") as mock_asyncio:
            mock_asyncio.create_task = MagicMock()
            result = await store_artifact(
                pool, "secret content", "learning", sensitive=True
            )

        assert result["artifact_id"] == str(fake_id)
        mock_asyncio.create_task.assert_not_called()


# ---------------------------------------------------------------------------
# get_artifact
# ---------------------------------------------------------------------------


class TestGetArtifact:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        """Returns None when no artifact matches the given ID."""
        pool, conn = _mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        result = await get_artifact(pool, str(uuid.uuid4()))
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_artifact_dict(self):
        """Returns a fully populated artifact dict when found."""
        pool, conn = _mock_pool()
        row = _make_artifact_row(content="hello artifact")
        conn.fetchrow = AsyncMock(return_value=row)
        # Default: include_feedback=True, so we need feedback fetch
        conn.fetch = AsyncMock(return_value=[])

        result = await get_artifact(pool, str(row["id"]))
        assert result is not None
        assert result["id"] == str(row["id"])
        assert result["content"] == "hello artifact"
        assert result["artifact_type"] == "learning"
        assert result["confidence"] == "MEDIUM"
        assert result["utility_score"] == 0.5
        assert result["versions"] is None  # include_versions default is False
        assert result["feedback"] == []  # include_feedback default is True

    @pytest.mark.asyncio
    async def test_include_versions(self):
        """include_versions=True fetches and returns version rows."""
        pool, conn = _mock_pool()
        row = _make_artifact_row()
        conn.fetchrow = AsyncMock(return_value=row)

        version_row = {
            "version": 1,
            "content": "v1 content",
            "content_hash": compute_content_hash("v1 content"),
            "created_at": datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
        }
        # fetch is called twice when both versions and feedback are included
        conn.fetch = AsyncMock(side_effect=[[version_row], []])

        result = await get_artifact(
            pool, str(row["id"]), include_versions=True, include_feedback=True
        )
        assert result["versions"] is not None
        assert len(result["versions"]) == 1
        assert result["versions"][0]["version"] == 1
        assert result["versions"][0]["content"] == "v1 content"

    @pytest.mark.asyncio
    async def test_include_feedback(self):
        """include_feedback=True fetches and returns feedback rows."""
        pool, conn = _mock_pool()
        row = _make_artifact_row()
        conn.fetchrow = AsyncMock(return_value=row)

        feedback_row = {
            "useful": True,
            "note": "worked well",
            "agent_id": "main",
            "content_version": 1,
            "created_at": datetime(2026, 3, 2, 10, 0, 0, tzinfo=timezone.utc),
        }
        conn.fetch = AsyncMock(return_value=[feedback_row])

        result = await get_artifact(
            pool, str(row["id"]), include_feedback=True
        )
        assert result["feedback"] is not None
        assert len(result["feedback"]) == 1
        assert result["feedback"][0]["useful"] is True
        assert result["feedback"][0]["note"] == "worked well"
        assert result["feedback"][0]["agent_id"] == "main"
        assert result["feedback"][0]["content_version"] == 1

    @pytest.mark.asyncio
    async def test_include_outcomes_backward_compat(self):
        """include_outcomes=True is treated as include_feedback=True for backward compat."""
        pool, conn = _mock_pool()
        row = _make_artifact_row()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.fetch = AsyncMock(return_value=[])

        result = await get_artifact(
            pool, str(row["id"]), include_outcomes=True
        )
        assert result["feedback"] == []


# ---------------------------------------------------------------------------
# search_artifacts
# ---------------------------------------------------------------------------


class TestSearchArtifacts:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_results(self):
        """Empty result set from the database returns an empty list."""
        pool, conn = _mock_pool()
        conn.fetch = AsyncMock(return_value=[])
        fake_embedding = [0.1] * 768

        with patch(
            "claude_hub.artifact_store.generate_query_embedding",
            new_callable=AsyncMock,
            return_value=fake_embedding,
        ):
            results = await search_artifacts(pool, "find something")

        assert results == []

    @pytest.mark.asyncio
    async def test_builds_correct_query_with_filters(self):
        """Filters (artifact_type, tags, date_from, date_to) add WHERE clauses."""
        pool, conn = _mock_pool()
        conn.fetch = AsyncMock(return_value=[])
        fake_embedding = [0.1] * 768

        with patch(
            "claude_hub.artifact_store.generate_query_embedding",
            new_callable=AsyncMock,
            return_value=fake_embedding,
        ):
            await search_artifacts(
                pool,
                "query",
                artifact_type="learning",
                tags=["infra"],
                date_from="2026-01-01",
                date_to="2026-12-31",
            )

        # Verify fetch was called with the right number of params
        fetch_call = conn.fetch.call_args
        args = fetch_call[0]  # positional args: (sql, *params)
        sql = args[0]
        params = args[1:]
        # Params: $1=embedding, $2=artifact_type, $3=tags, $4=date_from, $5=date_to, $6=limit
        assert len(params) == 6
        assert params[0] == fake_embedding  # query embedding
        assert params[1] == "learning"  # artifact_type
        assert params[2] == ["infra"]  # tags
        assert params[3] == "2026-01-01"  # date_from
        assert params[4] == "2026-12-31"  # date_to
        assert params[5] == 10  # default limit

    @pytest.mark.asyncio
    async def test_generates_query_embedding(self):
        """generate_query_embedding is called with the search query."""
        pool, conn = _mock_pool()
        conn.fetch = AsyncMock(return_value=[])
        fake_embedding = [0.5] * 768

        with patch(
            "claude_hub.artifact_store.generate_query_embedding",
            new_callable=AsyncMock,
            return_value=fake_embedding,
        ) as mock_embed:
            await search_artifacts(pool, "find learning artifacts")

        mock_embed.assert_awaited_once_with("find learning artifacts")

    @pytest.mark.asyncio
    async def test_results_include_expected_fields(self):
        """Returned results contain score, content_preview, and other fields."""
        pool, conn = _mock_pool()
        fake_embedding = [0.1] * 768
        result_row = {
            "artifact_id": uuid.uuid4(),
            "content_preview": "This is a preview of...",
            "artifact_type": "plan",
            "tags": ["deploy"],
            "base_score": 0.80,
            "confidence_boost": 0.1,
            "utility_boost": 0.0,
            "age_boost": -0.05,
            "final_score": 0.85,
            "utility_score": 0.5,
            "confidence": "HIGH",
            "created_at": datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
        }
        conn.fetch = AsyncMock(return_value=[result_row])
        conn.execute = AsyncMock()

        with patch(
            "claude_hub.artifact_store.generate_query_embedding",
            new_callable=AsyncMock,
            return_value=fake_embedding,
        ):
            results = await search_artifacts(pool, "deploy plan")

        assert len(results) == 1
        r = results[0]
        assert r["artifact_id"] == str(result_row["artifact_id"])
        assert r["content_preview"] == "This is a preview of..."
        assert r["artifact_type"] == "plan"
        assert r["tags"] == ["deploy"]
        assert r["score"] == 0.85
        assert r["utility_score"] == 0.5
        assert r["confidence"] == "HIGH"
        assert "created_at" in r


# ---------------------------------------------------------------------------
# list_artifacts
# ---------------------------------------------------------------------------


class TestListArtifacts:
    @pytest.mark.asyncio
    async def test_returns_results_with_total_count(self):
        """Returned dict has 'results' list and 'total_count' integer."""
        pool, conn = _mock_pool()
        row = {
            "id": uuid.uuid4(),
            "artifact_type": "learning",
            "tags": ["test"],
            "content_preview": "some content...",
            "created_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
            "archived": False,
            "total_count": 42,
        }
        conn.fetch = AsyncMock(return_value=[row])

        result = await list_artifacts(pool)
        assert result["total_count"] == 42
        assert len(result["results"]) == 1
        assert result["results"][0]["artifact_id"] == str(row["id"])
        assert result["results"][0]["artifact_type"] == "learning"

    @pytest.mark.asyncio
    async def test_filters_applied_correctly(self):
        """artifact_type and tags filters are passed as query params."""
        pool, conn = _mock_pool()
        conn.fetch = AsyncMock(return_value=[])

        await list_artifacts(
            pool, artifact_type="plan", tags=["deploy", "urgent"]
        )

        fetch_call = conn.fetch.call_args
        args = fetch_call[0]
        sql = args[0]
        params = args[1:]
        # Params: $1=artifact_type, $2=tags, $3=limit, $4=offset
        assert params[0] == "plan"
        assert params[1] == ["deploy", "urgent"]
        assert params[2] == 20  # default limit
        assert params[3] == 0  # default offset
        assert "artifact_type = $1" in sql
        assert "tags @> $2" in sql

    @pytest.mark.asyncio
    async def test_pagination_with_offset(self):
        """Custom limit and offset are forwarded to the SQL query."""
        pool, conn = _mock_pool()
        conn.fetch = AsyncMock(return_value=[])

        await list_artifacts(pool, limit=5, offset=15)

        fetch_call = conn.fetch.call_args
        args = fetch_call[0]
        params = args[1:]
        # No type/tags filters, so params are: $1=limit, $2=offset
        assert params[0] == 5
        assert params[1] == 15


# ---------------------------------------------------------------------------
# archive_artifact
# ---------------------------------------------------------------------------


class TestArchiveArtifact:
    @pytest.mark.asyncio
    async def test_returns_true_when_found(self):
        """Returns True when UPDATE affects exactly one row."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        result = await archive_artifact(pool, str(uuid.uuid4()))
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self):
        """Returns False when the artifact does not exist."""
        pool, conn = _mock_pool()
        conn.fetchval = AsyncMock(return_value=None)

        result = await archive_artifact(pool, str(uuid.uuid4()))
        assert result is False


# ---------------------------------------------------------------------------
# update_artifact
# ---------------------------------------------------------------------------


class TestUpdateArtifact:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        """Returns None when the artifact does not exist."""
        pool, conn = _mock_pool()
        conn.fetchrow = AsyncMock(return_value=None)

        result = await update_artifact(pool, str(uuid.uuid4()), "new content")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_new_version_number(self):
        """Returns incremented version number on successful update."""
        pool, conn = _mock_pool()
        fake_id = uuid.uuid4()
        conn.fetchrow = AsyncMock(
            return_value={"id": fake_id, "sensitive": False}
        )
        conn.fetchval = AsyncMock(return_value=2)  # max version is 2
        conn.execute = AsyncMock()

        with patch("claude_hub.artifact_store.embed_artifact", new_callable=AsyncMock):
            with patch("claude_hub.artifact_store.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                result = await update_artifact(
                    pool, str(fake_id), "updated content"
                )

        assert result is not None
        assert result["artifact_id"] == str(fake_id)
        assert result["version"] == 3  # max(2) + 1
        assert result["embedding_status"] == "pending"

    @pytest.mark.asyncio
    async def test_metadata_merge(self):
        """When metadata is provided, the UPDATE uses JSONB merge (||)."""
        pool, conn = _mock_pool()
        fake_id = uuid.uuid4()
        conn.fetchrow = AsyncMock(
            return_value={"id": fake_id, "sensitive": False}
        )
        conn.fetchval = AsyncMock(return_value=1)
        conn.execute = AsyncMock()

        with patch("claude_hub.artifact_store.embed_artifact", new_callable=AsyncMock):
            with patch("claude_hub.artifact_store.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                result = await update_artifact(
                    pool,
                    str(fake_id),
                    "updated content",
                    metadata={"reviewed": True},
                )

        assert result is not None
        assert result["version"] == 2

        # Verify execute was called with the metadata-merge SQL variant
        # Find the UPDATE call that includes the metadata merge
        execute_calls = conn.execute.call_args_list
        metadata_update_found = False
        for call in execute_calls:
            sql = call[0][0]
            if "metadata || " in sql:
                metadata_update_found = True
                # The metadata JSON string should be in the args
                args = call[0]
                assert json.loads(args[3]) == {"reviewed": True}
                break
        assert metadata_update_found, "Expected a metadata merge UPDATE call"


# ---------------------------------------------------------------------------
# update_metadata
# ---------------------------------------------------------------------------


class TestUpdateMetadata:
    @pytest.mark.asyncio
    async def test_successful_metadata_merge(self):
        """Metadata dict is JSONB-merged and returns True when artifact exists."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        result = await update_metadata(
            pool, str(uuid.uuid4()), {"reviewed": True, "priority": "high"}
        )
        assert result is True

        # Verify the SQL uses JSONB merge operator
        execute_call = conn.execute.call_args
        sql = execute_call[0][0]
        assert "metadata || " in sql or "metadata =" in sql

    @pytest.mark.asyncio
    async def test_tag_only_update(self):
        """Tags can be updated alongside metadata."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        result = await update_metadata(
            pool,
            str(uuid.uuid4()),
            {"source": "test"},
            tags=["new-tag", "another-tag"],
        )
        assert result is True

        # Verify tags param was passed
        execute_call = conn.execute.call_args
        args = execute_call[0]
        sql = args[0]
        assert "tags =" in sql
        # Tags should appear in the positional params
        all_args = list(execute_call[0][1:])
        assert ["new-tag", "another-tag"] in all_args

    @pytest.mark.asyncio
    async def test_archive_only_update(self):
        """Archived status can be updated via update_metadata."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 1")

        result = await update_metadata(
            pool, str(uuid.uuid4()), {}, archived=True
        )
        assert result is True

        execute_call = conn.execute.call_args
        sql = execute_call[0][0]
        assert "archived =" in sql

    @pytest.mark.asyncio
    async def test_artifact_not_found_returns_false(self):
        """Returns False when UPDATE affects zero rows (artifact not found)."""
        pool, conn = _mock_pool()
        conn.execute = AsyncMock(return_value="UPDATE 0")

        result = await update_metadata(
            pool, str(uuid.uuid4()), {"key": "value"}
        )
        assert result is False


# ---------------------------------------------------------------------------
# export_artifacts
# ---------------------------------------------------------------------------


class TestExportArtifacts:
    @pytest.mark.asyncio
    async def test_json_export_returns_expected_structure(self, tmp_path):
        """JSON export writes a file and returns export_path + artifact_count."""
        pool, conn = _mock_pool()

        fake_id = uuid.uuid4()
        artifact_row = {
            "id": fake_id,
            "content": "test content",
            "content_hash": compute_content_hash("test content"),
            "artifact_type": "learning",
            "tags": ["test"],
            "source_ref": None,
            "derives_from": [],
            "created_at": datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
            "sensitive": False,
            "archived": False,
            "metadata": "{}",
            "confidence": "MEDIUM",
            "utility_score": 0.5,
        }

        # conn.fetch is called: 1st for artifacts, then for versions, then for feedback
        conn.fetch = AsyncMock(
            side_effect=[[artifact_row], [], []]
        )

        with patch(
            "claude_hub.artifact_store._BACKUP_DIR", tmp_path
        ):
            result = await export_artifacts(pool, format="json")

        assert "export_path" in result
        assert result["artifact_count"] == 1

        # Verify the file was written with correct structure
        export_data = json.loads(Path(result["export_path"]).read_text())
        assert "exported_at" in export_data
        assert "artifact_count" in export_data
        assert "artifacts" in export_data
        assert len(export_data["artifacts"]) == 1
        assert export_data["artifacts"][0]["id"] == str(fake_id)

    @pytest.mark.asyncio
    async def test_json_export_with_artifact_type_filter(self, tmp_path):
        """JSON export with artifact_type filter passes WHERE clause."""
        pool, conn = _mock_pool()

        # Return no artifacts (empty list)
        conn.fetch = AsyncMock(return_value=[])

        with patch(
            "claude_hub.artifact_store._BACKUP_DIR", tmp_path
        ):
            result = await export_artifacts(
                pool, format="json", artifact_type="plan"
            )

        assert result["artifact_count"] == 0

        # Verify the SQL included the artifact_type filter
        fetch_call = conn.fetch.call_args
        sql = fetch_call[0][0]
        assert "artifact_type = $1" in sql
        params = fetch_call[0][1:]
        assert params[0] == "plan"

    @pytest.mark.asyncio
    async def test_pg_dump_format(self, tmp_path):
        """pg_dump format calls subprocess and returns export_path."""
        pool, conn = _mock_pool()

        with patch(
            "claude_hub.artifact_store._BACKUP_DIR", tmp_path
        ):
            with patch(
                "claude_hub.artifact_store.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout="", stderr=""
                )
                result = await export_artifacts(pool, format="pg_dump")

        assert "export_path" in result
        assert result["export_path"].endswith(".sql")

        # Verify pg_dump was called with correct table args
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "pg_dump" in call_args
        assert "--table=artifacts" in call_args
        assert "--table=artifact_versions" in call_args
        assert "--table=artifact_embeddings" in call_args
        assert "--table=artifact_feedback" in call_args


# ---------------------------------------------------------------------------
# import_artifacts
# ---------------------------------------------------------------------------


class TestImportArtifacts:
    @pytest.mark.asyncio
    async def test_successful_import_from_valid_json(self, tmp_path):
        """Imports artifacts from a valid JSON file and returns counts."""
        pool, conn = _mock_pool()

        fake_id = uuid.uuid4()
        conn.fetchval = AsyncMock(
            side_effect=[
                None,  # No existing duplicate (dedup check)
                fake_id,  # INSERT RETURNING id
            ]
        )
        conn.execute = AsyncMock()

        import_data = {
            "exported_at": "2026-03-01T00:00:00+00:00",
            "artifact_count": 1,
            "artifacts": [
                {
                    "content": "imported content",
                    "content_hash": compute_content_hash("imported content"),
                    "artifact_type": "learning",
                    "tags": ["imported"],
                    "source_ref": None,
                    "derives_from": [],
                    "sensitive": False,
                    "archived": False,
                    "metadata": {},
                    "versions": [
                        {
                            "version": 1,
                            "content": "imported content",
                            "content_hash": compute_content_hash(
                                "imported content"
                            ),
                        }
                    ],
                    "outcomes": [],
                }
            ],
        }

        import_file = tmp_path / "import.json"
        import_file.write_text(json.dumps(import_data))

        with patch(
            "claude_hub.artifact_store.batch_embed", new_callable=AsyncMock
        ):
            with patch("claude_hub.artifact_store.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                result = await import_artifacts(pool, str(import_file))

        assert result["imported"] == 1
        assert result["skipped"] == 0
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_invalid_json_raises_value_error(self, tmp_path):
        """Invalid JSON file raises ValueError."""
        import_file = tmp_path / "bad.json"
        import_file.write_text("not valid json {{{")

        pool, _ = _mock_pool()

        with pytest.raises(ValueError, match="Invalid JSON format"):
            await import_artifacts(pool, str(import_file))

    @pytest.mark.asyncio
    async def test_dedup_skip_existing_artifact(self, tmp_path):
        """Existing artifact with same content_hash is skipped."""
        pool, conn = _mock_pool()

        existing_id = uuid.uuid4()
        # Dedup check returns an existing ID
        conn.fetchval = AsyncMock(return_value=existing_id)

        import_data = {
            "artifacts": [
                {
                    "content": "existing content",
                    "content_hash": compute_content_hash("existing content"),
                    "artifact_type": "learning",
                    "tags": [],
                    "source_ref": None,
                    "derives_from": [],
                    "sensitive": False,
                    "archived": False,
                    "metadata": {},
                    "versions": [],
                    "outcomes": [],
                }
            ]
        }

        import_file = tmp_path / "import_dup.json"
        import_file.write_text(json.dumps(import_data))

        result = await import_artifacts(pool, str(import_file))

        assert result["imported"] == 0
        assert result["skipped"] == 1
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_invalid_derives_from_uuid_logged_as_error(self, tmp_path):
        """Invalid UUID in derives_from is caught and logged as an error."""
        pool, conn = _mock_pool()

        # Dedup check returns None (no existing)
        conn.fetchval = AsyncMock(
            side_effect=[
                None,  # dedup check
                # The INSERT will fail because of bad UUID
            ]
        )

        import_data = {
            "artifacts": [
                {
                    "content": "bad derives_from content",
                    "content_hash": compute_content_hash(
                        "bad derives_from content"
                    ),
                    "artifact_type": "learning",
                    "tags": [],
                    "source_ref": None,
                    "derives_from": ["not-a-valid-uuid"],
                    "sensitive": False,
                    "archived": False,
                    "metadata": {},
                    "versions": [],
                    "outcomes": [],
                }
            ]
        }

        import_file = tmp_path / "import_bad_uuid.json"
        import_file.write_text(json.dumps(import_data))

        result = await import_artifacts(pool, str(import_file))

        # The bad UUID should cause an error that's caught
        assert result["imported"] == 0
        assert len(result["errors"]) == 1
        assert "not-a-valid-uuid" in result["errors"][0] or "Error" in result["errors"][0]
