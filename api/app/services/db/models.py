"""アプリ所有テーブルの SQLAlchemy モデル。

ここで定義するのは「UI が読む会話履歴」（conversations / messages）だけ。
ADK の `DatabaseSessionService` が同じ PostgreSQL に自動生成するテーブル
（エージェントの内部状態・作業記憶）とは完全に別系統であり、本アプリの
コードからは一切触らない。表示用の履歴＝アプリ、エージェントの内部状態＝ADK
という分離がこのテンプレートの設計意図であるため、混同しないこと。

スキーマの唯一の定義はこの SQLAlchemy モデルであり、起動時に
`Base.metadata.create_all` 相当（`conn.run_sync`）でテーブルを作成する。
マイグレーションツールは導入していない。本番運用では Alembic 等の
マイグレーションツールに置き換えることを想定している。

型は PostgreSQL 固有の型（例: `sqlalchemy.dialects.postgresql.UUID`）を
使わず、`sa.Uuid` / `sa.Text` / `sa.DateTime(timezone=True)` のような
標準型のみを使う。これによりテストを SQLite（aiosqlite）で実行できる。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """アプリ所有テーブル用の宣言的ベースクラス。"""


def _utcnow() -> datetime:
    """DB 側の `now()` 方言差（PostgreSQL/SQLite）を避け、Python 側で統一する。"""
    return datetime.now(UTC)


class Conversation(Base):
    """会話（チャットスレッド）。"""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    """会話内の 1 発言（user または assistant）。"""

    __tablename__ = "messages"
    __table_args__ = (
        # 会話詳細取得時は「conversation_id で絞って created_at 順に並べる」が
        # 主なアクセスパターンなので、複合インデックスをこの順で張る。
        sa.Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
