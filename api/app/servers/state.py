"""FastAPI `app.state` に載せる、型付きの起動時共有オブジェクト。

Starlette の `State` は動的属性アクセス（実質 `Any`）のため、strict mypy の
下でそのまま `request.app.state.xxx` を型付きで使うのは難しい。ここでは
実体を 1 つの dataclass にまとめ、`app.state.app_state` という単一属性として
ぶら下げることで、`cast` を 1 箇所（`get_app_state`）に閉じ込める。

lifespan で 1 度だけ組み立て、全リクエストで使い回す（engine・runtime を
リクエストごとに作らないため）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.types.agent_runtime import ChatAgentRuntime


@dataclass
class AppState:
    """lifespan で構築し、リクエスト処理全体で共有する値。"""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    runtime: ChatAgentRuntime


def get_app_state(request: Request) -> AppState:
    """`request.app.state.app_state` を型付きで取り出す。

    テストでは lifespan を走らせず、ここに直接 `AppState`（フェイク
    runtime・SQLite session_factory）をセットして差し替える。
    """
    return cast(AppState, request.app.state.app_state)
