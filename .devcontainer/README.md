# 開発コンテナ

Node / Python のランタイムに、クラウド CLI (gcloud / az / aws)、Terraform、
Lint 一式、pre-commit をまとめた開発環境。
このリポジトリで定義・ビルドし、GHCR 経由で派生プロジェクトへ配布する。

## 基本方針

**派生プロジェクトは公開イメージを pull する。Dockerfile をコピーしない。**

重い部分 (gcloud / az / aws / terraform で約 1.5GB) はめったに変わらないのに、
ビルド方式だとプロジェクトごとに毎回取得し直すことになる。
それ以上に問題なのは、Dockerfile のコピーが各プロジェクトに散らばって
少しずつズレていくこと。定義を1箇所に集約すれば、タグを上げるだけで全プロジェクトに反映できる。

| 方法                                  | 用途                                          | 起動時間                        |
| ------------------------------------- | --------------------------------------------- | ------------------------------- |
| **GHCR の公開イメージを pull** (推奨) | 派生プロジェクト                              | 初回のみ pull、以降はキャッシュ |
| Dockerfile からビルド                 | このリポジトリ自身 / イメージを改造したい場合 | 5〜10 分                        |

トレードオフとして、イメージは非圧縮で約 4.9GB あり pull も軽くはない。
プライベートリポジトリの場合は各マシンで `docker login ghcr.io` が必要になる。

## ルール

1. **派生プロジェクトに Dockerfile を置かない。** `devcontainer.json` 1枚だけをコピーする
2. **コンテナ定義の変更はこのリポジトリで行う。** 派生側で `postCreateCommand` に
   `apt-get install` を足すような回避をしない。恒久的に必要なツールは Dockerfile に入れる
3. **CI や本番に関わる用途では日付付きタグを固定する。** `latest` は開発時のみ
4. **Node はタグ、Python / Terraform は `containerEnv` で指定する** (理由は後述)
5. **共通 Lint 設定は削除しない。** プロジェクト固有ルールは既存設定への追記で表現する
6. **認証情報をイメージやリポジトリに焼き込まない。** 名前付きボリュームに置く
7. **`.devcontainer/**` や Lint 設定を変更したら `main` に入れてイメージを再公開する。**
   ローカルビルドのまま放置すると、派生プロジェクトとの差異が生まれる

## 派生プロジェクトのセットアップ

1. `templates/devcontainer/devcontainer.json` を `<project>/.devcontainer/devcontainer.json` にコピーする
2. `image` の `OWNER/REPO` と `name` を書き換える
3. コンテナを起動し、必要なら `devtemplate-init` で共通 Lint 設定をコピーする

コピーするファイルはこの1つだけでよい。post-create スクリプトと共通 Lint 設定はイメージに同梱されている。

```bash
devtemplate-init          # 未配置の共通設定だけコピー
devtemplate-init --list   # イメージが持つ設定一覧
devtemplate-init --force  # 既存ファイルも上書き
```

## バージョン指定

Node だけがイメージタグで決まり、Python と Terraform は起動時に切り替わる。
Node はベースイメージに焼き込まれていて実行時に変えられないが、
Python は uv 管理、Terraform は単一バイナリなので差し替えられるため。
この分離によってタグの組み合わせ爆発を避けている
(全部タグにすると 3 Node × 3 Python × 2 アーキ = 18 ビルドになる)。

| ツール    | 指定方法                         | 既定値 |
| --------- | -------------------------------- | ------ |
| Node      | イメージタグ                     | 22     |
| Python    | `containerEnv.PYTHON_VERSION`    | 3.13   |
| Terraform | `containerEnv.TERRAFORM_VERSION` | 1.16.2 |

```jsonc
{
  // Node: タグで指定 (node20 / node22 / node24、latest = node22)
  "image": "ghcr.io/OWNER/REPO/devcontainer:node22",
  "containerEnv": {
    // Python / Terraform: 起動時に切り替え。イメージ内の版と同じなら何もしない
    "PYTHON_VERSION": "3.12",
    "TERRAFORM_VERSION": "1.13.4",
  },
}
```

切り替えコストは実測で合計 8 秒程度 (Python 約 2 秒、Terraform ダウンロード数秒)。
再現性を優先するなら `node22-20260912` のような日付付きタグを固定する。

Dockerfile からビルドする場合は build args で指定する。

```bash
NODE_VERSION=20 PYTHON_VERSION=3.12 devcontainer up --workspace-folder .
```

`NODE_VERSION` は Node 公式イメージのタグに対応するバージョンのみ。
`PYTHON_VERSION` は uv が取得できる CPython であれば任意。

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

## 認証情報

`gcloud auth login` / `az login` の結果は名前付きボリュームに保存されるため、
コンテナを作り直しても再ログインは不要。ホストの `~/.claude` はバインドマウントされる。

認証情報をイメージに焼き込んだり、リポジトリにコミットしてはいけない。
`.gitignore` と pre-commit の gitleaks / detect-private-key で二重に防いでいるが、
最終的な責任は書く側にある。

## コンテナ作成後の処理

`post-create.sh` (イメージ内では `devcontainer-post-create`) がワークスペースを見て自動実行する。

- `PYTHON_VERSION` / `TERRAFORM_VERSION` が指定されていれば切り替え
- `pyproject.toml` → `uv sync --all-groups` / `requirements.txt` → venv 作成
- `package-lock.json` → `npm ci` / `package.json` → `npm install`
- `.pre-commit-config.yaml` → `pre-commit install --install-hooks`
- git の pager を delta に設定

いずれも該当しなければスキップされ、失敗してもコンテナ作成は中断しない
(1つのプロジェクト都合でコンテナが起動しなくなる方が困るため)。

## Lint / フォーマット

設定ファイルはリポジトリルートに置き、イメージにも同梱して `devtemplate-init` で配布する。

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

## イメージの公開

`.github/workflows/devcontainer-image.yml` が GHCR へ push する。

- トリガー: `main` への `.devcontainer/**` や Lint 設定の変更 / 週次 / 手動
- タグ: Node バージョンごとに `node20` `node22` `node24`、日付付き、`latest` (= node22)
- アーキテクチャ: `linux/amd64` と `linux/arm64` をネイティブランナーでビルドして
  マニフェストリストに合成する

週次リビルドは OS とクラウド CLI のセキュリティ更新を取り込むため。

QEMU エミュレーションは使わない。このイメージだと azure-cli や CPython のビルドで
1時間近くかかり、タイムアウトのリスクがある。
`ubuntu-24.04-arm` ランナーはパブリックリポジトリでは無料だが、プライベートでは有料プランが必要。
使えない場合は arm64 レグを外すか、セルフホストの arm64 ランナーに差し替える。

## このリポジトリでイメージを変更する

`.devcontainer/devcontainer.json` は Dockerfile からビルドする設定になっている
(イメージを直す場所なので pull では意味がない)。
ビルドコンテキストはリポジトリルート — 共通 Lint 設定をイメージに焼き込むため。

ローカルでの確認:

```bash
docker build -f .devcontainer/Dockerfile -t devtemplate:local .
docker run --rm devtemplate:local bash -lc 'devcontainer-post-create'
```

Dockerfile を編集するときの注意:

- 重いレイヤ (apt / クラウド CLI / Terraform) を上、変更頻度の高いもの (COPY) を下に置く
- 実行時に切り替えたいものは `/opt/uv` や `/opt/devtemplate/bin` に置く。
  これらはコンテナユーザー所有で、sudo なしで書き換えられる
- ログインシェルは `/etc/profile` が PATH を上書きするため、
  PATH を足すときは `ENV` だけでなく `/etc/profile.d/` にも反映する

`runArgs` の `NET_ADMIN` / `NET_RAW` は egress firewall 用の権限。
該当スクリプトを追加しないなら削除してよい。
