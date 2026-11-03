import { useSession } from '../stores/session'

export class ApiError extends Error {
  status: number
  error: string
  fields: Record<string, string>

  constructor(status: number, error: string, message: string, fields: Record<string, string> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.error = error
    this.fields = fields
  }
}

export type ApiInit = RequestInit & { json?: unknown }

async function toApiError(res: Response): Promise<ApiError> {
  let payload: { error?: string; message?: string; fields?: Record<string, string> } = {}
  try {
    payload = await res.json()
  } catch {
    // non-JSON error body (e.g. a proxy page); fall back to the status text
  }
  if (res.status === 401) useSession().onUnauthenticated()
  return new ApiError(
    res.status,
    payload.error ?? 'error',
    payload.message ?? (res.statusText || `HTTP ${res.status}`),
    payload.fields ?? {},
  )
}

/** Like `apiFetch` but resolves to the response body as a Blob (e.g. a generated PDF). */
export async function apiFetchBlob(path: string, init: ApiInit = {}): Promise<Blob> {
  const { json, headers: initHeaders, ...rest } = init
  const headers = new Headers(initHeaders)
  let body = rest.body
  if (json !== undefined) {
    headers.set('content-type', 'application/json')
    body = JSON.stringify(json)
  }
  const res = await fetch(`/api/v1${path}`, { ...rest, headers, body, credentials: 'same-origin' })
  if (!res.ok) throw await toApiError(res)
  return res.blob()
}

/** Fetch `/api/v1{path}`; throws `ApiError` for any non-2xx response. */
export async function apiFetch<T>(path: string, init: ApiInit = {}): Promise<T> {
  const { json, headers: initHeaders, ...rest } = init
  const headers = new Headers(initHeaders)
  let body = rest.body
  if (json !== undefined) {
    headers.set('content-type', 'application/json')
    body = JSON.stringify(json)
  }
  const res = await fetch(`/api/v1${path}`, { ...rest, headers, body, credentials: 'same-origin' })

  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  const type = res.headers.get('content-type') ?? ''
  return (type.includes('json') ? res.json() : res.text()) as Promise<T>
}
