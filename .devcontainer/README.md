# 開発コンテナ

Node / Python のランタイムに、クラウド CLI (gcloud / az / aws)、Terraform、
Lint 一式、pre-commit をまとめた開発環境。
このディレクトリをプロジェクトにコピーして使う。

## 基本方針

**コンテナ定義はプロジェクトごとに持ち、そのリポジトリで管理する。**

| 得るもの                                    | 失うもの                                      |
| ------------------------------------------- | --------------------------------------------- |
| 定義が `.devcontainer/` に閉じる            | テンプレート更新が自動で伝播しない (再コピー) |
| 固有のツール追加に許可も調整も要らない      | セキュリティ更新は各プロジェクトでリビルド    |
| レジストリ認証・公開範囲・CI のコストがゼロ | 初回ビルドに 5〜10 分                         |

初回ビルドは同じマシンなら Docker のレイヤキャッシュが効くため、
Dockerfile が同一である限り実質1回で済む。

## ルール

1. **コンテナ定義の変更はそのプロジェクトのリポジトリで行い、コミットする。**
   手元のコンテナに `apt-get install` して済ませない。次に誰かが作り直したら消える
2. **`postCreateCommand` でツールを入れない。** 恒久的に必要なものは Dockerfile に書く。
   post-create はプロジェクトの依存解決 (`uv sync` / `npm ci` など) のためにある
3. **バージョンは build args の既定値としてコミットする** (後述)。
   シェルの環境変数任せにしない
4. **共通 Lint 設定は削除しない。** プロジェクト固有ルールは既存設定への追記で表現する
5. **認証情報をイメージやリポジトリに焼き込まない。** 名前付きボリュームに置く
6. **このリポジトリに入れた改善は、既存プロジェクトへ自動では届かない。**
   広く効く変更をしたらここにも反映し、必要なプロジェクトへ持っていく

## プロジェクトで使う

1. `.devcontainer/` をプロジェクトのルートにコピーする
2. `devcontainer.json` の `name` をプロジェクト名に書き換える
3. 使う Lint 設定をリポジトリルートにコピーする
   (`ruff.toml` / `eslint.config.mjs` / `.prettierrc.json` / `.prettierignore` /
   `.yamllint.yaml` / `.editorconfig` / `.pre-commit-config.yaml`)
4. コンテナを開く。使わない言語の設定は消してよい

あとはそのプロジェクトの持ち物になる。要らないツールは Dockerfile から削り、
足りないものは足す。このリポジトリへ戻す必要はない。

## バージョン指定

`devcontainer.json` の `build.args` が唯一の指定場所。

| ツール      | build arg             | 既定値   |
| ----------- | --------------------- | -------- |
| Node        | `NODE_VERSION`        | 22       |
| Python      | `PYTHON_VERSION`      | 3.13     |
| Terraform   | `TERRAFORM_VERSION`   | 1.16.2   |
| Debian      | `DEBIAN_VARIANT`      | bookworm |
| Claude Code | `CLAUDE_CODE_VERSION` | latest   |

```jsonc
"build": {
  "dockerfile": "Dockerfile",
  "context": ".",
  "args": {
    "NODE_VERSION": "22",
    "PYTHON_VERSION": "3.13",
  },
},
```

既定値はホストの環境変数で上書きもできるが、その場しのぎ用。

```bash
NODE_VERSION=20 PYTHON_VERSION=3.12 devcontainer up --workspace-folder .
```

`NODE_VERSION` は Node 公式イメージのタグに対応するバージョンのみ。
`PYTHON_VERSION` は uv が取得できる CPython であれば任意。
バージョンを変えたらコンテナのリビルドが必要。

## 同梱ツール

| 分類         | 内容                                                                 |
| ------------ | -------------------------------------------------------------------- |
| ランタイム   | Node.js / Python (uv 管理)                                           |
| クラウド CLI | `gcloud` (+ gke-gcloud-auth-plugin) / `az` / `aws` (v2)              |
| IaC          | `terraform`                                                          |
| Lint / 整形  | `ruff` / `eslint` / `prettier` / `yamllint` / `shellcheck`           |
| Git フック   | `pre-commit`                                                         |
| その他       | `uv` / `gh` / `git-delta` / `jq` / `make` / `zsh` (oh-my-zsh + p10k) |

Python は apt ではなく uv 管理の CPython を使い、`python` / `python3` が指定バージョンを指す。
AWS CLI は apt の v1 ではなく公式インストーラの v2、`gh` は Debian 版ではなく GitHub 公式リポジトリ版。

イメージは非圧縮で約 4.9GB ある。クラウドを使わないプロジェクトなら
gcloud / az / aws のレイヤを削るとかなり軽くなる。

## 認証情報

`gcloud auth login` / `az login` の結果は名前付きボリュームに保存されるため、
コンテナを作り直しても再ログインは不要。ホストの `~/.claude` はバインドマウントされる。

認証情報をイメージに焼き込んだり、リポジトリにコミットしてはいけない。
`.gitignore` と pre-commit の gitleaks / detect-private-key で二重に防いでいるが、
最終的な責任は書く側にある。

## コンテナ作成後の処理

`post-create.sh` がワークスペースを見て自動実行する。
イメージには焼き込まず、バインドマウントされたワークスペースから実行するので、
編集してもリビルドは要らない。

- `pyproject.toml` → `uv sync --all-groups` / `requirements.txt` → venv 作成
- `package-lock.json` → `npm ci` / `package.json` → `npm install`
- `.pre-commit-config.yaml` → `pre-commit install --install-hooks`
- git の pager を delta に設定
- 最後にツールのバージョン一覧を表示

いずれも該当しなければスキップされ、失敗してもコンテナ作成は中断しない
(1つのプロジェクト都合でコンテナが起動しなくなる方が困るため)。

## Lint / フォーマット

設定ファイルはリポジトリルートに置く (コンテナの中ではなく、プロジェクトの持ち物)。

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

ESLint / Prettier はコンテナにグローバル導入済みのため、`package.json` がない段階でも動作する
(`/node_modules` シンボリックリンクで ESM から解決させている)。
プロジェクト側の `node_modules` があればそちらが優先される。

言語別のフックは対象ファイルが存在しなければ実行されないので、
Python を使わないプロジェクトで ruff が邪魔になることはない。

## Dockerfile を編集する

ローカルでの確認:

```bash
docker build -f .devcontainer/Dockerfile -t devcontainer:local .devcontainer
docker run --rm -v "$PWD:/workspace" devcontainer:local bash -lc '.devcontainer/post-create.sh'
```

編集するときの注意:

- 重いレイヤ (apt / クラウド CLI / Terraform) を上、変更頻度の高いものを下に置く。
  上をいじるとそれ以降が全部焼き直しになる
- `apt-get` など root が必要な処理は `USER root` に切り替え、
  最後に `USER developer` へ戻す。戻し忘れるとコンテナが root で起動する
- ログインシェルは `/etc/profile` が PATH を上書きするため、
  PATH を足すときは `ENV` だけでなく `/etc/profile.d/` にも反映する
- `/opt/uv` はコンテナユーザー所有。`uv tool install` は sudo なしで通る

`runArgs` の `NET_ADMIN` / `NET_RAW` は egress firewall 用の権限。
該当スクリプトを追加しないなら削除してよい。

ビルドコンテキストは `.devcontainer/` のみ。
プロジェクトのファイルを `COPY` する必要が出たら `context` を `".."` に変える。
