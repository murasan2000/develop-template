// 表示専用のフォーマット関数。ロジックを持たない純粋関数だけを置く。

/** ISO 8601 の日時文字列を "HH:mm" 表示にする（サイドバー・吹き出しの時刻表示用）。 */
export function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
}

/** サイドバーの会話一覧を "直近更新が先頭" に保つための比較関数。 */
export function byUpdatedAtDesc<T extends { updated_at: string }>(a: T, b: T): number {
  return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
}

/** タイトル未設定（空文字）の会話をサイドバーで見分けられるようにする。 */
export function displayTitle(title: string): string {
  return title.trim().length > 0 ? title : '新しい会話';
}

/** 添付ファイルのサイズ表示用。バックエンドの上限（MiB 単位）に合わせ 1024 進数で計算する。 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unitIndex]}`;
}
