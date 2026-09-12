# develop-template

各種アプリの派生元となる開発テンプレートリポジトリ。
開発コンテナ定義・Lint / pre-commit 設定を共通化し、ここから fork / clone して個別アプリを作る想定。

## 開発コンテナ

`.devcontainer/` に定義。VS Code の「Reopen in Container」、または devcontainer CLI で起動する。

```bash
devcontainer up --workspace-folder .
```

### 同梱ツール

| 分類         | 内容                                                                 |
| ------------ | -------------------------------------------------------------------- |
| ランタイム   | Node.js (バージョン指定可) / Python (uv 管理・バージョン指定可)      |
| クラウド CLI | `gcloud` (+ gke-gcloud-auth-plugin) / `az` / `aws` (v2)              |
| IaC          | `terraform` (バージョン固定)                                         |
| Lint / 整形  | `ruff` / `eslint` / `prettier` / `yamllint` / `shellcheck`           |
| Git フック   | `pre-commit`                                                         |
| その他       | `uv` / `gh` / `git-delta` / `jq` / `make` / `zsh` (oh-my-zsh + p10k) |

Python は apt ではなく uv 管理の CPython を使用し、`python` / `python3` が指定バージョンを指す。

### バージョン指定

`.devcontainer/devcontainer.json` の `build.args` が唯一の指定箇所。
派生プロジェクトでは、ここの既定値を書き換えてリポジトリに固定するのが基本。

```jsonc
"args": {
  "NODE_VERSION": "${localEnv:NODE_VERSION:22}",
  "PYTHON_VERSION": "${localEnv:PYTHON_VERSION:3.13}",
  "TERRAFORM_VERSION": "${localEnv:TERRAFORM_VERSION:1.16.2}",
  "DEBIAN_VARIANT": "${localEnv:DEBIAN_VARIANT:bookworm}",
  ...
}
```

一時的に切り替えたい場合はホストの環境変数で上書きできる。

```bash
NODE_VERSION=20 PYTHON_VERSION=3.12 devcontainer up --workspace-folder .
```

`NODE_VERSION` はベースイメージ `node:<version>-<variant>` のタグに対応するため、
Node 公式イメージが存在するバージョン (18 / 20 / 22 / 24 …) を指定すること。
`PYTHON_VERSION` は uv が取得できる CPython であれば任意。

### 認証情報

`gcloud auth login` / `az login` の結果は名前付きボリュームに保存されるため、
コンテナを作り直しても再ログインは不要。ホストの `~/.claude` はバインドマウントされる。

### コンテナ作成後の処理

`.devcontainer/post-create.sh` がワークスペースを見て自動実行する。

- `pyproject.toml` → `uv sync --all-groups` / `requirements.txt` → venv 作成
- `package-lock.json` → `npm ci` / `package.json` → `npm install`
- `.pre-commit-config.yaml` → `pre-commit install --install-hooks`
- git の pager を delta に設定

いずれも存在しなければスキップされ、失敗してもコンテナ作成は中断しない。

## Lint / フォーマット

| ファイル                  | 対象                                          |
| ------------------------- | --------------------------------------------- |
| `ruff.toml`               | Python (lint + format、flake8/isort/black 兼) |
| `eslint.config.mjs`       | JS / TS (Flat Config)                         |
| `.prettierrc.json`        | JS / TS / JSON / YAML / Markdown / CSS        |
| `.yamllint.yaml`          | YAML                                          |
| `.editorconfig`           | エディタ共通のインデント・改行                |
| `.pre-commit-config.yaml` | 上記＋秘密情報検出・terraform fmt を集約      |

```bash
pre-commit run --all-files   # 全ファイルにフック実行
pre-commit autoupdate        # フックのバージョン更新
```

ESLint / Prettier はコンテナにグローバル導入済みのため、
`package.json` がない段階でも動作する (`/node_modules` シンボリックリンクで解決)。
プロジェクト側で `node_modules` に導入した場合はそちらが優先される。

## 派生プロジェクトでの手順

1. このリポジトリを clone / テンプレートとして新規作成する
2. `.devcontainer/devcontainer.json` の `name` とバージョン引数を調整する
3. 不要な VS Code 拡張・Lint 設定を削る
4. `runArgs` の `NET_ADMIN` / `NET_RAW` は egress firewall 用。使わないなら削除する
