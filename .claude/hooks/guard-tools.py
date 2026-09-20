#!/usr/bin/env python3
"""PreToolUse フック: 破壊的操作・秘密情報アクセスをブロックする。

役割分担の原則:
  - permissions（.claude/settings.json）のパターンで表現できるものは、そちらに任せる。
  - このフックは「パターンでは書きにくいもの」だけを担当する。具体的には次の3種類。

  1. フラグの書き方が複数あるもの（force push の --force / -f / --force-with-lease、
     rm の -r / -R / --recursive）。
  2. パスの種類で可否が変わるもの（プロジェクト内の相対パスへの rm は通し、
     絶対パス・ホーム・親ディレクトリ遡りだけを止める）。
  3. **例外を含むパターン**。`.env` 系は原則ブロックだが `.env.example` のような
     ひな形は通したい。permissions のパス指定には否定（`!`）が無く
     「`.env.*` を拒否しつつ `.env.example` だけ許可」が書けないため、ここで扱う。

なぜ Bash 以外も見るのか:
  秘密情報の保護は「どのツールを使ったか」に依存してはいけない。Bash の
  リダイレクトも Edit/Write/Read のファイルパスも同じルールで判定しないと、
  片方だけ塞いでももう片方から素通りしてしまう。

ブロック方法:
  exit 0 + hookSpecificOutput.permissionDecision="deny" を返す（理由が Claude に伝わる）。
  判断しない場合は exit 0 で何も出力せず、通常の permission フローに委ねる。
  jq に依存しないよう Python で実装している（本テンプレートは Python 前提のため）。
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable

# シェルの区切り文字。Claude Code の Bash ルール判定と同様、区切られた各コマンドを
# 個別に評価する（`safe && rm -rf /` のような合成を見逃さないため）。
SUBCOMMAND_SEPARATOR = re.compile(r"&&|\|\||;|\||\n")

# .env 本体および .env.local 等のサフィックス付き。パストークンとして現れた場合のみ拾う
# （`grep -rn "\.env" .` のような検索文字列は対象外にする）。
ENV_FILE_TOKEN = re.compile(r"(?:^|/)\.env(?:\.[\w-]+)?$")

# ひな形は秘密情報を持たず、リポジトリに commit される前提のもの
# （.gitignore も `!.env.example` で明示的に追跡対象にしている）。ひな形へ項目を
# 足すのは日常作業なので、ここだけは .env 系のブロックから除外する。
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")

# ロックファイルは uv / npm に生成させるもので、手書き（リダイレクト等）は不整合の元。
LOCKFILE_NAMES = ("uv.lock", "package-lock.json")
SHELL_WRITE_OP = re.compile(r">|\btee\b|\btruncate\b")

FORCE_PUSH_EXACT_FLAGS = {"-f"}

# ファイルパスを直接受け取るツール。Bash と同じ .env ルールを適用する。
FILE_PATH_TOOLS = {"Read", "Edit", "Write", "NotebookEdit", "MultiEdit"}

ENV_DENY_REASON = (
    ".env 系ファイルは秘密情報を含むため、Claude からの読み書きを禁止しています。"
    "値の確認・変更が必要な場合はユーザー自身が直接操作してください。"
    "（.env.example のようなひな形は編集できます）"
)


def _strip_token(token: str) -> str:
    """クォートやリダイレクト記号を落として、パストークンとして比較できる形にする。"""
    return token.strip("'\"<>()")


def _is_env_template(path: str) -> bool:
    """`.env.example` のようなひな形か（秘密情報を持たないので読み書きを許す）。"""
    return path.endswith(ENV_TEMPLATE_SUFFIXES)


def _is_protected_env_path(path: str) -> bool:
    """保護対象の .env ファイルか（ひな形は対象外）。"""
    return bool(ENV_FILE_TOKEN.search(path)) and not _is_env_template(path)


def _touches_env_file(segment: str) -> bool:
    """.env 系ファイルを操作対象にしているか（読み書きを問わずブロックする）。"""
    return any(_is_protected_env_path(_strip_token(t)) for t in segment.split())


def _writes_lockfile(segment: str) -> bool:
    """ロックファイルをシェル経由で書き換えようとしているか。

    `uv add` / `npm install` のようなパッケージマネージャ経由の更新は正規の手段なので
    ここには該当しない（コマンド文字列にロックファイル名が現れないため）。
    """
    if not any(name in segment for name in LOCKFILE_NAMES):
        return False
    if SHELL_WRITE_OP.search(segment):
        return True
    return bool(re.search(r"\bsed\b", segment) and re.search(r"\s-i\b", segment))


def _dangerous_recursive_rm(segment: str) -> bool:
    """プロジェクト外へ向かう再帰削除か。

    `rm -rf node_modules` や `rm -rf dist` は日常的な後片付けなので通し、
    絶対パス・ホーム・親ディレクトリ遡り・カレント全体・ワイルドカードだけを止める。
    """
    tokens = segment.split()
    if "rm" not in tokens:
        return False
    rest = tokens[tokens.index("rm") + 1 :]
    flags = [t for t in rest if t.startswith("-")]
    operands = [_strip_token(t) for t in rest if not t.startswith("-")]

    recursive = any(
        flag == "--recursive" or (not flag.startswith("--") and re.search(r"[rR]", flag))
        for flag in flags
    )
    if not recursive:
        return False

    return any(
        op.startswith("/") or op.startswith("~") or ".." in op or op in {".", "*"}
        for op in operands
    )


def _force_push(segment: str) -> bool:
    """force push か（--force / -f / --force-with-lease すべてを対象にする）。

    履歴の書き換えは影響が大きく、取り消しも難しいため、必要な場合は人間が手で行う。
    """
    tokens = segment.split()
    if "git" not in tokens or "push" not in tokens:
        return False
    return any(t in FORCE_PUSH_EXACT_FLAGS or t.startswith("--force") for t in tokens)


# (判定関数, ブロック理由) の一覧。上から順に評価する。
BASH_RULES: list[tuple[Callable[[str], bool], str]] = [
    (_touches_env_file, ENV_DENY_REASON),
    (
        _writes_lockfile,
        "ロックファイル（uv.lock / package-lock.json）のシェル経由の書き換えを禁止しています。"
        "依存を変更する場合は `uv add` / `npm install` を使ってください。",
    ),
    (
        _dangerous_recursive_rm,
        "プロジェクト外（絶対パス・ホーム・親ディレクトリ・カレント全体）への再帰削除を"
        "禁止しています。削除対象をプロジェクト内の相対パスに限定してください。",
    ),
    (
        _force_push,
        "force push（--force / -f / --force-with-lease）を禁止しています。"
        "履歴の書き換えが本当に必要な場合はユーザー自身が実行してください。",
    ),
]


def deny(reason: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
        ensure_ascii=False,
    )
    sys.exit(0)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # 解釈できない入力では判断しない（フックの不具合で作業を止めないため）。
        sys.exit(0)

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}

    if tool_name in FILE_PATH_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if _is_protected_env_path(path):
            deny(ENV_DENY_REASON)
        sys.exit(0)

    if tool_name != "Bash":
        sys.exit(0)

    command = tool_input.get("command") or ""
    for segment in SUBCOMMAND_SEPARATOR.split(command):
        for predicate, reason in BASH_RULES:
            if predicate(segment):
                deny(reason)

    sys.exit(0)


if __name__ == "__main__":
    main()
