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

# --- runtime toolchain overrides ---------------------------------------------
#
# When the image is consumed prebuilt from a registry, Node is fixed by the
# image tag, but Python and Terraform can still be switched here. Set
# PYTHON_VERSION / TERRAFORM_VERSION in devcontainer.json's `containerEnv`.
# Both are no-ops when the requested version is already the one in the image.

if [ -n "${PYTHON_VERSION:-}" ]; then
  current_python="$(python --version 2>/dev/null | awk '{print $2}')"
  case "$current_python" in
    "${PYTHON_VERSION}" | "${PYTHON_VERSION}".*) ;;
    *)
      log "switching Python ${current_python:-none} -> ${PYTHON_VERSION}"
      uv python install --default "$PYTHON_VERSION" || warn "Python switch failed"
      ;;
  esac
fi

if [ -n "${TERRAFORM_VERSION:-}" ]; then
  current_tf="$(terraform version -json 2>/dev/null | jq -r .terraform_version 2>/dev/null)"
  if [ "$current_tf" != "$TERRAFORM_VERSION" ]; then
    log "switching Terraform ${current_tf:-none} -> ${TERRAFORM_VERSION}"
    tf_arch="$(dpkg --print-architecture)"
    tf_url="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${tf_arch}.zip"
    if curl -fsSL -o /tmp/terraform.zip "$tf_url"; then
      # /opt/devtemplate/bin precedes the baked-in binary on PATH.
      unzip -qo -d /opt/devtemplate/bin /tmp/terraform.zip && rm -f /tmp/terraform.zip
    else
      warn "could not download Terraform ${TERRAFORM_VERSION}"
    fi
  fi
fi

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
  log "no shared lint config found - run 'devtemplate-init' to copy the template defaults"
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
