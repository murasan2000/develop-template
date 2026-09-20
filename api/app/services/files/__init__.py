"""ファイル置き場（アプリ所有テーブル `files`）の永続化層。"""

from app.services.files.repository import (
    attach_files_to_message,
    create_file_record,
    delete_file_record,
    get_file_record,
    get_files_by_ids,
    list_orphan_file_records,
)

__all__ = [
    "attach_files_to_message",
    "create_file_record",
    "delete_file_record",
    "get_file_record",
    "get_files_by_ids",
    "list_orphan_file_records",
]
