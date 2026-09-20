import { useLayoutEffect, useRef, useState } from 'react';
import type { DragEvent, KeyboardEvent } from 'react';
import type { PendingAttachment } from '../../hooks/useAttachments';
import { IconButton } from '../common/IconButton';
import { PaperclipIcon, SendIcon, StopIcon } from '../common/Icons';
import { AttachmentChip } from './AttachmentChip';
import './Composer.css';

type ComposerProps = {
  isStreaming: boolean;
  onSend: (text: string, attachmentIds: string[]) => void;
  onStop: () => void;
  attachments: PendingAttachment[];
  onAddFiles: (files: File[]) => void;
  onRemoveAttachment: (localId: string) => void;
  isUploadingAttachments: boolean;
  readyAttachmentIds: string[];
};

const MAX_HEIGHT_PX = 200;

/** 入力欄。textarea を内容に合わせて自動で伸縮させ、Enter/Shift+Enter を使い分ける。 */
export function Composer({
  isStreaming,
  onSend,
  onStop,
  attachments,
  onAddFiles,
  onRemoveAttachment,
  isUploadingAttachments,
  readyAttachmentIds,
}: ComposerProps) {
  const [value, setValue] = useState('');
  // ドラッグ中だけ枠線色を変えるための表示状態（DOM のドラッグイベントには
  // 「範囲外に出た」を確実に検知する標準的な仕組みが無いので、カウンタではなく
  // dragenter/leave の対称性に頼らず enter で true・drop/leave で false にする）。
  const [isDragOver, setIsDragOver] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 値が変わるたびに高さを一旦リセットしてから scrollHeight を測る。
  // リセットしないと、テキストを削ったときに高さが縮まらない。
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
  }, [value]);

  // 添付のみ（本文が空）でも送信できる（契約のゴール 3）。
  const canSend =
    !isStreaming &&
    !isUploadingAttachments &&
    (value.trim().length > 0 || readyAttachmentIds.length > 0);

  const submit = () => {
    const text = value.trim();
    if (!canSend) return;
    onSend(text, readyAttachmentIds);
    setValue('');
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // IME 変換確定の Enter まで拾わないよう isComposing を見る（日本語入力での誤送信対策）。
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const handleDrop = (e: DragEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files.length > 0) onAddFiles(Array.from(e.dataTransfer.files));
  };

  return (
    <form
      className={`composer ${isDragOver ? 'composer--dragover' : ''}`}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
    >
      {attachments.length > 0 && (
        <div className="composer__attachments">
          {attachments.map((a) => (
            <AttachmentChip
              key={a.localId}
              variant="pending"
              attachment={a}
              onRemove={onRemoveAttachment}
            />
          ))}
        </div>
      )}
      <div className="composer__row">
        <input
          ref={fileInputRef}
          className="composer__file-input"
          type="file"
          multiple
          onChange={(e) => {
            if (e.target.files) onAddFiles(Array.from(e.target.files));
            // 同じファイルを選び直しても change が発火するようにリセットする。
            e.target.value = '';
          }}
        />
        <IconButton
          label="ファイルを添付"
          onClick={() => fileInputRef.current?.click()}
          disabled={isStreaming}
        >
          <PaperclipIcon />
        </IconButton>
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
          <IconButton label="送信" variant="accent" type="submit" disabled={!canSend}>
            <SendIcon />
          </IconButton>
        )}
      </div>
    </form>
  );
}
