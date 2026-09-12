import { AlertIcon, CloseIcon } from './Icons';
import './ErrorBanner.css';

type ErrorBannerProps = {
  message: string;
  onDismiss: () => void;
};

/** API エラーを画面上部に出すバナー。role="alert" でスクリーンリーダーにも通知する。 */
export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  return (
    <div className="error-banner" role="alert">
      <AlertIcon size={18} />
      <span className="error-banner__message">{message}</span>
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
