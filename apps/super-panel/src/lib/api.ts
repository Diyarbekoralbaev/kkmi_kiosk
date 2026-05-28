import axios, { AxiosError } from 'axios'

const STORAGE_KEY = 'joqari_kenes_super_tokens'

export interface Tokens {
  access_token: string
  refresh_token: string
}

export function loadTokens(): Tokens | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as Tokens
  } catch {
    return null
  }
}

export function saveTokens(t: Tokens) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(t))
}

export function clearTokens() {
  localStorage.removeItem(STORAGE_KEY)
}

export const api = axios.create({
  baseURL: '/',
  timeout: 30_000,
})

api.interceptors.request.use((config) => {
  const t = loadTokens()
  if (t?.access_token) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${t.access_token}`
  }
  return config
})

let refreshing: Promise<Tokens | null> | null = null

async function tryRefresh(): Promise<Tokens | null> {
  const t = loadTokens()
  if (!t?.refresh_token) return null
  try {
    const res = await axios.post('/api/auth/refresh', {
      refresh_token: t.refresh_token,
    })
    const next: Tokens = {
      access_token: res.data.access_token,
      refresh_token: res.data.refresh_token,
    }
    saveTokens(next)
    return next
  } catch {
    clearTokens()
    return null
  }
}

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as (typeof error.config & { _retried?: boolean }) | undefined
    if (error.response?.status === 401 && original && !original._retried) {
      original._retried = true
      refreshing = refreshing ?? tryRefresh().finally(() => {
        refreshing = null
      })
      const next = await refreshing
      if (next?.access_token) {
        original.headers = original.headers ?? {}
        ;(original.headers as Record<string, string>).Authorization = `Bearer ${next.access_token}`
        return api.request(original)
      }
    }
    return Promise.reject(error)
  },
)

export interface ApiError {
  code: string
  message: string
  correlation_id?: string
}

export function asApiError(err: unknown): ApiError {
  const e = err as AxiosError<ApiError>
  if (e?.response?.data?.code) return e.response.data
  return { code: 'E_UNKNOWN', message: 'Bilinmeytugin qátelik' }
}
