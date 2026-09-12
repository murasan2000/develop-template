"""テストで SSE レスポンスをパースするための小さなヘルパ。"""

from __future__ import annotations

import json
from typing import Any


def parse_sse_events(raw: str) -> list[tuple[str, Any]]:
    """`app/utils/sse.py::format_sse` が組み立てた文字列を `(event, data)` の列に戻す。"""
    events: list[tuple[str, Any]] = []
    for block in raw.strip("\n").split("\n\n"):
        if not block.strip():
            continue
        event = ""
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip(" "))
        data_raw = "\n".join(data_lines)
        try:
            data: Any = json.loads(data_raw)
        except json.JSONDecodeError:
            data = data_raw
        events.append((event, data))
    return events
