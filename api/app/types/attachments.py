"""エージェント層へ渡す添付データの境界型（backend 側の宣言）。

`app/services/agents/attachments.py` にも同形の `AgentAttachment` が
独立して宣言されている。`TypedDict` は mypy において構造的に互換なので、
同じキー・同じ型で宣言されていれば、別モジュール宣言同士でも相互に
代入できる（`app/types/agent_runtime.py` が `ChatAgentRuntime` を具象
import せず `Protocol` として持つのと同じ考え方で、両層を独立して
型チェック・並行実装できるようにするため）。

**この定義を変えるときは、必ず `app/services/agents/attachments.py` 側も
同時に変えること。** 片方だけ変えると、キー・型が食い違っても mypy は
警告できない（構造的部分型は「両方が同じ形である」ことを検証しない。
それぞれが個別に妥当なだけ）。
"""

from __future__ import annotations

from typing import TypedDict


class AgentAttachment(TypedDict):
    """`ChatAgentRuntime.stream_reply` にマルチモーダル入力として渡す添付 1 件。

    `data` は常に実体のバイト列（API 層が `FileStorage` から読み出して渡す）。
    「この MIME タイプをモデルに読ませられるか」の判断はエージェント層が行う
    （モデルの能力に関する知識なので、モデル統合側に置く）。
    """

    filename: str
    mime_type: str
    size_bytes: int
    data: bytes
