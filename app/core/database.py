from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

from app.core.config import get_settings


_pool: asyncpg.Pool | None = None


def get_database_url() -> str:
    database_url = get_settings().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")

    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if database_url.startswith("postgres+asyncpg://"):
        return database_url.replace("postgres+asyncpg://", "postgres://", 1)

    return database_url


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=get_database_url())
    return _pool


@asynccontextmanager
async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    pool = await get_pool()
    async with pool.acquire() as connection:
        yield connection


async def close_db_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_db() -> None:
    async with get_connection() as connection:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                full_name TEXT,
                avatar_url TEXT,
                password_hash TEXT,
                google_sub TEXT UNIQUE,
                auth_provider TEXT NOT NULL DEFAULT 'email',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)"
        )
