import type { Conversation } from '../../types/api';
import type { DisplayMessage } from '../../hooks/useChat';
import type { PendingAttachment } from '../../hooks/useAttachments';
import { displayTitle } from '../../utils/format';
import { EmptyState } from '../common/EmptyState';
import { ErrorBanner } from '../common/ErrorBanner';
import { IconButton } from '../common/IconButton';
import { MenuIcon } from '../common/Icons';
import { Composer } from './Composer';
import { MessageList } from './MessageList';
import './ChatPane.css';

// 「今の会話に紐づくエラー」だけを ChatPane が受け取る。scope の意味（一覧取得
// 失敗との区別）は App 側の責務なので、ここでは message/retryText だけ見る。
type ConversationError = {
  message: string;
  retryText?: string;
};

type ChatPaneProps = {
  activeConversation: Conversation | undefined;
  messages: DisplayMessage[];
  isLoadingMessages: boolean;
  isStreaming: boolean;
  error: ConversationError | null;
  onSend: (text: string, attachmentIds: string[]) => void;
  onStop: () => void;
  onOpenSidebar: () => void;
  onStartNew: () => void;
  onDismissError: () => void;
  onRetryError: () => void;
  attachments: PendingAttachment[];
  onAddAttachments: (files: File[]) => void;
  onRemoveAttachment: (localId: string) => void;
  isUploadingAttachments: boolean;
  readyAttachmentIds: string[];
};

export function ChatPane({
  activeConversation,
  messages,
  isLoadingMessages,
  isStreaming,
  error,
  onSend,
  onStop,
  onOpenSidebar,
  onStartNew,
  onDismissError,
  onRetryError,
  attachments,
  onAddAttachments,
  onRemoveAttachment,
  isUploadingAttachments,
  readyAttachmentIds,
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
        {error && (
          // 送信・応答生成に関するエラーは、この会話の入力欄のすぐ上に出す。
          // 画面上部の全体バナーだと「どの会話の失敗か」が分かりにくいため。
          <ErrorBanner
            variant="inline"
            message={error.message}
            onDismiss={onDismissError}
            onRetry={error.retryText ? onRetryError : undefined}
            retryDisabled={isStreaming}
          />
        )}
        <Composer
          isStreaming={isStreaming}
          onSend={onSend}
          onStop={onStop}
          attachments={attachments}
          onAddFiles={onAddAttachments}
          onRemoveAttachment={onRemoveAttachment}
          isUploadingAttachments={isUploadingAttachments}
          readyAttachmentIds={readyAttachmentIds}
        />
      </div>
    </div>
  );
}
