import type { ButtonHTMLAttributes, ReactNode } from 'react';
import './IconButton.css';

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  variant?: 'ghost' | 'accent' | 'danger';
  label: string; // aria-label 必須にして、アイコンのみのボタンでも読み上げられるようにする
};

/** アイコンのみの丸ボタン。サイドバー・ヘッダー・入力欄の操作ボタンで共通利用する。 */
export function IconButton({
  children,
  variant = 'ghost',
  label,
  className,
  ...rest
}: IconButtonProps) {
  return (
    <button
      type="button"
      className={`icon-button icon-button--${variant} ${className ?? ''}`}
      aria-label={label}
      title={label}
      {...rest}
    >
      {children}
    </button>
  );
}
