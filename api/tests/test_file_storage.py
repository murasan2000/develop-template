"""`LocalFileStorage`（`FileStorage` の実装）の単体テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.services.storage import LocalFileStorage


async def test_save_load_roundtrip(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    await storage.save("uploads/abc/file.txt", b"hello")

    assert await storage.load("uploads/abc/file.txt") == b"hello"


async def test_open_stream_yields_full_content_in_chunks(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    data = b"x" * 200_000  # チャンクサイズ（64 KiB）を跨ぐ大きさ。
    await storage.save("uploads/abc/big.bin", data)

    chunks = [chunk async for chunk in storage.open_stream("uploads/abc/big.bin")]
    assert b"".join(chunks) == data
    assert len(chunks) > 1


async def test_load_missing_key_raises_file_not_found(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    with pytest.raises(FileNotFoundError):
        await storage.load("uploads/missing/none.txt")


def test_open_stream_missing_key_raises_immediately(tmp_path: Path) -> None:
    """`open_stream` は async generator 関数ではない（呼び出し即時に検査する）ため、
    `await`/`async for` の前、呼び出した瞬間に例外が飛ぶことを確認する。

    これは API 層が `StreamingResponse` を開始する**前**に 404 判定できる
    ようにするための意図的な設計（`app/services/storage/local.py` 参照）。
    """
    storage = LocalFileStorage(tmp_path)
    with pytest.raises(FileNotFoundError):
        storage.open_stream("uploads/missing/none.txt")


async def test_delete_is_idempotent(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    await storage.save("uploads/abc/file.txt", b"hello")

    await storage.delete("uploads/abc/file.txt")
    # 既に消えているキーを再度削除しても例外にならない。
    await storage.delete("uploads/abc/file.txt")

    with pytest.raises(FileNotFoundError):
        await storage.load("uploads/abc/file.txt")


async def test_save_rejects_keys_escaping_root(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    with pytest.raises(ValueError, match="escapes root"):
        await storage.save("../escape.txt", b"malicious")


async def test_load_rejects_keys_escaping_root(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    with pytest.raises(ValueError, match="escapes root"):
        await storage.load("../../etc/passwd")
