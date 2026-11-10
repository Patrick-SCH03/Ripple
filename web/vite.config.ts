import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

// 개발 중에는 /api를 로컬 API(uvicorn, 8010)로 넘긴다. 배포에서는 Caddy가 같은 일을 한다.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5173,
    proxy: { '/api': { target: process.env.RIPPLE_API_URL ?? 'http://127.0.0.1:8010', changeOrigin: false } },
  },
})
