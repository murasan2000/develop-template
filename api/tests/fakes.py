"""テスト用のフェイク `ChatAgentRuntime` 実装。

本物の ADK ランタイム（`app/services/agents/`）は LLM を呼ぶため、テストからは
一切 import しない。`app/types/agent_runtime.py` の Protocol を満たす形だけを
用意し、決め打ちの文字列を yield する。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from app.types.attachments import AgentAttachment


class AgentInvocationErrorStub(Exception):
    """`app.services.agents.AgentInvocationError` 相当のダミー例外。

    本物のクラスは並行実装中でまだ存在しない可能性があるため import せず、
    契約どおりの `code`/`message` 属性だけを持たせる。`app/utils/errors.py`
    は具象クラスを見ず属性の有無だけで判定するので、これで実運用相当の
    再現になる。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
        # 添付付きの呼び出しをテストから検証できるよう、渡された内容を
        # そのまま記録する（呼び出しごとに 1 件、添付のリストを保持）。
        self.stream_reply_attachment_calls: list[Sequence[AgentAttachment]] = []
        self.closed = False

    async def ensure_session(self, conversation_id: str, user_id: str) -> None:
        self.ensure_session_calls.append((conversation_id, user_id))

    async def stream_reply(
        self,
        conversation_id: str,
        user_id: str,
        text: str,
        attachments: Sequence[AgentAttachment] = (),
    ) -> AsyncIterator[str]:
        self.stream_reply_calls.append((conversation_id, user_id, text))
        self.stream_reply_attachment_calls.append(attachments)
        if self._partial_before_fail is not None:
            yield self._partial_before_fail
        if self._fail_with is not None:
            raise self._fail_with
        for chunk in self._reply_chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True
