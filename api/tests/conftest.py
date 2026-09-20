"""pytest 共通フィクスチャ。

DB は SQLite（一時ファイル）、エージェント層は `FakeChatAgentRuntime` に
差し替える。ネットワーク・LLM には一切触れない。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest_asyncio
from app.config import Settings
from app.servers.api import create_app
from app.servers.state import AppState
from app.services.db import create_engine, create_session_factory, init_models
from app.services.storage import LocalFileStorage
from httpx import ASGITransport, AsyncClient

from tests.fakes import FakeChatAgentRuntime


@asynccontextmanager
async def make_client(
    tmp_path: Path,
    runtime: FakeChatAgentRuntime | None = None,
    settings_overrides: dict[str, object] | None = None,
) -> AsyncIterator[tuple[AsyncClient, AppState]]:
    """SQLite（一時ファイル）+ フェイクランタイムでアプリを組み立てる。

    `ASGITransport` は ASGI の lifespan イベントを送らないため、本物の
    lifespan（DB init・agents ロード）は実行されない。その代わりここで
    `app.state.app_state` を直接差し替えることで、DI ポイントを経由した
    テストダブルの注入を実現する。

    `settings_overrides` は、アップロード上限のテスト（例: 極端に小さい
    `upload_max_file_bytes` を設定して 413 を再現する）のために、既定の
    `Settings` の一部だけを差し替えたいケース向け。
    """
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(database_url)
    await init_models(engine)
    session_factory = create_session_factory(engine)
    settings = Settings(database_url=database_url)
    for key, value in (settings_overrides or {}).items():
        setattr(settings, key, value)
    state = AppState(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        runtime=runtime if runtime is not None else FakeChatAgentRuntime(),
        storage=LocalFileStorage(tmp_path / "storage"),
    )

    app = create_app()
    app.state.app_state = state

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, state
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client_and_state(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, AppState]]:
    """デフォルトのフェイクランタイムでアプリを組み立てる標準フィクスチャ。"""
    async with make_client(tmp_path) as pair:
        yield pair


@pytest_asyncio.fixture
async def client(client_and_state: tuple[AsyncClient, AppState]) -> AsyncClient:
    """会話 CRUD 系のテストで runtime を意識しない場合の簡易フィクスチャ。"""
    http_client, _state = client_and_state
    return http_client
