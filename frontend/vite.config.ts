import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The browser calls /api; Vite forwards it to the API (API_URL, default :8000), so no CORS setup is needed.
const api = process.env.API_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  server: {
    port: Number(process.env.WEB_PORT ?? 5173),
    strictPort: true,
    // xfwd: the API sees the browser's address (X-Forwarded-For), so per-client rate limits aren't shared by everyone
    proxy: { '/api': { target: api, changeOrigin: true, xfwd: true, rewrite: (p) => p.replace(/^\/api/, '') } },
  },
})
