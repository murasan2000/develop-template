import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { DisplayMessage } from '../../hooks/useChat';
import { isPendingMessage } from '../../hooks/useChat';
import { formatTime } from '../../utils/format';
import './MessageBubble.css';

type MessageBubbleProps = {
  message: DisplayMessage;
};

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const isStreaming = isPendingMessage(message) && message.status === 'streaming';

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
      </div>
    </div>
  );
}
