# FastAPI バックエンドのイメージ。
#
# uv で依存を解決し、仮想環境を /opt/venv に置く。/app はバインドマウントで
# 上書きされることがあるため、venv をそこに置かないのが要点。
#
#   docker build --target dev  -t chat-api:dev  .
#   docker build --target prod -t chat-api:prod .
ARG PYTHON_VERSION=3.13

FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
  UV_COMPILE_BYTECODE=1 \
  UV_LINK_MODE=copy \
  PATH=/opt/venv/bin:$PATH \
  PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# --- 依存だけを先に解決するレイヤ（ソース変更でキャッシュを壊さない） ---------
FROM base AS deps
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --frozen --no-install-project --all-groups \
  || uv sync --no-install-project --all-groups

# --- 開発用: ソースはバインドマウントし、--reload で動かす -------------------
FROM deps AS dev
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.servers.api:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# --- 本番用: ソースを焼き込み、非 root で動かす ------------------------------
FROM deps AS prod
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --frozen --no-dev || uv sync --no-dev
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.servers.api:app", "--host", "0.0.0.0", "--port", "8000"]
