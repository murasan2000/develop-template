// docs/api-contract.md の型定義に 1:1 対応させる。
// バックエンド（FastAPI）側のスキーマが変わったら、まずこのファイルと契約書を
// 同時に更新する。

export type Role = 'user' | 'assistant';

export type Conversation = {
  id: string; // UUID
  title: string;
  created_at: string; // ISO 8601 (UTC)
  updated_at: string;
};

// ファイル置き場の用途区分。ストレージのレイアウト `storage/<purpose>/<uuid>/<filename>`
// の第 1 階層に一致する。generated は将来のエージェント生成ファイル用の予約で、
// 現時点では API 経由で作られることはない（サーバは常に uploads として保存する）。
export type FilePurpose = 'uploads' | 'generated';

export type FileMeta = {
  id: string; // UUID
  filename: string; // サニタイズ済みの表示名
  mime_type: string;
  size_bytes: number;
  purpose: FilePurpose;
  created_at: string; // ISO 8601 (UTC)
  content_url: string; // 例: "/api/files/<id>/content"
};

export type Message = {
  id: string; // UUID
  conversation_id: string;
  role: Role;
  content: string;
  created_at: string;
  attachments: FileMeta[]; // 添付が無ければ空配列（null / undefined にはしない）
};

export type ConversationDetail = {
  conversation: Conversation;
  messages: Message[];
};

export type HealthResponse = {
  status: 'ok';
  model: string;
  database: 'ok' | 'error';
};

// --- リクエストボディ --------------------------------------------------------

export type CreateConversationRequest = {
  title?: string | null;
};

export type SendMessageRequest = {
  content: string; // attachment_ids が空でないときに限り空文字を許す
  attachment_ids?: string[]; // 省略時は [] として扱う
};

// --- SSE イベント ------------------------------------------------------------
// event 名ごとに data の形が異なるため、判別可能なユニオンとして表現する。
// api/client.ts のパーサはこの型に沿って event/data を組み立てる。

export type DoneEventData = Message & { title: string };

// クライアントが「再試行を勧めるか」を判断するための分類。
// model_overloaded / rate_limited は再送で直る見込みがあり、
// model_unavailable / internal は設定やサーバ側の問題なので再送しても直らない。
export type ErrorCode = 'model_overloaded' | 'rate_limited' | 'model_unavailable' | 'internal';

export type ErrorEventData = {
  message: string; // サーバ側でユーザー向け日本語に変換済み。そのまま表示してよい
  code: ErrorCode;
};

export type DeltaEventData = {
  text: string;
};

export type ChatStreamEvent =
  | { event: 'user'; data: Message }
  | { event: 'delta'; data: DeltaEventData }
  | { event: 'done'; data: DoneEventData }
  | { event: 'error'; data: ErrorEventData };
