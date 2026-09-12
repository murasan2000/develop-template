"""`Runner` と `SessionService` の組み立て、および薄いラッパ。

設計原則: Runner / SessionService の組み立ては、このモジュールの
`create_chat_runtime` 1 箇所だけに集約する。エージェント定義
（`chat.py`）は Runner の存在を知らない。バックエンド（`app/servers/`
や `app/services/chat/`）は、この `ChatAgentRuntime` の公開メソッドだけを
使い、ADK の型（`Event`, `RunConfig` など）を直接扱わない。

責務分離についての重要な注意:
    アプリの永続履歴（PostgreSQL の `conversations` / `messages` テーブル、
    UI に表示する会話ログ）と、ADK の `SessionService` が保持するセッション
    （エージェントの作業記憶・ツール呼び出し履歴などの内部状態）は完全な別物。
    `ChatAgentRuntime` は前者を一切知らず、後者（ADK セッション）だけを
    `conversation_id` をキーにして管理する。会話の表示用永続化は呼び出し元
    （`app/services/chat/` 側）の責任である。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from google.adk import Runner

# ADK 側が `StreamingMode` を `__all__` 等で明示的に再エクスポートしていないため、
# strict mypy の no-implicit-reexport 検査に引っかかる。実体は存在し実行時には
# 問題ないため、型チェックのみ抑止する（ADK 側のスタブ整備待ち）。
from google.adk.agents.run_config import RunConfig, StreamingMode  # type: ignore[attr-defined]
from google.adk.apps import App
from google.adk.sessions import BaseSessionService, DatabaseSessionService, InMemorySessionService
from google.genai import types

from app.services.agents.chat import build_chat_agent

# ADK セッションの `app_name` は、アプリインスタンスの識別子であって
# ユーザーごとに変える値ではない。会話（ユーザーとの 1 スレッド）と
# ADK セッションを 1:1 対応させるため、`conversation_id` をそのまま
# ADK の `session_id` として使う。
_DEFAULT_APP_NAME = "chat_template"


class AgentInvocationError(Exception):
    """エージェント呼び出しが最終的に失敗したことを表す例外。

    ADK はモデル呼び出しの失敗を、例外として送出する前に（あるいは代わりに）
    `Event.error_code` / `Event.error_message` としてイベントストリームに
    乗せてくる。バックエンドが `code`（`UNAVAILABLE` / `RESOURCE_EXHAUSTED` /
    `NOT_FOUND` など google-genai 由来の値）を見て失敗の種類を分類できるよう、
    メッセージ文字列に埋め込むのではなく属性として保持する。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class ChatAgentRuntime:
    """バックエンドが使うエージェント層の唯一の窓口。

    `Runner` と `SessionService` をまとめて保持し、会話単位（会話 ID =
    ADK セッション ID）でのセッション管理・応答ストリーミングを提供する。
    このクラス自身はステートレスな薄いラッパであり、アプリ起動時に 1 つ
    だけ作って全リクエストで使い回すことを想定している。
    """

    def __init__(
        self,
        *,
        runner: Runner,
        session_service: BaseSessionService,
        app_name: str,
        model: str,
    ) -> None:
        self._runner = runner
        self._session_service = session_service
        self._app_name = app_name
        self.model_name = model

    async def ensure_session(self, conversation_id: str, user_id: str) -> None:
        """ADK セッションが無ければ作る（冪等）。

        `Runner` は既定で `auto_create_session=False` であり、事前に
        セッションが存在しないと `run_async` が失敗する。`get_session` が
        `None` を返すとき（＝未作成のとき）だけ `create_session` を呼ぶことで、
        何度呼んでも安全にする。
        """
        existing = await self._session_service.get_session(
            app_name=self._app_name,
            user_id=user_id,
            session_id=conversation_id,
        )
        if existing is None:
            await self._session_service.create_session(
                app_name=self._app_name,
                user_id=user_id,
                session_id=conversation_id,
            )

    async def stream_reply(
        self, conversation_id: str, user_id: str, text: str
    ) -> AsyncIterator[str]:
        """ユーザー発言に対する応答を、増分テキストだけ yield する。

        StreamingMode.SSE では、部分テキスト（`partial=True`）を積み重ねた
        「これまでの全文」が最終イベント（`partial` が立っていないイベント）
        にもう一度乗ってくる。両方を素朴に連結すると応答が丸ごと二重に
        表示されるため、増分イベントを 1 つでも yield していれば最終イベントの
        テキストは捨てる。

        一方で、ストリーミングが実質的に効かないケース（モデル側の都合、
        非常に短い応答、ツール呼び出し後の要約のみ、など）では増分イベントが
        1 つも来ず、最終イベントにしかテキストが乗らないことがある。ここで
        機械的に「最終イベントは常に捨てる」としてしまうと、ユーザーには
        何も表示されないまま `done` が届くという、テンプレートとして最も
        避けたい壊れ方をする。そのため「増分を 1 つも yield していないときに
        限り、最終応答イベントの全文をフォールバックとして 1 回だけ yield する」
        という条件にし、二重表示と無応答のどちらも避ける。

        エラーイベントと ADK のリトライ機構についての重要な注意（ここが
        一番の落とし穴）:
            ADK（`google/adk/workflow/_node_runner.py` の
            `_run_node_with_retry`）は、ノードの実行が例外で失敗すると
            「(1) まずエラーイベントを enqueue し、(2) そのあとで
            `retry_config` に基づきリトライするかどうかを判定する」という
            順序で動く。つまり `event.error_code` が入ったイベントが流れて
            きた時点では、まだリトライが成功する可能性が残っている
            （例: Gemini が 503 を 2 回返した後に成功する場合、エラー
            イベントが 2 回流れたあとに正常なテキストが続く）。ここで
            エラーイベントを見た瞬間に例外を送出すると、`retry_config` を
            設定して 503 を自動回復できるようにしても、回復する前に
            自分で失敗を確定させてしまう。
            そのため、エラーイベントは「最後に見たエラー」として保持する
            だけにとどめ、実際に例外にするかどうかはストリームが終わる
            瞬間に判断する: テキストを 1 文字でも yield できていれば
            リトライの末に回復したとみなして握りつぶし（＝正常終了）、
            1 つも yield できていなければ、そこで初めて
            `AgentInvocationError` として送出する。
            さらに、ADK はリトライを使い切った（または `retry_config` が
            無い）場合、エラーイベントを流したあとに元の例外
            （`ServerError` など）を `run_async` 自身からも送出してくる
            （実機で確認済み）。この場合はストリームが正常終了しないため、
            下の `except` 節でその例外を捕まえて `AgentInvocationError` に
            変換する。ここでの `try/except Exception` は失敗を握りつぶす
            ためのものではなく、常に何らかの形で例外を送出し直す
            （`raise ... from exc`）ための変換であることに注意。
        """
        new_message = types.Content(role="user", parts=[types.Part(text=text)])
        run_config = RunConfig(streaming_mode=StreamingMode.SSE)

        yielded_any = False
        last_error_code: str | None = None
        last_error_message: str | None = None

        try:
            async for event in self._runner.run_async(
                user_id=user_id,
                session_id=conversation_id,
                new_message=new_message,
                run_config=run_config,
            ):
                if event.error_code is not None:
                    # ここでは即座に例外化しない（上の docstring 参照）。
                    last_error_code = event.error_code
                    last_error_message = event.error_message
                    continue

                if event.partial:
                    content = event.content
                    if content is None:
                        continue
                    for part in content.parts or []:
                        if part.text:
                            yielded_any = True
                            yield part.text
                    continue

                # ここに来るのは `partial=False` のイベント（最終応答、または
                # ツール呼び出しなどテキストを伴わない制御イベント）。
                if not event.is_final_response():
                    continue
                if yielded_any:
                    # 増分イベント側で既に全文を流し終えている。ここで yield
                    # すると二重表示になるため捨てる。
                    continue

                # 増分イベントが 1 つも来なかった場合のフォールバック。
                content = event.content
                if content is None:
                    continue
                for part in content.parts or []:
                    if part.text:
                        yielded_any = True
                        yield part.text
        except Exception as exc:
            if yielded_any:
                # 既にテキストが流れ始めた後に発生した別要因の例外なので、
                # 「リトライが尽きた末の無応答」とは別物として扱い、変換せず
                # そのまま送出する。
                raise
            code = last_error_code or type(exc).__name__
            message = last_error_message or str(exc)
            raise AgentInvocationError(code, message) from exc

        if not yielded_any and last_error_code is not None:
            # ストリームは例外を送出せず正常終了したが、テキストは 1 つも
            # 出せず、エラーイベントだけが残った場合（リトライ機構が
            # 例外を再送出しない実装・経路のとき）。
            raise AgentInvocationError(last_error_code, last_error_message or "")

    async def aclose(self) -> None:
        """Runner とセッションサービスが保持するリソースを解放する。

        `Runner.close()` はツールセット・プラグインを閉じ、セッション
        サービスの `flush()` までは呼ぶが、`DatabaseSessionService` が
        内部で保持する SQLAlchemy エンジンの破棄（コネクションプールの
        解放）まではしない。エンジンを自前で作った場合に接続が残り続け
        ないよう、`close` を持つセッションサービスに対しては明示的に
        呼び出す。
        """
        await self._runner.close()
        close = getattr(self._session_service, "close", None)
        if close is not None:
            await close()


async def create_chat_runtime(
    *,
    database_url: str | None,
    model: str,
    app_name: str = _DEFAULT_APP_NAME,
    max_retry_attempts: int = 3,
) -> ChatAgentRuntime:
    """`ChatAgentRuntime` を組み立てる。

    `database_url` が `None` のときは `InMemorySessionService` にフォール
    バックする（テスト・オフライン実行用）。それ以外は
    `postgresql+asyncpg://` 形式の URL をそのまま `DatabaseSessionService`
    に渡す（ADK が内部で SQLAlchemy の非同期エンジンとして扱う）。

    `max_retry_attempts` は Gemini の一時的な障害（503 UNAVAILABLE など）に
    対するリトライ回数の上限で、そのまま `build_chat_agent` に渡す
    （実際のリトライ設定の組み立ては `chat.py` 側の責務）。バックエンドが
    環境変数（例: `AGENT_RETRY_MAX_ATTEMPTS`）から値を渡すことを想定している。
    """
    session_service: BaseSessionService
    if database_url is None:
        session_service = InMemorySessionService()
    else:
        session_service = DatabaseSessionService(db_url=database_url)

    agent = build_chat_agent(model=model, max_retry_attempts=max_retry_attempts)
    app = App(name=app_name, root_agent=agent)
    runner = Runner(app=app, session_service=session_service)

    return ChatAgentRuntime(
        runner=runner,
        session_service=session_service,
        app_name=app_name,
        model=model,
    )
