---
name: backend-workflow
description: api/（FastAPI / Python 3.13 / uv）実装時に守る規約と検証手順。エンドポイント・永続化・設定・SSE 等のサービス層を実装する際に必ず使う。Google ADK エージェント（api/app/services/agents/）の設計は adk-agent-design スキルを使う。
---

# バックエンド実装ワークフロー（api/）

## ディレクトリ構成

```
api/app/
  servers/api.py        FastAPI アプリ本体・エンドポイント・lifespan
  config.py             pydantic-settings による設定（環境変数を 1 箇所で読む）
  services/db/          SQLAlchemy の engine / session / モデル定義
  services/chat/        会話・メッセージのリポジトリ（永続化）
  services/agents/      Google ADK エージェント（adk-agent-design スキル参照）
  types/api.py          Pydantic のリクエスト / レスポンス型
  utils/                純粋関数のユーティリティ（SSE 整形など）
api/tests/              pytest（ネットワーク・LLM 非依存）
```

新しい関心事が増えたら `services/<名前>/` を足す。`servers/api.py` を太らせない
（エンドポイントは「入力を検証し、サービスを呼び、型に詰めて返す」までに留める）。

## 型の使い分け

- **Pydantic**: API 境界（リクエスト / レスポンス）。`app/types/api.py`。
  フロントの `web/src/types/api.ts` と 1:1 で対応させる。
- **SQLAlchemy モデル**: 永続化の形。API のレスポンス型を兼ねさせない
  （DB のカラム変更がそのまま API の破壊的変更になるのを防ぐため）。
- **TypedDict / Protocol**: 内部の受け渡しや、実装を差し替える境界。
  エージェント層のように「テストでフェイクに差し替えたい」境界は `Protocol` にする。

## データベース

- **スキーマの唯一の定義は SQLAlchemy モデル**。起動時に `run_sync(Base.metadata.create_all)`
  で作る。テンプレートの段階ではマイグレーションツールを入れていないので、
  **本番運用に入る前に Alembic 等へ置き換える**こと。
- **PostgreSQL 固有型を安易に使わない**。`sa.Uuid` / `sa.Text` / `sa.DateTime(timezone=True)`
  のような可搬な型を使う（テストを `sqlite+aiosqlite` で回せなくなるため）。
  固有型が本当に要る場面（`JSONB`・全文検索）だけ意図的に使う。
- **engine は lifespan で 1 度だけ作る**。リクエストごとに作らない。
- **アプリ所有のテーブルと ADK 所有のテーブルは別物**。`conversations` / `messages` は
  UI が読む表示用の履歴、ADK の `SessionService` が作るテーブルはエージェントの
  作業記憶。同じ DB に同居するが、統合しない。

## エラーハンドリング / ログの方針

- **ユーザーに見える失敗と、握りつぶしてよい失敗を分ける**。前者は例外を送出して
  API 層で変換する。後者（機能縮退で済む補助的な外部呼び出し）は空結果を返して続行する。
- **SSE のストリーム開始後は HTTP ステータスを変えられない**。ストリーム中の失敗は
  `event: error` として返し、ステータスは 200 のままにする。
- **部分的な結果を捨てない**。ストリームが途中で切れても、そこまでに受け取った
  テキストは保存する（履歴が欠けるのはユーザーにとって最悪の壊れ方のため）。
- ログは概況（所要時間・文字数・会話 ID）に留める。**プロンプト全文や応答全文を
  アプリログに吐かない**（個人情報が混ざるうえ、追跡には専用のトレーシングを使うため）。

## テスト

- **ネットワーク・LLM 非依存**。エージェント層はフェイクに差し替える
  （`Protocol` で境界を切ってあるのはこのため）。
- DB は `sqlite+aiosqlite:///:memory:` を使う。
- API は `httpx.ASGITransport` + `httpx.AsyncClient` で叩く。
- **正常系だけでなく、404 とストリーム中の例外を必ず 1 本ずつ書く**。

## 検証手順（完了前に必ず実行、`api/` で）

```bash
uv run pytest -q                          # テスト
uv run ruff check app/ tests/             # Lint（設定はリポジトリルートの ruff.toml）
uv run ruff format --check app/ tests/    # フォーマット
uv run mypy app/                          # 型チェック（strict）
```

依存を増やすときは `uv add`（`settings.json` で確認が入る）。`uv.lock` を手で編集しない。

## コーディング規約

- コメント・docstring は日本語。**「何をしているか」ではなく「なぜそうしているか」**を書く
  （何をしているかはコードが語る）。
- 変更は既存コードのスタイル・粒度に合わせる。新しい抽象を持ち込む前に、
  似た既存実装が無いか探す。

## 完了時

作業が一区切りついたら `git-workflow` スキルに従い commit + push する。
