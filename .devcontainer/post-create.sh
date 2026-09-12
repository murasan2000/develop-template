#!/usr/bin/env bash
#
# Runs once after the dev container is created (postCreateCommand).
#
# Everything here is optional and detected from the workspace, so the same
# script works for an empty template checkout and for any project derived
# from it. A failure in one step must not abort container creation.
set -uo pipefail

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }

cd "${WORKSPACE_FOLDER:-/workspace}" || exit 0

# --- git ---------------------------------------------------------------------
if [ -d .git ]; then
  git config --global --add safe.directory "$PWD"
  # Use git-delta for diffs if it is installed (it is, in this image).
  if command -v delta >/dev/null 2>&1; then
    git config --global core.pager delta
    git config --global interactive.diffFilter "delta --color-only"
    git config --global delta.navigate true
  fi
fi

# --- Python project ----------------------------------------------------------
if [ -f pyproject.toml ]; then
  log "pyproject.toml found - running uv sync"
  uv sync --all-groups || warn "uv sync failed"
elif [ -f requirements.txt ]; then
  log "requirements.txt found - creating .venv"
  if uv venv; then
    uv pip install -r requirements.txt || warn "pip install failed"
  else
    warn "uv venv failed"
  fi
fi

# --- Node project ------------------------------------------------------------
if [ -f package-lock.json ]; then
  log "package-lock.json found - running npm ci"
  npm ci || warn "npm ci failed"
elif [ -f package.json ]; then
  log "package.json found - running npm install"
  npm install || warn "npm install failed"
fi

# --- Terraform ---------------------------------------------------------------
if compgen -G "*.tf" >/dev/null || [ -d terraform ]; then
  log "Terraform configuration found - skipping automatic init (run 'terraform init' yourself)"
fi

# --- pre-commit --------------------------------------------------------------
if [ -f .pre-commit-config.yaml ] && [ -d .git ]; then
  log "installing pre-commit hooks"
  pre-commit install --install-hooks || warn "pre-commit install failed"
fi

log "toolchain:"
printf '  node       %s\n' "$(node --version 2>/dev/null || echo 'n/a')"
printf '  python     %s\n' "$(python --version 2>/dev/null || echo 'n/a')"
printf '  uv         %s\n' "$(uv --version 2>/dev/null || echo 'n/a')"
printf '  terraform  %s\n' "$(terraform version -json 2>/dev/null | jq -r .terraform_version || echo 'n/a')"
printf '  gcloud     %s\n' "$(gcloud version --format='value(\"Google Cloud SDK\")' 2>/dev/null || echo 'n/a')"
printf '  az         %s\n' "$(az version --output tsv --query '\"azure-cli\"' 2>/dev/null || echo 'n/a')"
printf '  aws        %s\n' "$(aws --version 2>/dev/null || echo 'n/a')"
printf '  pre-commit %s\n' "$(pre-commit --version 2>/dev/null || echo 'n/a')"
printf '  ruff       %s\n' "$(ruff --version 2>/dev/null || echo 'n/a')"
printf '  eslint     %s\n' "$(eslint --version 2>/dev/null || echo 'n/a')"

exit 0
