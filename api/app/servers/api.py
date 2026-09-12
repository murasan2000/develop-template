"""FastAPI アプリ本体・エンドポイント・lifespan。

`uvicorn app.servers.api:app` で起動する（Dockerfile 参照）。
"""

from __future__ import annotations

import importlib
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal, cast

import anyio
import sqlalchemy as sa
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.servers.state import AppState, get_app_state
from app.services import chat as chat_service
from app.services.db import (
    Message,
    create_engine,
    create_session_factory,
    init_models,
    session_scope,
)
from app.types.agent_runtime import ChatAgentRuntime
from app.types.api import (
    ConversationDetail,
    ConversationOut,
    CreateConversationRequest,
    DoneEventPayload,
    ErrorEventPayload,
    HealthResponse,
    MessageOut,
    SendMessageRequest,
)
from app.utils.errors import to_user_facing_error
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
    )
    try:
        yield
    finally:
        await runtime.aclose()
        await engine.dispose()


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
async def delete_conversation(conversation_id: uuid.UUID, session: SessionDep) -> None:
    deleted = await chat_service.delete_conversation(session, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="conversation not found")


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
    runtime = state.runtime
    user_id = state.settings.default_user_id

    # 会話の存在確認とユーザー発言の保存は、ストリーム開始"前"に行う。ここで
    # 404 を通常の JSON エラーとして返せるのは、まだ SSE を開始していないため。
    async with session_factory() as session:
        conversation = await chat_service.get_conversation(session, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        should_retitle = chat_service.is_default_title(conversation.title)
        user_message = await chat_service.add_message(
            session, conversation_id, "user", body.content
        )
        await session.commit()
        user_message_out = MessageOut.model_validate(user_message)

    new_title = chat_service.derive_title_from_content(body.content) if should_retitle else None

    async def event_stream() -> AsyncIterator[str]:
        yield format_sse("user", user_message_out.model_dump(mode="json"))

        collected = ""
        try:
            await runtime.ensure_session(str(conversation_id), user_id)
            async for delta in runtime.stream_reply(str(conversation_id), user_id, body.content):
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
