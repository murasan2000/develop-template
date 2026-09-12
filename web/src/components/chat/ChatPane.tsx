import type { Conversation } from '../../types/api';
import type { DisplayMessage } from '../../hooks/useChat';
import { displayTitle } from '../../utils/format';
import { EmptyState } from '../common/EmptyState';
import { IconButton } from '../common/IconButton';
import { MenuIcon } from '../common/Icons';
import { Composer } from './Composer';
import { MessageList } from './MessageList';
import './ChatPane.css';

type ChatPaneProps = {
  activeConversation: Conversation | undefined;
  messages: DisplayMessage[];
  isLoadingMessages: boolean;
  isStreaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  onOpenSidebar: () => void;
  onStartNew: () => void;
};

export function ChatPane({
  activeConversation,
  messages,
  isLoadingMessages,
  isStreaming,
  onSend,
  onStop,
  onOpenSidebar,
  onStartNew,
}: ChatPaneProps) {
  // 「会話は選ばれているが読み込み中」「そもそも何も選ばれていない」を区別する。
  // 前者はメッセージ一覧の場所にスピナー的な余白を出し、後者はウェルカム画面にする。
  const hasActiveConversation = activeConversation !== undefined || messages.length > 0;

  return (
    <div className="chat-pane">
      <header className="chat-pane__header">
        <IconButton
          label="会話一覧を開く"
          className="chat-pane__menu-button"
          onClick={onOpenSidebar}
        >
          <MenuIcon />
        </IconButton>
        <h2 className="chat-pane__title">
          {activeConversation ? displayTitle(activeConversation.title) : '新しい会話'}
        </h2>
      </header>

      {hasActiveConversation ? (
        isLoadingMessages ? (
          <div className="chat-pane__loading">読み込み中…</div>
        ) : (
          <MessageList messages={messages} />
        )
      ) : (
        <EmptyState onStart={onStartNew} />
      )}

      <div className="chat-pane__composer-wrap">
        <Composer isStreaming={isStreaming} onSend={onSend} onStop={onStop} />
      </div>
    </div>
  );
}
