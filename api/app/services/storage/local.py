"""ローカルディスクを実体とする `FileStorage` 実装。

テンプレートのスコープでは唯一の実装（S3/Azure Blob 等は作らない。
`docs/plans/file-attachments.md` の非ゴール参照）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import anyio

# ダウンロード時に一度にメモリへ載せるチャンクサイズ。
_STREAM_CHUNK_BYTES = 64 * 1024


class LocalFileStorage:
    """`root` 配下にファイルを格納する `FileStorage` 実装。"""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _resolve(self, key: str) -> Path:
        """`key` を絶対パスへ解決し、`root` 配下に収まっているか検査する。

        `app/utils/files.py::sanitize_filename` によるファイル名の正規化
        （1 段目の防御）に加えて、こちらは「実際に書き込み/読み込みを行う
        直前に、組み立てられたパスが本当にルート配下か」を検査する 2 段目の
        防御。`key` を組み立てる呼び出し元が将来増えても、ここで一律に
        検査されるため破れにくい。
        """
        candidate = (self._root / key).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise ValueError(f"storage key escapes root: {key!r}")
        return candidate

    async def save(self, key: str, data: bytes) -> None:
        path = self._resolve(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await anyio.to_thread.run_sync(_write)

    async def load(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return await anyio.to_thread.run_sync(path.read_bytes)

    def open_stream(self, key: str) -> AsyncIterator[bytes]:
        # 存在確認はここで（呼び出し即時に）行う。async generator 関数にすると
        # 本体は最初の `__anext__()`（= 実際にストリームを読み始めた後）まで
        # 実行されないため、`StreamingResponse` が既に 200 を返した後に
        # `FileNotFoundError` が起きてしまう。API 層が「ストリーム開始前に
        # 404 で弾く」ためには、この関数自体は同期関数のままで即座に検査し、
        # 中身の読み出しだけを別の async generator に委ねる必要がある。
        path = self._resolve(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return self._read_chunks(path)

    async def _read_chunks(self, path: Path) -> AsyncIterator[bytes]:
        async with await anyio.open_file(path, "rb") as f:
            while True:
                chunk = await f.read(_STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                yield chunk

    async def delete(self, key: str) -> None:
        path = self._resolve(key)

        def _delete() -> None:
            path.unlink(missing_ok=True)

        await anyio.to_thread.run_sync(_delete)
