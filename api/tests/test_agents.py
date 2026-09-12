"""エージェント層（`app/services/agents/`）のオフラインテスト。

実際の Gemini（ネットワーク越しの LLM）は一切呼ばない。前半は
`Runner.run_async` をフェイクに差し替えて `ChatAgentRuntime` のロジックだけを
検証し、後半（`_FlakyLlm` を使うテスト）は `retry_config` が ADK 本体の
リトライ機構に正しく渡り機能することまで、実際の `Agent` / `Runner` /
`InMemorySessionService` を組み合わせて検証する（LLM だけをフェイクに
差し替える）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast

import pytest
from app.services.agents import AgentInvocationError, ChatAgentRuntime, create_chat_runtime
from app.services.agents.chat import _build_retry_config
from app.services.agents.tools import get_current_time
from google.adk import Agent, Runner
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.sessions import BaseSessionService, InMemorySessionService, Session
from google.adk.workflow import RetryConfig
from google.genai import types
from google.genai.errors import ServerError


def _text_event(*, partial: bool, text: str) -> Any:
    """テスト用に `Event` を組み立てる（`author` は任意の固定値でよい）。"""
    from google.adk.events.event import Event

    return Event(
        author="chat_agent",
        partial=partial,
        content=types.Content(role="model", parts=[types.Part(text=text)]),
    )


class _FakeRunner:
    """`Runner.run_async` だけを模したフェイク。

    実際の ADK は `run_async` が非同期ジェネレータなので、同じ形（呼び出すと
    async iterator を返す）を再現する。それ以外のメソッドは
    `ChatAgentRuntime` から使われないため実装しない。
    """

    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self.close_called = False
        self.received_kwargs: dict[str, Any] = {}

    async def run_async(self, **kwargs: Any) -> AsyncIterator[Any]:
        self.received_kwargs = kwargs
        for event in self._events:
            yield event

    async def close(self) -> None:
        self.close_called = True


class _FakeSessionService:
    """`get_session` / `create_session` の呼び出し回数を数えるフェイク。"""

    def __init__(self) -> None:
        self.get_calls = 0
        self.create_calls = 0
        self._session: Session | None = None

    async def get_session(
        self, *, app_name: str, user_id: str, session_id: str, config: Any = None
    ) -> Session | None:
        self.get_calls += 1
        return self._session

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> Session:
        self.create_calls += 1
        self._session = Session(id=session_id or "sid", app_name=app_name, user_id=user_id)
        return self._session


def _build_runtime(runner: _FakeRunner, session_service: _FakeSessionService) -> ChatAgentRuntime:
    return ChatAgentRuntime(
        runner=cast(Runner, runner),
        session_service=cast(BaseSessionService, session_service),
        app_name="chat_template",
        model="gemini-3.8-flash",
    )


async def test_stream_reply_yields_only_partial_text_without_duplication() -> None:
    """partial イベントの増分だけを流し、最終イベントの全文と二重にならないこと。"""
    events = [
        _text_event(partial=True, text="こんにちは"),
        _text_event(partial=True, text="、世界"),
        # StreamingMode.SSE では最終イベントに「これまでの全文」が再度乗るので、
        # partial=False のこのイベントは yield されてはいけない。
        _text_event(partial=False, text="こんにちは、世界"),
    ]
    runtime = _build_runtime(_FakeRunner(events), _FakeSessionService())

    chunks = [chunk async for chunk in runtime.stream_reply("conv-1", "user-1", "hi")]

    assert chunks == ["こんにちは", "、世界"]
    assert "".join(chunks) == "こんにちは、世界"


async def test_stream_reply_skips_events_without_text() -> None:
    """テキストを持たないイベント（ツール呼び出しなど）は無視して例外を出さないこと。"""
    from google.adk.events.event import Event

    events = [
        Event(author="chat_agent", partial=True, content=None),
        _text_event(partial=True, text="ok"),
    ]
    runtime = _build_runtime(_FakeRunner(events), _FakeSessionService())

    chunks = [chunk async for chunk in runtime.stream_reply("conv-1", "user-1", "hi")]

    assert chunks == ["ok"]


async def test_stream_reply_falls_back_to_final_text_when_no_partial_events() -> None:
    """増分イベントが 1 つも来なくても、最終イベントの全文が 1 回だけ yield されること。"""
    events = [
        _text_event(partial=False, text="こんにちは、世界"),
    ]
    runtime = _build_runtime(_FakeRunner(events), _FakeSessionService())

    chunks = [chunk async for chunk in runtime.stream_reply("conv-1", "user-1", "hi")]

    assert chunks == ["こんにちは、世界"]


async def test_stream_reply_recovers_when_error_event_is_followed_by_text() -> None:
    """エラーイベントの後にテキストが来れば、リトライで回復したとみなし例外にならないこと。

    ADK はノードの実行失敗時に「エラーイベントを流してからリトライするか判定する」
    順序で動くため、`error_code` 付きイベントの直後にテキストが続くのは
    「一時的な障害からリトライで回復した」ケースを表す。ここで即座に例外化しては
    いけない。
    """
    from google.adk.events.event import Event

    events = [
        Event(
            author="chat_agent",
            partial=False,
            error_code="UNAVAILABLE",
            error_message="503 UNAVAILABLE. high demand",
        ),
        _text_event(partial=True, text="こんにちは"),
        _text_event(partial=True, text="！"),
    ]
    runtime = _build_runtime(_FakeRunner(events), _FakeSessionService())

    chunks = [chunk async for chunk in runtime.stream_reply("conv-1", "user-1", "hi")]

    assert chunks == ["こんにちは", "！"]


async def test_stream_reply_raises_agent_invocation_error_when_only_error_events() -> None:
    """テキストが 1 つも来ずエラーイベントだけが残った場合、`AgentInvocationError` になること。"""
    from google.adk.events.event import Event

    events = [
        Event(
            author="chat_agent",
            partial=False,
            error_code="RESOURCE_EXHAUSTED",
            error_message="クォータを超過しました。",
        ),
    ]
    runtime = _build_runtime(_FakeRunner(events), _FakeSessionService())

    with pytest.raises(AgentInvocationError) as exc_info:
        async for _ in runtime.stream_reply("conv-1", "user-1", "hi"):
            pass

    assert exc_info.value.code == "RESOURCE_EXHAUSTED"
    assert exc_info.value.message == "クォータを超過しました。"


async def test_stream_reply_passes_ids_through_to_runner() -> None:
    """`conversation_id` / `user_id` がそのまま ADK の session_id / user_id に渡ること。"""
    fake_runner = _FakeRunner([])
    runtime = _build_runtime(fake_runner, _FakeSessionService())

    async for _ in runtime.stream_reply("conv-42", "user-42", "hi"):
        pass

    assert fake_runner.received_kwargs["session_id"] == "conv-42"
    assert fake_runner.received_kwargs["user_id"] == "user-42"


async def test_ensure_session_is_idempotent() -> None:
    """2 回呼んでも `create_session` は 1 回しか呼ばれないこと。"""
    session_service = _FakeSessionService()
    runtime = _build_runtime(_FakeRunner([]), session_service)

    await runtime.ensure_session("conv-1", "user-1")
    await runtime.ensure_session("conv-1", "user-1")

    assert session_service.get_calls == 2
    assert session_service.create_calls == 1


async def test_aclose_closes_runner() -> None:
    """`aclose` が Runner の `close` を呼ぶこと。"""
    fake_runner = _FakeRunner([])
    runtime = _build_runtime(fake_runner, _FakeSessionService())

    await runtime.aclose()

    assert fake_runner.close_called is True


async def test_create_chat_runtime_falls_back_to_in_memory_session_service_when_no_database_url() -> (
    None
):
    """`database_url=None` のとき `InMemorySessionService` が選ばれること。"""
    runtime = await create_chat_runtime(database_url=None, model="gemini-3.8-flash")
    try:
        assert isinstance(runtime._session_service, InMemorySessionService)  # noqa: SLF001
        assert runtime.model_name == "gemini-3.8-flash"
    finally:
        await runtime.aclose()


def test_build_retry_config_targets_server_error_only() -> None:
    """`_build_retry_config` が `ServerError`（5xx）だけをリトライ対象にすること。

    `ClientError`（4xx）をリトライ対象に含めない設計判断（429 は本来リトライ
    し得るが、400/401/403 と同じクラスでクラス名では区別できないため、
    回復不能な失敗まで待たされないよう除外している）はコードコメント側で
    説明済みなので、ここでは「意図どおりの値が設定されること」だけを確認する。
    """
    config = _build_retry_config(3)

    assert config is not None
    assert config.max_attempts == 3
    assert config.exceptions == ["ServerError"]


def test_build_retry_config_disables_retry_for_max_attempts_one_or_less() -> None:
    """`max_attempts` が 1 以下ならリトライを無効化する（`None`）こと。"""
    assert _build_retry_config(1) is None
    assert _build_retry_config(0) is None


async def test_create_chat_runtime_wires_max_retry_attempts_into_agent() -> None:
    """`create_chat_runtime` の `max_retry_attempts` が Agent の `retry_config` に反映されること。"""
    runtime = await create_chat_runtime(
        database_url=None, model="gemini-3.8-flash", max_retry_attempts=5
    )
    try:
        agent = runtime._runner.agent  # noqa: SLF001
        assert isinstance(agent, Agent)
        assert agent.retry_config is not None
        assert agent.retry_config.max_attempts == 5
    finally:
        await runtime.aclose()


class _FlakyLlm(BaseLlm):
    """最初の `fail_times` 回は 503 (`ServerError`) を投げ、その後成功するフェイクモデル。

    `retry_config` が実際に ADK 本体（`_node_runner.py` のリトライ機構）へ渡り
    機能していることを、`Agent` / `Runner` / `InMemorySessionService` を実際に
    組み合わせて検証するために使う。ネットワークには一切出ない。

    `calls` は `type(self).calls` としてのみ読み書きする。pydantic モデルの
    インスタンス属性は `__init__` 時点で自分の値を持ってしまうため、
    `self.calls` を直接更新すると別インスタンスやテスト側から見えなくなる。
    クラス属性として明示的に読み書きすることで、Runner 内部で保持される
    インスタンス経由でもテスト側から呼び出し回数を確認できるようにする。
    """

    model: str = "flaky-fake-model"
    fail_times: int = 0
    calls: int = 0

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse]:
        type(self).calls += 1
        if type(self).calls <= self.fail_times:
            raise ServerError(
                503,
                {
                    "error": {
                        "code": 503,
                        "message": "This model is currently experiencing high demand.",
                        "status": "UNAVAILABLE",
                    }
                },
            )
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text="こんにちは！")])
        )


async def _build_runtime_with_flaky_llm(llm: _FlakyLlm, *, max_attempts: int) -> ChatAgentRuntime:
    """`_FlakyLlm` を積んだ実物の Agent/Runner から `ChatAgentRuntime` を組み立てる。

    `build_chat_agent` が組み立てる本番用の `retry_config`（`initial_delay=1.0`
    秒など）をそのまま使うとテストが数秒単位で遅くなるため、ここでは待ち時間
    だけを小さくしたテスト用の `RetryConfig` を直接組み立てる
    （`exceptions=["ServerError"]` に絞る設計自体は `build_chat_agent` と同じ）。
    """
    retry_config = (
        RetryConfig(
            max_attempts=max_attempts,
            initial_delay=0.01,
            backoff_factor=1.0,
            max_delay=0.01,
            exceptions=["ServerError"],
        )
        if max_attempts > 1
        else None
    )
    agent = Agent(name="chat_agent", model=llm, retry_config=retry_config)
    app = App(name="chat_template", root_agent=agent)
    session_service = InMemorySessionService()
    runner = Runner(app=app, session_service=session_service)
    runtime = ChatAgentRuntime(
        runner=runner,
        session_service=session_service,
        app_name="chat_template",
        model="flaky-fake-model",
    )
    await runtime.ensure_session("conv-1", "user-1")
    return runtime


async def test_retry_config_recovers_from_transient_503_and_calls_llm_multiple_times() -> None:
    """`max_attempts=3` なら 503 を挟んでも LLM が複数回呼ばれ、最終的にテキストが返ること。

    `stream_reply` 単体のロジックだけでなく、`retry_config` が実際に ADK の
    リトライ機構へ渡り機能していることまで、実物の `Agent`/`Runner` で検証する
    本修正の中心となるテスト。
    """
    _FlakyLlm.calls = 0
    llm = _FlakyLlm(fail_times=2)
    runtime = await _build_runtime_with_flaky_llm(llm, max_attempts=3)
    try:
        chunks = [chunk async for chunk in runtime.stream_reply("conv-1", "user-1", "hi")]
        assert "".join(chunks) == "こんにちは！"
        assert _FlakyLlm.calls == 3
    finally:
        await runtime.aclose()


async def test_no_retry_config_fails_immediately_on_transient_503() -> None:
    """`max_attempts=1`（リトライ無効）なら 1 回の呼び出しで `AgentInvocationError` になること。"""
    _FlakyLlm.calls = 0
    llm = _FlakyLlm(fail_times=2)
    runtime = await _build_runtime_with_flaky_llm(llm, max_attempts=1)
    try:
        with pytest.raises(AgentInvocationError) as exc_info:
            async for _ in runtime.stream_reply("conv-1", "user-1", "hi"):
                pass
        assert _FlakyLlm.calls == 1
        assert exc_info.value.code == "UNAVAILABLE"
    finally:
        await runtime.aclose()


def test_get_current_time_returns_ok_status_and_iso8601_string() -> None:
    """`get_current_time` ツールが status と ISO 8601 形式の日時を返すこと。"""
    from datetime import datetime

    result = get_current_time()

    assert result["status"] == "ok"
    # 妥当な ISO 8601 文字列であることを確認する（形式が壊れていれば例外になる）。
    datetime.fromisoformat(result["iso8601"])


@pytest.mark.parametrize("_i", range(2))
async def test_get_current_time_is_deterministic_in_shape(_i: int) -> None:
    """複数回呼んでも常に同じキー構成を返すこと（外部ネットワークに出ないことの傍証）。"""
    result = get_current_time()
    assert set(result.keys()) == {"status", "iso8601"}
