"""ファイル添付機能で使う純粋関数。

DB・I/O には触れない（単体テストしやすくするため）。パストラバーサル対策
（`sanitize_filename`）は「2 重に防ぐ」設計の 1 段目。2 段目は
`app/services/storage/local.py` の `_resolve` によるルート外脱出検査。
"""

from __future__ import annotations

import mimetypes
import re
import urllib.parse

# 制御文字（NUL 含む C0/C1 領域）を除去するための正規表現。
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# ファイル名の最大バイト数（UTF-8）。多くのファイルシステムの上限（255 バイト）に合わせる。
_MAX_FILENAME_BYTES = 255

_FALLBACK_FILENAME = "file"


def sanitize_filename(raw: str) -> str:
    """アップロードされたファイル名を安全な表示名に正規化する。

    - POSIX (`/`) / Windows (`\\`) 両方のパス区切りで分割し、最後の要素だけを
      使う（`../../etc/passwd` → `passwd`、`C:\\tmp\\a.txt` → `a.txt`）。
    - NUL・制御文字を除去する。
    - 先頭の `.`（隠しファイル化・`..` の残骸）と前後の空白を除去する。
    - 結果が空 / `.` / `..` になったら `"file"` にフォールバックする。
    - 日本語などの非 ASCII 文字は**そのまま残す**（ファイル名が読めなくなる方が
      ユーザーへの損害が大きいと判断）。
    - UTF-8 で `_MAX_FILENAME_BYTES` バイトを超える場合は、拡張子を保ったまま
      本体部分だけを切り詰める。
    """
    # パス区切りのどちらでも最後の要素だけを見る。
    last_component = raw.replace("\\", "/").rsplit("/", 1)[-1]
    without_control = _CONTROL_CHARS_RE.sub("", last_component)
    stripped = without_control.strip().lstrip(".")

    if stripped in ("", ".", ".."):
        return _FALLBACK_FILENAME

    return _truncate_to_byte_limit(stripped, _MAX_FILENAME_BYTES)


def _truncate_to_byte_limit(filename: str, max_bytes: int) -> str:
    """UTF-8 バイト長が `max_bytes` を超える場合、拡張子を保ったまま切り詰める。"""
    encoded = filename.encode("utf-8")
    if len(encoded) <= max_bytes:
        return filename

    stem, _, ext = filename.rpartition(".")
    if not stem:
        # 拡張子が無い（または先頭がドットのみで stem が空になる）場合は
        # ファイル名全体を 1 つの本体として切り詰める。
        stem, ext = filename, ""
    ext_suffix = f".{ext}" if ext else ""
    ext_bytes = len(ext_suffix.encode("utf-8"))
    budget = max(max_bytes - ext_bytes, 0)

    truncated_stem_bytes = stem.encode("utf-8")[:budget]
    # マルチバイト文字の境界で切れて壊れた文字列にならないよう、
    # 不完全な末尾バイト列を捨てながらデコードする。
    truncated_stem = truncated_stem_bytes.decode("utf-8", errors="ignore")
    result = f"{truncated_stem}{ext_suffix}"
    return result or _FALLBACK_FILENAME


def resolve_mime_type(declared_content_type: str | None, sanitized_filename: str) -> str:
    """MIME タイプを決定する。

    1. クライアントが申告した `content_type` からパラメータ（`; charset=...` 等）を
       落として小文字化する。
    2. 未指定、または `application/octet-stream`（=「不明」を表す既定値）の場合は、
       サニタイズ済みファイル名の拡張子から `mimetypes.guess_type` で推測する。
    3. それでも不明なら `application/octet-stream` に落とす。

    中身のバイト列を検査する sniffing（`python-magic` 等）は依存を増やさない
    方針のため導入していない。**クライアントの申告を信用する形になる**ことを
    呼び出し側は認識しておくこと（`docs/plans/file-attachments.md` のリスク節参照）。
    """
    normalized = _normalize_declared_content_type(declared_content_type)
    if normalized is not None and normalized != "application/octet-stream":
        return normalized

    guessed, _ = mimetypes.guess_type(sanitized_filename)
    return guessed or "application/octet-stream"


def _normalize_declared_content_type(declared_content_type: str | None) -> str | None:
    if not declared_content_type:
        return None
    return declared_content_type.split(";", 1)[0].strip().lower() or None


def build_storage_key(purpose: str, file_id: str, filename: str) -> str:
    """ストレージ上のキー（`"<purpose>/<uuid>/<filename>"`）を組み立てる。

    UUID ディレクトリが同名ファイルの衝突を吸収するため、`filename` 自体の
    一意性には依存しない。
    """
    return f"{purpose}/{file_id}/{filename}"


def content_disposition_header(filename: str) -> str:
    """ダウンロード応答用の `Content-Disposition` ヘッダ値を組み立てる。

    非 ASCII なファイル名も安全に運ぶため RFC 5987 の `filename*=UTF-8''...`
    形式を使う（`filename=` だけだと非 ASCII の扱いがブラウザ間で割れる）。
    常に `attachment` にして既定でダウンロードさせる（D7: 保存型 XSS 対策の一環。
    `<img src>` のようなサブリソース読み込みは Content-Disposition を無視するため、
    画像プレビュー用の埋め込みは影響を受けない）。
    """
    encoded = urllib.parse.quote(filename, safe="")
    return f"attachment; filename*=UTF-8''{encoded}"
