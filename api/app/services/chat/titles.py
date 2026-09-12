"""会話タイトル関連の純粋関数。

DB アクセスを含まないため、単体テストしやすいようリポジトリ層から分離している。
"""

from __future__ import annotations

DEFAULT_CONVERSATION_TITLE = "新しい会話"

_TITLE_MAX_LENGTH = 30


def derive_title_from_content(content: str) -> str:
    """最初のユーザー発言から会話タイトルを作る。

    先頭 30 文字程度に丸め、切り詰めた場合は省略記号を付ける。空文字列
    （例: 全角スペースのみ等）の場合はデフォルトタイトルにフォールバックする。
    """
    normalized = content.strip()
    if not normalized:
        return DEFAULT_CONVERSATION_TITLE
    if len(normalized) <= _TITLE_MAX_LENGTH:
        return normalized
    return normalized[:_TITLE_MAX_LENGTH] + "…"


def is_default_title(title: str) -> bool:
    """タイトルが「未設定」を表すデフォルト値かどうか。"""
    return title == DEFAULT_CONVERSATION_TITLE
