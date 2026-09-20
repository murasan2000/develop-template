import { AlertIcon, CloseIcon } from './Icons';
import './ErrorBanner.css';

type ErrorBannerProps = {
  message: string;
  onDismiss: () => void;
  /** 再送で直る見込みがあるエラーのときだけ渡す。渡さなければボタンごと出さない。 */
  onRetry?: () => void;
  /** ストリーミング中の連打防止用。onRetry が無ければ無視される。 */
  retryDisabled?: boolean;
  /**
   * 'top': 画面全体に対するお知らせ（会話一覧の読み込み失敗など）。
   * 'inline': 特定の会話の流れに紐づくお知らせ（送信・応答生成の失敗）。
   *           チャットペイン内に収め、会話の文脈の中で分かる位置に置く。
   */
  variant?: 'top' | 'inline';
};

/** API エラーを表示するバナー。role="alert" でスクリーンリーダーにも通知する。 */
export function ErrorBanner({
  message,
  onDismiss,
  onRetry,
  retryDisabled,
  variant = 'top',
}: ErrorBannerProps) {
  return (
    <div className={`error-banner error-banner--${variant}`} role="alert">
      <AlertIcon size={18} />
      <span className="error-banner__message">{message}</span>
      {onRetry && (
        <button
          type="button"
          className="error-banner__retry"
          onClick={onRetry}
          disabled={retryDisabled}
        >
          再試行
        </button>
      )}
      <button
        type="button"
        className="error-banner__close"
        onClick={onDismiss}
        aria-label="エラーを閉じる"
      >
        <CloseIcon size={16} />
      </button>
    </div>
  );
}
