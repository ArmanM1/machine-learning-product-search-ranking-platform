import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 4173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/healthz': 'http://127.0.0.1:8000',
      '/readyz': 'http://127.0.0.1:8000',
    },
  },
  preview: {
    port: 4173,
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: './tests/setup.ts',
    css: true,
    globals: true,
    exclude: ['tests/e2e/**', 'node_modules/**', 'dist/**'],
  },
})
