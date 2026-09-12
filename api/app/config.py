"""アプリ設定。

環境変数（および `.env`）から読み込む。値の定義場所をここに集約することで、
各モジュールが `os.environ` を直接参照して設定が散らばるのを防ぐ。
"""

from __future__ import annotations

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

    # カンマ区切りの文字列で受け取り、list[str] に変換して CORS ミドルウェアへ渡す。
    cors_origins: str = "http://localhost:5173"

    # 認証を持たないテンプレートなので、ADK セッションの所有者は固定値にする。
    # 認証を足すときは、ここをログインユーザー ID に差し替える。
    default_user_id: str = "local-user"

    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS_ORIGINS をカンマ区切りで list[str] に分解する。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


def get_settings() -> Settings:
    """設定を生成する。

    プロセス内でキャッシュしない（テストが環境変数を差し替えて呼び直せるようにするため）。
    実運用では lifespan 内で 1 度だけ呼び、`app.state` に保持して使い回す。
    """
    return Settings()
