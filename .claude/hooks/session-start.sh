#!/usr/bin/env bash
# SessionStart フック: Claude Code on the web のリモート環境でだけ、
# api/（uv）・web/（npm）の依存関係を自動インストールする。
#
# なぜ必要か:
#   ローカル開発では .devcontainer の postCreateCommand が依存を解決するが、
#   postCreateCommand は VS Code Dev Containers 用であり、Claude Code on the web の
#   リモート環境では実行されない。そのままだとリモートセッション開始直後は
#   api/.venv も web/node_modules も無く、CLAUDE.md に書いてある検証コマンド
#   （uv run pytest / npm run build 等）が動かない状態になる。
#
# ローカル（devcontainer / 手元環境）では実行しない。ローカルは
# postCreateCommand や開発者自身の `uv sync` / `npm install` に任せる。
#
# フックの失敗でセッション開始を止めないため、各ステップの失敗は警告に留める。
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

warn() { printf '[session-start] %s\n' "$*" >&2; }

if [ -f "${CLAUDE_PROJECT_DIR}/api/pyproject.toml" ]; then
  (cd "${CLAUDE_PROJECT_DIR}/api" && uv sync --all-groups) || warn "api: uv sync failed"
fi

if [ -f "${CLAUDE_PROJECT_DIR}/web/package.json" ]; then
  if [ -f "${CLAUDE_PROJECT_DIR}/web/package-lock.json" ]; then
    (cd "${CLAUDE_PROJECT_DIR}/web" && npm ci) || warn "web: npm ci failed"
  else
    (cd "${CLAUDE_PROJECT_DIR}/web" && npm install) || warn "web: npm install failed"
  fi
fi

exit 0
