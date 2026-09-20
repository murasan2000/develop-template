# React + Vite フロントエンドのイメージ。
#
#   docker build --target dev  -t chat-web:dev  .   # Vite dev サーバ（HMR）
#   docker build --target prod -t chat-web:prod .   # ビルド成果物を nginx で配信
ARG NODE_VERSION=22

FROM node:${NODE_VERSION}-bookworm-slim AS deps
WORKDIR /app
# package.json だけ先に入れて、ソース変更で依存の再取得が走らないようにする。
COPY package.json package-lock.json* ./
RUN npm ci || npm install

# --- 開発用: ソースはバインドマウント、HMR を有効にする ----------------------
FROM deps AS dev
ENV NODE_ENV=development
COPY . .
EXPOSE 5173
# --host なしだとコンテナ内の 127.0.0.1 にしか bind せず、ホストから届かない。
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

# --- ビルド ------------------------------------------------------------------
FROM deps AS build
COPY . .
RUN npm run build

# --- 本番用: 静的配信のみ。/api は前段のリバースプロキシで API に振る想定 -----
FROM nginx:1.29-alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
