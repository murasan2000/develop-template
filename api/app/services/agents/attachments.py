"""マルチモーダル添付ファイルを ADK の `Part` へ組み立てる純粋関数群。

`AgentAttachment` は backend 側（`app/types/attachments.py`）にも同形で
独立に宣言されている。`TypedDict` は mypy において構造的部分型として扱われる
ため、キーと型が一致していれば別モジュールの宣言同士でも相互に代入できる
（`app/types/agent_runtime.py` が `ChatAgentRuntime` の具象を import せず
`Protocol` で構造的に持っているのと同じ理由づけ）。**この構造的互換性に
依存しているので、フィールドを追加・変更するときは backend 側の宣言も
必ず同時に変えること。** 片方だけ変えても型チェックは沈黙したまま実行時に
壊れる（キーが合わない TypedDict は mypy では検出できるが、うっかり
両方を同じ形に変え忘れた場合は検出できない）。

このモジュールは副作用を持たない（ストレージや DB を一切知らない）。
バイト列の読み出しは API 層（backend-builder 側）の責務で、ここでは
渡されたバイト列を ADK の `Part` にどう並べるかだけを扱う。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from google.genai import types

from app.services.agents.prompts import ATTACHMENT_LABEL, UNSUPPORTED_ATTACHMENT_NOTE


class AgentAttachment(TypedDict):
    """`stream_reply` にマルチモーダル入力として渡す添付 1 件。

    `data` は常に実体のバイト列（API 層が `FileStorage` から読み出して渡す）。
    「この MIME タイプをモデルに読ませられるか」の判断はエージェント層が行う
    （モデルの能力に関する知識なので、モデル統合側に置く）。
    """

    filename: str
    mime_type: str
    size_bytes: int
    data: bytes


def is_inlinable(mime_type: str) -> bool:
    """モデルに中身を読ませられる MIME タイプかどうかを判定する。

    Gemini がそのまま解釈できる範囲（画像全般・テキスト全般・PDF）に限定する。
    それ以外（`application/zip` など）はここで `False` を返し、呼び出し側
    （`build_user_parts`）がファイル名とサイズだけを伝える扱いに落とす。
    """
    return (
        mime_type.startswith("image/")
        or mime_type.startswith("text/")
        or mime_type == "application/pdf"
    )


def build_user_parts(text: str, attachments: Sequence[AgentAttachment]) -> list[types.Part]:
    """ユーザーターンの `Part` 列を組み立てる。

    並び順は `[ラベル(file1), inline(file1), ラベル(file2), inline(file2), ...,
    本文テキスト]`。`Part.from_bytes` にはファイル名を載せる口が無い
    （`types.Blob.display_name` は存在するが `from_bytes` はこれを設定しない）
    ため、各添付の直前にファイル名を伝える text パートを 1 つ置くことで
    モデルへファイル名を伝える。

    非対応 MIME タイプ（`is_inlinable` が偽）の添付は inline パートを作らず、
    ファイル名・MIME タイプ・サイズだけを伝える text パート（
    `UNSUPPORTED_ATTACHMENT_NOTE`）に置き換える。エラーにはしない
    （D5: 非対応形式でも送信自体は成立させる）。

    本文テキストが空文字のときはテキストパートを足さない（空の `Part` を
    送らない）。添付が 0 件かつ本文が空になることは API 層の検証で防がれて
    いる前提だが、ここでも空文字を無条件に送らないことで二重に安全にする。
    """
    parts: list[types.Part] = []
    for attachment in attachments:
        if is_inlinable(attachment["mime_type"]):
            parts.append(
                types.Part(
                    text=ATTACHMENT_LABEL.format(
                        filename=attachment["filename"],
                        mime_type=attachment["mime_type"],
                    )
                )
            )
            parts.append(
                types.Part.from_bytes(
                    data=attachment["data"],
                    mime_type=attachment["mime_type"],
                )
            )
        else:
            parts.append(
                types.Part(
                    text=UNSUPPORTED_ATTACHMENT_NOTE.format(
                        filename=attachment["filename"],
                        mime_type=attachment["mime_type"],
                        size_bytes=attachment["size_bytes"],
                    )
                )
            )

    if text:
        parts.append(types.Part(text=text))

    return parts
