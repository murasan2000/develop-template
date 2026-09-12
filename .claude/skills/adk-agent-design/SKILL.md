---
name: adk-agent-design
description: api/app/services/agents/ 配下で Google ADK のエージェント（Agent / App / Runner / SessionService / ツール）を新規作成・変更する際に必ず使う。エージェント実装のスパゲティ化を防ぐための設計原則チェックリストと、ADK 2.x の検証済み API リファレンス。
---

# Google ADK エージェント設計チェックリスト（api/app/services/agents/）

エージェント実装は、気を抜くと「LLM 呼び出し・DB アクセス・整形・分岐」が
1 つの関数に溜まってスパゲティ化する。着手前と実装後に、このチェックリストで
自己点検する。背景は CLAUDE.md「Google ADK / LLM エージェント設計方針」節。

## 7 原則チェックリスト

1. **1 エージェント = 1 モジュール = 1 `build_*_agent()`**。
   各エージェントは自分のモジュールで完結させる。共有の `BaseAgent` 基底クラスは
   作らない（エージェントごとに instruction もツールも違い、共通化しても
   分岐が増えるだけで読みにくくなるため）。
2. **Runner / SessionService の組み立ては `runtime.py` の 1 箇所だけ**。
   エージェント定義（`chat.py`）は Runner の存在を知らない。逆に `runtime.py` は
   instruction の中身を知らない。この向きの依存を崩さない。
3. **instruction・description は `prompts.py` に置く**。コードと文面を混ぜない。
   プロンプトは「コードの変更」ではなく「仕様の変更」として差分を読みたいため。
4. **ツールは素の関数で書き、型注釈と docstring を必ず付ける**。
   ADK は関数シグネチャと docstring をそのまま LLM へ渡す。つまり docstring は
   コメントではなく**仕様**。戻り値は `dict` にして `status` を持たせ、
   失敗も構造化して返す。
5. **例外を握りつぶさない**。ADK 2.x はツールから送出された例外を `RetryConfig`
   に照らして評価する。広い `try/except` で囲むとリトライ機構から失敗が見えなくなる。
   呼び出し元（API 層）がユーザー向けエラーへ変換する前提で、そのまま送出する。
   ただし**エラーイベントは例外とは別物**で、見つけた瞬間に raise してはいけない
   （下記「リトライ」節）。
6. **副作用の置き場所を決める**。外部 I/O はツール関数か、明示した収集関数に限定し、
   整形・判定は純粋関数に切り出してテスト可能にする。
7. **アプリの永続履歴と ADK セッションを混同しない**。
   - `conversations` / `messages` テーブル = アプリ所有。UI が読む表示用の履歴。
   - ADK の `SessionService` が作るテーブル = エージェントの作業記憶（イベント列）。
     `ChatAgentRuntime` は前者を一切知らない。片方を見て「履歴が二重だ」と早合点して
     統合しないこと（役割が違う）。

## ADK 2.x API リファレンス（検証済み）

ADK 1.x 系の記事はグラフ構造も import パスも違う。以下はこのリポジトリの
バージョンで実際に動かして確認した形。

```python
from google.adk import Agent, Runner
from google.adk.apps import App
from google.adk.sessions import DatabaseSessionService, InMemorySessionService
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

agent = Agent(
    name="chat_agent",  # [a-zA-Z0-9_] のみ
    model="gemini-3.8-flash",
    instruction=...,
    description=...,
    tools=[my_tool],  # 素の関数でよい
)
app = App(name="chat_template", root_agent=agent)
runner = Runner(app=app, session_service=session_service)
```

主なシグネチャ:

- `Runner(*, app=None, app_name=None, agent=None, node=None, plugins=None, artifact_service=None, session_service, memory_service=None, credential_service=None, plugin_close_timeout=5.0, auto_create_session=False)`
- `Runner.run_async(*, user_id, session_id, invocation_id=None, new_message=None, state_delta=None, run_config=None, yield_user_message=False) -> AsyncGenerator[Event, None]`
- `BaseSessionService.create_session(*, app_name, user_id, state=None, session_id=None) -> Session`
- `BaseSessionService.get_session(*, app_name, user_id, session_id, config=None) -> Session | None`
- `Event`: `content` / `partial` / `author` / `turn_complete` / `error_code` / `error_message` /
  `invocation_id` / `actions` / `id` / `timestamp`、メソッド `is_final_response()` /
  `get_function_calls()` / `get_function_responses()`
- `StreamingMode`: `NONE` / `SSE` / `BIDI`

### 落とし穴

- **`Runner` の既定は `auto_create_session=False`**。`run_async` の前に
  `create_session` が要る。`ensure_session` を冪等にして毎回呼ぶのが安全。
- **`StreamingMode.SSE` ではテキストが二重に届く**。`partial=True` の増分イベントが
  流れたあと、同じ内容を持つ最終イベントが来る。**`partial` が真のイベントだけを
  流す**こと。素朴に全イベントを連結すると応答が 2 回繰り返される。
- **`event.content` は `Optional`**、`content.parts[i].text` も `None` になり得る。
  必ず両方チェックしてから使う。
- **`Runner` はステートレスで共有前提**。会話履歴は `SessionService` が持つので、
  リクエストごとに `Runner` を作り直さない。アプリ起動時に 1 つ作って使い回す。
- **`DatabaseSessionService` は `google-adk[db]` extra が要る**。`[db]` 抜きで
  import すると `ImportError: The 'sqlalchemy' package is required` になる。
- **API キーは `GOOGLE_API_KEY` 環境変数**を google-genai が自動で読む。
  未設定だと実行時に `ValueError: No API key was provided.`。

## リトライ（`RetryConfig`）— 落とし穴が 2 つある

Gemini は混雑時に `503 UNAVAILABLE`（"This model is currently experiencing high
demand"）を返す。時間を置けば成功する一時的な失敗なので、自動で再試行すべき失敗の
代表例。ここには**逆向きの落とし穴が 2 つ**あり、両方を同時に踏むと気づきにくい。

### 1. `retry_config` を渡さないと、リトライは一切行われない

`workflow/utils/_retry_utils.py` の `_should_retry_node` は冒頭が
`if not retry_config: return False`。`Agent(retry_config=...)` を明示しない限り
再試行はゼロ回で、一時的な 503 がそのままユーザーの失敗になる。

```python
from google.adk.workflow._retry_config import RetryConfig

RetryConfig(
    max_attempts=3,  # 初回を含む試行回数。未指定時の既定は 5
    initial_delay=1.0,
    backoff_factor=2.0,
    max_delay=8.0,  # 既定の 60.0 は対話型 UI には長すぎる
    exceptions=["ServerError"],
)
```

`exceptions` は**例外クラス名の文字列**で照合する（クラスを渡しても名前に正規化
される）。`None` は「全例外でリトライ」を意味するので、認証エラーや不正なモデル名の
ような**何度やっても直らない失敗まで待たされる**。`google.genai.errors` の階層は
`APIError` ← `ServerError`(5xx) / `ClientError`(4xx)。429 は `ClientError` だが、
同じクラスに 400/401/403 も含まれるためクラス名では切り分けられない。

### 2. リトライされる場合も、エラーイベントは先に流れる

`workflow/_node_runner.py` は「**エラーイベントを enqueue してから**リトライ判定」
という順序になっている。

```python
except Exception as e:
    error_event = Event(error_code=..., error_message=str(e))
    await self._enqueue_event(error_event, ctx)     # ← 先に流れる
    if not await self._attempt_retry(e, attempt_count):  # ← 判定はこの後
        ...
```

つまり `error_code` 付きイベントを見た瞬間に raise すると、**ADK が再試行して成功
するはずだった実行を自分で潰す**。実測（`ServerError` を 2 回投げてから成功する
フェイク LLM）:

| 設定                          | LLM 呼び出し | 流れたイベント                                  |
| ----------------------------- | ------------ | ----------------------------------------------- |
| `retry_config` なし           | 1 回         | `UNAVAILABLE` → 例外送出                        |
| `retry_config`（max 3 / 5xx） | 3 回         | `UNAVAILABLE`, `UNAVAILABLE` → **成功テキスト** |

**正しい扱い**: エラーイベントは「最後に見たエラー」として保持するだけにし、
**ストリームが終わった時点で「テキストを 1 つも出していない、かつエラーを見た」
ときにだけ例外にする**。テキストが出ていれば、途中のエラーは回復済みとして握る。

例外は機械可読な `code` を持つ専用クラスにして送出する。API 層がそれを見て
ユーザー向けの文言（混雑／レート制限／設定ミス）に振り分けられるようにするため、
`RuntimeError` にメッセージを詰め込まない。

## 新規エージェントを足すときの型

```
prompts.py に instruction を足す
  → xxx.py に build_xxx_agent(model) を書く
    → runtime.py で App / Runner に載せる
      → API 層から runtime のメソッドを呼ぶ
```

- 複数のエージェントに振り分けたくなったら、まず「ツールを足すだけで済まないか」を
  検討する。エージェントを増やすのは、instruction が両立しないほど役割が違うときだけ。
- モデル名は引数で受け取り、モジュール内にハードコードしない（環境変数で差し替える）。

## テスト方針

**LLM を呼ばずにオフラインで完結させる**。`Runner.run_async` をフェイクに差し替え、
イベント列を自前で組み立てて検証する。最低限、次の 5 つは必ず担保する。

- ストリーミングのテキストが二重にならないこと。
- `ensure_session` が冪等であること。
- `database_url` が `None` のとき `InMemorySessionService` にフォールバックすること。
- **エラーイベントの後にテキストが来た場合、例外にならないこと**（リトライ回復）。
- **テキストが来なければ例外になり、`code` が保たれること**。

リトライ自体を検証するときは、`BaseLlm` を継承したフェイクモデルを `Agent(model=...)`
に渡すと ADK 込みで確認できる（`generate_content_async` で最初の N 回だけ
`ServerError(503, ...)` を投げる）。`initial_delay` を 0.05 秒程度に落として
テストが遅くならないようにする。

## 完了時

- `backend-workflow` スキルの検証コマンド（`uv run pytest -q` /
  `uv run ruff check` / `uv run mypy app/`）を通す。
- 一区切りついたら `git-workflow` スキルに従い commit + push する。
