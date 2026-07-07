"""Tests for asyncpg connection pool management and migration runner."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import claude_hub.database as database


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_pool():
    """Ensure the module-level _pool is reset after every test."""
    yield
    database._pool = None


def _mock_pool() -> MagicMock:
    """Return a mock asyncpg pool whose acquire() yields a mock connection."""
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire.return_value = ctx
    pool.close = AsyncMock()
    return pool


# ---------------------------------------------------------------------------
# Pool management
# ---------------------------------------------------------------------------


class TestPoolManagement:
    def test_get_pool_raises_when_not_set(self):
        """get_pool raises RuntimeError when no pool has been configured."""
        with pytest.raises(RuntimeError, match="Database pool not initialised"):
            database.get_pool()

    def test_set_pool_get_pool_round_trip(self):
        """set_pool stores a pool that get_pool returns."""
        pool = _mock_pool()
        database.set_pool(pool)

        assert database.get_pool() is pool

    @pytest.mark.asyncio
    async def test_close_pool_closes_and_resets(self):
        """close_pool awaits pool.close() and resets the module reference to None."""
        pool = _mock_pool()
        database.set_pool(pool)

        await database.close_pool()

        pool.close.assert_awaited_once()
        with pytest.raises(RuntimeError, match="Database pool not initialised"):
            database.get_pool()


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


class TestRunMigrations:
    @pytest.mark.asyncio
    async def test_applies_unapplied_migrations_in_order(self, tmp_path: Path):
        """Runs SQL files in lexicographic order and records each version."""
        # Write two migration files
        (tmp_path / "001_create_users.sql").write_text("CREATE TABLE users (id INT);")
        (tmp_path / "002_create_posts.sql").write_text("CREATE TABLE posts (id INT);")

        pool = _mock_pool()
        conn = pool.acquire().__aenter__.return_value

        # No migrations applied yet
        conn.fetch = AsyncMock(return_value=[])

        await database.run_migrations(pool, tmp_path)

        # Collect all SQL statements executed via conn.execute
        executed_sql = [str(call) for call in conn.execute.call_args_list]

        # Should have: CREATE IF NOT EXISTS schema_migrations, then for each migration:
        #   the migration SQL + the INSERT INTO schema_migrations
        # Verify both migration SQL statements were executed
        assert any("CREATE TABLE users" in sql for sql in executed_sql)
        assert any("CREATE TABLE posts" in sql for sql in executed_sql)
        # Verify version recording
        assert any("001_create_users" in sql for sql in executed_sql)
        assert any("002_create_posts" in sql for sql in executed_sql)

    @pytest.mark.asyncio
    async def test_skips_already_applied_migrations(self, tmp_path: Path):
        """Migrations whose version is already in schema_migrations are skipped."""
        (tmp_path / "001_create_users.sql").write_text("CREATE TABLE users (id INT);")
        (tmp_path / "002_create_posts.sql").write_text("CREATE TABLE posts (id INT);")

        pool = _mock_pool()
        conn = pool.acquire().__aenter__.return_value

        # Simulate that migration 001 was already applied
        already_applied = [{"version": "001_create_users"}]
        conn.fetch = AsyncMock(return_value=already_applied)

        # Mock the transaction context manager on the connection
        tx_ctx = AsyncMock()
        tx_ctx.__aenter__ = AsyncMock()
        tx_ctx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx_ctx)

        await database.run_migrations(pool, tmp_path)

        executed_sql = [str(call) for call in conn.execute.call_args_list]

        # 001 should NOT be executed (already applied)
        assert not any("CREATE TABLE users" in sql for sql in executed_sql)
        # 002 SHOULD be executed
        assert any("CREATE TABLE posts" in sql for sql in executed_sql)
        assert any("002_create_posts" in sql for sql in executed_sql)


# ---------------------------------------------------------------------------
# create_pool: fresh-database pgvector bootstrap
# ---------------------------------------------------------------------------


class TestCreatePoolBootstrap:
    @pytest.mark.asyncio
    async def test_ensures_vector_extension_before_pool(self):
        """create_pool must CREATE EXTENSION IF NOT EXISTS vector first.

        The pool's init callback registers the pgvector codec, which fails
        on a fresh database where migration 001 (which creates the
        extension) has not run yet — and can't, without a pool.
        """
        boot_conn = MagicMock()
        boot_conn.execute = AsyncMock()
        boot_conn.close = AsyncMock()

        call_order = []
        boot_conn.execute.side_effect = lambda sql: call_order.append("extension") or None

        async def fake_create_pool(*args, **kwargs):
            call_order.append("pool")
            return _mock_pool()

        with patch.object(database.asyncpg, "connect", AsyncMock(return_value=boot_conn)), \
             patch.object(database.asyncpg, "create_pool", side_effect=fake_create_pool):
            await database.create_pool("postgresql://example/fresh")

        boot_conn.execute.assert_awaited_once_with("CREATE EXTENSION IF NOT EXISTS vector")
        boot_conn.close.assert_awaited_once()
        assert call_order == ["extension", "pool"]

    @pytest.mark.asyncio
    async def test_bootstrap_failure_does_not_block_pool_creation(self):
        """A permission error on CREATE EXTENSION is logged, not fatal."""
        async def fake_create_pool(*args, **kwargs):
            return _mock_pool()

        with patch.object(database.asyncpg, "connect", AsyncMock(side_effect=RuntimeError("no perms"))), \
             patch.object(database.asyncpg, "create_pool", side_effect=fake_create_pool):
            pool = await database.create_pool("postgresql://example/fresh")

        assert pool is not None
