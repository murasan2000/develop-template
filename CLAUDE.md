# CLAUDE.md

**チャットアプリ開発テンプレート**の開発ガイド。React + FastAPI + Google ADK（Gemini）

- PostgreSQL の最小構成のチャットアプリが動く状態で入っており、新しいアプリは
  これをコピーして始める。

このファイルは**派生プロジェクトでそのまま使い続ける**前提で書いてある。アプリ固有の
事情（ドメイン用語・追加した外部 API・独自の運用ルール）は、コピー先で追記していく。

## プロジェクト構成

```
api/    FastAPI バックエンド（Python 3.13 / uv）
  app/servers/api.py          エンドポイント・lifespan
  app/config.py               設定（環境変数を読む唯一の場所）
  app/services/db/            SQLAlchemy の engine / session / モデル
  app/services/chat/          会話・メッセージの永続化
  app/services/agents/        AI エージェント（Google ADK）
  app/types/api.py            Pydantic のリクエスト / レスポンス型
  app/utils/                  純粋関数のユーティリティ
  tests/                      pytest（ネットワーク・LLM 非依存）
web/    React + TypeScript + Vite フロントエンド
  src/components/             表示に専念するコンポーネント
  src/hooks/                  状態と API 呼び出しを閉じ込めたフック
  src/api/client.ts           バックエンド呼び出しの一箇所集約（SSE 含む）
  src/types/api.ts            docs/api-contract.md に 1:1 対応する型
docs/
  api-contract.md             ★ 層の間の契約。3 層に跨る変更はここから始める
  plans/                      task-planner が書く実装計画
.devcontainer/                開発コンテナ（詳細は .devcontainer/README.md）
.claude/                      エージェント・スキル・ガードレール（後述）
docker-compose.yml            db / api / web をまとめて起動する開発用定義
.env.example                  環境変数のひな形（`cp .env.example .env` して使う）
```

## セットアップと起動

```bash
cp .env.example .env          # GOOGLE_API_KEY を埋める（AI Studio で発行）
docker compose up --build     # web:5173 / api:8000 / db:5432
```

個別に動かす場合:

```bash
cd api && uv sync --all-groups && uv run uvicorn app.servers.api:app --reload
cd web && npm install && npm run dev
```

## 開発コマンド

バックエンド（`api/` で実行）:

```bash
uv run pytest -q                          # テスト（LLM・ネットワーク非依存）
uv run ruff check app/ tests/             # Lint（設定はルートの ruff.toml）
uv run ruff format --check app/ tests/    # フォーマット
uv run mypy app/                          # 型チェック（strict）
```

フロントエンド（`web/` で実行）:

```bash
npm run lint    # eslint
npm run build   # tsc -b && vite build（型チェックを含む）
npm run dev     # 開発サーバ（:5173、/api を :8000 にプロキシ）
```

- **テストは LLM を呼ばない**。エージェント層は `Protocol` 境界でフェイクに差し替え、
  DB は `sqlite+aiosqlite` を使う。API キー無しで全テストが通ることが正常な状態。
- 実際に Gemini と喋る確認は `docker compose up` か、`api/` を手で起動して行う。

## アーキテクチャの中心的な約束事

### 1. 3 層の境界と、その間の契約

`web/` ・ `api/`（エージェント以外）・ `api/app/services/agents/` の 3 層に分かれている。
**層を跨ぐ形は `docs/api-contract.md` が唯一の正**。

- 3 層に跨る変更は、**まず契約ファイルを更新してから**各層を直す。
- 片側だけ直して辻褄を合わせない。型は通るのに実行時に壊れる、という最悪の壊れ方をする。
- この境界は `.claude/agents/` の 3 つの builder エージェントの担当範囲と一致している
  （並列実装させても衝突しないように設計されている）。

### 2. データベースは 2 系統ある

同じ PostgreSQL に、役割の違うデータが同居している。**統合しないこと。**

| 所有者 | テーブル                     | 役割                                                 |
| ------ | ---------------------------- | ---------------------------------------------------- |
| アプリ | `conversations` / `messages` | UI が読む表示用の履歴。一覧・削除・検索の対象        |
| ADK    | `SessionService` が自動生成  | エージェントの作業記憶（イベント列）。LLM に渡る文脈 |

「履歴が二重にあるから片方に寄せよう」は誤り。前者はユーザーに見せるための
ドメインデータ、後者はエージェントの実行状態で、寿命も更新タイミングも違う。

スキーマの定義は SQLAlchemy モデルが唯一の正で、起動時に `create_all` で作る。
**本番運用に入る前に Alembic 等のマイグレーションに置き換えること。**

### 3. 応答は SSE でストリーミングする

`POST /api/conversations/{id}/messages` は `text/event-stream` を返す。

- ストリーム開始後は HTTP ステータスを変えられないため、失敗は `event: error` で
  返し、ステータスは 200 のままにする。
- **部分的に受け取ったテキストは必ず保存する**。履歴が欠けるのはユーザーにとって
  最悪の壊れ方のため。
- プロキシのバッファリングで「応答が最後にまとめて届く」事故が起きやすい。
  `X-Accel-Buffering: no` と `Cache-Control: no-cache` を付ける。

### 4. Google ADK / LLM エージェント設計方針（可読性優先）

エージェント実装はスパゲティ化しやすい。詳細なチェックリストと ADK 2.x の
検証済み API は `.claude/skills/adk-agent-design/SKILL.md` にある。要点:

1. **1 エージェント = 1 モジュール = 1 `build_*_agent()`**。共有の基底クラスは作らない。
2. **Runner / SessionService の組み立ては `runtime.py` の 1 箇所だけ**。
   エージェント定義は Runner を知らず、`runtime.py` は instruction を知らない。
3. **instruction は `prompts.py`**。コードと文面を混ぜない（プロンプトの変更を
   「仕様の変更」として差分で読みたいため）。
4. **ツールは素の関数 + 型注釈 + docstring**。docstring はコメントではなく、
   そのまま LLM に渡る**仕様**。
5. **例外を握りつぶさない**。ADK 2.x は例外を `RetryConfig` に照らして評価するため、
   広い `try/except` はリトライ機構から失敗を隠してしまう。
6. **`StreamingMode.SSE` ではテキストが二重に届く**。`partial=True` の増分イベントの
   後に、同内容の最終イベントが来る。`partial` が真のものだけを流す。
7. **`Runner` はステートレスで共有前提**。リクエストごとに作り直さず、起動時に
   1 つ作って使い回す（会話履歴は `SessionService` が持つ）。

### 5. フロントエンドは「フック = 状態、コンポーネント = 表示」

状態と API 呼び出しは `hooks/useXxx.ts` に閉じ込め、`components/` は表示に専念させる。
状態管理ライブラリも UI フレームワークも入れない（この規模では依存を増やす理由がない）。
色は `:root` の CSS カスタムプロパティで管理し、個別 CSS に生の色コードを書かない。

## コーディング規約

- Python は ruff（E/W/F/I/B/UP/SIM/C4）+ mypy strict を通す。
- **コメント・docstring は日本語**。「何をしているか」ではなく**「なぜそうしているか」**を書く
  （何をしているかはコードが語る）。
- 変更は既存コードのスタイル・粒度に合わせる。新しい抽象を持ち込む前に、
  似た既存実装が無いか探す。
- 依存を増やすときは `uv add` / `npm install`（`settings.json` で確認が入る）。
  ロックファイルは手で編集しない。

## サブエージェントの使い方

`.claude/agents/` に 4 つのエージェントがある。**3 層に跨るタスクは、計画 → 並列実装の
順で進めるのが既定の進め方**。

| エージェント       | 担当                                                                       |
| ------------------ | -------------------------------------------------------------------------- |
| `task-planner`     | 実装計画。層への分割・契約変更の有無・並列可否を決める（コードは書かない） |
| `frontend-builder` | `web/` 配下                                                                |
| `backend-builder`  | `api/` のうち `app/services/agents/` を除く部分                            |
| `agent-builder`    | `api/app/services/agents/` とそのテスト                                    |

進め方:

1. `task-planner` を呼び、`docs/plans/<topic>.md` に計画を書かせる。
   **契約（`docs/api-contract.md`）が変わるかどうかをここで確定させる**のが要点。
   自明な 1 ファイル修正には使わない（過剰なため）。
2. 契約変更と依存の追加（`uv add` / `npm install`）は**親がまとめて先に**行う。
   ロックファイルを複数エージェントが同時に生成すると競合するため。
3. 3 つの builder を**並列に**呼ぶ。担当範囲が重ならないので同時に走らせてよい。
4. 全員の完了後、**親が結合を確認して commit する**。並列実行中は各エージェントに
   commit させない（履歴が入り乱れて、どの変更がどのタスクのものか読めなくなるため）。

## 開発フロー

実装はローカルの Claude Code CLI が担い、検証は CI が Claude 抜きで再現する、
という役割分担を取る。**CI の定義（`.github/workflows/`）はまだこのテンプレートに
入っていない**ので、派生プロジェクトで最初に足すこと（内容は下記の検証コマンドと
同一にする）。

1. **Issue 作成**: `gh issue create`、または GitHub 上で直接。
   粒度は `issue-deepdive` スキルに従う（`.claude/skills/issue-deepdive/SKILL.md`）。
2. **計画**: 3 層に跨るなら `task-planner` を呼ぶ。
3. **実装**: この CLAUDE.md の規約に従う。ブランチ運用・commit/push は
   `git-workflow` スキルに従う（`claude/feature/<topic>` を切る、一区切りで
   commit + push、`<action>(<prefix>): <context>` 形式）。
4. **ローカル検証**: 上記の lint / 型チェック / テストを通す。
5. **自己レビュー**: ユーザーのレビューに回す前に `/code-review` で self-review し、
   指摘を検証・修正してから提出する。
6. **push & PR**: `gh pr create` で draft PR を作り、Issue を `Refs #N` で紐付ける。

**CI を足したあとも、それはローカル検証を省く理由にはならない。** CI の役割は
「Claude が自分の変更を甘く判定していないか」を機械的に潰すことなので、
両方通るのが正常な状態。

## ガードレール（.claude/）

`settings.json` の permissions と、`hooks/guard-tools.py`（PreToolUse フック）で構成。
settings.json は厳密 JSON でコメントを書けないため、意図はここに記す。

### permissions

- **allow**: ファイル編集（`Edit` / `Write`）と、テスト・lint・ビルド・git / gh の大半
  （`git push`、`gh pr create` 等の外向き操作を含む）。実装はローカルの Claude Code /
  gh 認証で完結し、最終的に PR で人間がレビューするため、この粒度の操作は都度の確認を
  求めない。
- **ask**: 依存の増減（`uv add` 等。インストールスクリプト経由でコードが実行され得るため）、
  `docker` コマンド（ホスト側のリソースを動かすため）、および CI 定義・ガードレール自身の
  編集（`Edit(/.github/workflows/**)` / `Edit(/.claude/**)`。Claude が自分自身の制限を
  気づかれずに緩められないようにするため）。これらはパス指定の `ask` ルールが `allow` の
  `Edit`/`Write` より先に評価されるため、他のファイル編集が確認不要でもここだけは確認が残る。
- **deny**: ロックファイルの直接編集、`gh secret`、force push。
- パスを対象にする権限ルールは **`Edit(...)` / `Read(...)` のみが参照される**。
  `Write(...)` でパスを書いても無視され、起動時に警告が出るので使わないこと
  （パス指定なしの bare `Write` ルール自体は有効で、上記の allow で使っている）。
- **`ask` は毎回確認が出る**。権限プロンプトで「今後は確認しない」を選んでも、それは
  `settings.local.json` の allow として保存されるだけで、project 側の `ask` を上書き
  できない。煩わしくなった項目は、この `settings.json` から外して調整する。

### PreToolUse フック（`hooks/guard-tools.py`）

permissions のパターンで表現しにくいものだけを担当する。具体的には次の 3 種類。

1. **フラグの書き方が複数あるもの**: force push（`--force` / `-f` / `--force-with-lease`）、
   再帰 rm（`-r` / `-R` / `--recursive`）。
2. **パスの種類で可否が変わるもの**: `rm -rf node_modules` のようなプロジェクト内の
   後片付けは通し、絶対パス・ホーム・親ディレクトリ遡りへの再帰削除だけを止める
   （このため `rm` の一律 deny は置いていない）。
3. **例外を含むパターン**: `.env` 系は原則ブロックだが `.env.example` のようなひな形は
   通したい。permissions のパス指定には否定（`!`）が無く「`.env.*` を拒否しつつ
   `.env.example` だけ許可」が書けないため、フックで扱っている。

**Bash だけでなく `Edit` / `Write` / `Read` も検査対象にしている。** 秘密情報の保護が
「どのツールを使ったか」で変わってはいけないため。シェルのリダイレクトや `sed -i` は
permissions の Edit ルールの検査対象外で素通りする、という穴も同時に塞いでいる。

このフックには回帰テストがある。**ルールを足すときは、先にテストへケースを追加する**:

```bash
python3 .claude/hooks/test_guard_tools.py
```

なお、副作用として「コマンド文字列の中に `.env` というトークンが現れるだけ」でも
ブロックされる（ヒアドキュメントで `.dockerignore` を書く場合など）。その場合は
Bash ではなく `Write` ツールでファイルを作れば通る。

### SessionStart フック（`hooks/session-start.sh`）

Claude Code on the web のリモート環境でだけ、`api/`（`uv sync --all-groups`）と
`web/`（`npm ci` / `npm install`）の依存を自動インストールする。ローカルでは実行しない
（`$CLAUDE_CODE_REMOTE` で判定し、devcontainer の `postCreateCommand` に任せる）。
これが無いと、リモートセッション開始直後は依存が無く、上記の検証コマンドが動かない。
