"""root agent（チャットエージェント）の定義。

設計原則: 「1 エージェント = 1 モジュール = 1 `build_*_agent()`」。
このモジュールは `Agent` インスタンスの組み立てにのみ責任を持ち、
`Runner` や `SessionService` の存在を一切知らない（それらの組み立ては
`runtime.py` に一元化する）。エージェントを増やすときは、共通の
BaseAgent を作るのではなく、このファイルと同じ形の新しいモジュールを
追加する。
"""

from __future__ import annotations

from google.adk import Agent

from app.services.agents.prompts import CHAT_AGENT_DESCRIPTION, CHAT_AGENT_INSTRUCTION
from app.services.agents.tools import get_current_time


def build_chat_agent(*, model: str) -> Agent:
    """root agent を組み立てる。

    モデル名は `runtime.py`（さらに遡ると設定値）から引数で受け取る。
    ここでモデル名をハードコードしないことで、LLM 設定を 1 箇所
    （呼び出し元）に集約する。
    """
    return Agent(
        name="chat_agent",
        model=model,
        instruction=CHAT_AGENT_INSTRUCTION,
        description=CHAT_AGENT_DESCRIPTION,
        tools=[get_current_time],
    )
