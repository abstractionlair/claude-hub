"""asyncpg connection pool and migration runner."""

import logging
from pathlib import Path

import asyncpg
from pgvector.asyncpg import register_vector

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


def get_pool() -> asyncpg.Pool:
    """Return the module-level pool, or raise if not yet initialised."""
    if _pool is None:
        raise RuntimeError("Database pool not initialised — call set_pool() first")
    return _pool


def set_pool(pool: asyncpg.Pool) -> None:
    """Set the module-level pool."""
    global _pool
    _pool = pool


async def close_pool() -> None:
    """Close the pool and clear the module-level reference."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Per-connection init callback: register pgvector type and set HNSW search params."""
    await register_vector(conn)
    await conn.execute("SET hnsw.ef_search = 64")


async def create_pool(dsn: str) -> asyncpg.Pool:
    """Create an asyncpg connection pool sized for a 4 GB VPS.

    Args:
        dsn: PostgreSQL connection string (e.g. ``postgresql://user:pass@host/db``).

    Returns:
        A ready-to-use :class:`asyncpg.Pool`.
    """
    pool = await asyncpg.create_pool(
        dsn,
        min_size=2,
        max_size=10,
        command_timeout=30,
        init=_init_connection,
    )
    logger.info("Database pool created (min=2, max=10)")
    return pool


async def run_migrations(pool: asyncpg.Pool, migrations_dir: Path) -> None:
    """Apply unapplied SQL migrations in order.

    Reads ``migrations_dir/*.sql``, sorts them lexicographically, and runs each
    file whose version (filename stem) is not yet recorded in the
    ``schema_migrations`` table.  Each migration runs inside its own
    transaction.

    Args:
        pool: An asyncpg connection pool.
        migrations_dir: Directory containing numbered ``*.sql`` files.
    """
    async with pool.acquire() as conn:
        # Ensure the tracking table exists (idempotent).
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

        applied: set[str] = {
            row["version"]
            for row in await conn.fetch("SELECT version FROM schema_migrations")
        }

    migration_files = sorted(migrations_dir.glob("*.sql"))

    for path in migration_files:
        version = path.stem
        if version in applied:
            logger.debug("Migration %s already applied, skipping", version)
            continue

        sql = path.read_text(encoding="utf-8")
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)",
                    version,
                )
        logger.info("Applied migration %s", version)
