import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { DisplayMessage } from '../../hooks/useChat';
import { isPendingMessage } from '../../hooks/useChat';
import { formatTime } from '../../utils/format';
import { AttachmentChip } from './AttachmentChip';
import './MessageBubble.css';

type MessageBubbleProps = {
  message: DisplayMessage;
};

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const isStreaming = isPendingMessage(message) && message.status === 'streaming';
  // 添付のみ（本文が空）の送信では、空の吹き出しを出すと見た目が壊れて見える
  // ので、本文が無いときは吹き出し自体を描画しない（添付チップだけ見せる）。
  const hasText = message.content.length > 0;

  return (
    <div className={`message ${isUser ? 'message--user' : 'message--assistant'}`}>
      <div className="message__avatar" aria-hidden="true">
        {isUser ? 'You' : 'AI'}
      </div>
      <div className="message__body">
        <div className="message__meta">
          <span className="message__role">{isUser ? 'あなた' : 'アシスタント'}</span>
          {!isPendingMessage(message) && (
            <span className="message__time">{formatTime(message.created_at)}</span>
          )}
        </div>
        {message.attachments.length > 0 && (
          <div className="message__attachments">
            {message.attachments.map((file) => (
              <AttachmentChip key={file.id} variant="sent" file={file} />
            ))}
          </div>
        )}
        {(hasText || isStreaming) && (
          <div className="message__bubble">
            {isUser ? (
              // ユーザー入力はそのまま表示する（改行だけ活かす）。任意の Markdown 記法を
              // 解釈すると、意図しない強調やリンク化が起きて驚かせてしまうため。
              <p className="message__text">{message.content}</p>
            ) : (
              <div className="message__markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
              </div>
            )}
            {isStreaming && <span className="message__cursor" aria-hidden="true" />}
          </div>
        )}
      </div>
    </div>
  );
}
