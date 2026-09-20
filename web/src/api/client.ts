// バックエンド API 呼び出しをここに集約する。
// コンポーネントや hooks が fetch を直接叩かないようにし、エンドポイントや
// エラー処理の変更をこのファイルだけで吸収できるようにするため。
import type {
  ChatStreamEvent,
  Conversation,
  ConversationDetail,
  CreateConversationRequest,
  FileMeta,
  HealthResponse,
} from '../types/api';

const BASE_URL = '/api';

/** API がエラーを返したときに、HTTP ステータスと detail を保持して投げる例外。 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

// FastAPI の既定エラー形式 `{"detail": "..."}` を読み取る。detail が無い/JSON
// でない場合は status text にフォールバックし、どんな失敗でも例外化を保証する。
async function throwIfError(res: Response): Promise<void> {
  if (res.ok) return;
  let message = res.statusText || `HTTP ${res.status}`;
  try {
    const body: unknown = await res.json();
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail?: unknown }).detail;
      if (typeof detail === 'string') message = detail;
    }
  } catch {
    // JSON でなければ statusText のまま使う。
  }
  throw new ApiError(res.status, message);
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  await throwIfError(res);
  return (await res.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>('/health');
}

export function listConversations(): Promise<Conversation[]> {
  return requestJson<Conversation[]>('/conversations');
}

export function createConversation(body: CreateConversationRequest = {}): Promise<Conversation> {
  return requestJson<Conversation>('/conversations', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return requestJson<ConversationDetail>(`/conversations/${id}`);
}

export async function deleteConversation(id: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/conversations/${id}`, { method: 'DELETE' });
  await throwIfError(res);
}

/**
 * ファイルを 1 件アップロードする。
 *
 * `requestJson` は使わない。`fetch` に `Content-Type` を渡すと固定の
 * `application/json` になってしまい、`FormData` に必要な
 * `multipart/form-data; boundary=...`（ブラウザが自動生成する）を上書きして
 * サーバ側のパースを壊す。そのためヘッダを一切指定せず、ブラウザに任せる。
 */
export async function uploadFile(file: File, signal?: AbortSignal): Promise<FileMeta> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE_URL}/files`, {
    method: 'POST',
    body: form,
    signal,
  });
  await throwIfError(res);
  return (await res.json()) as FileMeta;
}

export async function deleteFile(id: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/files/${id}`, { method: 'DELETE' });
  await throwIfError(res);
}

export type ChatStreamCallbacks = {
  onEvent: (event: ChatStreamEvent) => void;
};

/**
 * メッセージ送信 + SSE 応答の読み取り。
 *
 * POST で SSE を受けるため `EventSource` は使えず、`fetch` の
 * `ReadableStream` を手でパースする。SSE は空行区切りのイベント塊で届き、
 * 1 塊の中に `event:` 行と `data:` 行（複数行は改行で連結）が入る仕様
 * （WHATWG "Server-Sent Events" 準拠）なので、それに沿って組み立てる。
 */
export async function sendMessage(
  conversationId: string,
  content: string,
  attachmentIds: string[],
  { onEvent }: ChatStreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE_URL}/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, attachment_ids: attachmentIds }),
    signal,
  });
  await throwIfError(res);
  if (!res.body) throw new ApiError(0, 'レスポンスボディがありません');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // イベント塊は "\n\n" 区切り。最後の未完成な塊は buffer に残しておく。
      let sepIndex: number;
      while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
        const chunk = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);
        const parsed = parseEventChunk(chunk);
        if (parsed) onEvent(parsed);
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** SSE の 1 イベント塊（`event:` 行 + `data:` 行群）を ChatStreamEvent に変換する。 */
function parseEventChunk(chunk: string): ChatStreamEvent | null {
  let eventName = '';
  const dataLines: string[] = [];

  for (const rawLine of chunk.split('\n')) {
    // CRLF 対策。サーバが \r\n で送ってきても壊れないようにする。
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
    if (line.startsWith('event:')) {
      eventName = line.slice('event:'.length).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart());
    }
  }

  if (!eventName || dataLines.length === 0) return null;
  const rawData = dataLines.join('\n');

  try {
    const data: unknown = JSON.parse(rawData);
    // 契約書の event 名以外は未知のイベントとして無視する（将来の拡張に強くする）。
    switch (eventName) {
      case 'user':
      case 'delta':
      case 'done':
      case 'error':
        return { event: eventName, data } as ChatStreamEvent;
      default:
        return null;
    }
  } catch {
    return null;
  }
}
