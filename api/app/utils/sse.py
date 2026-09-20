"""Server-Sent Events (SSE) の行整形ユーティリティ。

FastAPI の `StreamingResponse` に渡す文字列を組み立てる純粋関数だけを置く。
イベント種別ごとの業務ロジック（DB 保存など）は含めない（テスト容易性のため）。
"""

from __future__ import annotations

import json
from typing import Any


def format_sse(event: str, data: Any) -> str:
    """1 件の SSE イベントを文字列に整形する。

    - `data` が複数行にまたがる場合、SSE 仕様では行ごとに `data: ` を
      付け直す必要がある（さもないと受信側でデータが途中で切れる）ため、
      改行で分割してから 1 行ずつ `data:` を付与する。
    - 末尾は空行（`\n\n`）で終える必要がある（SSE のイベント区切り）。
    """
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    lines = payload.split("\n")
    data_lines = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event}\n{data_lines}\n\n"
