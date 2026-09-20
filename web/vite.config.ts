import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// docker compose からは api コンテナ名で、ローカル単独起動では localhost で
// バックエンドに届く必要があるため、プロキシ先を環境変数で切り替えられるようにする。
const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
        // SSE (text/event-stream) はチャンクを溜め込まずに即座に転送する必要がある。
        // Node の http-proxy はデフォルトで問題ないが、明示して意図を残す。
        ws: false,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            // nginx 等の中間バッファリングを避けるためのヒント。
            proxyReq.setHeader('X-Accel-Buffering', 'no');
          });
        },
      },
    },
  },
});
