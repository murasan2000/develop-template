"""テスト用のフェイク `ChatAgentRuntime` 実装。

本物の ADK ランタイム（`app/services/agents/`）は LLM を呼ぶため、テストからは
一切 import しない。`app/types/agent_runtime.py` の Protocol を満たす形だけを
用意し、決め打ちの文字列を yield する。
"""

from __future__ import annotations

from collections.abc import AsyncIterator


class FakeChatAgentRuntime:
    """`ChatAgentRuntime` を構造的に満たすフェイク実装。"""

    def __init__(
        self,
        *,
        model_name: str = "fake-model",
        reply_chunks: list[str] | None = None,
        fail_with: Exception | None = None,
        partial_before_fail: str | None = None,
    ) -> None:
        self.model_name = model_name
        self._reply_chunks = reply_chunks if reply_chunks is not None else ["こんにちは", "、世界"]
        self._fail_with = fail_with
        self._partial_before_fail = partial_before_fail
        self.ensure_session_calls: list[tuple[str, str]] = []
        self.stream_reply_calls: list[tuple[str, str, str]] = []
        self.closed = False

    async def ensure_session(self, conversation_id: str, user_id: str) -> None:
        self.ensure_session_calls.append((conversation_id, user_id))

    async def stream_reply(
        self, conversation_id: str, user_id: str, text: str
    ) -> AsyncIterator[str]:
        self.stream_reply_calls.append((conversation_id, user_id, text))
        if self._partial_before_fail is not None:
            yield self._partial_before_fail
        if self._fail_with is not None:
            raise self._fail_with
        for chunk in self._reply_chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True
