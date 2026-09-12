"""API 境界（リクエスト/レスポンス）の Pydantic 型。

`docs/api-contract.md` のスキーマ定義をそのまま型に落としたもの。フロントエンド
と合意した形なので、フィールド名・型は契約書と 1 対 1 で対応させること。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

Role = Literal["user", "assistant"]

# クライアントが「再送を勧めるか」を判断するための機械可読コード。
# `model_overloaded`/`rate_limited` は再送で直る見込みがあるが、
# `model_unavailable`（設定不備）は再送しても無駄、`internal` はそれ以外。
ErrorCode = Literal["model_overloaded", "rate_limited", "model_unavailable", "internal"]


def _ensure_utc(value: datetime) -> datetime:
    """naive な datetime は UTC とみなし、常に tz-aware な UTC に揃える。

    `sa.DateTime(timezone=True)` は DB 方言によって読み戻し後の tzinfo の
    有無が割れる（SQLite は naive に落ちる／PostgreSQL の timestamptz は
    aware のまま）。書き込みは常に UTC aware で行っている前提なので、
    naive な値は UTC とみなしてよい。DB 方言の違いを
    `docs/api-contract.md` の契約（"ISO 8601 (UTC)"、常に `Z`/`+00:00`
    付き）に漏らさないよう、DB の値を直接返さずこの API 境界で正規化する。
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class ConversationOut(BaseModel):
    """会話（一覧・詳細で共通して使うレスポンス表現）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def _normalize_timezone(cls, value: datetime) -> datetime:
        return _ensure_utc(value)


class MessageOut(BaseModel):
    """メッセージ 1 件のレスポンス表現。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: Role
    content: str
    created_at: datetime

    @field_validator("created_at", mode="after")
    @classmethod
    def _normalize_timezone(cls, value: datetime) -> datetime:
        return _ensure_utc(value)


class ConversationDetail(BaseModel):
    """会話 1 件＋メッセージ全件。"""

    conversation: ConversationOut
    messages: list[MessageOut]


class HealthResponse(BaseModel):
    """ヘルスチェック応答。"""

    status: Literal["ok"] = "ok"
    model: str
    database: Literal["ok", "error"]


class CreateConversationRequest(BaseModel):
    """会話新規作成のリクエストボディ。"""

    title: str | None = None


class SendMessageRequest(BaseModel):
    """メッセージ送信のリクエストボディ。"""

    content: str


class DoneEventPayload(BaseModel):
    """SSE `done` イベントの data。確定した assistant メッセージ＋更新後タイトル。"""

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: Role
    content: str
    created_at: datetime
    title: str

    @field_validator("created_at", mode="after")
    @classmethod
    def _normalize_timezone(cls, value: datetime) -> datetime:
        # ConversationOut/MessageOut と同じ理由（DB 方言差を契約に漏らさない）。
        return _ensure_utc(value)


class DeltaEventPayload(BaseModel):
    """SSE `delta` イベントの data。応答の増分テキスト。"""

    text: str


class ErrorEventPayload(BaseModel):
    """SSE `error` イベントの data。

    `message` はそのまま画面に出せる日本語（プロバイダの生ペイロードを含めない）。
    `code` はクライアントが再送を勧めるかどうかの判断材料
    （`app/utils/errors.py::to_user_facing_error` が変換する）。
    """

    message: str
    code: ErrorCode
