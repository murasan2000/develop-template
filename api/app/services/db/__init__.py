"""アプリ所有テーブル（conversations / messages）の DB アクセス層。

ADK 所有テーブルとは別系統であることに注意（`models.py` のモジュール docstring 参照）。
"""

from app.services.db.engine import (
    create_engine,
    create_session_factory,
    init_models,
    session_scope,
)
from app.services.db.models import Base, Conversation, FileRecord, Message

__all__ = [
    "Base",
    "Conversation",
    "FileRecord",
    "Message",
    "create_engine",
    "create_session_factory",
    "init_models",
    "session_scope",
]
