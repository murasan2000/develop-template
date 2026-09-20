"""会話・メッセージ（アプリ所有テーブル）に対するリポジトリ層。

ここでの「メッセージ」は UI が表示する履歴であり、ADK がセッション内部で
保持する会話コンテキストとは別物（`app/services/db/models.py` 参照）。
API 層（`servers/api.py`）はこのモジュール経由でのみ DB を操作し、
SQLAlchemy の詳細（クエリの組み立て方など）を意識しなくて済むようにする。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.chat.titles import DEFAULT_CONVERSATION_TITLE
from app.services.db.models import Conversation, FileRecord, Message


async def create_conversation(session: AsyncSession, title: str | None) -> Conversation:
    """会話を新規作成する。タイトル未指定時はデフォルトタイトルを使う。"""
    conversation = Conversation(title=title or DEFAULT_CONVERSATION_TITLE)
    session.add(conversation)
    await session.flush()
    return conversation


async def list_conversations(session: AsyncSession) -> list[Conversation]:
    """会話一覧を `updated_at` 降順で返す。"""
    stmt = select(Conversation).order_by(Conversation.updated_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_conversation(
    session: AsyncSession, conversation_id: uuid.UUID
) -> Conversation | None:
    """会話 1 件を取得する（メッセージは含まない）。"""
    return await session.get(Conversation, conversation_id)


async def get_conversation_with_messages(
    session: AsyncSession, conversation_id: uuid.UUID
) -> Conversation | None:
    """会話 1 件をメッセージ込みで取得する。

    `selectinload` で N+1 を避ける（`messages` は `created_at` 順に
    並ぶようリレーション側で `order_by` 済み）。`Message.attachments` も
    合わせて先読みする——**入れ忘れると非同期セッションでは lazy load が
    例外になる**（`AsyncSession` はリクエスト外で暗黙のクエリを発行できない）
    ため、`messages` を辿るときは必ずセットで指定する。
    """
    stmt = (
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages).selectinload(Message.attachments))
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def delete_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> bool:
    """会話を削除する。メッセージ・添付ファイル行は ORM の cascade で一緒に消える。

    DB 側の `ON DELETE CASCADE` にも同じ意図で設定しているが、SQLite は
    既定で外部キー制約を強制しないため、バックエンド非依存で確実に消すには
    ORM レベルの cascade（`delete-orphan`）に頼る方が安全。

    添付ファイルの**実体**（`storage/` 上のファイル）は DB 行と違って
    ORM cascade では消えないため、呼び出し元（`app/servers/api.py`）が
    削除前に `storage_key` を集め、DB コミット成功後にベストエフォートで
    `FileStorage.delete` を呼ぶ必要がある。そのための一覧をここで返す。
    """
    conversation = await session.get(
        Conversation,
        conversation_id,
        options=[selectinload(Conversation.messages).selectinload(Message.attachments)],
    )
    if conversation is None:
        return False
    await session.delete(conversation)
    await session.flush()
    return True


async def collect_attachment_storage_keys(
    session: AsyncSession, conversation_id: uuid.UUID
) -> list[str]:
    """会話に属する全メッセージの添付ファイルの `storage_key` を集める。

    `delete_conversation` の**前**に呼ぶこと（削除後は当然辿れない）。
    実体削除は DB トランザクションの外（コミット後）で行うため、キーの
    収集とファイル実体の削除を分離できるようにこの関数を独立させている。
    """
    stmt = (
        select(FileRecord.storage_key)
        .join(Message, FileRecord.message_id == Message.id)
        .where(Message.conversation_id == conversation_id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def add_message(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    *,
    attachments: Sequence[FileRecord] | None = None,
) -> Message:
    """メッセージを 1 件追加する。

    `attachments` は**必ずコンストラクタ引数として**（後から
    `message.attachments = ...` を代入するのではなく）渡す。理由:
    `AsyncSession` はまだ一度もロードしていない関連コレクションを、後から
    上書き代入すると「以前の内容との差分を取るために現在の子集合を読む」
    暗黙の SELECT を発行しようとし、これが同期的な greenlet コンテキスト外で
    起きて `MissingGreenlet` エラーになる。作成時（オブジェクトがまだ
    transient で、DB 上に「以前の状態」が存在しない）にコレクションを渡せば、
    この差分読み込みが発生せず安全。渡さなければ空リストになり、その場でもう
    `attachments` 属性が「ロード済み・空」の状態になるため、直後に
    `MessageOut.model_validate(message)` で読んでも lazy load 例外にならない。
    """
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        attachments=list(attachments) if attachments else [],
    )
    session.add(message)
    await session.flush()
    return message


async def touch_conversation(
    session: AsyncSession,
    conversation: Conversation,
    *,
    new_title: str | None = None,
) -> None:
    """応答完了後に会話のメタ情報を更新する。

    `updated_at` を更新して一覧の並び順に反映させる。`new_title` が
    渡された場合はタイトルも差し替える（未設定タイトルへの自動命名用）。
    """
    conversation.updated_at = datetime.now(UTC)
    if new_title is not None:
        conversation.title = new_title
    await session.flush()
