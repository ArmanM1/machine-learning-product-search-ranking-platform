import { useCallback, useEffect, useReducer, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiClientError } from './client'

export type PreviewState = 'loading' | 'empty' | 'error' | 'not-ready' | 'conflict' | null

export type ResourceState<T> =
  | { status: 'loading' }
  | { status: 'empty' }
  | { status: 'success'; data: T }
  | { status: 'error'; error: ApiClientError }
  | { status: 'not-ready'; error: ApiClientError }
  | { status: 'conflict'; error: ApiClientError }

type Action<T> =
  | { type: 'load' }
  | { type: 'resolve'; value: T }
  | { type: 'reject'; error: ApiClientError }
  | { type: 'preview'; state: Exclude<PreviewState, null | 'loading'> }

function isEmpty(value: unknown): boolean {
  if (Array.isArray(value)) return value.length === 0
  return value === null || value === undefined
}

function reducer<T>(state: ResourceState<T>, action: Action<T>): ResourceState<T> {
  switch (action.type) {
    case 'load':
      return { status: 'loading' }
    case 'resolve':
      return isEmpty(action.value) ? { status: 'empty' } : { status: 'success', data: action.value }
    case 'reject':
      if (action.error.status === 409 && action.error.code.includes('ready')) {
        return { status: 'not-ready', error: action.error }
      }
      if (action.error.status === 409) return { status: 'conflict', error: action.error }
      return { status: 'error', error: action.error }
    case 'preview': {
      const messages = {
        empty: new ApiClientError('No evidence is available for this view.', 200, 'empty'),
        error: new ApiClientError('The evidence service could not complete this request.', 500, 'preview_error', 'preview-request'),
        'not-ready': new ApiClientError('The promoted model is still loading.', 409, 'model_not_ready'),
        conflict: new ApiClientError('This evidence version conflicts with the promoted manifest.', 409, 'artifact_conflict'),
      }
      if (action.state === 'empty') return { status: 'empty' }
      if (action.state === 'not-ready') return { status: 'not-ready', error: messages[action.state] }
      if (action.state === 'conflict') return { status: 'conflict', error: messages[action.state] }
      return { status: 'error', error: messages[action.state] }
    }
    default:
      return state
  }
}

export function usePreviewState(): PreviewState {
  const [searchParams] = useSearchParams()
  const value = searchParams.get('state')
  if (value === 'loading' || value === 'empty' || value === 'error' || value === 'not-ready' || value === 'conflict') {
    return value
  }
  return null
}

export function useApiResource<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  requestKey: string,
): ResourceState<T> & { retry: () => void } {
  const previewState = usePreviewState()
  const [retryKey, retry] = useReducer((value: number) => value + 1, 0)
  const [state, dispatch] = useReducer(reducer<T>, { status: 'loading' })
  const loaderRef = useRef(loader)

  useEffect(() => {
    loaderRef.current = loader
  }, [loader])

  useEffect(() => {
    if (previewState === 'loading') {
      dispatch({ type: 'load' })
      return
    }
    if (previewState) {
      dispatch({ type: 'preview', state: previewState })
      return
    }

    const controller = new AbortController()
    dispatch({ type: 'load' })
    loaderRef.current(controller.signal).then(
      (value) => dispatch({ type: 'resolve', value }),
      (error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        const apiError = error instanceof ApiClientError
          ? error
          : new ApiClientError('An unexpected interface error occurred.', 500, 'unexpected_error')
        dispatch({ type: 'reject', error: apiError })
      },
    )
    return () => controller.abort()
  }, [previewState, requestKey, retryKey])

  const retryRequest = useCallback(() => retry(), [])
  return { ...state, retry: retryRequest }
}
