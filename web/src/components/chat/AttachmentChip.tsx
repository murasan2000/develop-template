// 添付ファイル 1 件の表示。Composer の送信前プレビューと MessageBubble の
// 確定済み添付表示の両方から使う（見た目の骨格を 1 箇所にまとめるため）。
// 状態やアップロード処理は持たず、渡された props をそのまま描画するだけにする。
import type { PendingAttachment } from '../../hooks/useAttachments';
import type { FileMeta } from '../../types/api';
import { formatFileSize } from '../../utils/format';
import { IconButton } from '../common/IconButton';
import { CloseIcon } from '../common/Icons';
import './AttachmentChip.css';

function isImage(mimeType: string): boolean {
  return mimeType.startsWith('image/');
}

type AttachmentChipProps =
  // 送信前プレビュー。取り消しボタンを持つ。
  | { variant: 'pending'; attachment: PendingAttachment; onRemove: (localId: string) => void }
  // 確定済みメッセージへの添付。ダウンロード用リンクとして振る舞う。
  | { variant: 'sent'; file: FileMeta };

export function AttachmentChip(props: AttachmentChipProps) {
  if (props.variant === 'sent') {
    const { file } = props;
    if (isImage(file.mime_type)) {
      return (
        <a
          className="attachment-chip attachment-chip--image"
          href={file.content_url}
          target="_blank"
          rel="noreferrer"
        >
          <img className="attachment-chip__thumb" src={file.content_url} alt={file.filename} />
        </a>
      );
    }
    return (
      <a className="attachment-chip attachment-chip--file" href={file.content_url}>
        <span className="attachment-chip__name">{file.filename}</span>
        <span className="attachment-chip__size">{formatFileSize(file.size_bytes)}</span>
      </a>
    );
  }

  const { attachment, onRemove } = props;

  if (attachment.status === 'uploading') {
    return (
      <div className="attachment-chip attachment-chip--pending">
        <span className="attachment-chip__name">{attachment.name}</span>
        <span className="attachment-chip__status">アップロード中…</span>
        <IconButton
          label={`${attachment.name} の添付を取り消す`}
          className="attachment-chip__remove"
          onClick={() => onRemove(attachment.localId)}
        >
          <CloseIcon size={14} />
        </IconButton>
      </div>
    );
  }

  if (attachment.status === 'error') {
    return (
      <div className="attachment-chip attachment-chip--error">
        <span className="attachment-chip__name">{attachment.name}</span>
        <span className="attachment-chip__status">{attachment.message}</span>
        <IconButton
          label={`${attachment.name} の添付を取り消す`}
          className="attachment-chip__remove"
          onClick={() => onRemove(attachment.localId)}
        >
          <CloseIcon size={14} />
        </IconButton>
      </div>
    );
  }

  const { file } = attachment;
  if (isImage(file.mime_type)) {
    return (
      <div className="attachment-chip attachment-chip--image">
        <img className="attachment-chip__thumb" src={file.content_url} alt={file.filename} />
        <IconButton
          label={`${file.filename} の添付を取り消す`}
          className="attachment-chip__remove attachment-chip__remove--overlay"
          onClick={() => onRemove(attachment.localId)}
        >
          <CloseIcon size={14} />
        </IconButton>
      </div>
    );
  }

  return (
    <div className="attachment-chip attachment-chip--file">
      <span className="attachment-chip__name">{file.filename}</span>
      <span className="attachment-chip__size">{formatFileSize(file.size_bytes)}</span>
      <IconButton
        label={`${file.filename} の添付を取り消す`}
        className="attachment-chip__remove"
        onClick={() => onRemove(attachment.localId)}
      >
        <CloseIcon size={14} />
      </IconButton>
    </div>
  );
}
