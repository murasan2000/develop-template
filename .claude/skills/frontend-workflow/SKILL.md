---
name: frontend-workflow
description: web/（React + TypeScript + Vite）実装時に守る規約と検証手順。新規コンポーネント・フック・API 連携・UI/CSS 変更を行う際に必ず使う。
---

# フロントエンド実装ワークフロー（web/）

## ディレクトリ構成

```
web/src/
  components/
    chat/        メッセージ一覧・吹き出し・入力欄・ストリーミング表示
    sidebar/     会話一覧・新規作成・削除
    common/      画面横断の小物
  hooks/         画面ごとの状態管理フック（useChat.ts 等）
  api/client.ts  バックエンド API 呼び出しの一箇所集約（SSE の読み取り含む）
  types/api.ts   docs/api-contract.md の型に 1:1 対応する型定義
  utils/         フォーマット等の純粋関数
```

画面が増えたら `components/<画面名>/` と `hooks/use<画面名>.ts` をペアで足す。

## 状態管理パターン

**状態と API 呼び出しはフックに閉じ込め、`components/` は表示に専念させる。**
これがこのテンプレートの中心的な約束事。状態管理ライブラリは入れない
（この規模では `useState` + カスタムフックで足り、依存を増やす理由がないため）。

- **ストリーミング（SSE）の受け口は `api/client.ts` に集約する**。`POST` が必要なため
  `EventSource` は使えず、`fetch` + `ReadableStream` を自前でパースする。
  `event:` 行と `data:` 行の解釈をコンポーネントに散らさない。
- **競合状態に注意**。応答ストリーム中に別の会話へ切り替えられたら、古いストリームの
  増分を捨てる。`AbortController` で中断し、「いま表示中の会話か」を ref で判定する
  （`setState` は次のレンダーまで反映されないので、同一関数内で最新値を見たい場合は
  state ではなく ref のミラーを参照する）。
- **部分更新**は `Record<string, T>` に対する `patchXxx` ヘルパを用意し、
  スプレッドで浅くマージする。

## 型

`types/api.ts` は `docs/api-contract.md` と 1:1 に対応させる。バックエンドの
Pydantic 型を変えたら、**まず契約ファイルを直してから**両側を追随させる
（片側だけ直すと、型は通るのに実行時に壊れる状態になる）。

## デザイン方針

- **色は CSS カスタムプロパティ（トークン）で `:root` に定義する**。
  個別のコンポーネント CSS に生の色コードを書かない。ダークは
  `@media (prefers-color-scheme: dark)` でトークンだけを差し替える。
- レスポンシブ必須。768px 以下でサイドバーをドロワーに畳む。
- アニメーションは CSS で書き、`prefers-reduced-motion` を尊重する。
- アクセシビリティの最低線: フォーカスリングを消さない、アイコンだけのボタンに
  `aria-label`、更新される領域に `role="log"` / `aria-live`。
- UI フレームワーク（MUI / Tailwind / shadcn 等）は入れない。素の CSS で作る。

## 検証手順（完了前に必ず実行、`web/` で）

```bash
npm run lint    # eslint
npm run build   # tsc -b && vite build（型チェックを含む）
```

開発サーバは `npm run dev`（:5173、`/api` を `VITE_PROXY_TARGET`（既定 :8000）へプロキシ）。
バックエンドごと動かすなら、リポジトリルートで `docker compose up`。

依存を増やすときは `npm install`（`settings.json` で確認が入る）。
`package-lock.json` を手で編集しない。

## コーディング規約

- コメントは日本語。**「何をしているか」ではなく「なぜそうしているか」**を書く。
- 新しい抽象を持ち込む前に、既存の `hooks/` に似たものが無いか探す。

## 完了時

作業が一区切りついたら `git-workflow` スキルに従い commit + push まで行う。
