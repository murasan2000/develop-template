"""アプリ設定。

環境変数（および `.env`）から読み込む。値の定義場所をここに集約することで、
各モジュールが `os.environ` を直接参照して設定が散らばるのを防ぐ。
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """アプリ全体で共有する設定値。

    `.env` はこのテンプレート自体には含めないが、開発時に利用者が作成する
    運用を前提として `env_file` を指定しておく（存在しなくてもエラーにはならない）。
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # アプリ所有テーブル（conversations / messages）と ADK 所有テーブルは
    # 同じ PostgreSQL インスタンスに同居させる想定なので、DSN は 1 本で足りる。
    database_url: str = "postgresql+asyncpg://app:app_local_password@localhost:5432/chat"

    # Gemini のモデル名。エージェント層（agents/）へそのまま渡す。
    gemini_model: str = "gemini-3.8-flash"

    # 503（モデル混雑）等を ADK 側でリトライさせる回数の上限。ADK の
    # `Agent.retry_config` を設定しないと 503 が一切リトライされないため、
    # エージェント層の `create_chat_runtime(..., max_retry_attempts=...)` へ
    # そのまま渡す。ここに来た例外は「ADK がリトライを使い切った後」の意味に
    # なるので、API 層側で追加のリトライは行わない（二重リトライを避ける）。
    agent_retry_max_attempts: int = 3

    # カンマ区切りの文字列で受け取り、list[str] に変換して CORS ミドルウェアへ渡す。
    cors_origins: str = "http://localhost:5173"

    # 認証を持たないテンプレートなので、ADK セッションの所有者は固定値にする。
    # 認証を足すときは、ここをログインユーザー ID に差し替える。
    default_user_id: str = "local-user"

    log_level: str = "INFO"

    # --- ファイル置き場 -----------------------------------------------------
    # 実体の保存先ディレクトリ。None（未設定）ならリポジトリ直下の storage/ を
    # 使う（`storage_path` 参照）。Docker では STORAGE_DIR=/data/storage が
    # 必ず設定されるため、フォールバックはローカル直起動時のみ使われる。
    storage_dir: str | None = None

    # 1 ファイルあたりのサイズ上限（バイト）。既定 10 MiB。
    upload_max_file_bytes: int = 10_485_760
    # 1 メッセージに添付できる件数の上限。
    upload_max_files_per_message: int = 5
    # 1 メッセージあたりの添付合計サイズの上限（バイト）。既定 15 MiB。
    # 添付は Gemini へ inline で渡すため、この上限は「1 リクエストで API
    # プロセスがメモリに載せる量」の上限も兼ねている（D4）。
    upload_max_total_bytes_per_message: int = 15_728_640
    # アップロードを許可する MIME タイプ（カンマ区切り）。ここに無いものは
    # 415 で弾く。既定値には**わざと** inline 非対応の形式
    # （application/json / application/zip）を含めている。「Gemini が読めない
    # 形式はファイル名だけ伝えてエラーにしない」という経路を、テンプレートの
    # 既定状態でも到達可能にするため（`docs/plans/file-attachments.md` D5）。
    upload_allowed_mime_types: str = (
        "image/png,image/jpeg,image/webp,image/gif,"
        "application/pdf,text/plain,text/markdown,text/csv,"
        "application/json,application/zip"
    )
    # どのメッセージにも紐づかないファイル（孤児）を掃除するまでの時間（時間単位）。
    orphan_file_ttl_hours: int = 24

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS をカンマ区切りで list[str] に分解する。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def storage_path(self) -> Path:
        """ファイル実体の保存先ディレクトリ。

        `storage_dir` が設定されていればそれを展開・正規化して使う。未設定
        なら**リポジトリ直下の `storage/`** を指す
        （このファイル `api/app/config.py` から見て `parents[2]` ==
        `api/app/` → `api/` → リポジトリルート）。`cd api && uv run
        uvicorn ...` でもリポジトリルートから起動しても同じ場所を指すのが
        狙い。**Docker コンテナ内（`/app/app/config.py`）では `parents[2]`
        が `/` になってしまう**ため、compose では必ず `STORAGE_DIR` を
        設定してこのフォールバックを使わせない。
        """
        if self.storage_dir:
            return Path(self.storage_dir).expanduser().resolve()
        return Path(__file__).resolve().parents[2] / "storage"

    @property
    def allowed_mime_type_list(self) -> list[str]:
        """UPLOAD_ALLOWED_MIME_TYPES をカンマ区切りで list[str] に分解する。

        空文字列は「全許可」として扱う（派生プロジェクト向けの脱出口）。
        """
        return [t.strip() for t in self.upload_allowed_mime_types.split(",") if t.strip()]


def get_settings() -> Settings:
    """設定を生成する。

    プロセス内でキャッシュしない（テストが環境変数を差し替えて呼び直せるようにするため）。
    実運用では lifespan 内で 1 度だけ呼び、`app.state` に保持して使い回す。
    """
    return Settings()
