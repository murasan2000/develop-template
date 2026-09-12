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

export type Message = {
  id: string; // UUID
  conversation_id: string;
  role: Role;
  content: string;
  created_at: string;
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
  content: string;
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
