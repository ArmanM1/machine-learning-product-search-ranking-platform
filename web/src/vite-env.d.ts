/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DATA_MODE?: 'fixture' | 'api'
  readonly VITE_API_BASE_URL?: string
  readonly VITE_PUBLIC_RUN_ID?: string
  readonly VITE_DEFAULT_QUERY_ID?: string
  readonly VITE_BASELINE_MODEL_ID?: string
  readonly VITE_CANDIDATE_MODEL_ID?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
