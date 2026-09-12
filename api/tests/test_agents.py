"""エージェント層（`app/services/agents/`）のオフラインテスト。

LLM を一切呼ばない。`Runner.run_async` をフェイクに差し替えることで、
ADK が返すイベント列を制御し、`ChatAgentRuntime` のロジックだけを検証する。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from app.services.agents import ChatAgentRuntime, create_chat_runtime
from app.services.agents.tools import get_current_time
from google.adk import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService, Session
from google.genai import types


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


async def test_stream_reply_raises_on_error_event() -> None:
    """`error_code` 付きイベントは無視されず、例外として送出されること。"""
    from google.adk.events.event import Event

    events = [
        _text_event(partial=True, text="途中まで"),
        Event(
            author="chat_agent",
            partial=False,
            error_code="SAFETY",
            error_message="コンテンツが安全フィルタでブロックされました。",
        ),
    ]
    runtime = _build_runtime(_FakeRunner(events), _FakeSessionService())

    with pytest.raises(RuntimeError, match="コンテンツが安全フィルタでブロックされました。"):
        async for _ in runtime.stream_reply("conv-1", "user-1", "hi"):
            pass


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
