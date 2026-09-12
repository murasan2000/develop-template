#!/usr/bin/env bash
#
# Runs once after the dev container is created (postCreateCommand).
#
# Everything here is detected from the workspace, so the same script works for
# an empty checkout and for a project that uses only part of the toolchain.
# A failure in one step must not abort container creation - one project's
# quirk should never make the container unopenable.
set -uo pipefail

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }

cd "${WORKSPACE_FOLDER:-/workspace}" || exit 0

# Toolchain versions come from the Dockerfile's build args, not from here:
# this container is built per project, so there is exactly one place to set them.

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

if [ ! -f .pre-commit-config.yaml ] && [ ! -f ruff.toml ]; then
  log "no lint config found - copy the ones from the develop-template repository root"
fi

# --- summary -----------------------------------------------------------------
# Print `<cmd> ...` output on one line, or "n/a" if the tool is missing/silent.
ver() {
  local out
  out="$("$@" 2>/dev/null | head -1)"
  printf '%s' "${out:-n/a}"
}

log "toolchain:"
printf '  node       %s\n' "$(ver node --version)"
printf '  python     %s\n' "$(ver python --version)"
printf '  uv         %s\n' "$(ver uv --version)"
printf '  terraform  %s\n' "$(terraform version -json 2>/dev/null | jq -r '.terraform_version // "n/a"')"
printf '  gcloud     %s\n' "$(gcloud version 2>/dev/null | awk '/^Google Cloud SDK/ {print $NF; exit}')"
printf '  az         %s\n' "$(az version --output json 2>/dev/null | jq -r '."azure-cli" // "n/a"')"
printf '  aws        %s\n' "$(aws --version 2>&1 | awk '{print $1}')"
printf '  pre-commit %s\n' "$(ver pre-commit --version)"
printf '  ruff       %s\n' "$(ver ruff --version)"
printf '  eslint     %s\n' "$(ver eslint --version)"
printf '  prettier   %s\n' "$(ver prettier --version)"

exit 0
