"""アプリ所有テーブル用の async engine / session factory。

ADK 側（`DatabaseSessionService`）は自分自身で別の engine を内部的に
持つため、ここで作る engine・セッションはアプリ所有テーブル
（conversations / messages）専用と考えてよい。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.services.db.models import Base


def create_engine(database_url: str) -> AsyncEngine:
    """DSN から async engine を作る。

    lifespan で 1 度だけ呼び出し、アプリ終了まで使い回す想定
    （リクエストごとに engine を作るとコネクションプールの利点が失われる）。
    """
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """engine から session factory を作る。"""
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine: AsyncEngine) -> None:
    """アプリ所有テーブルを作成する。

    マイグレーションツール（Alembic 等）を導入する代わりに、起動時に
    `create_all` 相当の処理を行う簡易運用。本番ではマイグレーションツールに
    置き換えることを想定している。ADK 所有テーブルはここでは一切作らない
    （ADK 側が自分の `DatabaseSessionService` 初期化時に作成する）。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """1 トランザクション分のセッションを提供する。

    例外時は rollback、正常終了時は commit まで面倒を見る。呼び出し側で
    commit を書き忘れる事故を防ぐために薄いラッパにしている。
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
