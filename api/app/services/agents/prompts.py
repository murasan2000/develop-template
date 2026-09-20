"""エージェントの instruction / description 文字列。

LLM 設定（モデル名・プロンプト文面）を `chat.py` に直書きすると、
プロンプトを調整するたびにエージェント定義のコードを触ることになり
差分が読みにくくなる。文面はここに集約し、`chat.py` からは定数として
import するだけにする。
"""

from __future__ import annotations

CHAT_AGENT_DESCRIPTION = "ユーザーと日本語で会話する、テンプレート用の汎用チャットエージェント。"

CHAT_AGENT_INSTRUCTION = """\
あなたはチャットアプリのテンプレートに組み込まれているアシスタントです。

- ユーザーとは日本語で、簡潔かつ丁寧に会話してください。
- 現在時刻が必要な場合は `get_current_time` ツールを使い、憶測で答えないでください。
- 分からないことは分からないと正直に伝えてください。
- ユーザーの発言に添付ファイルが含まれる場合は、その内容を踏まえて答えてください。
  `[添付ファイル: ...]` という注記はシステムが自動的に付けたものであり、
  ユーザー自身の発言ではありません。
"""

# 添付ファイルのファイル名をモデルに伝えるための注記。
#
# `google.genai.types.Part.from_bytes` にはファイル名を載せる口が無い
# （`types.Blob.display_name` は存在するが `from_bytes` は設定しない）ため、
# inline パートの直前にこの text パートを 1 つ置いてファイル名を伝える
# （`attachments.py` の `build_user_parts` 参照）。
ATTACHMENT_LABEL = "[添付ファイル: {filename}（{mime_type}）]"

# モデルが直接読み取れない MIME タイプの添付に付ける注記。
#
# 画像・テキスト・PDF 以外（`application/zip` など）はバイト列を送らず、
# この文面でファイル名・MIME タイプ・サイズだけを伝える（エラーにはしない。
# D5: 非対応形式でも送信自体は成立させる）。
UNSUPPORTED_ATTACHMENT_NOTE = (
    "[添付ファイル: {filename}（{mime_type}, {size_bytes} バイト）。"
    "この形式は直接読み取れないため、内容は不明です。]"
)
