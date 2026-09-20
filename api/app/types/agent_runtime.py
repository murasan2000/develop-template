"""エージェント層 (`app.services.agents`) との境界インターフェース。

`app/services/agents/` は別のエージェントが並行実装中のため、このパッケージ
側では具象クラスを直接 import せず、`docs/api-contract.md` に定義された
形を構造的部分型（`typing.Protocol`）として自前で持つ。こうしておくことで、
- agents 側の実装が未完成／未 import でも、こちら側の mypy 型チェックは
  この Protocol を基準に独立して成立する。
- テストでは本物の ADK ランタイムの代わりに、この Protocol を満たす
  フェイク実装を作って差し替えられる（LLM・ネットワーク非依存でテストするため）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from app.types.attachments import AgentAttachment


@runtime_checkable
class ChatAgentRuntime(Protocol):
    """会話単位でエージェントとやり取りするための実行時インターフェース。"""

    model_name: str

    async def ensure_session(self, conversation_id: str, user_id: str) -> None:
        """ADK セッション（エージェントの作業記憶）が無ければ作る。"""
        ...

    def stream_reply(
        self,
        conversation_id: str,
        user_id: str,
        text: str,
        attachments: Sequence[AgentAttachment] = (),
    ) -> AsyncIterator[str]:
        """応答の増分テキストだけを yield する。例外はそのまま送出してよい。

        `attachments` はそのターンで新たに添付されたファイルのみを渡す
        （ADK の `SessionService` が送信済みパートをセッション内に保持する
        ため、以降のターンで同じファイルを送り直す必要はない）。
        """
        ...

    async def aclose(self) -> None:
        """ランタイムが保持するリソース（DB 接続等）を解放する。"""
        ...
