"""ファイル実体の保存先（`FileStorage` の実装）を提供するパッケージ。"""

from app.services.storage.local import LocalFileStorage

__all__ = ["LocalFileStorage"]
