import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Staging frontend config (v0.6) — mirrors the dev config, but:
//   * web port 3001 (dev is 3000, so both can run side by side)
//   * /api proxy target is the staging API on :8001 (dev is :8000)
//   * build output goes to dist-staging (dev dist/ is left untouched)
//
// Build + serve:
//   npm run build -- --mode staging --config vite.config.staging.ts
//   npx vite preview --port 3001 --config vite.config.staging.ts
// The built bundle also bakes in VITE_API_URL from .env.staging, so
// the browser calls the staging API directly (CORS allows
// localhost:3001). The proxy below is the fallback for same-origin
// /api calls.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist-staging',
  },
  server: {
    port: 3001,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 3001,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
})
