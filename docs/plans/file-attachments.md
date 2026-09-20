# 計画: ファイル添付（汎用ファイルストア + チャット添付）

## ゴール

ユーザーから見て次ができたら完了。

1. Composer でファイルを選ぶ（クリック選択 / ドラッグ&ドロップ）と、送信前にプレビュー
   （画像はサムネイル、その他はファイル名チップ）が並び、個別に取り消せる。
2. テキストと一緒に送信すると、ユーザー吹き出しに添付が表示され、**Gemini が中身を
   読んだうえで**返答する（画像・PDF・テキスト）。非対応形式はファイル名とサイズだけが
   モデルに伝わり、エラーにはならない。
3. 添付のみ（本文が空）でも送信できる。
4. 会話を開き直しても添付は履歴に残り、クリックでダウンロードできる。
5. 会話を削除すると、その会話の添付の実体（`storage/` 上のファイル）も消える。

非ゴール（**意図的なスコープ制限。実装時に広げない**）:

- エージェントが生成ファイルを保存するツール（`save_generated_file` 等）は**作らない**。
  `FileStorage` 抽象と `generated` purpose の区分だけ用意する。
- S3 / Azure Blob の実装は**作らない**。`LocalFileStorage` のみ。
- 署名付き URL、クリップボード貼り付け、アップロード進捗バー、ファイルの差し替え編集。

---

## 現状調査

実際に読んだファイルと、そこで分かった事実。

### 契約・規約

- `CLAUDE.md` — 3 層境界、SSE の約束（ストリーム開始後にステータスを変えない／部分応答は
  必ず保存）、DB は 2 系統（アプリ所有 `conversations`/`messages` と ADK 所有）。
- `docs/api-contract.md` — 現在のエンドポイント 6 本、`Message` スキーマ、SSE 4 イベント、
  エージェント層の `stream_reply(conversation_id, user_id, text)`。

### バックエンド

- `/workspace/api/app/servers/api.py`
  - `send_message` は **ストリーム開始前**に会話の存在確認とユーザー発言の永続化を行い、
    ここでだけ 404 を通常の JSON エラーで返している。→ **添付 ID の検証もこの位置で行えば
    通常の HTTP エラーで返せる**（設計の要点）。
  - `_persist_assistant_reply` が「正常完了／例外／クライアント切断」の 3 経路で共有される。
  - `lifespan` で `engine` と `runtime` を 1 度だけ作り `AppState` に載せる。
- `/workspace/api/app/servers/state.py` — `AppState` は `settings / engine / session_factory /
runtime` の dataclass。テストはここを直接差し替えて DI する。
- `/workspace/api/app/services/db/models.py` — `Conversation` / `Message`。`sa.Uuid` / `sa.Text` /
  `sa.DateTime(timezone=True)` のみ使用（SQLite 互換）。`Conversation.messages` は
  `cascade="all, delete-orphan"`。**SQLite は FK を既定で強制しないため ORM cascade に頼る**
  方針がコメントで明記されている。
- `/workspace/api/app/services/chat/repository.py` — `delete_conversation` は ORM の
  `session.delete()` で cascade させている。
- `/workspace/api/app/services/chat/titles.py` — `derive_title_from_content("")` は
  `DEFAULT_CONVERSATION_TITLE` を返す（空本文でも壊れない）。
- `/workspace/api/app/config.py` — `Settings(BaseSettings)`。カンマ区切り文字列を
  `cors_origin_list` プロパティで `list[str]` に割るパターンが既にある（**MIME 許可リストは
  これを踏襲する**）。
- `/workspace/api/app/types/agent_runtime.py` — `ChatAgentRuntime` Protocol。
  「agents が未実装でも backend 側の型チェックが独立して成立するように、具象を import せず
  構造的部分型で持つ」という方針がモジュール docstring に明記されている。
- `/workspace/api/app/utils/errors.py` — 例外 → ユーザー向け文言の純粋関数。`code` 属性の
  有無で構造的に判定している。
- `/workspace/api/tests/conftest.py` — `AppState` を直接組み立てて注入。**`AppState` に
  フィールドを足すとここも直す必要がある**。
- `/workspace/api/tests/fakes.py` — `FakeChatAgentRuntime`。`stream_reply` のシグネチャを
  変えるとここも直す必要がある。`grep` の結果、`fakes.py` を import しているのは
  `tests/conftest.py` と `tests/test_api.py` のみで、**`tests/test_agents.py` は import して
  いない**（＝ fakes.py は backend-builder 側のファイルとして扱ってよい）。

### エージェント層

- `/workspace/api/app/services/agents/runtime.py` — `stream_reply` は
  `types.Content(role="user", parts=[types.Part(text=text)])` を組み立てて `run_async` に渡す。
  **ここが唯一の変更点**（partial の二重排除・エラーイベントの遅延例外化のロジックには触らない）。
- `/workspace/api/app/services/agents/chat.py` / `prompts.py` / `tools.py` — instruction は
  `prompts.py` に分離済み。
- `google.genai` 2.23.0 を実機確認:
  - `types.Part.from_bytes(*, data: bytes, mime_type: str, media_resolution=None) -> Part`
  - `types.Blob` のフィールドは `data` / `display_name` / `mime_type`
  - `types.Part` に `inline_data` / `text` フィールドあり
    → **`types.Part.from_bytes(data=..., mime_type=...)` をそのまま使える**。ファイル名を
    モデルに伝えるには `Part.from_bytes` の戻り値に `display_name` が入らないため、
    **ファイル名は直前に置く text パートで伝える**（下記参照）。

### フロントエンド

- `/workspace/web/src/api/client.ts` — `requestJson` が `Content-Type: application/json` を
  常に付ける。**FormData では使えない**（別経路が要る）。SSE パーサは
  `event:`/`data:` 行を解釈し、未知の event 名は無視する（＝イベント追加に強い）。
- `/workspace/web/src/hooks/useChat.ts` — 状態を全部持つ。`PendingMessage`（表示専用型）、
  `activeIdRef` による stale 判定、`reconcileAfterInterruption`、`RETRYABLE_ERROR_CODES`。
- `/workspace/web/src/components/chat/Composer.tsx` — `value` state と textarea 自動伸縮、
  IME 対応の Enter 送信。`onSend(text)` を呼ぶ。
- `/workspace/web/src/components/chat/MessageBubble.tsx` — user は素のテキスト、assistant は
  `ReactMarkdown`。
- `/workspace/web/src/components/common/Icons.tsx` — inline SVG を自作する方針（アイコン
  ライブラリを入れない）。
- `/workspace/web/src/index.css` — 色は `:root` のトークン（`--surface-2` / `--border` /
  `--text-muted` / `--radius-sm` 等）。**生の色コードを新規 CSS に書かない**。

### インフラ・依存

- `/workspace/api/uv.lock` — **`python-multipart` 0.0.32 は `google-adk` 2.9.0 の依存として
  既にロック済みで、`api/.venv` にもインストール済み**。つまり今日でも `UploadFile` は動く。
  ただし**推移依存に依存した状態は壊れやすい**ので、直接依存として明示する（下記「親が行う」）。
- `/workspace/docker-compose.yml` — api は `./api/app` と `./api/tests` だけをバインド
  マウント（`.venv` は `/opt/venv`）。WORKDIR は `/app`。
- `/workspace/api/Dockerfile` — `dev` stage は root、`prod` stage は uid 10001 `appuser`。
- `/workspace/.gitignore` — `.env.*` + `!.env.example` の否定パターンの前例あり。

---

## 契約変更

**`docs/api-contract.md` は変わる。** 更新は**親（呼び出し元）が builder 起動前に行う**。
以下がそのまま新しい契約の本文になる（担当エージェントはこれを唯一の正として実装する）。

### 追加エンドポイント

| メソッド | パス                      | 概要                                               |
| -------- | ------------------------- | -------------------------------------------------- |
| `POST`   | `/api/files`              | ファイルを 1 件アップロード（multipart/form-data） |
| `GET`    | `/api/files/{id}/content` | ファイル本体をダウンロード                         |
| `DELETE` | `/api/files/{id}`         | 未添付ファイルを削除（添付済みは 409）             |

### 追加・変更スキーマ

```ts
// ファイル置き場の用途区分。ストレージのレイアウト `storage/<purpose>/<uuid>/<filename>`
// の第 1 階層に一致する。generated は将来のエージェント生成ファイル用の予約で、
// 今回のスコープでは API 経由で作られることはない。
type FilePurpose = "uploads" | "generated";

type FileMeta = {
  id: string; // UUID
  filename: string; // サニタイズ済みの表示名
  mime_type: string;
  size_bytes: number;
  purpose: FilePurpose;
  created_at: string; // ISO 8601 (UTC)
  content_url: string; // 例: "/api/files/<id>/content"
};

// 変更: attachments を追加（添付が無ければ空配列。null や undefined にはしない）
type Message = {
  id: string;
  conversation_id: string;
  role: Role;
  content: string;
  created_at: string;
  attachments: FileMeta[]; // ★追加
};

// 変更: attachment_ids を追加
type SendMessageRequest = {
  content: string; // attachment_ids が空でないときに限り空文字を許す
  attachment_ids?: string[]; // 省略時は [] として扱う
};
```

`content_url` を持たせる理由: クライアントに URL を組み立てさせない。将来クラウド
ストレージへ移行して署名付き URL を返すようになっても、**サーバがこのフィールドの中身を
差し替えるだけでフロントエンドは無変更で済む**。

### SSE への影響

**イベントの種類は増えない。** 既存イベントの data の形だけが変わる。

- `user` イベントの data（`Message`）に `attachments: FileMeta[]` が乗る。
  ユーザーが添付したファイルのメタ情報がここに入る。
- `done` イベントの data（`Message & { title }`）にも `attachments: FileMeta[]` が乗る。
  **今回のスコープでは assistant メッセージに添付は付かないので、常に `[]`**。
  それでも省略せず必ず入れる（`Message` の形を role で分岐させない方が、クライアントの
  分岐が減って壊れにくいため）。
- `delta` / `error` は変更なし。

### エラー応答（SSE 以外）

`POST /api/files`:

| ステータス | detail の意味                |
| ---------- | ---------------------------- |
| 413        | ファイルサイズが上限を超えた |
| 415        | 許可されていない MIME タイプ |
| 400        | ファイルが空（0 バイト）     |

`GET /api/files/{id}/content`: 404（DB に無い / 実体が無い）

`DELETE /api/files/{id}`: 404（無い） / 409（既にメッセージに添付済み）

`POST /api/conversations/{id}/messages`（**すべてストリーム開始前に返す**）:

| ステータス | 条件                                                           |
| ---------- | -------------------------------------------------------------- |
| 404        | 会話が存在しない / `attachment_ids` に存在しない ID が含まれる |
| 409        | `attachment_ids` に既に別メッセージへ添付済みの ID が含まれる  |
| 400        | `content` が空かつ `attachment_ids` も空                       |
| 400        | 添付の件数上限超過 / 添付の合計サイズ上限超過                  |

### エージェント層の契約（`app/services/agents/`）

```python
from collections.abc import AsyncIterator, Sequence
from typing import TypedDict


class AgentAttachment(TypedDict):
    """`stream_reply` にマルチモーダル入力として渡す添付 1 件。

    `data` は常に実体のバイト列（API 層が FileStorage から読み出して渡す）。
    「この MIME タイプをモデルに読ませられるか」の判断はエージェント層が行う
    （モデルの能力に関する知識なので、モデル統合側に置く）。
    """

    filename: str
    mime_type: str
    size_bytes: int
    data: bytes


# 変更後のシグネチャ（attachments は既定値つきで追加する）
runtime.stream_reply(
    conversation_id: str,
    user_id: str,
    text: str,
    attachments: Sequence[AgentAttachment] = (),
) -> AsyncIterator[str]
```

`ensure_session` / `aclose` / `model_name` / `create_chat_runtime` / `AgentInvocationError` は
**変更なし**。

**`AgentAttachment` は両層でそれぞれ宣言する**（backend 側は
`api/app/types/attachments.py`、agent 側は `api/app/services/agents/attachments.py`）。
`TypedDict` は mypy において構造的に互換なので、**同じキー・同じ型で宣言されていれば
別モジュールで宣言されたもの同士が相互に代入可能**。実際に `mypy --strict` で検証済み
（別モジュールで独立宣言した同形 TypedDict を跨いで渡して `Success: no issues found`）。
これにより `app/types/agent_runtime.py` の既存方針（具象を import せず構造的部分型で持つ）を
そのまま添付にも適用でき、**backend と agent を完全に並列実装できる**。
定義を変える場合は必ず両方を同時に変えること。

---

## 設計判断（担当エージェントはここを前提に実装する。勝手に変えない）

### D1. アップロードは送信とは別エンドポイントにする

`POST /api/files` で先に上げ、`POST /api/conversations/{id}/messages` には
`attachment_ids` だけを JSON で渡す。multipart で一緒に送らない。

理由:

1. **失敗を通常の HTTP ステータスで返せる**。サイズ超過・MIME 不許可は SSE が始まった後では
   `event: error` でしか返せず（契約より、ストリーム開始後はステータスを変えられない）、
   「送信を押すまで弾かれたか分からない」体験になる。分離すればファイルを選んだ瞬間に
   413/415 で弾ける。
2. **既存の SSE エンドポイントの入力形式を壊さない**。`SendMessageRequest` は JSON のまま
   なので、`web/src/api/client.ts` の `sendMessage`（fetch + ReadableStream パーサ）も、
   `app/servers/api.py` の `send_message`（Pydantic ボディ）も構造を維持できる。
3. **汎用ファイルストアという前提に合う**。ファイルはチャットとは独立した資源として作られ、
   後からメッセージに紐づく。エージェント生成ファイル（`generated`）も同じテーブル・同じ
   ストレージに入る。
4. ユーザーが本文を打っている間に裏でアップロードが終わるので、体感が速い。

### D2. 孤児ファイル（アップロードされたが送信されなかったファイル）

3 段構えにする。

1. **能動的削除**: フロントエンドはプレビューの取り消しボタンで `DELETE /api/files/{id}` を
   呼ぶ。通常の操作で出る孤児はここでほぼ消える。
2. **TTL による掃除**: `files.message_id IS NULL` かつ `created_at` が
   `ORPHAN_FILE_TTL_HOURS`（既定 24）より古い行を、DB 行と実体の両方削除する
   `sweep_orphan_files()` を用意し、**lifespan の起動時に 1 回だけ**呼ぶ。
3. **限界の明示**: 起動時のみなので、長時間動き続けるプロセスでは掃除されない。
   これは `create_all` をマイグレーションの代わりにしているのと同じ性質の割り切りなので、
   **同じトーンでコメントに残す**（「本番ではスケジューラ / cron ジョブに置き換えること」）。
   テンプレートに常駐バックグラウンドタスクのライフサイクル管理を持ち込むのは、得られる
   ものに対して機構が重いと判断した。

会話削除時: `delete_conversation` は**削除前に対象の `storage_key` を集め、コミット成功後に
`storage.delete()` をベストエフォートで呼ぶ**（失敗しても例外にせず warning ログ）。
DB 行は ORM cascade（`Conversation.messages` → `Message.attachments`）で消える。
実体の削除に失敗してもユーザーに見える壊れ方はしない（ディスクにゴミが残るだけ）一方、
ここで例外にすると会話削除そのものが失敗する。この非対称性が理由。

### D3. `FileStorage` Protocol に署名付き URL を入れるか → **入れない**

理由:

1. **Protocol には「どの実装でも無理なく実装できる操作」だけを置く**。`LocalFileStorage` は
   本物の署名を発行できず、偽の URL を返すか `NotImplementedError` を投げるしかない。
   境界に「実装によっては使えないメソッド」が混ざると、呼び出し側が結局分岐を持つことになり、
   Protocol で差し替え可能にした意味が薄れる。
2. **今回のダウンロード経路は、どのみち API を通す必要がある**。`GET /api/files/{id}/content`
   は DB でメタデータを引き、（将来は）認可も見る。署名付き URL はこの 1 箇所の関門を
   迂回するので、認可を足した瞬間に穴になる。
3. **後から足すのは壊さずにできる**。別の任意ケイパビリティとして
   `SignedUrlCapableStorage(Protocol)` を定義し、API 層で `isinstance(storage,
SignedUrlCapableStorage)` を見て、対応していれば 307 リダイレクト、していなければ
   従来どおりストリーム、とする。**これを「将来こうする」とコードコメントに残す**ので、
   実装漏れではなく意図的な先送りだと分かる形にする。
4. 追加すべき時期の判断基準も残す: 大きいファイルを API プロセス経由で流す帯域コストが
   問題になったとき（つまりクラウド移行と同時）。

### D4. マルチモーダルの送り方と、ADK セッションへの inline データ蓄積

**添付のバイト列は、添付されたそのターンにだけ送る。以降のターンで送り直さない。**

ADK の `SessionService` は `run_async` に渡した `new_message` をイベントとして保持するため、
一度送った inline データはそのセッションの文脈に残り続ける。したがって:

- **送り直す必要がない**。モデルは同じ会話の後続ターンでも、セッション履歴を通じて
  その画像／PDF を参照できる。毎ターン送り直すと同じバイト列がセッションに何重にも
  積み上がり、リクエストサイズとコストが線形に膨らむ。
- **蓄積そのものは避けられない**ので、**入口で上限を掛けることで境界を作る**:
  - 1 ファイル 10 MiB（`UPLOAD_MAX_FILE_BYTES`）
  - 1 メッセージあたり 5 件（`UPLOAD_MAX_FILES_PER_MESSAGE`）
  - 1 メッセージあたり合計 15 MiB（`UPLOAD_MAX_TOTAL_BYTES_PER_MESSAGE`）
    合計上限は、Gemini のリクエストサイズ制限（inline_data 込みで概ね 20MB）に対する余裕であり、
    同時に**1 リクエストで API プロセスがメモリに載せるバイト数の上限**でもある。
- 残る限界（**リスク節にも再掲**）: 1 つの会話で画像を何度も添付し続けると、ADK
  セッションが膨らみ、いずれコンテキスト長やレイテンシに響く。今回は上限で緩和するに
  留め、セッションの剪定（古い inline パートの間引き）は行わない。

Google Files API（アップロード後にファイル参照を渡す方式）は採らない。外部への
アップロードという副作用と 48 時間の有効期限という別のライフサイクルが増え、
「ローカルの `storage/` を唯一の実体とする」という今回の前提とずれるため。

### D5. 非対応 MIME タイプの扱い

エージェント層が判定する。**inline で渡せるのは次だけ**:

- `image/` で始まる
- `text/` で始まる
- ちょうど `application/pdf`

それ以外は `types.Part.from_bytes` を使わず、**text パートで存在だけを伝える**。
この文面は LLM に渡る仕様なので、**`prompts.py` に定数として置く**（コードと文面を混ぜない、
という ADK 設計方針 3 に従う）:

```python
# prompts.py
UNSUPPORTED_ATTACHMENT_NOTE = (
    "[添付ファイル: {filename}（{mime_type}, {size_bytes} バイト）。"
    "この形式は直接読み取れないため、内容は不明です。]"
)
```

ファイル名をモデルに伝える方法: `Part.from_bytes` にはファイル名を載せる口が無い
（`types.Blob.display_name` は存在するが `from_bytes` は設定しない）。そこで
**対応形式でも、inline パートの直前にファイル名を伝える text パートを 1 つ置く**:

```python
# prompts.py
ATTACHMENT_LABEL = "[添付ファイル: {filename}（{mime_type}）]"
```

パートの並び順（この順で組み立てる）:

```
[ラベル(file1), inline(file1), ラベル(file2), inline(file2), ..., 本文テキスト]
```

本文テキストが空文字のときは**テキストパートを足さない**（空の Part を送らない）。
添付が 0 件かつ本文が空になることは API 層の検証で起こり得ない。

### D6. ファイル名サニタイズとパストラバーサル

**2 重に防ぐ。**

1. **`app/utils/files.py`（新規・純粋関数）でファイル名を正規化する**。
   `sanitize_filename(raw: str) -> str`:
   - POSIX / Windows 両方のパス区切りで分割して最後の要素だけ取る（`../../etc/passwd` →
     `passwd`、`C:\tmp\a.txt` → `a.txt`）
   - NUL・制御文字を除去、先頭の `.` と空白を除去
   - 結果が空 / `.` / `..` なら `"file"` にフォールバック
   - **日本語などの非 ASCII は残す**（ファイル名が読めなくなる方がユーザーに損）
   - UTF-8 で 255 バイトを超えたら拡張子を保ったまま切り詰める
2. **`LocalFileStorage` 側でルート外への脱出を再検査する**。Protocol は任意の `key` 文字列を
   受けるので、実装側で `(root / key).resolve()` が `root.resolve()` の配下にあることを
   確認し、外れていれば `ValueError` を投げる。1 だけに頼ると、将来 `key` を組み立てる
   別の呼び出し元が増えたときに破れる。

なお**保存先の一意性はサニタイズに依存しない**。レイアウトが
`storage/<purpose>/<uuid>/<filename>` で、UUID ディレクトリが衝突を吸収するため、
サニタイズの目的は純粋に安全性（脱出・制御文字）に絞れる。

MIME タイプの決定（`app/utils/files.py` の純粋関数 `resolve_mime_type`）:
`UploadFile.content_type` からパラメータを落として小文字化 → 未指定または
`application/octet-stream` ならサニタイズ済みファイル名の拡張子から `mimetypes.guess_type`
→ それでも不明なら `application/octet-stream`。**中身のバイト列による sniffing（python-magic
等）は導入しない**（依存を増やさない方針）。クライアント申告を信用する形になることは
docstring に明記する。

### D7. ダウンロード応答の安全性

同一オリジンから任意のユーザーアップロードを配るため、保存型 XSS の温床になり得る。
`GET /api/files/{id}/content` のレスポンスヘッダに必ず次を付ける:

- `Content-Disposition: attachment; filename*=UTF-8''<percent-encoded>` — 既定でダウンロード。
  **`<img src>` のようなサブリソース読み込みは Content-Disposition を無視する**ので、
  これを付けても画像プレビューは動く（HTML/SVG をブラウザに描画させない効果だけが残る）。
- `X-Content-Type-Options: nosniff`
- `Content-Security-Policy: default-src 'none'; sandbox`
- `Cache-Control: private, max-age=3600`（ファイルは UUID キーで不変なのでキャッシュしてよい）

### D8. 本文が空の場合のタイトル

現状 `send_message` は `derive_title_from_content(body.content)` でタイトルを作る。
本文が空（添付のみ）のときは**最初の添付のファイル名を渡す**:

```python
title_source = body.content.strip() or (attachments[0].filename if attachments else "")
new_title = chat_service.derive_title_from_content(title_source) if should_retitle else None
```

`derive_title_from_content` 自体は変更不要（空文字ならデフォルトタイトルを返す既存挙動で
問題ない）。

### D9. 再試行（retry）ボタンと添付

`useChat` の `retryLastMessage` は**本文のみを再送する**。添付があったターンの失敗では
**再試行ボタンを出さない**（`retryText` を立てない）。

理由: 失敗時もユーザーメッセージは既に永続化されており（`send_message` はストリーム開始前に
保存する）、その添付は既にそのメッセージに紐づいている。1 ファイルは 1 メッセージにしか
属せないので、同じ `attachment_ids` を再送すると 409 になる。「再添付」の意味論を
テンプレートに発明するより、再試行の対象を添付なしのケースに限る方が正直で壊れない。
ユーザーは通常どおり新しくメッセージを送ればよい。

---

## 担当分割

### frontend-builder（`web/` 配下のみ）

**変更するファイル**

- `web/src/types/api.ts`（変更）
- `web/src/api/client.ts`（変更）
- `web/src/hooks/useAttachments.ts`（新規）
- `web/src/hooks/useChat.ts`（変更）
- `web/src/components/chat/Composer.tsx` / `Composer.css`（変更）
- `web/src/components/chat/ChatPane.tsx`（変更・props の中継のみ）
- `web/src/components/chat/MessageBubble.tsx` / `MessageBubble.css`（変更）
- `web/src/components/chat/AttachmentChip.tsx` / `AttachmentChip.css`（新規・表示専用）
- `web/src/components/common/Icons.tsx`（`PaperclipIcon` を追加）
- `web/src/App.tsx`（変更・`useChat` の新しい戻り値を `ChatPane` へ渡す）

**やること**

1. `types/api.ts` に上の契約どおり `FilePurpose` / `FileMeta` を足し、`Message` に
   `attachments: FileMeta[]`、`SendMessageRequest` に `attachment_ids?: string[]` を足す。
   `DoneEventData` は `Message & { title }` のままで自動的に追随する。
2. `api/client.ts` に追加:
   - `uploadFile(file: File, signal?: AbortSignal): Promise<FileMeta>` —
     `FormData` を使う。**`Content-Type` ヘッダを自分で設定しないこと**（ブラウザが
     `multipart/form-data; boundary=...` を付ける。手で付けると boundary が落ちてサーバが
     パースできなくなる）。既存の `requestJson` は常に JSON ヘッダを付けるので**使わず**、
     `fetch` + `throwIfError` を直接使う。フォームのフィールド名は **`file`**。
   - `deleteFile(id: string): Promise<void>`
   - `sendMessage` の引数に `attachmentIds: string[]` を追加し、ボディを
     `JSON.stringify({ content, attachment_ids: attachmentIds })` にする。
     SSE パーサ部分は変更しない。
3. `hooks/useAttachments.ts`（新規）— 送信前の添付リストの状態だけを持つ。
   ```ts
   export type PendingAttachment =
     | { localId: string; status: "uploading"; name: string; size: number }
     | { localId: string; status: "ready"; file: FileMeta }
     | { localId: string; status: "error"; name: string; message: string };
   ```
   公開 API: `attachments`, `addFiles(files: File[]): void`, `remove(localId): void`,
   `clear(): void`, `readyIds: string[]`, `isUploading: boolean`。
   - `remove` は `status: 'ready'` のとき `api.deleteFile` も呼ぶ（孤児を残さない。D2）。
   - アップロード失敗時は `ApiError.message`（サーバの `detail`）をそのまま表示に使う。
   - アンマウント時に in-flight のアップロードを abort する。
4. `hooks/useChat.ts` — `useAttachments` を**内部で組み立てて再公開する**
   （`ChatPane` → `Composer` への props 経路を 1 本に保つため、新しい独立フックを
   `App` 側で併置しない）。
   - `sendMessage(content: string)` を `sendMessage(content: string, attachmentIds: string[])`
     に変更。`if (!text && attachmentIds.length === 0) return;` へ条件を緩める
     （**本文が空でも添付があれば送れる**）。
   - 送信開始時に、表示用の `PendingMessage` へ `attachments: FileMeta[]` を持たせる
     （送信直後の吹き出しにも添付が出るように）。`pendingUserText` の代わりに
     `pendingUser: { text: string; attachments: FileMeta[] } | null` にする。
   - `user` イベントを受けたら `clear()` で添付リストを空にする（サーバが受理した確証が
     得られた時点。ここより早いとエラー時に添付が消えてしまう）。
   - `retryLastMessage` は D9 のとおり。`retryText` は**添付なしの送信だったときだけ**立てる。
   - 既存の `reconcileAfterInterruption` / stale 判定 / `RETRYABLE_ERROR_CODES` の構造は
     **崩さない**。
5. `Composer.tsx` —
   - クリップアイコンのボタン（`IconButton` + 新規 `PaperclipIcon`、`aria-label="ファイルを添付"`）と
     隠し `<input type="file" multiple>`。
   - `onDragOver` / `onDragLeave` / `onDrop` で D&D を受ける。ドラッグ中は
     `composer--dragover` クラスでトークン由来の枠線色に変える。
   - プレビュー行: 画像（`mime_type` が `image/` で始まる）は `content_url` をそのまま
     `<img>` の `src` に、それ以外はファイル名チップ。各チップに取り消しボタン
     （`aria-label` 必須）。`uploading` はスピナー的なテキスト、`error` は文言を出す。
   - 送信可否: `text.trim().length > 0 || readyIds.length > 0`。アップロード中は送信不可。
   - 送信時に `onSend(text, readyIds)`。
6. `MessageBubble.tsx` — `message.attachments` を `AttachmentChip` で描画する。画像は
   サムネイル（`<img>`、`alt` にファイル名）、それ以外は `<a href={content_url}>` の
   ダウンロードリンク。`attachments` が空配列のときは何も描画しない。
7. CSS は `index.css` の既存トークンのみ使用。**生の色コードを書かない。**
   `prefers-reduced-motion` を尊重する。

**やらないこと**

- `docs/api-contract.md` の更新（親）。
- 依存ライブラリの追加（**`npm install` は一切しない**。D&D もプレビューも素の DOM API で書く）。
- クリップボード貼り付け、アップロード進捗率の表示（スコープ外）。
- `api/` 配下のファイル。

---

### backend-builder（`api/` のうち `app/services/agents/` を除く部分）

**変更するファイル**

- `api/app/config.py`（変更）
- `api/app/services/db/models.py`（変更 — `FileRecord` 追加、`Message.attachments` 追加）
- `api/app/services/db/__init__.py`（変更 — 再エクスポート）
- `api/app/services/storage/__init__.py`, `local.py`（新規）
- `api/app/services/files/__init__.py`, `repository.py`（新規）
- `api/app/types/file_storage.py`（新規 — `FileStorage` Protocol）
- `api/app/types/attachments.py`（新規 — `AgentAttachment` TypedDict、backend 側の宣言）
- `api/app/types/agent_runtime.py`（変更 — `stream_reply` に `attachments` を追加）
- `api/app/types/api.py`（変更 — `FileOut` 追加、`MessageOut`/`DoneEventPayload` に
  `attachments`、`SendMessageRequest` に `attachment_ids`）
- `api/app/utils/files.py`（新規 — 純粋関数）
- `api/app/servers/state.py`（変更 — `AppState.storage` を追加）
- `api/app/servers/api.py`（変更 — files ルータ 3 本、`send_message` の添付処理、lifespan）
- `api/app/services/chat/repository.py`（変更 — 添付の解決／紐付け／削除時のキー収集）
- `api/tests/conftest.py`, `api/tests/fakes.py`（変更）
- `api/tests/test_api.py`（変更）、`api/tests/test_files_api.py` /
  `api/tests/test_file_storage.py` / `api/tests/test_file_utils.py`（新規）

**やること**

1. **`FileStorage` Protocol**（`api/app/types/file_storage.py`）。
   `app/types/agent_runtime.py` と同じ書き方（`@runtime_checkable`、docstring に意図）。

   ```python
   @runtime_checkable
   class FileStorage(Protocol):
       async def save(self, key: str, data: bytes) -> None: ...
       async def load(self, key: str) -> bytes: ...
       def open_stream(self, key: str) -> AsyncIterator[bytes]: ...
       async def delete(self, key: str) -> None: ...
   ```

   - `key` は `"<purpose>/<uuid>/<filename>"` 形式の POSIX 風パス。
   - `load` / `open_stream` は存在しないキーで **`FileNotFoundError`** を送出する
     （将来の S3/Azure 実装もこれに合わせる、と docstring に明記）。
   - `delete` は存在しないキーでも**例外にしない**（冪等）。
   - **署名付き URL は入れない**。D3 の理由と、将来の
     `SignedUrlCapableStorage(Protocol)` による拡張方針をモジュール docstring に残す。
   - `load` と `open_stream` を両方持つ理由もコメントに残す（前者は Gemini へ渡す
     バイト列用で上限付き、後者はダウンロードでメモリに全部載せないため）。

2. **`LocalFileStorage`**（`api/app/services/storage/local.py`）。
   - コンストラクタで `root: Path` を受ける。
   - `_resolve(key)` で D6-2 のルート外脱出検査を行い、全メソッドがこれを通る。
   - `save` は親ディレクトリを `mkdir(parents=True, exist_ok=True)` してから書く。
   - ブロッキング I/O は `anyio.to_thread.run_sync` でスレッドに逃がす
     （`anyio` は既に `api.py` で使用済みの依存）。
   - `open_stream` は 64 KiB 程度のチャンクで `AsyncIterator[bytes]` を返す。
   - `__init__.py` で `LocalFileStorage` を再エクスポート。

3. **DB モデル**（`api/app/services/db/models.py`）。

   ```python
   class FileRecord(Base):
       """ファイル置き場のメタデータ。実体は FileStorage 側にあり、ここには入れない。"""

       __tablename__ = "files"
       __table_args__ = (
           sa.Index("ix_files_message_id", "message_id"),
           # 孤児掃除（message_id IS NULL かつ古いもの）の走査用。
           sa.Index("ix_files_created_at", "created_at"),
       )

       id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
       purpose: Mapped[str] = mapped_column(sa.Text, nullable=False)
       filename: Mapped[str] = mapped_column(sa.Text, nullable=False)
       mime_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
       size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
       storage_key: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True)
       message_id: Mapped[uuid.UUID | None] = mapped_column(
           sa.Uuid, sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
       )
       created_at: Mapped[datetime] = mapped_column(
           sa.DateTime(timezone=True), nullable=False, default=_utcnow
       )

       message: Mapped[Message | None] = relationship(back_populates="attachments")
   ```

   `Message` 側に追加:

   ```python
   attachments: Mapped[list[FileRecord]] = relationship(
       back_populates="message",
       cascade="all, delete-orphan",
       order_by="FileRecord.created_at",
   )
   ```

   - **PostgreSQL 固有型は使わない**（`sa.BigInteger` は SQLite でも動く可搬型）。
   - **`conversation_id` は持たせない**。`useChat` は最初の送信時に会話を遅延作成するため、
     アップロード時点では会話がまだ存在しないことがある。またファイル置き場は会話に
     従属しない汎用資源として設計する（前提 1）。紐付けはメッセージ経由でのみ行う。
   - 会話削除 → メッセージ削除 → ファイル行削除、が ORM cascade で繋がることを確認する。
   - `Conversation.messages` に `selectinload` している既存箇所
     （`get_conversation_with_messages`）は、`attachments` も
     `selectinload(Conversation.messages).selectinload(Message.attachments)` で先読みする。
     **入れ忘れると非同期セッションで lazy load 例外になる**ので必ず入れる。

4. **設定**（`api/app/config.py`）。既存の `cors_origin_list` と同じ形で:

   ```python
   storage_dir: str | None = None
   upload_max_file_bytes: int = 10_485_760  # 10 MiB
   upload_max_files_per_message: int = 5
   upload_max_total_bytes_per_message: int = 15_728_640  # 15 MiB
   upload_allowed_mime_types: str = (
       "image/png,image/jpeg,image/webp,image/gif,"
       "application/pdf,text/plain,text/markdown,text/csv,"
       "application/json,application/zip"
   )
   orphan_file_ttl_hours: int = 24


   @property
   def storage_path(self) -> Path: ...
   @property
   def allowed_mime_type_list(self) -> list[str]: ...
   ```

   - `storage_path`: `storage_dir` が設定されていればそれを `expanduser().resolve()`。
     `None` なら**リポジトリ直下の `storage/`** を指す
     （`Path(__file__).resolve().parents[2] / "storage"` = `api/app/config.py` →
     `api/app/` → `api/` → リポジトリルート）。`cd api && uv run uvicorn ...` でも
     リポジトリルートから起動しても同じ場所を指すのが狙い。**Docker では
     `STORAGE_DIR=/data/storage` が必ず設定される**のでフォールバックは使われない
     （コンテナ内の `/app/app/config.py` では parents[2] が `/` になってしまうため、
     この前提をコメントに残す）。
   - `allowed_mime_type_list`: **空文字列は「全許可」**とする（派生プロジェクト向けの
     脱出口）。docstring に明記。
   - 既定の許可リストには**わざと inline 非対応のもの（`application/json` /
     `application/zip`）を含める**。前提 4 の「非対応 MIME はファイル名とサイズだけ
     伝える」経路が実際に到達可能であるようにするため。

5. **純粋関数**（`api/app/utils/files.py`）— D6 の `sanitize_filename` /
   `resolve_mime_type` / `build_storage_key(purpose, file_id, filename) -> str` /
   `content_disposition_header(filename) -> str`（RFC 5987 の `filename*=UTF-8''...`）。
   DB も I/O も触らない。

6. **リポジトリ**（`api/app/services/files/repository.py`）。
   `create_file_record` / `get_file_record` / `get_unattached_files_by_ids` /
   `attach_files_to_message` / `delete_file_record` / `list_orphan_file_keys`。
   SQLAlchemy の詳細はここに閉じる（`app/services/chat/repository.py` と同じ粒度）。

7. **エンドポイント**（`api/app/servers/api.py`）。既存の
   「入力を検証し、サービスを呼び、型に詰めて返す」粒度を守る。
   - `POST /api/files`: `file: Annotated[UploadFile, File()]`。
     **読みながら上限を検査する**（`await file.read(1 MiB)` をループし、累計が
     `upload_max_file_bytes` を超えた時点で即 413。先に全部読んでから測るとメモリ枯渇の
     経路になる、という理由をコメントに残す）。0 バイトは 400。MIME を `resolve_mime_type`
     で決めて許可リストと照合、外れていれば 415。`purpose` は**常に `"uploads"`
     でサーバが決める**（クライアントに `generated` を作らせない。`generated` は将来の
     サーバ側ツール専用、という理由をコメントに残す）。
     保存 → DB 行作成 → 201 で `FileOut`。**ストレージ保存に成功して DB コミットに失敗
     した場合は、保存済みの実体を削除してから例外を投げ直す**（孤児を作らない）。
   - `GET /api/files/{id}/content`: DB から引き、`StreamingResponse(storage.open_stream(key))`。
     D7 のヘッダを全部付ける。DB に無い / `FileNotFoundError` は 404。
   - `DELETE /api/files/{id}`: `message_id` が非 NULL なら 409。NULL なら実体 → DB 行の順に削除、204。
   - `send_message` の変更（**ストリーム開始前のブロック内で完結させる**）:
     1. `body.content.strip()` が空かつ `attachment_ids` が空 → 400。
     2. `attachment_ids` の件数 / 重複を検査（重複は 400）。
     3. DB から該当 `FileRecord` を取得。欠けていれば 404、`message_id` が非 NULL なら 409。
     4. 合計 `size_bytes` が上限超過なら 400。
     5. ユーザーメッセージを保存し、`attach_files_to_message` で紐付けて commit。
     6. `MessageOut.model_validate(user_message)` に `attachments` が乗るようにする。
     7. **ストレージからバイト列を読み、`AgentAttachment` のリストを組み立てる**
        （`event_stream` の外、ストリーム開始前に読む。ここで `FileNotFoundError` が出たら
        500 を返せるため）。
     8. `runtime.stream_reply(..., attachments=agent_attachments)` に渡す。
     9. タイトルは D8。
   - `lifespan`: `LocalFileStorage(settings.storage_path)` を作って `AppState.storage` に
     載せ、`sweep_orphan_files()` を 1 回呼ぶ（D2-2/3。TODO コメント付き）。
   - `delete_conversation`: D2 のとおり、削除前にキーを集め、コミット後にベストエフォートで
     `storage.delete`。失敗は `logger.warning` で、例外にしない。

8. **境界型の更新**:
   - `api/app/types/attachments.py` に `AgentAttachment` TypedDict を**契約どおり**宣言する。
   - `api/app/types/agent_runtime.py` の `stream_reply` に
     `attachments: Sequence[AgentAttachment] = ()` を追加。**この TypedDict は
     `app/services/agents/` 側にも独立に同形で宣言される**（構造的互換）ことを docstring に
     書き、片方だけ変えると静かに壊れることを警告する。

9. **テスト**:
   - `tests/conftest.py` — `AppState` に `storage=LocalFileStorage(tmp_path / "storage")` を
     足す。
   - `tests/fakes.py` — `FakeChatAgentRuntime.stream_reply` に
     `attachments: Sequence[AgentAttachment] = ()` を足し、受け取った内容を
     `self.stream_reply_calls` に記録する（テストから中身を検証できるように）。
   - `tests/test_file_utils.py` — `sanitize_filename`（`../../etc/passwd`、
     `C:\tmp\a.txt`、制御文字、先頭ドット、日本語が残ること、255 バイト超の切り詰め、
     空文字フォールバック）、`resolve_mime_type`、`content_disposition_header`。
   - `tests/test_file_storage.py` — save/load/open_stream/delete の往復、存在しないキーで
     `FileNotFoundError`、`delete` の冪等性、**`"../escape.txt"` のようなキーで
     `ValueError`**。
   - `tests/test_files_api.py` — 201 の形、413、415、400（0 バイト）、ダウンロードの
     ヘッダ（`Content-Disposition` / `X-Content-Type-Options`）と本文一致、404、
     DELETE 204、添付済み DELETE の 409。
   - `tests/test_api.py` に追加 — 添付付き送信で `user` イベントに `attachments` が乗る／
     `stream_reply` に正しいバイト列が渡る／本文空＋添付で送れる／本文空＋添付なしで 400／
     存在しない添付 ID で 404／使用済み添付 ID で 409／会話削除でファイル行と実体が消える。
   - **既存テストの期待値更新**（`Message` に `attachments: []` が増える）も忘れない。

**やらないこと**

- `api/app/services/agents/` 配下のファイル（agent-builder）。
- `docs/api-contract.md`、`docker-compose.yml`、`.env.example`、`.gitignore`（親）。
- `uv add`（親が先に実行済みの前提で進める）。
- エージェント生成ファイルの保存 API（スコープ外）。`purpose` の enum に `generated` を
  含めるところまで。

---

### agent-builder（`api/app/services/agents/` とそのテスト）

**変更するファイル**

- `api/app/services/agents/attachments.py`（新規）
- `api/app/services/agents/prompts.py`（変更）
- `api/app/services/agents/runtime.py`（変更）
- `api/app/services/agents/__init__.py`（変更 — `AgentAttachment` を再エクスポート）
- `api/tests/test_agents.py`（変更）

**やること**

1. `attachments.py`（新規）に**契約どおりの `AgentAttachment` TypedDict** を宣言する。
   backend 側（`app/types/attachments.py`）に同形の宣言があり、mypy の構造的互換で
   相互運用していること、**片方だけ変えると静かに壊れる**ことを docstring に書く。
   併せて、パート組み立ての純粋関数をここに置く:

   ```python
   def is_inlinable(mime_type: str) -> bool:
       """モデルに中身を読ませられる MIME タイプか。"""


   def build_user_parts(text: str, attachments: Sequence[AgentAttachment]) -> list[types.Part]:
       """ユーザーターンの Part 列を組み立てる（D5 の並び順）。"""
   ```

   純粋関数に切り出す理由は、ADK 設計方針 6（副作用と整形を分ける／テスト可能にする）。

2. `prompts.py` に `ATTACHMENT_LABEL` と `UNSUPPORTED_ATTACHMENT_NOTE` を追加する
   （D5 の文面）。**文面を `runtime.py` / `attachments.py` に直接書かない。**
   `CHAT_AGENT_INSTRUCTION` に「添付ファイルが与えられた場合は内容を踏まえて答える。
   `[添付ファイル: ...]` というラベルはシステムが付けた注記であり、ユーザーの発言では
   ない」旨を 1〜2 文足す。

3. `runtime.py` の `stream_reply` シグネチャに
   `attachments: Sequence[AgentAttachment] = ()` を追加し、`new_message` の組み立てを
   `types.Content(role="user", parts=build_user_parts(text, attachments))` に差し替える。
   **既定値を付けることで、添付なしの既存呼び出しは一切変えずに済む。**

   ```python
   # 変更前
   new_message = types.Content(role="user", parts=[types.Part(text=text)])
   # 変更後
   new_message = types.Content(role="user", parts=build_user_parts(text, attachments))
   ```

   inline パートは `types.Part.from_bytes(data=a["data"], mime_type=a["mime_type"])`
   （`google.genai` 2.23.0 で実機確認済みのシグネチャ）。

   **`stream_reply` のそれ以外のロジック（partial の二重排除、最終イベントへの
   フォールバック、エラーイベントを即座に例外化しない扱い、`except` での
   `AgentInvocationError` 変換）には一切手を入れない。** ここはリトライ回復の
   微妙な挙動が効いている箇所で、添付とは無関係。

   D4 の判断（**バイト列はそのターンだけ送り、以降は ADK セッションに任せる**）を
   `stream_reply` の docstring に理由付きで残す。将来「毎ターン送り直すべきでは」と
   考えた人が再調査せずに済むように。

4. `__init__.py` に `AgentAttachment` を足して再エクスポートする
   （`__all__` も更新）。

5. `tests/test_agents.py` に追加（すべてオフライン。`Runner.run_async` を差し替える
   既存の書き方を踏襲）:
   - 対応形式（`image/png`）の添付が `inline_data` パートになり、**ラベルの text パートが
     その直前に置かれる**こと。
   - 非対応形式（`application/zip`）は `inline_data` にならず、ファイル名とサイズを含む
     text パートだけになること。
   - 複数添付の順序が保たれ、**本文テキストが最後**に来ること。
   - 本文が空文字のときに**空の text パートが作られない**こと。
   - `attachments` を渡さない従来の呼び出しで、パートが `[Part(text=...)]` 1 個のままで
     あること（**回帰テスト**）。
   - `is_inlinable` の単体テスト（`image/*` / `text/*` / `application/pdf` が真、
     `application/zip` / `application/json` が偽）。

**やらないこと**

- `api/app/services/agents/` 以外の `api/` 配下のファイル。**特に
  `api/tests/conftest.py` と `api/tests/fakes.py` は backend-builder の担当**
  （`tests/test_agents.py` はこれらを import していないので、触る必要がない）。
- `FileStorage` の利用。**エージェント層はストレージを一切知らない**。バイト列は
  API 層が読んで渡す。
- `save_generated_file` 等の生成ファイル保存ツール（スコープ外）。
- `docs/api-contract.md` の更新（親）。

---

### 親（呼び出し元）が行う

**builder 起動前に（この順で）:**

1. `docs/api-contract.md` を上の「契約変更」節のとおりに更新する。
   3 層の唯一の正なので、これが先。
2. `cd api && uv add python-multipart` を実行する。
   - **注意**: `python-multipart` 0.0.32 は既に `google-adk` 2.9.0 の推移依存として
     `uv.lock` に入っており、`api/.venv` にもインストール済み（調査で確認）。したがって
     新規ダウンロードは発生せず、`pyproject.toml` の `dependencies` に 1 行増えるだけの
     変更になる。それでも**明示する**理由は、FastAPI の `UploadFile` がこのパッケージを
     直接必要とするのに、その事実が「ADK の依存がたまたま入っている」ことに依存している
     のは壊れやすいため（ADK が依存を落とした瞬間に原因の分かりにくい ImportError になる）。
3. `.gitignore` に追記する。**ディレクトリごと ignore すると否定パターンが効かない**
   （git は ignore されたディレクトリの中を辿らない）ので、必ず `/storage/*` の形にする:
   ```gitignore
   # ローカルのファイル置き場（実体はコミットしない）
   /storage/*
   !/storage/.gitkeep
   ```
4. `storage/.gitkeep` を作成してコミット対象にする（`uploads/` と `generated/` の
   サブディレクトリは `LocalFileStorage` が実行時に作るので置かない）。
5. `docker-compose.yml` の `api` サービスに追記する:
   ```yaml
   environment:
     STORAGE_DIR: /data/storage
   volumes:
     - ./api/app:/app/app
     - ./api/tests:/app/tests
     - ./storage:/data/storage
   ```
   `/app/storage` ではなく `/data/storage` にするのは、`/app` 配下がソースの
   バインドマウント領域で、そこにデータを混ぜたくないため。
   **`prod` stage は uid 10001 の非 root で動く**ので、本番相当で動かす場合は
   ホスト側 `./storage` の書き込み権限が必要になる点をコメントに残す（dev stage は root で
   動くので開発時は問題にならない）。
6. `.env.example` に追記する:
   ```dotenv
   # --- ファイル置き場 ----------------------------------------------------------
   # 実体の保存先。未設定ならリポジトリ直下の storage/ を使う。
   # compose では /data/storage にマウントするので docker-compose.yml 側で上書きされる。
   STORAGE_DIR=
   UPLOAD_MAX_FILE_BYTES=10485760
   UPLOAD_MAX_FILES_PER_MESSAGE=5
   UPLOAD_MAX_TOTAL_BYTES_PER_MESSAGE=15728640
   UPLOAD_ALLOWED_MIME_TYPES=image/png,image/jpeg,image/webp,image/gif,application/pdf,text/plain,text/markdown,text/csv,application/json,application/zip
   ORPHAN_FILE_TTL_HOURS=24
   ```

**builder 完了後に:**

7. 結合確認（下記「検証」）。
8. `CLAUDE.md` の「プロジェクト構成」に `storage/` と
   `api/app/services/storage/` / `api/app/services/files/` を追記する。
9. commit（`git-workflow` に従う。**並列実行中は各 builder に commit させない**）。

---

## 実行順序

```
[親] 契約更新 → uv add python-multipart → .gitignore / storage/.gitkeep
     → docker-compose.yml → .env.example
                     │
                     ▼
   ┌─────────────────┼─────────────────┐
   ▼                 ▼                 ▼
frontend-builder  backend-builder  agent-builder    ← 3 層を並列実行
   ▼                 ▼                 ▼
   └─────────────────┼─────────────────┘
                     ▼
              [親] 結合確認 → CLAUDE.md 追記 → commit
```

**3 層は並列でよい。** 根拠:

- 触るファイルが 1 つも重ならない（frontend は `web/`、agent は
  `api/app/services/agents/` + `tests/test_agents.py`、backend はそれ以外の `api/`）。
  **`tests/conftest.py` と `tests/fakes.py` が唯一の衝突候補だったが、`grep` で
  `tests/test_agents.py` がこれらを import していないことを確認済みなので、
  backend-builder の単独担当にできる。**
- 層を跨ぐ型（`FileMeta` / `SendMessageRequest` / `AgentAttachment` /
  `stream_reply` のシグネチャ）はすべてこの計画に具体値で書き切ってあり、実装中の
  合意事項は残っていない。
- **backend ↔ agent の唯一の共有型 `AgentAttachment` は `TypedDict` なので構造的に
  互換**で、どちらかの出力を他方が待つ必要がない。これは `mypy --strict` で実際に
  検証済み（別モジュールで独立宣言した同形 TypedDict を跨いで渡して
  `Success: no issues found`）。

**親が先に行う必要がある理由**:

- `uv add` は `uv.lock` を書き換える。複数エージェントが同時に走らせると競合する。
- 契約ファイルは 3 層の唯一の正なので、実装が始まる前に確定していなければ意味がない。
- `.gitignore` / compose / `.env.example` はどの builder の担当範囲にも属さない。

`npm install` は**不要**（フロントエンドは依存を増やさない）。

---

## 検証

### 各担当の完了条件

frontend-builder（`web/` で実行）:

```bash
npm run lint
npm run build    # tsc -b を含む = 型チェック
```

backend-builder / agent-builder（`api/` で実行）:

```bash
uv run pytest -q
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run mypy app/
```

- **API キー無し・ネットワーク無しで全テストが通ること**（テンプレートの正常な状態）。
- backend-builder は「ストレージのパストラバーサル」「413」「415」「409」のテストが
  あること。agent-builder は「非対応 MIME でファイル名とサイズだけになる」「添付なしの
  回帰」テストがあること。

### 統合後に親が確認すること

1. `cd api && uv run pytest -q && uv run mypy app/ && uv run ruff check app/ tests/`
   — 3 者の変更を合わせて通ること（特に `tests/fakes.py` の新シグネチャと
   `app/services/agents/runtime.py` の新シグネチャが噛み合っていること）。
2. `cd web && npm run build` — `Message.attachments` の型が backend の `MessageOut` と
   一致していること。
3. `docker compose up --build` で実際に Gemini へ通す（ここだけは LLM を呼ぶ）:
   - 画像を D&D → プレビュー → 送信 → **モデルが画像の内容に言及する**こと。
   - PDF とテキストファイルでも同様。
   - `.zip` を添付 → エラーにならず、モデルが「読めない」旨を答えること。
   - 本文を空にして画像だけ送れること。会話タイトルがファイル名由来になること。
   - リロードしても添付が履歴に残り、クリックでダウンロードできること。
   - 会話を削除 → `storage/uploads/<uuid>/` が消えていること。
   - プレビューの取り消し → `storage/` から実体が消えていること。
4. `ls storage/` が `.gitkeep` だけ追跡されていること（`git status` に
   `storage/uploads/...` が出ないこと）。
5. 添付を 2 ターン続けて送り、2 ターン目の応答が**1 ターン目の画像にも言及できる**こと
   （D4 の「送り直さなくてもセッションが覚えている」前提の確認）。

---

## リスク・未決事項

1. **ADK セッションへの inline データ蓄積（D4 の残余リスク）**。同じ会話で画像を
   繰り返し添付すると、ADK の `SessionService` に inline バイト列が積み上がり、
   いずれコンテキスト長超過・レイテンシ増・コスト増として顕在化する。今回は入口の
   上限（1 ファイル 10 MiB / 1 メッセージ 5 件・合計 15 MiB）で緩和するに留め、
   セッションの剪定は**行わない**。実運用で問題になったら、古い inline パートを
   要約テキストへ置き換える処理を `runtime.py` に足すのが次の一手。
2. **MIME タイプはクライアント申告を信用する**。`python-magic` 等によるバイト列の
   sniffing は依存を増やすため入れない。許可リストを通るように MIME を詐称した
   ファイルをアップロードできる。D7 のダウンロードヘッダ（`attachment` +
   `nosniff` + CSP）でブラウザ側の実害は抑えているが、モデルには「宣言された
   MIME」で渡ることになる。
3. **認証が無いテンプレートなので、ファイルの認可も無い**。ファイル ID（UUID）を
   知っていれば誰でもダウンロードできる。`DEFAULT_USER_ID` を実ユーザーに
   差し替える段階で、`files` に所有者列を足して `GET /api/files/{id}/content` で
   検査する必要がある。**この計画ではそこまで作らない。**
4. **孤児掃除は起動時のみ**（D2-3）。長時間稼働するプロセスでは掃除されない。
   `create_all` をマイグレーションの代わりにしているのと同種の、テンプレート
   としての割り切り。
5. **添付付き送信の失敗には再試行ボタンが出ない**（D9）。1 ファイル = 1 メッセージの
   モデルを崩さないための割り切りで、`model_overloaded`（503）が添付付きターンで
   起きたときの体験は添付なしより劣る。改善するなら `files` とメッセージを中間テーブルで
   多対多にするのが筋だが、今回のスコープには入れない。
6. **`LocalFileStorage` はプロセスローカル**。api コンテナを複数レプリカで動かすと、
   バインドマウントを共有しない限りダウンロードが 404 になる。開発用 compose では
   1 レプリカなので問題にならないが、クラウド移行（S3/Azure）が必要になる最初の
   理由がこれである点をドキュメントに残しておくとよい。
7. **既存テストの期待値更新が広範囲に及ぶ可能性**。`Message` に `attachments: []` が
   増えるため、`tests/test_api.py` の既存アサーションのうち `==` でレスポンス全体を
   比較している箇所があれば落ちる。実装時に判明する類の作業で、計画側では
   潰しきれない。
8. （範囲外の気づき）`docs/api-contract.md` は `Message` の形を 1 箇所でしか定義して
   いないため、`user` / `done` の両イベントが同じ形に追随する。逆に言うと将来
   assistant 側にだけフィールドを足したくなったときに分岐が必要になる。今回は
   `attachments` を両方に持たせる（assistant は常に `[]`）ことで回避している。
