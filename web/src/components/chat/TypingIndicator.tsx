import './TypingIndicator.css';

/** 送信直後、まだ delta が 1 文字も届いていない間に出す 3 点アニメーション。 */
export function TypingIndicator() {
  return (
    <div className="typing-indicator" role="status" aria-label="応答を生成中">
      <span className="typing-indicator__dot" />
      <span className="typing-indicator__dot" />
      <span className="typing-indicator__dot" />
    </div>
  );
}
