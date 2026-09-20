---
name: git-workflow
description: Claude が実装作業を行う際のブランチ運用・コミット/push・コミットメッセージ規約。作業を開始する前（ブランチ作成）と、実装が一区切りついた時（commit + push）に必ず使う。作業の消失防止と、コミット履歴からタスク・スコープが分かる状態を保つのが目的。
---

# Git ワークフロー（ブランチ・コミット・push）

Claude Code が実装作業を行う際は、以下を必ず守る。ローカルセッション・
Claude.ai セッションのどちらで作業していても同じルールを適用する。

## 1. 作業開始時に必ずブランチを切る

- `main` 上で直接作業しない。実装に着手する前に必ず `main` に移動して最新化してから
  ブランチを切る。
- ブランチ名: `claude/feature/<topic>`（例: `claude/feature/add-message-search`）
  - `<topic>` は作業内容が分かる kebab-case の短い名前にする。
- 既に作業用ブランチ（`claude/...` や `feature/...`）上にいる場合は切り直さない。

```bash
git switch main && git pull
git switch -c claude/feature/<topic>
```

## 2. 作業が一区切りついたら必ず commit して push する

- 目的は「ローカル or Claude.ai のセッションが途中で終了・切断しても、やっていた
  作業がリモートに残っている」状態を常に保つこと（作業消失の防止）。
- 実装が一区切りついた時点（1 機能・1 修正の実装が終わった、lint / test が通った、など）で、
  指示を待たずに commit → push まで行ってよい。
- push は `.claude/settings.json` で `allow` に設定されているため、確認なしで実行してよい
  （PR で人間がレビューする前提のため）。
- **サブエージェントに実装させている間は、親（呼び出し元）がまとめて commit する**。
  複数のサブエージェントが同時に commit すると履歴が入り乱れ、
  どの変更がどのタスクのものか読めなくなるため。

## 3. コミットメッセージ規約

```
<action>(<prefix>): <context>
```

- `prefix`: 変更領域。`api` / `web` / `agent` / `doc` / `infra` / `ci` / `cd` / `test` など。
- `action`: 変更種別。`add`（新規追加）/ `fix`（修正）/ `bug`（バグ修正）/
  `refactor`（リファクタ）など。
- `context`: 何を変更したかが後から読んで分かる説明（日本語可）。多少長くても
  タスク・スコープが伝わることを優先する。

例:

- `add(api): 会話一覧取得エンドポイントを追加`
- `fix(web): ストリーミング中の会話切替でテキストが混ざる問題を修正`
- `add(agent): 現在時刻ツールを追加`
- `fix(doc): セットアップ手順のポート番号を修正`
- `bug(infra): compose の db ヘルスチェック前に api が起動する問題を修正`

## 4. やらないこと

- force push（`--force` / `-f` / `--force-with-lease`）。フックでブロックされている。
  履歴の書き換えが必要ならユーザー自身が行う。
- `.env` のコミット。`.gitignore` と pre-commit の gitleaks で二重に防いでいるが、
  最終的な責任は書く側にある。
- ロックファイル（`uv.lock` / `package-lock.json`）の手編集。
