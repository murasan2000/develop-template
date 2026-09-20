"""`app/services/chat/titles.py` の単体テスト。"""

from __future__ import annotations

from app.services.chat.titles import (
    DEFAULT_CONVERSATION_TITLE,
    derive_title_from_content,
    is_default_title,
)


def test_derive_title_short_content_is_used_as_is() -> None:
    assert derive_title_from_content("こんにちは") == "こんにちは"


def test_derive_title_strips_surrounding_whitespace() -> None:
    assert derive_title_from_content("  hello  ") == "hello"


def test_derive_title_truncates_long_content() -> None:
    content = "あ" * 50
    title = derive_title_from_content(content)
    assert title == "あ" * 30 + "…"


def test_derive_title_falls_back_to_default_for_blank_content() -> None:
    assert derive_title_from_content("   ") == DEFAULT_CONVERSATION_TITLE


def test_is_default_title() -> None:
    assert is_default_title(DEFAULT_CONVERSATION_TITLE) is True
    assert is_default_title("カスタムタイトル") is False
