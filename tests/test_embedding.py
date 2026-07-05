"""Tests for the Gemini embedding client and async retry loop."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import claude_hub.embedding as embedding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_embed_result(dim: int = 768):
    """Return a fake client.models.embed_content result with *dim*-dimensional vector."""
    embedding_obj = MagicMock()
    embedding_obj.values = [0.1] * dim
    result = MagicMock()
    result.embeddings = [embedding_obj]
    return result


def _mock_pool() -> MagicMock:
    """Return a mock asyncpg pool whose acquire() yields a mock connection.

    Usage in tests::

        pool = _mock_pool()
        conn = pool.acquire().__aenter__.return_value
        conn.execute = AsyncMock()
    """
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = ctx
    return pool


@pytest.fixture(autouse=True)
def _reset_configured():
    """Ensure the module-level _configured flag and _client are reset after every test."""
    yield
    embedding._configured = False
    embedding._client = None


# ---------------------------------------------------------------------------
# configure_gemini
# ---------------------------------------------------------------------------


class TestConfigureGemini:
    def test_sets_configured_true_when_key_present(self):
        """Sets _configured=True when GEMINI_API_KEY is in the environment."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            with patch("claude_hub.embedding.genai.Client"):
                embedding.configure_gemini()

        assert embedding._configured is True
        assert embedding._client is not None

    def test_sets_configured_false_and_warns_when_key_missing(self, caplog):
        """Sets _configured=False and logs a warning when the key is absent."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("GEMINI_API_KEY", "GEMINI_EMBEDDING_API_KEY")}
        with patch.dict(os.environ, env, clear=True):
            embedding.configure_gemini()

        assert embedding._configured is False
        assert embedding._client is None
        assert "GEMINI_EMBEDDING_API_KEY is not set" in caplog.text

    def test_calls_genai_client_with_key(self):
        """Creates a genai.Client with the API key."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "my-secret-key"}):
            with patch("claude_hub.embedding.genai.Client") as mock_client_cls:
                embedding.configure_gemini()

        mock_client_cls.assert_called_once_with(api_key="my-secret-key")


# ---------------------------------------------------------------------------
# generate_embedding
# ---------------------------------------------------------------------------


class TestGenerateEmbedding:
    @pytest.mark.asyncio
    async def test_returns_list_of_floats(self):
        """Returns the embedding vector from client.models.embed_content."""
        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = _fake_embed_result()
        embedding._configured = True
        embedding._client = mock_client

        result = await embedding.generate_embedding("hello world")

        assert isinstance(result, list)
        assert len(result) == 768
        assert all(isinstance(v, float) for v in result)

    @pytest.mark.asyncio
    async def test_raises_runtime_error_if_not_configured(self):
        """Raises RuntimeError when Gemini has not been configured."""
        embedding._configured = False

        with pytest.raises(RuntimeError, match="Gemini is not configured"):
            await embedding.generate_embedding("hello")

    @pytest.mark.asyncio
    async def test_uses_retrieval_document_task_type(self):
        """Calls client.models.embed_content with task_type='RETRIEVAL_DOCUMENT'."""
        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = _fake_embed_result()
        embedding._configured = True
        embedding._client = mock_client

        await embedding.generate_embedding("some text")

        mock_client.models.embed_content.assert_called_once_with(
            model=embedding._MODEL,
            contents="some text",
            config={
                "task_type": "RETRIEVAL_DOCUMENT",
                "output_dimensionality": embedding._EMBEDDING_DIM,
            },
        )


# ---------------------------------------------------------------------------
# generate_query_embedding
# ---------------------------------------------------------------------------


class TestGenerateQueryEmbedding:
    @pytest.mark.asyncio
    async def test_uses_retrieval_query_task_type(self):
        """Calls client.models.embed_content with task_type='RETRIEVAL_QUERY'."""
        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = _fake_embed_result()
        embedding._configured = True
        embedding._client = mock_client

        await embedding.generate_query_embedding("search terms")

        mock_client.models.embed_content.assert_called_once_with(
            model=embedding._MODEL,
            contents="search terms",
            config={
                "task_type": "RETRIEVAL_QUERY",
                "output_dimensionality": embedding._EMBEDDING_DIM,
            },
        )

    @pytest.mark.asyncio
    async def test_raises_runtime_error_if_not_configured(self):
        """Raises RuntimeError when Gemini has not been configured."""
        embedding._configured = False

        with pytest.raises(RuntimeError, match="Gemini is not configured"):
            await embedding.generate_query_embedding("hello")


# ---------------------------------------------------------------------------
# embed_artifact
# ---------------------------------------------------------------------------


class TestEmbedArtifact:
    @pytest.mark.asyncio
    async def test_skips_when_sensitive(self):
        """No API call or DB update when sensitive=True."""
        mock_client = MagicMock()
        embedding._configured = True
        embedding._client = mock_client
        pool = _mock_pool()

        await embedding.embed_artifact(
            pool, "artifact-1", "secret content", sensitive=True
        )

        mock_client.models.embed_content.assert_not_called()
        pool.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_updates_to_complete_on_success(self):
        """On success, updates the embedding row to status='complete'."""
        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = _fake_embed_result()
        embedding._configured = True
        embedding._client = mock_client
        pool = _mock_pool()
        conn = pool.acquire().__aenter__.return_value

        await embedding.embed_artifact(
            pool, "artifact-1", "embed me", sensitive=False
        )

        # The success path calls conn.execute with the UPDATE ... status = 'complete'
        call_args_list = conn.execute.call_args_list
        assert any("'complete'" in str(call) for call in call_args_list)

    @pytest.mark.asyncio
    async def test_updates_to_failed_on_error(self):
        """On failure, updates the embedding row to status='failed' with error message."""
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = Exception("API rate limit exceeded")
        embedding._configured = True
        embedding._client = mock_client
        pool = _mock_pool()
        conn = pool.acquire().__aenter__.return_value

        await embedding.embed_artifact(
            pool, "artifact-1", "embed me", sensitive=False
        )

        call_args_list = conn.execute.call_args_list
        assert any("'failed'" in str(call) for call in call_args_list)
        assert any("API rate limit exceeded" in str(call) for call in call_args_list)

    @pytest.mark.asyncio
    async def test_calls_generate_embedding_with_content(self):
        """Passes the artifact content to generate_embedding."""
        embedding._configured = True
        embedding._client = MagicMock()
        pool = _mock_pool()

        with patch(
            "claude_hub.embedding.generate_embedding",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ) as mock_gen:
            await embedding.embed_artifact(
                pool, "artifact-1", "the content to embed", sensitive=False
            )

        mock_gen.assert_awaited_once_with("the content to embed")


# ---------------------------------------------------------------------------
# embedding_retry_loop
# ---------------------------------------------------------------------------


class TestEmbeddingRetryLoop:
    @pytest.mark.asyncio
    async def test_returns_immediately_if_not_configured(self):
        """Exits without error when Gemini is not configured."""
        embedding._configured = False
        pool = _mock_pool()

        # Should return immediately, not loop forever
        await embedding.embedding_retry_loop(pool)

    @pytest.mark.asyncio
    async def test_calls_sweep_pending_on_startup(self):
        """Calls _sweep_pending immediately on startup before entering the poll loop."""
        embedding._configured = True
        pool = _mock_pool()

        with patch(
            "claude_hub.embedding._sweep_pending",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_sweep:
            # Cancel after the initial sweep to prevent infinite loop
            async def cancel_after_sweep(*args, **kwargs):
                raise asyncio.CancelledError()

            with patch(
                "asyncio.sleep", new_callable=AsyncMock, side_effect=cancel_after_sweep
            ):
                await embedding.embedding_retry_loop(pool)

        mock_sweep.assert_awaited_once_with(pool)

    @pytest.mark.asyncio
    async def test_handles_cancelled_error_gracefully(self):
        """CancelledError is caught and the loop shuts down cleanly."""
        embedding._configured = True
        pool = _mock_pool()

        with patch(
            "claude_hub.embedding._sweep_pending",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError(),
        ):
            # Should not propagate the CancelledError
            await embedding.embedding_retry_loop(pool)
