"""FastAPI アプリ本体・エンドポイント・lifespan。

`uvicorn app.servers.api:app` で起動する（Dockerfile 参照）。
"""

from __future__ import annotations

import importlib
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast

import anyio
import sqlalchemy as sa
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.servers.state import AppState, get_app_state
from app.services import chat as chat_service
from app.services import files as files_service
from app.services.db import (
    FileRecord,
    Message,
    create_engine,
    create_session_factory,
    init_models,
    session_scope,
)
from app.services.storage import LocalFileStorage
from app.types.agent_runtime import ChatAgentRuntime
from app.types.api import (
    ConversationDetail,
    ConversationOut,
    CreateConversationRequest,
    DoneEventPayload,
    ErrorEventPayload,
    FileOut,
    HealthResponse,
    MessageOut,
    SendMessageRequest,
)
from app.types.attachments import AgentAttachment
from app.types.file_storage import FileStorage
from app.utils.errors import to_user_facing_error
from app.utils.files import (
    build_storage_key,
    content_disposition_header,
    resolve_mime_type,
    sanitize_filename,
)
from app.utils.sse import format_sse

logger = logging.getLogger(__name__)

# エージェント層 (`app/services/agents/`) が提供するはずのファクトリのシグネチャ。
# `docs/api-contract.md` の契約をこちら側の型として持つ（実装未完でも型チェックが
# 独立して成立するように、具象は import せず Protocol/Callable で表現する）。
CreateChatRuntime = Callable[..., Coroutine[Any, Any, ChatAgentRuntime]]


def _load_create_chat_runtime() -> CreateChatRuntime:
    """`app.services.agents.create_chat_runtime` を実行時に取得する。

    `app/services/agents/` は別エージェントが並行実装中で、このファイルを
    書いている時点ではまだ存在しない可能性がある。トップレベルで
    `from app.services.agents import create_chat_runtime` すると、agents が
    未実装の間は import 自体が失敗し、pytest・mypy・ruff といった他の検証まで
    巻き込んで壊れてしまう。実際にサーバを起動する（lifespan が呼ばれる）
    タイミングまで解決を遅らせることで、テストは常にフェイクランタイムを
    注入して agents に触れずに完走できる。
    """
    module = importlib.import_module("app.services.agents")
    factory = getattr(module, "create_chat_runtime", None)
    if factory is None:
        raise RuntimeError(
            "app.services.agents.create_chat_runtime が見つかりません。"
            "エージェント層の実装待ちです（docs/api-contract.md 参照）。"
        )
    return cast(CreateChatRuntime, factory)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """起動時に engine・runtime を 1 度だけ作り、終了時に解放する。

    ADK の Runner はステートレスで共有前提のため、リクエストごとに
    作り直さない（コネクション/セッションのオーバーヘッドを避ける）。
    """
    settings = get_settings()
    engine = create_engine(settings.database_url)
    # スキーマの唯一の定義は SQLAlchemy モデル（app/services/db/models.py）。
    # マイグレーションツールは導入しておらず、本番では Alembic 等に置き換える想定。
    # ここで作るのはアプリ所有テーブルのみで、ADK 所有テーブルは
    # create_chat_runtime 側（DatabaseSessionService の初期化）が自分で作る。
    await init_models(engine)
    session_factory = create_session_factory(engine)

    storage = LocalFileStorage(settings.storage_path)
    # 起動時に 1 回だけ、孤児ファイル（どのメッセージにも紐付かないまま
    # TTL を過ぎたアップロード）を掃除する（D2-2/3）。**この方式の限界**:
    # 常駐のバックグラウンドタスクは持たないので、長時間動き続けるプロセス
    # では起動後に生まれた孤児は掃除されない。`create_all` をマイグレーション
    # の代わりにしているのと同種の、テンプレートとしての割り切り。
    # 本番運用ではスケジューラ／cron ジョブに置き換えること。
    await _sweep_orphan_files(session_factory, storage, settings.orphan_file_ttl_hours)

    create_chat_runtime = _load_create_chat_runtime()
    runtime = await create_chat_runtime(
        database_url=settings.database_url,
        model=settings.gemini_model,
        app_name="chat-template",
        # ADK は `Agent.retry_config` を設定しないと 503（モデル混雑）等を
        # 一切リトライしない。ここに例外が届く時点で「ADK がリトライを使い
        # 切った後」の意味になるため、API 層側では追加のリトライをしない
        # （二重リトライを避ける）。
        max_retry_attempts=settings.agent_retry_max_attempts,
    )

    app.state.app_state = AppState(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        runtime=runtime,
        storage=storage,
    )
    try:
        yield
    finally:
        await runtime.aclose()
        await engine.dispose()


async def _sweep_orphan_files(
    session_factory: async_sessionmaker[AsyncSession],
    storage: FileStorage,
    ttl_hours: int,
) -> None:
    """どのメッセージにも紐付いていない、TTL より古いファイルを削除する。

    実体（`storage.delete`）→ DB 行の順で削除する。実体を消す前に DB 行を
    消してしまうと、途中で失敗したときに「メタデータは無いのに実体だけ残る」
    孤児が生まれてしまうため。
    """
    cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
    async with session_factory() as session:
        orphans = await files_service.list_orphan_file_records(session, cutoff)
        for record in orphans:
            await storage.delete(record.storage_key)
            await files_service.delete_file_record(session, record)
        await session.commit()


router = APIRouter(prefix="/api")


def create_app() -> FastAPI:
    """アプリを組み立てる。テストからも呼べるようファクトリ関数にしている。"""
    settings = get_settings()
    app = FastAPI(title="Chat Template API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """通常の CRUD エンドポイント用の DB セッション依存性。

    SSE エンドポイント（メッセージ送信）ではこれを使わない。Starlette/FastAPI は
    `yield` 付き依存性のクリーンアップを、エンドポイント関数が `StreamingResponse`
    オブジェクトを返した直後に行うため、ストリーム本体がまだ送信されている間に
    セッションが閉じてしまう可能性がある。SSE 側は `AppState.session_factory` から
    都度セッションを自前で開閉することでこれを避ける。
    """
    state = get_app_state(request)
    async with session_scope(state.session_factory) as session:
        yield session


# `Depends(get_session)` を各シグネチャの引数デフォルトに直接書くと ruff(B008)
# に引っかかる（引数デフォルトでの関数呼び出しは可変デフォルト引数の事故が
# 起きやすいため警告される）ため、モジュール変数に一度だけ束ねておく。
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    """DB 接続とモデル名を返すヘルスチェック。"""
    state = get_app_state(request)
    database: Literal["ok", "error"]
    try:
        async with state.session_factory() as session:
            await session.execute(sa.text("SELECT 1"))
        database = "ok"
    except Exception:  # DB 障害を "error" として返すための意図的な broad catch
        database = "error"
    return HealthResponse(model=state.runtime.model_name, database=database)


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(session: SessionDep) -> list[ConversationOut]:
    conversations = await chat_service.list_conversations(session)
    return [ConversationOut.model_validate(c) for c in conversations]


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(
    body: CreateConversationRequest, session: SessionDep
) -> ConversationOut:
    conversation = await chat_service.create_conversation(session, body.title)
    return ConversationOut.model_validate(conversation)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: uuid.UUID, session: SessionDep) -> ConversationDetail:
    conversation = await chat_service.get_conversation_with_messages(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationDetail(
        conversation=ConversationOut.model_validate(conversation),
        messages=[MessageOut.model_validate(m) for m in conversation.messages],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, request: Request) -> None:
    """会話を削除する。メッセージ・添付のメタデータは DB cascade で消える。

    添付ファイルの**実体**は ORM cascade の対象外（`storage/` 上のファイル）
    なので、削除前に `storage_key` を集めておき、DB コミットが成功した後に
    ベストエフォートで実体を削除する（D2）。ここで実体削除に使う `session`
    を `SessionDep` ではなく自前で開閉するのは、「コミット成功後」という
    タイミングを明示的に扱いたいため（`SessionDep` はコミットをリクエスト
    終了時の後処理に委ねるため、この位置に割り込めない）。
    """
    state = get_app_state(request)
    async with state.session_factory() as session:
        storage_keys = await chat_service.collect_attachment_storage_keys(session, conversation_id)
        deleted = await chat_service.delete_conversation(session, conversation_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="conversation not found")
        await session.commit()

    for storage_key in storage_keys:
        try:
            await state.storage.delete(storage_key)
        except Exception:
            # 実体の削除に失敗してもユーザーに見える壊れ方はしない
            # （ディスクにゴミが残るだけ）一方、ここで例外にすると会話削除
            # そのものが失敗してしまう。この非対称性から握りつぶして warning
            # ログに残すに留める（D2）。
            logger.warning(
                "failed to delete attachment file after conversation deletion: "
                "conversation_id=%s storage_key=%s",
                conversation_id,
                storage_key,
                exc_info=True,
            )


# アップロード読み取りの 1 チャンクあたりのサイズ。読みながら上限を検査する
# ため、上限を大きく超えるファイルでもメモリに載るのはこのチャンク分だけに
# 抑えられる（先に全部読んでから測るとメモリ枯渇の経路になる）。
_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024


@router.post("/files", response_model=FileOut, status_code=201)
async def upload_file(
    request: Request,
    file: Annotated[UploadFile, File()],
) -> FileOut:
    """ファイルを 1 件アップロードする。

    サイズ・MIME タイプの検証をここで完結させる（D1: アップロードは送信とは
    別エンドポイントにすることで、413/415/400 を通常の HTTP ステータスで
    即座に返せる）。`purpose` は常にサーバが `"uploads"` と決める
    （クライアントに `generated` を作らせない。`generated` は将来のサーバ側
    ツール専用の予約区分）。
    """
    state = get_app_state(request)
    settings = state.settings

    sanitized_name = sanitize_filename(file.filename or "")
    mime_type = resolve_mime_type(file.content_type, sanitized_name)
    allowed = settings.allowed_mime_type_list
    if allowed and mime_type not in allowed:
        raise HTTPException(status_code=415, detail="unsupported file type")

    max_bytes = settings.upload_max_file_bytes
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = await file.read(_UPLOAD_READ_CHUNK_BYTES)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise HTTPException(status_code=413, detail="file too large")
        chunks.append(chunk)
    if total_bytes == 0:
        raise HTTPException(status_code=400, detail="empty file")
    data = b"".join(chunks)

    file_id = uuid.uuid4()
    storage_key = build_storage_key("uploads", str(file_id), sanitized_name)
    await state.storage.save(storage_key, data)

    try:
        async with state.session_factory() as session:
            record = await files_service.create_file_record(
                session,
                file_id=file_id,
                purpose="uploads",
                filename=sanitized_name,
                mime_type=mime_type,
                size_bytes=total_bytes,
                storage_key=storage_key,
            )
            await session.commit()
            file_out = FileOut.model_validate(record)
    except Exception:
        # 実体の保存には成功したが DB へのメタデータ保存に失敗した場合。
        # ここで実体を削除せずに re-raise すると、DB に存在しないのに
        # `storage/` にだけファイルが残る孤児を作ってしまう。
        await state.storage.delete(storage_key)
        raise

    return file_out


@router.get("/files/{file_id}/content")
async def download_file(
    file_id: uuid.UUID, session: SessionDep, request: Request
) -> StreamingResponse:
    """ファイル本体をダウンロードする。

    D7: 保存型 XSS 対策として、常にダウンロード用のヘッダを付ける
    （`<img src>` のようなサブリソース読み込みは `Content-Disposition` を
    無視するため、画像プレビューへの埋め込みは影響を受けない）。
    """
    state = get_app_state(request)
    record = await files_service.get_file_record(session, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="file not found")

    try:
        stream = state.storage.open_stream(record.storage_key)
    except FileNotFoundError:
        # DB にメタデータは残っているが実体が無い場合も 404 として扱う。
        raise HTTPException(status_code=404, detail="file not found") from None

    headers = {
        "Content-Disposition": content_disposition_header(record.filename),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, max-age=3600",
    }
    return StreamingResponse(stream, media_type=record.mime_type, headers=headers)


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(file_id: uuid.UUID, session: SessionDep, request: Request) -> None:
    """未添付のファイルを削除する。既にメッセージへ添付済みなら 409。

    1 ファイルは 1 メッセージにしか属せない設計（D9 参照）なので、添付済み
    ファイルの削除を許すと、そのメッセージの履歴が指すファイルが失われる。
    """
    state = get_app_state(request)
    record = await files_service.get_file_record(session, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="file not found")
    if record.message_id is not None:
        raise HTTPException(status_code=409, detail="file already attached to a message")

    # 実体 → DB 行の順に削除する（DB 行を先に消すと、途中で失敗したときに
    # 「メタデータは無いのに実体だけ残る」孤児が生まれてしまうため）。
    await state.storage.delete(record.storage_key)
    await files_service.delete_file_record(session, record)


async def _persist_assistant_reply(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    content: str,
    new_title: str | None,
) -> tuple[Message, str]:
    """assistant メッセージを保存し、会話の `updated_at`/タイトルを更新する。

    正常完了・エージェント側の例外・クライアントの切断という 3 つの経路
    すべてで使う共通処理。各経路は互いに排他（1 リクエストにつきどれか
    1 つしか通らない）なので、呼び出しは合計で高々 1 回になる。
    """
    async with session_factory() as session:
        assistant_message = await chat_service.add_message(
            session, conversation_id, "assistant", content
        )
        conv = await chat_service.get_conversation(session, conversation_id)
        final_title = new_title or chat_service.DEFAULT_CONVERSATION_TITLE
        if conv is not None:
            await chat_service.touch_conversation(session, conv, new_title=new_title)
            final_title = conv.title
        await session.commit()
    return assistant_message, final_title


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    request: Request,
) -> StreamingResponse:
    """ユーザー発言を保存し、エージェントの応答を SSE でストリームする。

    ステータスコードは常に 200（SSE を開始した後は HTTP ステータスを
    変更できないため、失敗は `error` イベントで表現する。詳細は
    `docs/api-contract.md` の SSE 節を参照）。
    """
    state = get_app_state(request)
    session_factory = state.session_factory
    settings = state.settings
    runtime = state.runtime
    user_id = state.settings.default_user_id

    content_text = body.content
    attachment_ids = body.attachment_ids

    # 添付の検証（存在・重複・件数・合計サイズ）はすべてストリーム開始前に
    # 行う。SSE を開始した後は HTTP ステータスを変えられないため。
    if not content_text.strip() and not attachment_ids:
        raise HTTPException(status_code=400, detail="content または attachment_ids が必要です")
    if len(attachment_ids) != len(set(attachment_ids)):
        raise HTTPException(status_code=400, detail="attachment_ids に重複があります")
    if len(attachment_ids) > settings.upload_max_files_per_message:
        raise HTTPException(status_code=400, detail="添付ファイルの件数が上限を超えています")

    # 会話の存在確認とユーザー発言の保存は、ストリーム開始"前"に行う。ここで
    # 404/409/400 を通常の JSON エラーとして返せるのは、まだ SSE を開始
    # していないため。
    async with session_factory() as session:
        conversation = await chat_service.get_conversation(session, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")

        attachment_records: list[FileRecord] = []
        if attachment_ids:
            found = await files_service.get_files_by_ids(session, attachment_ids)
            found_by_id = {record.id: record for record in found}
            missing_ids = [str(i) for i in attachment_ids if i not in found_by_id]
            if missing_ids:
                raise HTTPException(status_code=404, detail="attachment not found")
            already_attached_ids = [
                str(i) for i in attachment_ids if found_by_id[i].message_id is not None
            ]
            if already_attached_ids:
                raise HTTPException(
                    status_code=409, detail="attachment already attached to another message"
                )
            # リクエストで指定された順序を保つ（DB の取得順は保証されないため）。
            attachment_records = [found_by_id[i] for i in attachment_ids]
            total_attachment_bytes = sum(r.size_bytes for r in attachment_records)
            if total_attachment_bytes > settings.upload_max_total_bytes_per_message:
                raise HTTPException(
                    status_code=400, detail="添付ファイルの合計サイズが上限を超えています"
                )

        should_retitle = chat_service.is_default_title(conversation.title)
        # 添付はメッセージ作成のコンストラクタ引数として渡す
        # （`add_message` のコメント参照。後から代入すると AsyncSession で
        # `MissingGreenlet` になる）。
        user_message = await chat_service.add_message(
            session, conversation_id, "user", content_text, attachments=attachment_records
        )
        await session.commit()
        user_message_out = MessageOut.model_validate(user_message)

    # D8: 本文が空（添付のみ）のときは最初の添付のファイル名をタイトルの
    # 元にする。`derive_title_from_content` 自体は変更不要（空文字なら
    # デフォルトタイトルを返す既存挙動のままで良い）。
    title_source = content_text.strip() or (
        attachment_records[0].filename if attachment_records else ""
    )
    new_title = chat_service.derive_title_from_content(title_source) if should_retitle else None

    # ストレージからバイト列を読み、エージェント層へ渡す AgentAttachment を
    # 組み立てる。ここ（ストリーム開始前）で読むのは、`FileNotFoundError` が
    # 起きた場合に通常の HTTP エラー（500）を返せるようにするため。
    agent_attachments: list[AgentAttachment] = [
        AgentAttachment(
            filename=record.filename,
            mime_type=record.mime_type,
            size_bytes=record.size_bytes,
            data=await state.storage.load(record.storage_key),
        )
        for record in attachment_records
    ]

    async def event_stream() -> AsyncIterator[str]:
        yield format_sse("user", user_message_out.model_dump(mode="json"))

        collected = ""
        try:
            await runtime.ensure_session(str(conversation_id), user_id)
            async for delta in runtime.stream_reply(
                str(conversation_id), user_id, content_text, attachments=agent_attachments
            ):
                collected += delta
                yield format_sse("delta", {"text": delta})
        except (GeneratorExit, anyio.get_cancelled_exc_class()):
            # クライアントの切断（停止ボタン / タブを閉じる等）。Starlette は
            # クライアント切断を検知すると、このジェネレータに対して
            # `aclose()` を呼ぶ（内部的には現在の中断点へ `GeneratorExit` を
            # 送り込む）。切断の検知経路によっては、内部的に進行中のタスクが
            # キャンセルされたことで `CancelledError`（anyio 経由。asyncio
            # バックエンドでは `asyncio.CancelledError`）が飛んでくることも
            # あり、どちらも `BaseException` 派生のため上の `except Exception`
            # では捕まらない。
            #
            # また、ここで `yield` すると
            # `RuntimeError: async generator ignored GeneratorExit` になる
            # ため、SSE イベントは送らず保存のみ行う（クライアントは既に
            # 見ていないので送っても意味がない）。
            #
            # この時点で外側のタスクは（原因が何であれ）キャンセル状態に
            # 向かっており、素朴に `await` すると DB 書き込みの途中で
            # 即座に `CancelledError` が再送出され、保存が完了しない。
            # `anyio.CancelScope(shield=True)` で一時的にキャンセルを
            # 遮蔽し、部分応答の保存だけは確実に完了させる。
            if collected:
                with anyio.CancelScope(shield=True):
                    await _persist_assistant_reply(
                        session_factory, conversation_id, collected, new_title
                    )
            raise
        except Exception as exc:  # エージェント側の例外を error イベントへ変換する（契約どおり）
            # 履歴が欠けないよう、部分的にでも受け取れたテキストは保存する。
            if collected:
                await _persist_assistant_reply(
                    session_factory, conversation_id, collected, new_title
                )
            # プロバイダの生ペイロード（Gemini の 503 の JSON 文字列等）を
            # そのまま画面に流すのはテンプレートとして不適切なので、必ず
            # 定型文に変換する。原因調査に要る詳細（例外の型・元の文字列）は
            # 捨てずにここでログへ残す（プロンプト全文・応答全文は出さない）。
            logger.warning(
                "agent invocation failed: conversation_id=%s exc_type=%s detail=%s",
                conversation_id,
                type(exc).__name__,
                exc,
            )
            error_code, error_message = to_user_facing_error(exc)
            error_payload = ErrorEventPayload(message=error_message, code=error_code)
            yield format_sse("error", error_payload.model_dump(mode="json"))
            return

        assistant_message, final_title = await _persist_assistant_reply(
            session_factory, conversation_id, collected, new_title
        )

        payload = DoneEventPayload(
            id=assistant_message.id,
            conversation_id=assistant_message.conversation_id,
            role="assistant",
            content=assistant_message.content,
            created_at=assistant_message.created_at,
            title=final_title,
            # 今回のスコープでは assistant メッセージに添付が付くことは無いが、
            # `Message` と同じ形を保つため常に空配列を明示する（契約参照）。
            attachments=[],
        )
        yield format_sse("done", payload.model_dump(mode="json"))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # SSE はプロキシ（nginx 等）にバッファリングされると増分が届かない
            # ことがあるため、明示的にバッファリング無効・keep-alive を指示する。
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


app = create_app()
