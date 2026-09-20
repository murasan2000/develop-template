"""`app/utils/sse.py` の純粋関数の単体テスト。"""

from __future__ import annotations

from app.utils.sse import format_sse


def test_format_sse_simple_dict() -> None:
    result = format_sse("delta", {"text": "こんにちは"})
    assert result == 'event: delta\ndata: {"text": "こんにちは"}\n\n'


def test_format_sse_ends_with_blank_line() -> None:
    result = format_sse("done", {"a": 1})
    assert result.endswith("\n\n")
    assert not result.endswith("\n\n\n")


def test_format_sse_multiline_data_gets_prefixed_per_line() -> None:
    # JSON エンコードされた文字列に改行が含まれるケース（例: content に \n を含む）を
    # 想定し、各行に data: を付け直せていることを確認する。
    result = format_sse("delta", "line1\nline2")
    assert result == "event: delta\ndata: line1\ndata: line2\n\n"


def test_format_sse_plain_string_is_not_json_encoded() -> None:
    result = format_sse("error", "boom")
    assert result == "event: error\ndata: boom\n\n"
