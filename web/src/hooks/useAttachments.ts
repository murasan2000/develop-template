// Composer で「送信前に選んだファイル」の状態だけを持つフック。
// useChat.ts から内部で組み立てて再公開する（App からは useChat の戻り値だけを
// 経由させ、ChatPane → Composer の props 経路を 1 本に保つため）。
import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../api/client';
import { ApiError } from '../api/client';
import type { FileMeta } from '../types/api';

export type PendingAttachment =
  | { localId: string; status: 'uploading'; name: string; size: number }
  | { localId: string; status: 'ready'; file: FileMeta }
  | { localId: string; status: 'error'; name: string; message: string };

// クライアント側だけで一意であればよいので、単純な連番でよい（サーバに送らない）。
let localIdSeq = 0;
function nextLocalId(): string {
  localIdSeq += 1;
  return `pending-attachment-${localIdSeq}`;
}

export function useAttachments() {
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);

  // localId ごとの AbortController。アンマウント時や clear() 時に、まだ終わって
  // いないアップロードを中断してレスポンス到着後の setState を防ぐ。
  const controllersRef = useRef<Map<string, AbortController>>(new Map());

  useEffect(() => {
    // クリーンアップ内で ref を直接読むと「実行時に変わっているかもしれない」と
    // lint が警告するため、マウント時点の Map インスタンスを変数で固定して使う
    // （このフックでは Map 自体を作り直さないので実質的には同じものだが、
    // lint の警告に対する素直な対処として変数化する）。
    const controllers = controllersRef.current;
    return () => {
      controllers.forEach((controller) => controller.abort());
      controllers.clear();
    };
  }, []);

  const patch = useCallback((localId: string, next: PendingAttachment) => {
    setAttachments((prev) => prev.map((a) => (a.localId === localId ? next : a)));
  }, []);

  const addFiles = useCallback(
    (files: File[]) => {
      for (const file of files) {
        const localId = nextLocalId();
        setAttachments((prev) => [
          ...prev,
          { localId, status: 'uploading', name: file.name, size: file.size },
        ]);

        const controller = new AbortController();
        controllersRef.current.set(localId, controller);

        api.uploadFile(file, controller.signal).then(
          (meta) => {
            controllersRef.current.delete(localId);
            patch(localId, { localId, status: 'ready', file: meta });
          },
          (e: unknown) => {
            controllersRef.current.delete(localId);
            // 中断（remove / clear / アンマウント）による失敗はユーザー操作の結果なので
            // エラー表示にはしない。
            if (e instanceof DOMException && e.name === 'AbortError') return;
            const message = e instanceof ApiError ? e.message : 'アップロードに失敗しました';
            patch(localId, { localId, status: 'error', name: file.name, message });
          },
        );
      }
    },
    [patch],
  );

  // 個別の取り消し。'ready' は既にサーバ上にファイルが存在するので、孤児として
  // 残さないよう DELETE を呼ぶ（D2: 能動的削除が孤児対策の第一段）。
  // 削除に失敗しても画面からは消してよい（TTL 掃除が最終的な安全網のため）。
  const remove = useCallback((localId: string) => {
    setAttachments((prev) => {
      const target = prev.find((a) => a.localId === localId);
      if (target?.status === 'uploading') {
        controllersRef.current.get(localId)?.abort();
        controllersRef.current.delete(localId);
      }
      if (target?.status === 'ready') {
        void api.deleteFile(target.file.id).catch(() => {
          // 孤児化してもディスクにゴミが残るだけで、TTL 掃除が最終的に回収する。
        });
      }
      return prev.filter((a) => a.localId !== localId);
    });
  }, []);

  // 送信が確定した（サーバが user イベントを返した）後の全消去。この時点の
  // ready ファイルは既にメッセージへ紐づいているので DELETE は呼ばない
  // （呼ぶと 409 になるうえ、そもそも消してはいけない実体）。
  const clear = useCallback(() => {
    controllersRef.current.forEach((controller) => controller.abort());
    controllersRef.current.clear();
    setAttachments([]);
  }, []);

  const readyIds = attachments
    .filter((a): a is { localId: string; status: 'ready'; file: FileMeta } => a.status === 'ready')
    .map((a) => a.file.id);
  const isUploading = attachments.some((a) => a.status === 'uploading');

  return { attachments, addFiles, remove, clear, readyIds, isUploading };
}
