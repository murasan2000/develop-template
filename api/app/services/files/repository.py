"""ファイル置き場（`files` テーブル）のメタデータに対する DB アクセス層。

`app/services/chat/repository.py` と同じ粒度で、SQLAlchemy の詳細
（クエリの組み立て方など）をここに閉じる。実体（バイト列）の保存・削除は
一切行わない（それは `FileStorage` の責務）。呼び出し元（`app/servers/api.py`）
が DB 操作と `FileStorage` 呼び出しを組み合わせる。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.db.models import FileRecord, Message


async def create_file_record(
    session: AsyncSession,
    *,
    file_id: uuid.UUID,
    purpose: str,
    filename: str,
    mime_type: str,
    size_bytes: int,
    storage_key: str,
) -> FileRecord:
    """ファイル 1 件のメタデータ行を作成する（`message_id` は未紐付けの `None`）。

    `file_id` を呼び出し元から受け取る（自動生成に任せない）のは、
    ストレージ上のキー（`<purpose>/<uuid>/<filename>`）を DB 書き込みより
    前に組み立てて先に実体を保存する必要があり、その UUID と DB 行の
    `id` を一致させたいため。
    """
    record = FileRecord(
        id=file_id,
        purpose=purpose,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        storage_key=storage_key,
    )
    session.add(record)
    await session.flush()
    return record


async def get_file_record(session: AsyncSession, file_id: uuid.UUID) -> FileRecord | None:
    """ファイル 1 件を取得する。"""
    return await session.get(FileRecord, file_id)


async def get_files_by_ids(
    session: AsyncSession, file_ids: Sequence[uuid.UUID]
) -> list[FileRecord]:
    """`file_ids` に含まれるファイルを（添付状態を問わず）取得する。

    `send_message` の添付検証は「存在しない ID → 404」「既に別メッセージへ
    添付済みの ID → 409」を区別する必要があるため、あえて絞り込まず全件
    返す（呼び出し側で `message_id` の有無を見て 404/409 を判定する）。
    """
    if not file_ids:
        return []
    stmt = select(FileRecord).where(FileRecord.id.in_(file_ids))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def attach_files_to_message(
    session: AsyncSession, message: Message, files: Sequence[FileRecord]
) -> None:
    """ファイル群を 1 件のメッセージに紐付ける。

    `FileRecord.message_id` を直接代入するのではなく、リレーションシップの
    コレクション（`message.attachments`）へ代入する。こうすると ORM が
    `back_populates` で双方向を自動的に同期するため、この呼び出しの直後に
    `message.attachments` を読んでも（`AsyncSession` は明示的にロードして
    いない関連の lazy load を許さないため）追加のクエリなしに正しい値が
    見える。
    """
    message.attachments = list(files)
    await session.flush()


async def delete_file_record(session: AsyncSession, file_record: FileRecord) -> None:
    """ファイルのメタデータ行を削除する。実体の削除は呼び出し元の責務。"""
    await session.delete(file_record)
    await session.flush()


async def list_orphan_file_records(session: AsyncSession, older_than: datetime) -> list[FileRecord]:
    """どのメッセージにも紐付いておらず、`older_than` より古いファイルを列挙する。

    孤児ファイルの掃除（D2-2）用。呼び出し元がこの一覧を使って
    `FileStorage.delete` と `delete_file_record` を順に呼ぶ。
    """
    stmt = select(FileRecord).where(
        FileRecord.message_id.is_(None), FileRecord.created_at < older_than
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
