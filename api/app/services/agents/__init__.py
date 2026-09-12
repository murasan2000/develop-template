"""エージェント層の公開インターフェース。

バックエンド（`app/servers/`, `app/services/chat/`）はこのモジュールが
再エクスポートするシンボルだけを使い、`google.adk` や `runtime.py` の
内部実装を直接 import しない。実装を変更してもここでの公開面が
変わらなければ、バックエンド側の変更は不要になる。
"""

from __future__ import annotations

from app.services.agents.runtime import ChatAgentRuntime, create_chat_runtime

__all__ = ["ChatAgentRuntime", "create_chat_runtime"]
