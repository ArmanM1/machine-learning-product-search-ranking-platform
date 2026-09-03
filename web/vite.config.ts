import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const publicBuildConfig = {
  data_mode: process.env.VITE_DATA_MODE ?? 'fixture',
  api_base_url: process.env.VITE_API_BASE_URL ?? '',
  public_run_id: process.env.VITE_PUBLIC_RUN_ID ?? 'run-demo-fixture',
  default_query_id: process.env.VITE_DEFAULT_QUERY_ID ?? 'query-fixture-001',
  baseline_model_id: process.env.VITE_BASELINE_MODEL_ID ?? 'bm25-v1',
  candidate_model_id: process.env.VITE_CANDIDATE_MODEL_ID ?? 'candidate-v1',
}

if (publicBuildConfig.data_mode !== 'fixture' && publicBuildConfig.data_mode !== 'api') {
  throw new Error('VITE_DATA_MODE must be exactly fixture or api')
}

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'public-build-config-attestation',
      generateBundle() {
        this.emitFile({
          type: 'asset',
          fileName: 'build-config.json',
          source: `${JSON.stringify(publicBuildConfig, null, 2)}\n`,
        })
      },
    },
  ],
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
