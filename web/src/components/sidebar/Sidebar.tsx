import type { Conversation } from '../../types/api';
import { byUpdatedAtDesc } from '../../utils/format';
import { IconButton } from '../common/IconButton';
import { CloseIcon, PlusIcon } from '../common/Icons';
import { ConversationListItem } from './ConversationListItem';
import './Sidebar.css';

type SidebarProps = {
  conversations: Conversation[];
  activeId: string | null;
  isLoading: boolean;
  isOpen: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onClose: () => void;
};

/**
 * 会話一覧サイドバー。768px 以下ではドロワー化する（isOpen で表示切替）。
 * オーバーレイは isOpen のときだけ DOM に出し、モバイルでの誤タップ・
 * スクリーンリーダーでの読み上げを避ける。
 */
export function Sidebar({
  conversations,
  activeId,
  isLoading,
  isOpen,
  onSelect,
  onNew,
  onDelete,
  onClose,
}: SidebarProps) {
  const sorted = [...conversations].sort(byUpdatedAtDesc);

  return (
    <>
      {isOpen && <div className="sidebar-overlay" onClick={onClose} aria-hidden="true" />}
      <aside className={`sidebar ${isOpen ? 'sidebar--open' : ''}`} aria-label="会話一覧">
        <div className="sidebar__header">
          <button type="button" className="sidebar__new" onClick={onNew}>
            <PlusIcon size={16} />
            新しい会話
          </button>
          <IconButton label="サイドバーを閉じる" onClick={onClose} className="sidebar__close">
            <CloseIcon size={18} />
          </IconButton>
        </div>

        <nav className="sidebar__list-wrap">
          {isLoading ? (
            <p className="sidebar__hint">読み込み中…</p>
          ) : sorted.length === 0 ? (
            <p className="sidebar__hint">まだ会話がありません</p>
          ) : (
            <ul className="sidebar__list">
              {sorted.map((c) => (
                <ConversationListItem
                  key={c.id}
                  conversation={c}
                  isActive={c.id === activeId}
                  onSelect={() => onSelect(c.id)}
                  onDelete={() => onDelete(c.id)}
                />
              ))}
            </ul>
          )}
        </nav>
      </aside>
    </>
  );
}
