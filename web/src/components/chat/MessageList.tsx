import { useEffect, useRef } from 'react';
import type { DisplayMessage } from '../../hooks/useChat';
import { isPendingMessage } from '../../hooks/useChat';
import { MessageBubble } from './MessageBubble';
import { TypingIndicator } from './TypingIndicator';
import './MessageList.css';

type MessageListProps = {
  messages: DisplayMessage[];
};

export function MessageList({ messages }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // メッセージが増えた／ストリーミングでテキストが伸びるたびに最下部へ追従する。
  // 会話を読む体験として自然な挙動で、チャット UI ではほぼ必須の動作のため。
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [messages]);

  return (
    // role="log" + aria-live で、支援技術にも新着メッセージが増分で読み上げられるようにする。
    <div className="message-list" role="log" aria-live="polite" aria-relevant="additions">
      {messages.map((m) => {
        if (isPendingMessage(m) && m.role === 'assistant' && m.content === '') {
          // まだ 1 文字も delta が届いていない = 応答生成の待機中。
          return (
            <div className="message-list__typing-row" key={m.id}>
              <TypingIndicator />
            </div>
          );
        }
        return <MessageBubble key={m.id} message={m} />;
      })}
      <div ref={bottomRef} />
    </div>
  );
}
