"""`app/utils/files.py` の純粋関数の単体テスト。"""

from __future__ import annotations

from app.utils.files import (
    build_storage_key,
    content_disposition_header,
    resolve_mime_type,
    sanitize_filename,
)


def test_sanitize_filename_strips_posix_path_traversal() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"


def test_sanitize_filename_strips_windows_path() -> None:
    assert sanitize_filename("C:\\tmp\\a.txt") == "a.txt"


def test_sanitize_filename_removes_control_characters() -> None:
    assert sanitize_filename("a\x00\x01b.txt") == "ab.txt"


def test_sanitize_filename_strips_leading_dot() -> None:
    assert sanitize_filename(".hidden") == "hidden"


def test_sanitize_filename_keeps_non_ascii() -> None:
    assert sanitize_filename("日本語ファイル名.txt") == "日本語ファイル名.txt"


def test_sanitize_filename_empty_or_dot_falls_back() -> None:
    assert sanitize_filename("") == "file"
    assert sanitize_filename(".") == "file"
    assert sanitize_filename("..") == "file"
    assert sanitize_filename("   ") == "file"


def test_sanitize_filename_truncates_long_names_preserving_extension() -> None:
    long_name = ("あ" * 200) + ".txt"
    result = sanitize_filename(long_name)

    assert result.endswith(".txt")
    assert len(result.encode("utf-8")) <= 255
    # 切り詰められて元より短くなっていること（有効なテストであることの確認）。
    assert len(result) < len(long_name)


def test_resolve_mime_type_uses_declared_content_type() -> None:
    assert resolve_mime_type("image/png; charset=binary", "a.png") == "image/png"


def test_resolve_mime_type_falls_back_to_extension_when_unspecified() -> None:
    assert resolve_mime_type(None, "a.pdf") == "application/pdf"
    assert resolve_mime_type("application/octet-stream", "a.txt") == "text/plain"


def test_resolve_mime_type_unknown_extension_falls_back_to_octet_stream() -> None:
    assert resolve_mime_type(None, "a.unknownext") == "application/octet-stream"


def test_build_storage_key_layout() -> None:
    key = build_storage_key("uploads", "abc-123", "photo.png")
    assert key == "uploads/abc-123/photo.png"


def test_content_disposition_header_uses_rfc5987_encoding() -> None:
    header = content_disposition_header("日本語.txt")
    assert header.startswith("attachment; filename*=UTF-8''")
    assert "%E6%97%A5%E6%9C%AC%E8%AA%9E" in header
