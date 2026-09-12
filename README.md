# develop-template

各種アプリの派生元となる**開発テンプレートリポジトリ**。

開発コンテナ定義、Lint / pre-commit 設定、Claude Code のエージェント・スキル・
ガードレール、そして**動くサンプルアプリ**（React + FastAPI + Google ADK +
PostgreSQL のチャットアプリ）を置いてある。新しいアプリはこれをコピーして始める。

コピーした後はそれぞれのリポジトリの持ち物で、変更もそこで行う。共有イメージも
配信の仕組みもなく、渡すのはファイルだけ。その代わり、ここへの改善が既存
プロジェクトへ自動で届くこともない。

## 入っているもの

| 分類                | 内容                                                                                                                    |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| サンプルアプリ      | チャットアプリ一式（`web/` + `api/` + `docker-compose.yml`）                                                            |
| 開発環境            | `.devcontainer/`（Node / Python / クラウド CLI / Terraform / Lint）                                                     |
| Lint / フォーマット | `ruff.toml` / `eslint.config.mjs` / `.prettierrc.json` / `.yamllint.yaml` / `.editorconfig` / `.pre-commit-config.yaml` |
| Claude Code 設定    | `CLAUDE.md` / `.claude/`（エージェント・スキル・権限・フック）                                                          |

### サンプルアプリの構成

| 層              | 技術                                         |
| --------------- | -------------------------------------------- |
| フロントエンド  | React 19 + TypeScript + Vite（依存は最小限） |
| バックエンド    | FastAPI（Python 3.13 / uv）、応答は SSE      |
| AI エージェント | Google ADK 2.x + Gemini                      |
| データベース    | PostgreSQL 18                                |

アプリの中身そのものは「テンプレートとして真似される構造」を示すためのもので、
機能は意図的に最小限（会話の作成・一覧・削除と、ストリーミング応答）にしてある。

## 使ってみる

```bash
cp .env.example .env      # GOOGLE_API_KEY を埋める（https://aistudio.google.com/apikey）
docker compose up --build
```

- web: <http://localhost:5173>
- api: <http://localhost:8000/docs>
- db: `localhost:5432`

個別に動かす場合や、検証コマンド・設計方針は [CLAUDE.md](CLAUDE.md) を参照。

## ドキュメント

| ドキュメント                                       | 内容                                                         |
| -------------------------------------------------- | ------------------------------------------------------------ |
| [CLAUDE.md](CLAUDE.md)                             | 開発ガイド。構成・規約・設計方針・ガードレールの意図         |
| [docs/api-contract.md](docs/api-contract.md)       | web / api / エージェント層の間の契約（3 層に跨る変更の起点） |
| [.devcontainer/README.md](.devcontainer/README.md) | 開発コンテナのルール・バージョン指定・編集方法               |

CI/CD パイプラインの定義とそのドキュメントは今後追加する。

## 構成

```
api/                     FastAPI バックエンド
  app/servers/api.py     エンドポイント・lifespan
  app/config.py          設定（環境変数を読む唯一の場所）
  app/services/db/       SQLAlchemy の engine / session / モデル
  app/services/chat/     会話・メッセージの永続化
  app/services/agents/   Google ADK エージェント
  tests/                 pytest（ネットワーク・LLM 非依存）
web/                     React + TypeScript + Vite フロントエンド
  src/components/        表示に専念するコンポーネント
  src/hooks/             状態と API 呼び出しを閉じ込めたフック
  src/api/client.ts      バックエンド呼び出しの一箇所集約（SSE 含む）
docs/                    契約と実装計画
.devcontainer/           開発コンテナ（そのままプロジェクトへコピーする）
.claude/                 Claude Code のエージェント・スキル・権限・フック
docker-compose.yml       db / api / web をまとめて起動する開発用定義
.env.example             環境変数のひな形

ruff.toml                Python の Lint / フォーマット
eslint.config.mjs        JS / TS の Lint
.prettierrc.json         フォーマッタ
.yamllint.yaml           YAML の Lint
.editorconfig            エディタ共通設定
.pre-commit-config.yaml  上記を Git フックに集約
```

Lint 設定はリポジトリルートに置く。プロジェクトのファイルなので、コンテナ側では
なくプロジェクト側で管理する。

## Claude Code のエージェントとスキル

`.claude/` には、このアプリ構成を前提としたサブエージェントとスキルが入っている。

| エージェント       | 担当                                             |
| ------------------ | ------------------------------------------------ |
| `task-planner`     | 実装計画（層への分割・契約変更の有無・並列可否） |
| `frontend-builder` | `web/` 配下                                      |
| `backend-builder`  | `api/` のうち `app/services/agents/` を除く部分  |
| `agent-builder`    | `api/app/services/agents/`                       |

| スキル              | 内容                                                         |
| ------------------- | ------------------------------------------------------------ |
| `adk-agent-design`  | Google ADK エージェントの設計原則と検証済み API リファレンス |
| `backend-workflow`  | `api/` の規約と検証手順                                      |
| `frontend-workflow` | `web/` の規約と検証手順                                      |
| `git-workflow`      | ブランチ・commit・push の規約                                |
| `issue-deepdive`    | GitHub issue の粒度・構成ルール                              |

3 層に跨るタスクは「`task-planner` で計画 → 3 つの builder を並列実行 → 親が結合して
commit」が既定の進め方。詳細は [CLAUDE.md](CLAUDE.md) の「サブエージェントの使い方」節。

## 新しいプロジェクトを作る

### アプリごと使う場合

1. このリポジトリをコピーして新しいリポジトリにする
2. `.devcontainer/devcontainer.json` の `name` を書き換える
3. `docker-compose.yml` の `name` と、`api/pyproject.toml` の `name` を書き換える
4. `CLAUDE.md` の冒頭をそのアプリの説明に差し替える
5. サンプルのチャット機能を、作りたいアプリに作り替えていく

`.claude/` のエージェント・スキルはディレクトリ構成に依存しているので、構成を
大きく変えるならスキルの記述も併せて直す。

### 開発環境だけ使う場合

1. `.devcontainer/` を新しいリポジトリのルートにコピーする
2. `devcontainer.json` の `name` を書き換える
3. 使う Lint 設定（`ruff.toml` など）をルートにコピーする
4. コンテナを開く

以降はそのリポジトリで自由に変えてよい。要らないツールは Dockerfile から削る。
バージョン指定や編集時の注意は [.devcontainer/README.md](.devcontainer/README.md) を参照。

## このリポジトリでの作業

開発コンテナで開く（VS Code の「Reopen in Container」、または
`devcontainer up --workspace-folder .`）。このリポジトリ自身も、コピー先と同じ
`.devcontainer/` をそのまま使う。
