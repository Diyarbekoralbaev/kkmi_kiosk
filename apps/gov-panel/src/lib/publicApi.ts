import axios, { AxiosError } from 'axios'

/**
 * Auth-less axios client for the public qabul (booking + verify) routes.
 *
 * Separate from the authenticated `api` client because:
 *   - Adding the Bearer token would leak gov-admin sessions to the public
 *     surface, which the backend's per-org endpoints don't expect.
 *   - 401 retry/refresh is irrelevant — the public endpoints never 401.
 *
 * baseURL is the same (vite proxy forwards /api → backend).
 */
export const publicApi = axios.create({
  baseURL: '/',
  timeout: 30_000,
})

export interface PublicApiError {
  code: string
  message: string
}

export function asPublicError(err: unknown): PublicApiError {
  const e = err as AxiosError<PublicApiError>
  if (e?.response?.data?.code) return e.response.data
  if (e?.response?.status === 429) return { code: 'rate_limited', message: 'Tım kóp soraw, biraz kútiń.' }
  return { code: 'E_UNKNOWN', message: 'Bilinmeytugin qátelik' }
}
