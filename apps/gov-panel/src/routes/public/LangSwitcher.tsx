import { SUPPORTED_LANGS, useI18n, type Lang } from './i18n'

const LABELS: Record<Lang, { code: string; alt: string }> = {
  uz: { code: 'UZ', alt: "O'zbekcha" },
  kk: { code: 'KK', alt: 'Қарақалпақша' },
  ru: { code: 'RU', alt: 'Русский' },
}

/**
 * Flag-button language picker for the public-facing pages. SVG flags from
 * /public/flags/*.svg. Active flag gets a thick brand-blue ring; inactive
 * ones desaturated until hover, so the visitor's eye lands on the current
 * choice immediately.
 */
export function LangSwitcher() {
  const { lang, setLang } = useI18n()
  return (
    <div className="flex items-center gap-2" role="group" aria-label="Language">
      {SUPPORTED_LANGS.map((code) => {
        const active = code === lang
        return (
          <button
            key={code}
            type="button"
            onClick={() => setLang(code)}
            aria-pressed={active}
            aria-label={LABELS[code].alt}
            title={LABELS[code].alt}
            className={
              'group relative flex h-8 w-12 items-center justify-center overflow-hidden rounded-md border-2 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 ' +
              (active
                ? 'border-brand shadow-md'
                : 'border-line opacity-60 hover:opacity-100 hover:border-brand/40')
            }
          >
            <img
              src={`/flags/${code}.svg`}
              alt=""
              className="h-full w-full object-cover"
            />
            <span className="sr-only">{LABELS[code].alt}</span>
          </button>
        )
      })}
    </div>
  )
}
