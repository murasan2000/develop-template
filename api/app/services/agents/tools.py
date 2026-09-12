"""root agent に渡すツール群。

ADK は素の関数をそのままツールとして扱う。関数の型注釈とシグネチャから
パラメータスキーマを、docstring から LLM に見せる説明文を生成するため、
docstring は「実装メモ」ではなく「LLM向けの仕様書」として日本語で書く。

テンプレートの動作確認をオフラインで完結させたいので、ここに置く例は
外部ネットワークに一切出ないものに限定する（実運用でツールを追加する際は
このモジュールに関数を足し、`chat.py` の `tools=[...]` に登録するだけでよい）。
"""

from __future__ import annotations

from datetime import UTC, datetime


def get_current_time() -> dict[str, str]:
    """現在の日時を UTC で返す。

    ユーザーが「今何時？」「今日の日付は？」のように尋ねたときに使う。
    このツール自身は日時を推測せず、実行時刻をそのまま返す。

    Returns:
        dict: `status`（常に "ok"）と `iso8601`（UTC の ISO 8601 文字列）を含む辞書。
    """
    return {
        "status": "ok",
        "iso8601": datetime.now(UTC).isoformat(),
    }
