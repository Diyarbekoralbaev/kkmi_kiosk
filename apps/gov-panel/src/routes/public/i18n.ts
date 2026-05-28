import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import strings from './i18n.json'

export type Lang = 'uz' | 'kk' | 'ru'

export const SUPPORTED_LANGS: readonly Lang[] = ['uz', 'kk', 'ru'] as const

// Default = kk to match kiosk + receipt (operator decision). The QR landing
// page however usually arrives from a kiosk that was printed in whatever
// language the visitor picked, so we also persist the choice locally —
// next visit resumes their preferred language without prompting.
const STORAGE_KEY = 'kioskGovPublicLang'
const DEFAULT_LANG: Lang = 'kk'

// `strings` typed loosely because the JSON file includes an `_meta` object
// alongside the keyed entries (glossary reference for translators). At
// runtime we only ever look up by string key.
type StringRow = { uz: string; kk: string; ru: string }
const TABLE = strings as unknown as Record<string, StringRow | unknown>

function isStringRow(v: unknown): v is StringRow {
  if (!v || typeof v !== 'object') return false
  const r = v as Record<string, unknown>
  return typeof r.uz === 'string' && typeof r.kk === 'string' && typeof r.ru === 'string'
}

export function getString(key: string, lang: Lang): string {
  const row = TABLE[key]
  if (!isStringRow(row)) return key
  return row[lang] || row.kk || row.uz || key
}

interface I18nCtx {
  lang: Lang
  setLang: (lang: Lang) => void
  t: (key: string) => string
}

const Ctx = createContext<I18nCtx | null>(null)

function readStoredLang(): Lang {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY)
    if (v && (SUPPORTED_LANGS as readonly string[]).includes(v)) {
      return v as Lang
    }
  } catch {
    /* SSR / privacy-mode browsers throw — fall through */
  }
  return DEFAULT_LANG
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => readStoredLang())

  useEffect(() => {
    // <html lang="..."> for accessibility + screen readers.
    document.documentElement.lang = lang
    try {
      window.localStorage.setItem(STORAGE_KEY, lang)
    } catch {
      /* persistence is best-effort */
    }
  }, [lang])

  const t = useCallback((key: string) => getString(key, lang), [lang])

  const value = useMemo<I18nCtx>(
    () => ({ lang, setLang: setLangState, t }),
    [lang, t],
  )

  return createElement(Ctx.Provider, { value }, children)
}

export function useI18n(): I18nCtx {
  const ctx = useContext(Ctx)
  if (!ctx) {
    throw new Error('useI18n must be used inside <I18nProvider>')
  }
  return ctx
}

const DAY_KEYS = {
  mon: 'dayMon',
  tue: 'dayTue',
  wed: 'dayWed',
  thu: 'dayThu',
  fri: 'dayFri',
  sat: 'daySat',
  sun: 'daySun',
} as const

/**
 * Resolve an ISO weekday code ("mon"…"sun") into its localized form for the
 * current language. Returns the input unchanged for unknown codes so we
 * don't suddenly show empty cells if the backend ever ships a typo.
 */
export function formatDay(iso: string, lang: Lang): string {
  const key = DAY_KEYS[iso as keyof typeof DAY_KEYS]
  if (!key) return iso
  return getString(key, lang)
}

/**
 * Pick the right localized org name from the dict the backend sends
 * (`org_name_translations`). Falls back through kk → uz → the legacy
 * single `org_name` so old backends keep working.
 */
export function pickOrgName(
  translations: Record<string, string> | undefined | null,
  fallback: string,
  lang: Lang,
): string {
  const t = translations ?? {}
  return t[lang] || t.kk || t.uz || t.ru || fallback || ''
}
