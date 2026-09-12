"""会話・メッセージ（アプリ所有テーブル）の永続化とビジネスロジック。"""

from app.services.chat.repository import (
    add_message,
    create_conversation,
    delete_conversation,
    get_conversation,
    get_conversation_with_messages,
    list_conversations,
    touch_conversation,
)
from app.services.chat.titles import (
    DEFAULT_CONVERSATION_TITLE,
    derive_title_from_content,
    is_default_title,
)

__all__ = [
    "DEFAULT_CONVERSATION_TITLE",
    "add_message",
    "create_conversation",
    "delete_conversation",
    "derive_title_from_content",
    "get_conversation",
    "get_conversation_with_messages",
    "is_default_title",
    "list_conversations",
    "touch_conversation",
]
