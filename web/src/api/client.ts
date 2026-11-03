export interface ErrorBody {
  error?: string
  message?: string
  fields?: Record<string, string>
}

export class ApiError extends Error {
  status: number
  error: string
  fields: Record<string, string>

  constructor(status: number, body: ErrorBody) {
    super(body.message || `Request failed (${status})`)
    this.status = status
    this.error = body.error || 'error'
    this.fields = body.fields || {}
  }
}

let unauthenticated: () => void = () => {}

export function setUnauthenticatedHandler(fn: () => void): void {
  unauthenticated = fn
}

type Init = Omit<RequestInit, 'body'> & { json?: unknown; body?: BodyInit | null }

async function send(path: string, init: Init = {}): Promise<Response> {
  const { json, headers, ...rest } = init
  const h: Record<string, string> = { Accept: 'application/json', ...(headers as Record<string, string>) }
  let body = rest.body
  if (json !== undefined) {
    h['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  }
  const res = await fetch(`/api/v1${path}`, { ...rest, body, headers: h, credentials: 'same-origin' })
  if (!res.ok) {
    let parsed: ErrorBody = {}
    try {
      parsed = await res.json()
    } catch {
      parsed = { message: res.statusText }
    }
    if (res.status === 401 && !path.startsWith('/auth/')) unauthenticated()
    throw new ApiError(res.status, parsed)
  }
  return res
}

/** JSON request helper; resolves to undefined for 204 responses. */
export async function apiFetch<T = unknown>(path: string, init: Init = {}): Promise<T> {
  const res = await send(path, init)
  if (res.status === 204) return undefined as T
  const type = res.headers.get('content-type') || ''
  return (type.includes('json') ? await res.json() : await res.text()) as T
}

/** For binary responses (PDF, PNG, CSV downloads). */
export async function apiBlob(path: string, init: Init = {}): Promise<Blob> {
  return (await send(path, init)).blob()
}

export function openBlob(blob: Blob): void {
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
