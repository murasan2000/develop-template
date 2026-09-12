# develop-template

各種アプリの派生元となる開発テンプレートリポジトリ。

開発コンテナ定義、Lint / pre-commit 設定、CI/CD 定義の出発点を置いておき、
新しいアプリはここからコピーして始める。

コピーした後はそれぞれのリポジトリの持ち物で、変更もそこで行う。
共有イメージも配信の仕組みもなく、渡すのはファイルだけ。
その代わり、ここへの改善が既存プロジェクトへ自動で届くこともない。

## ドキュメント

| ドキュメント                                       | 内容                                                           |
| -------------------------------------------------- | -------------------------------------------------------------- |
| [.devcontainer/README.md](.devcontainer/README.md) | 開発コンテナのルール・ポリシー、バージョン指定、Lint、編集方法 |

CI/CD パイプラインの定義とそのドキュメントは今後追加する。

## 構成

```
.devcontainer/           そのままプロジェクトへコピーする
  README.md              開発コンテナのドキュメント
  Dockerfile             イメージ定義
  devcontainer.json      コンテナ設定 (Dockerfile からビルド)
  post-create.sh         コンテナ作成後の初期化

ruff.toml                Python の Lint / フォーマット
eslint.config.mjs        JS / TS の Lint
.prettierrc.json         フォーマッタ
.yamllint.yaml           YAML の Lint
.editorconfig            エディタ共通設定
.pre-commit-config.yaml  上記を Git フックに集約
```

Lint 設定はリポジトリルートに置く。プロジェクトのファイルなので、
コンテナ側ではなくプロジェクト側で管理する。

## 新しいプロジェクトを作る

1. `.devcontainer/` を新しいリポジトリのルートにコピーする
2. `devcontainer.json` の `name` を書き換える
3. 使う Lint 設定 (`ruff.toml` など) をルートにコピーする
4. コンテナを開く

以降はそのリポジトリで自由に変えてよい。要らないツールは Dockerfile から削る。
バージョン指定や編集時の注意は [.devcontainer/README.md](.devcontainer/README.md) を参照。

## このリポジトリでの作業

開発コンテナで開く (VS Code の「Reopen in Container」、または `devcontainer up --workspace-folder .`)。
このリポジトリ自身も、コピー先と同じ `.devcontainer/` をそのまま使う。
