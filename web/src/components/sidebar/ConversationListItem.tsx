import type { Conversation } from '../../types/api';
import { displayTitle, formatTime } from '../../utils/format';
import { IconButton } from '../common/IconButton';
import { TrashIcon } from '../common/Icons';
import './ConversationListItem.css';

type ConversationListItemProps = {
  conversation: Conversation;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
};

export function ConversationListItem({
  conversation,
  isActive,
  onSelect,
  onDelete,
}: ConversationListItemProps) {
  return (
    <li className={`conversation-item ${isActive ? 'conversation-item--active' : ''}`}>
      <button type="button" className="conversation-item__button" onClick={onSelect}>
        <span className="conversation-item__title">{displayTitle(conversation.title)}</span>
        <span className="conversation-item__time">{formatTime(conversation.updated_at)}</span>
      </button>
      <IconButton
        label="この会話を削除"
        variant="danger"
        className="conversation-item__delete"
        onClick={(e) => {
          // ボタンの親要素（会話選択ボタン）にクリックが伝播すると選択されてしまうため止める。
          e.stopPropagation();
          onDelete();
        }}
      >
        <TrashIcon size={14} />
      </IconButton>
    </li>
  );
}
