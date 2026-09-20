"""ファイル実体の保存・読み出しを抽象化する境界インターフェース。

`app/types/agent_runtime.py` と同じ考え方で、実装（`LocalFileStorage`）を
直接 import せず、構造的部分型（`typing.Protocol`）として持つ。将来
S3/Azure Blob 等のクラウド実装を追加するときも、この Protocol を満たせば
呼び出し側（`app/servers/api.py`）は無変更で差し替えられる。

## 署名付き URL をここに入れない理由（D3）

`LocalFileStorage` は本物の署名付き URL を発行できず、偽の URL を返すか
`NotImplementedError` を投げるしかない。Protocol には「どの実装でも無理なく
実装できる操作」だけを置く方針を守るため、署名付き URL はこの Protocol の
メソッドにはしない。

また `GET /api/files/{id}/content` は DB でメタデータを引き、将来は認可も
見る関門になる。署名付き URL はこの関門を迂回するので、認可を足した瞬間に
穴になる。

後から足す場合は、別の任意ケイパビリティとして
`SignedUrlCapableStorage(Protocol)` を新たに定義し、API 層で
`isinstance(storage, SignedUrlCapableStorage)` を見て対応していれば
307 リダイレクト、していなければ従来どおりストリーム、とするのが壊さない
拡張方法。追加すべき時期の目安は、大きいファイルを API プロセス経由で
流す帯域コストが問題になったとき（≒クラウド移行のタイミングと重なる）。

## `load` と `open_stream` を両方持つ理由

- `load`: Gemini へ渡すバイト列の取得用。呼び出し側が事前にサイズ上限を
  検査済みであることを前提に、まるごとメモリに載せる。
- `open_stream`: ダウンロード応答用。ファイルサイズに関わらずメモリに
  全部載せずにチャンク単位で返せるようにするため、`load` とは別に用意する。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class FileStorage(Protocol):
    """ファイル実体の保存先を表す境界。`key` は `"<purpose>/<uuid>/<filename>"`
    形式の POSIX 風パス文字列。
    """

    async def save(self, key: str, data: bytes) -> None:
        """`key` にバイト列を保存する。親ディレクトリが無ければ作る。"""
        ...

    async def load(self, key: str) -> bytes:
        """`key` の実体を丸ごと読み出す。存在しなければ `FileNotFoundError`。

        将来の S3/Azure 実装も同じ例外規約に合わせること。
        """
        ...

    def open_stream(self, key: str) -> AsyncIterator[bytes]:
        """`key` の実体をチャンク単位で読み出す。存在しなければ `FileNotFoundError`。"""
        ...

    async def delete(self, key: str) -> None:
        """`key` の実体を削除する。存在しない場合も例外にしない（冪等）。"""
        ...
