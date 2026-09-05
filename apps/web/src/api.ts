const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
let token = sessionStorage.getItem('sports_mate_session') || ''

export class ApiError extends Error {
  constructor(public status: number, message: string, public code = 'request_error') {
    super(message)
  }
}

export function setToken(value: string) {
  token = value
  sessionStorage.setItem('sports_mate_session', value)
}

export function clearToken() {
  token = ''
  sessionStorage.removeItem('sports_mate_session')
}

export function hasToken() {
  return Boolean(token)
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401) clearToken()
    throw new ApiError(response.status, data?.error?.message || 'Не удалось связаться с сервером', data?.error?.code)
  }
  return data as T
}

export async function track(event_name: string, properties: Record<string, string | boolean> = {}, activity_id?: string) {
  if (!hasToken()) return
  await api('/analytics/events', {
    method: 'POST',
    body: JSON.stringify({ event_id: crypto.randomUUID(), event_name, activity_id, properties }),
  }).catch(() => undefined)
}
