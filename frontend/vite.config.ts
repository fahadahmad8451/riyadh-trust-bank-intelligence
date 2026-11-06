import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Riyadh Trust Bank — Enterprise Intelligence Platform (Setup v0.1)
// Dev proxy: /api -> FastAPI on :8000, so the browser never hard-codes a host.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 3000,
  },
})
