# API 契約（web ⇄ api ⇄ agent）

フロントエンド・バックエンド・エージェント層を並行実装するための取り決め。
3 層が同時に変更される場合は、まずこのファイルを更新して合意を取る。

## HTTP エンドポイント

ベースパスは `/api`。開発時は Vite が `:5173/api` を `:8000` にプロキシする。

| メソッド | パス                               | 概要                                        |
| -------- | ---------------------------------- | ------------------------------------------- |
| `GET`    | `/api/health`                      | ヘルスチェック（DB 接続とモデル名を返す）   |
| `GET`    | `/api/conversations`               | 会話一覧（`updated_at` 降順）               |
| `POST`   | `/api/conversations`               | 会話を新規作成                              |
| `GET`    | `/api/conversations/{id}`          | 会話 1 件＋メッセージ全件                   |
| `DELETE` | `/api/conversations/{id}`          | 会話を削除（メッセージも cascade で削除）   |
| `POST`   | `/api/conversations/{id}/messages` | ユーザー発言を送り、応答を SSE でストリーム |

## スキーマ

```ts
type Role = "user" | "assistant";

type Conversation = {
  id: string; // UUID
  title: string;
  created_at: string; // ISO 8601 (UTC)
  updated_at: string;
};

type Message = {
  id: string; // UUID
  conversation_id: string;
  role: Role;
  content: string;
  created_at: string;
};

type ConversationDetail = {
  conversation: Conversation;
  messages: Message[];
};

type HealthResponse = {
  status: "ok";
  model: string; // 例: "gemini-3.8-flash"
  database: "ok" | "error";
};
```

リクエストボディ:

```ts
// POST /api/conversations
type CreateConversationRequest = { title?: string | null };

// POST /api/conversations/{id}/messages
type SendMessageRequest = { content: string };
```

## SSE（`POST /api/conversations/{id}/messages`）

`Content-Type: text/event-stream`。イベント名付きで送る。

| event   | data                                                            | 意味                             |
| ------- | --------------------------------------------------------------- | -------------------------------- |
| `user`  | `Message`                                                       | 永続化されたユーザー発言         |
| `delta` | `{ "text": "..." }`                                             | 応答の増分テキスト               |
| `done`  | `Message`（assistant の確定メッセージ）＋ `{ "title": string }` | 応答完了。`title` は更新後の題名 |
| `error` | `{ "message": "...", "code": "..." }`                           | 失敗。以降 `delta` は来ない      |

`done` の実体:

```ts
type DoneEvent = Message & { title: string };
```

- 失敗時も HTTP ステータスは 200 のまま `error` イベントで返す
  （ストリーム開始後にステータスを変えられないため）。
- ストリームの最後には必ず `done` か `error` のどちらか一方だけが流れる。
- `done` の `title` は**毎ターン必ず入る**（そのターンで題名が変わらなかった場合も、
  現在の題名をそのまま返す）。クライアントは「無いかもしれない」扱いをしなくてよい。

### `error` イベントの中身

```ts
type ErrorEvent = {
  message: string; // そのまま画面に出せる日本語のメッセージ
  code: ErrorCode;
};

type ErrorCode =
  | "model_overloaded" // モデル混雑（503）。時間を置けば成功する見込みが高い
  | "rate_limited" // レート制限・クォータ超過（429）
  | "model_unavailable" // モデル名誤り・権限不足など、設定を直さないと直らない
  | "internal"; // それ以外
```

- `message` は**ユーザーにそのまま見せられる文面**にする。プロバイダが返す生の
  ペイロード（`{'error': {'code': 503, ...}}` のような JSON 文字列）を画面に流さない。
  原因調査に要る詳細はサーバのログに残す。
- `code` は、クライアントが「再試行を勧めるか」を判断するためにある。
  `model_overloaded` と `rate_limited` は再送で直る見込みがあるので、UI から
  再送できるようにする。`model_unavailable` は再送しても無駄なので勧めない。

### クライアントが途中で切断した場合

ユーザーが停止ボタンを押す等でクライアントが接続を切ったときも、**そこまでに
生成された部分応答はサーバ側で assistant メッセージとして保存する**。

画面に出ていたテキストが、再読み込みすると消えている——という壊れ方を避けるため。
「部分的な結果を捨てない」という方針は、例外で失敗した場合と切断された場合の
どちらにも等しく適用する。

クライアント側は、切断後に画面へ残したテキストとサーバの保存内容が一致する前提で
よい（再取得しても同じものが返る）。

## エラー応答（SSE 以外）

FastAPI 既定の `{"detail": "..."}` 形式。存在しない会話は 404。

## エージェント層の契約（`app/services/agents/`）

バックエンドはエージェントの内部構造を知らず、以下だけを使う。

```python
from app.services.agents import ChatAgentRuntime, create_chat_runtime

# アプリ起動時（lifespan）に 1 つだけ作り、全リクエストで使い回す。
# ADK の Runner はステートレスで、会話履歴は SessionService が持つため。
runtime: ChatAgentRuntime = await create_chat_runtime(
    database_url=...,        # None なら InMemorySessionService にフォールバック
    model=...,
    app_name="chat_template",
    max_retry_attempts=...,  # 初回を含む試行回数（AGENT_RETRY_MAX_ATTEMPTS）
)

await runtime.ensure_session(conversation_id: str, user_id: str) -> None
runtime.stream_reply(conversation_id: str, user_id: str, text: str) -> AsyncIterator[str]
runtime.model_name: str
await runtime.aclose() -> None
```

- `stream_reply` は応答の増分テキストだけを yield する（SSE の `delta` にそのまま載る）。
- 失敗時は `AgentInvocationError`（`code: str` / `message: str` を持つ）を送出する。
  API 層はこの `code` を見て、上記の `ErrorCode` へ振り分ける。
- **一時的な失敗の再試行はエージェント層が内部で行う**（ADK の `RetryConfig`）。
  例外が来た時点で再試行は尽きているので、**API 層で重ねてリトライしない**。
