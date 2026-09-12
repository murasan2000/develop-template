# develop-template

各種アプリの派生元となる開発テンプレートリポジトリ。

開発コンテナ定義、Lint / pre-commit 設定、CI/CD 定義を共通化し、
ここから派生して個別アプリを作る。共通部分はこのリポジトリで一元管理し、
派生プロジェクトへはビルド済みのコンテナイメージと設定ファイルとして配布する。

## ドキュメント

| ドキュメント                                       | 内容                                                               |
| -------------------------------------------------- | ------------------------------------------------------------------ |
| [.devcontainer/README.md](.devcontainer/README.md) | 開発コンテナのルール・ポリシー、バージョン指定、Lint、イメージ公開 |

CI/CD パイプラインの定義とそのドキュメントは今後追加する。

## 構成

```
.devcontainer/
  README.md              開発コンテナのドキュメント
  Dockerfile             イメージ定義 (このリポジトリでビルド・公開する)
  devcontainer.json      このリポジトリ用 (Dockerfile からビルド)
  post-create.sh         コンテナ作成後の初期化
  devtemplate-init.sh    共通 Lint 設定をプロジェクトへ配布するヘルパー

templates/
  devcontainer/
    devcontainer.json    派生プロジェクトがコピーする設定 (公開イメージを pull)

.github/workflows/
  devcontainer-image.yml GHCR へのイメージ公開

ruff.toml                Python の Lint / フォーマット
eslint.config.mjs        JS / TS の Lint
.prettierrc.json         フォーマッタ
.yamllint.yaml           YAML の Lint
.editorconfig            エディタ共通設定
.pre-commit-config.yaml  上記を Git フックに集約
```

Lint 設定はリポジトリルートに置き、同じものがコンテナイメージにも同梱される。
派生プロジェクトは `devtemplate-init` で取り込む。

## 派生プロジェクトを作る

`templates/devcontainer/devcontainer.json` を新しいプロジェクトの
`.devcontainer/devcontainer.json` にコピーし、`image` と `name` を書き換えるだけでよい。

手順の詳細とバージョン指定の方法は [.devcontainer/README.md](.devcontainer/README.md) を参照。

## このリポジトリでの作業

開発コンテナで開く (VS Code の「Reopen in Container」、または `devcontainer up --workspace-folder .`)。
このリポジトリ自身は公開イメージを pull せず、Dockerfile からビルドする。
