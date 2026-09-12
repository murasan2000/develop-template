import { useLayoutEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { IconButton } from '../common/IconButton';
import { SendIcon, StopIcon } from '../common/Icons';
import './Composer.css';

type ComposerProps = {
  isStreaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
};

const MAX_HEIGHT_PX = 200;

/** 入力欄。textarea を内容に合わせて自動で伸縮させ、Enter/Shift+Enter を使い分ける。 */
export function Composer({ isStreaming, onSend, onStop }: ComposerProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 値が変わるたびに高さを一旦リセットしてから scrollHeight を測る。
  // リセットしないと、テキストを削ったときに高さが縮まらない。
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
  }, [value]);

  const submit = () => {
    const text = value.trim();
    if (!text || isStreaming) return;
    onSend(text);
    setValue('');
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // IME 変換確定の Enter まで拾わないよう isComposing を見る（日本語入力での誤送信対策）。
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <textarea
        ref={textareaRef}
        className="composer__textarea"
        placeholder="メッセージを入力…（Shift+Enter で改行）"
        rows={1}
        value={value}
        disabled={isStreaming}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        aria-label="メッセージ入力"
      />
      {isStreaming ? (
        <IconButton label="生成を停止" variant="danger" onClick={onStop}>
          <StopIcon />
        </IconButton>
      ) : (
        <IconButton
          label="送信"
          variant="accent"
          type="submit"
          disabled={value.trim().length === 0}
        >
          <SendIcon />
        </IconButton>
      )}
    </form>
  );
}
