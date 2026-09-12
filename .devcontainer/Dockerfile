# syntax=docker/dockerfile:1
#
# Development container.
#
# Copied from the develop-template repository and owned by this project: add
# whatever this project needs, remove what it does not. There is no shared
# registry image behind it - the only copy that matters is this file.
#
# Toolchain versions are build args (see .devcontainer/devcontainer.json).
# Edit the defaults there to pin them for the project, or override per run:
#
#   NODE_VERSION=20 PYTHON_VERSION=3.12 devcontainer up --workspace-folder .
#
ARG NODE_VERSION=22
ARG DEBIAN_VARIANT=bookworm

FROM node:${NODE_VERSION}-${DEBIAN_VARIANT}

# Re-declare args needed after FROM (args before FROM are out of scope in the stage).
ARG NODE_VERSION
ARG DEBIAN_VARIANT

ARG TZ
ENV TZ="$TZ"

ARG USERNAME=developer

# ---------------------------------------------------------------------------
# Toolchain versions
# ---------------------------------------------------------------------------
# Python is provided by uv (not by apt), so any CPython release can be selected.
ARG PYTHON_VERSION=3.13
ARG TERRAFORM_VERSION=1.16.2
ARG GIT_DELTA_VERSION=0.18.2
ARG ZSH_IN_DOCKER_VERSION=1.2.0
ARG CLAUDE_CODE_VERSION=latest

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# ---------------------------------------------------------------------------
# Base OS packages
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  less \
  git \
  procps \
  sudo \
  fzf \
  zsh \
  man-db \
  unzip \
  zip \
  wget \
  gnupg2 \
  iptables \
  ipset \
  iproute2 \
  dnsutils \
  aggregate \
  jq \
  nano \
  vim \
  make \
  build-essential \
  sqlite3 \
  shellcheck \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Third-party apt repositories: Google Cloud SDK, Azure CLI, GitHub CLI
# (all three publish amd64 and arm64 packages)
# ---------------------------------------------------------------------------
RUN install -d -m 0755 /usr/share/keyrings && \
  . /etc/os-release && \
  ARCH="$(dpkg --print-architecture)" && \
  curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
  echo "deb [arch=${ARCH} signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    > /etc/apt/sources.list.d/google-cloud-sdk.list && \
  curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
    | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg && \
  echo "deb [arch=${ARCH} signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ ${VERSION_CODENAME} main" \
    > /etc/apt/sources.list.d/azure-cli.list && \
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    -o /usr/share/keyrings/githubcli-archive-keyring.gpg && \
  chmod 0644 /usr/share/keyrings/githubcli-archive-keyring.gpg && \
  echo "deb [arch=${ARCH} signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list && \
  apt-get update && apt-get install -y --no-install-recommends \
    google-cloud-cli \
    google-cloud-cli-gke-gcloud-auth-plugin \
    azure-cli \
    gh \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Terraform (pinned; HashiCorp release archive)
# ---------------------------------------------------------------------------
RUN ARCH="$(dpkg --print-architecture)" && \
  curl -fsSL -o /tmp/terraform.zip \
    "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${ARCH}.zip" && \
  unzip -q -d /usr/local/bin /tmp/terraform.zip && \
  rm /tmp/terraform.zip && \
  terraform version

# ---------------------------------------------------------------------------
# AWS CLI v2 (the Debian `awscli` package is still v1)
# ---------------------------------------------------------------------------
RUN case "$(dpkg --print-architecture)" in \
    amd64) AWS_ARCH=x86_64 ;; \
    arm64) AWS_ARCH=aarch64 ;; \
    *) echo "unsupported architecture" >&2; exit 1 ;; \
  esac && \
  curl -fsSL -o /tmp/awscliv2.zip "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" && \
  unzip -q /tmp/awscliv2.zip -d /tmp && \
  /tmp/aws/install && \
  rm -rf /tmp/aws /tmp/awscliv2.zip

# ---------------------------------------------------------------------------
# git-delta (nicer diffs for git / gh)
# ---------------------------------------------------------------------------
RUN ARCH="$(dpkg --print-architecture)" && \
  curl -fsSL -o /tmp/git-delta.deb \
    "https://github.com/dandavison/delta/releases/download/${GIT_DELTA_VERSION}/git-delta_${GIT_DELTA_VERSION}_${ARCH}.deb" && \
  dpkg -i /tmp/git-delta.deb && \
  rm /tmp/git-delta.deb

# ---------------------------------------------------------------------------
# Python toolchain via uv
#
# uv itself, the managed CPython build and uv-installed tools all live outside
# $HOME so they survive a bind-mounted home and are shared by every user.
# ---------------------------------------------------------------------------
# The uv-managed interpreter, its shims and uv-installed tools all live under
# /opt/uv rather than in $HOME, and /opt/uv/bin comes first on PATH. That tree
# is writable by the container user (see the User setup section), so
# `uv tool install` and `uv python install` work without sudo at runtime too.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python \
  UV_PYTHON_BIN_DIR=/opt/uv/bin \
  UV_TOOL_DIR=/opt/uv/tools \
  UV_TOOL_BIN_DIR=/opt/uv/bin \
  PATH=/opt/uv/bin:$PATH

RUN curl -LsSf https://astral.sh/uv/install.sh \
    | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh && \
  uv --version

# `--default` also creates the bare `python` / `python3` shims in UV_PYTHON_BIN_DIR.
RUN uv python install --default "${PYTHON_VERSION}" && \
  python --version

# Python-based lint / hook tooling, each in its own isolated environment.
RUN uv tool install --python "${PYTHON_VERSION}" pre-commit && \
  uv tool install --python "${PYTHON_VERSION}" ruff && \
  uv tool install --python "${PYTHON_VERSION}" yamllint

# ---------------------------------------------------------------------------
# User setup
# ---------------------------------------------------------------------------
# Rename the image's default `node` user to a language-neutral name.
RUN usermod -l ${USERNAME} -d /home/${USERNAME} -m node && \
  groupmod -n ${USERNAME} node && \
  echo "${USERNAME} ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} && \
  chmod 0440 /etc/sudoers.d/${USERNAME}

# Ensure the non-root user owns the shared npm prefix.
#
# The /node_modules symlink is what makes the globally installed packages
# resolvable from an ESM config such as eslint.config.mjs: NODE_PATH only
# applies to CommonJS `require`, while ESM resolution walks `node_modules`
# directories up to the filesystem root. A project's own /workspace/node_modules
# still takes precedence.
RUN mkdir -p /usr/local/share/npm-global/lib/node_modules && \
  chown -R ${USERNAME}:${USERNAME} /usr/local/share && \
  ln -s /usr/local/share/npm-global/lib/node_modules /node_modules

# /opt/uv is owned by the container user so that `uv python install` and
# `uv tool install` work without sudo.
RUN chown -R ${USERNAME}:${USERNAME} /opt/uv

# Persist shell history across container rebuilds (see the mount in devcontainer.json).
RUN mkdir -p /commandhistory && \
  touch /commandhistory/.bash_history && \
  chown -R ${USERNAME}:${USERNAME} /commandhistory

# Workspace and per-user config directories.
#
# .config/gcloud and .azure are created here on purpose: devcontainer.json mounts
# named volumes over them, and Docker seeds a fresh volume with the ownership of
# the directory that already exists in the image. Without this they would be
# root-owned and `gcloud auth login` / `az login` would fail.
RUN mkdir -p \
    /workspace \
    /home/${USERNAME}/.claude \
    /home/${USERNAME}/.cache \
    /home/${USERNAME}/.config/gcloud \
    /home/${USERNAME}/.azure && \
  chown -R ${USERNAME}:${USERNAME} /workspace /home/${USERNAME}

# Debian's /etc/profile hard-resets PATH for login shells (and /etc/zsh/zprofile
# sources it), which would drop the npm global bin dir set below. Re-add it for
# every shell flavour.
RUN printf '%s\n' \
    'export PATH="/opt/uv/bin:/usr/local/share/npm-global/bin:$HOME/.local/bin:$PATH"' \
    > /etc/profile.d/10-devcontainer-path.sh && \
  chmod 0644 /etc/profile.d/10-devcontainer-path.sh

# Help tooling detect that it is running inside the dev container.
ENV DEVCONTAINER=true
WORKDIR /workspace

USER ${USERNAME}

# ---------------------------------------------------------------------------
# Node global tooling
#
# NODE_PATH lets a project resolve these globally installed packages (e.g. a
# flat eslint.config.mjs importing @eslint/js) before it has its own node_modules.
# ---------------------------------------------------------------------------
ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global \
  NODE_PATH=/usr/local/share/npm-global/lib/node_modules \
  PATH=/usr/local/share/npm-global/bin:/home/${USERNAME}/.local/bin:$PATH

RUN npm install -g \
    @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    eslint \
    @eslint/js \
    globals \
    typescript-eslint \
    prettier \
  && npm cache clean --force

# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------
ENV SHELL=/bin/zsh \
  EDITOR=nano \
  VISUAL=nano

RUN sh -c "$(wget -O- https://github.com/deluan/zsh-in-docker/releases/download/v${ZSH_IN_DOCKER_VERSION}/zsh-in-docker.sh)" -- \
  -p git \
  -p fzf \
  -a "source /usr/share/doc/fzf/examples/key-bindings.zsh" \
  -a "source /usr/share/doc/fzf/examples/completion.zsh" \
  -a "export PROMPT_COMMAND='history -a' && export HISTFILE=/commandhistory/.bash_history" \
  -x

# Same history persistence for bash.
RUN echo "export PROMPT_COMMAND='history -a' && export HISTFILE=/commandhistory/.bash_history" \
  >> /home/${USERNAME}/.bashrc
