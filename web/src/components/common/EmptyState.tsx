import { SparkleIcon } from './Icons';
import './EmptyState.css';

type EmptyStateProps = {
  onStart: () => void;
};

/** 会話が選択されていないときのウェルカム画面。 */
export function EmptyState({ onStart }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <div className="empty-state__icon">
        <SparkleIcon size={32} />
      </div>
      <h1 className="empty-state__title">何を手伝いましょうか？</h1>
      <p className="empty-state__desc">
        メッセージを送ると新しい会話が始まります。左のサイドバーから過去の会話にも戻れます。
      </p>
      <button type="button" className="empty-state__cta" onClick={onStart}>
        新しい会話を始める
      </button>
    </div>
  );
}
