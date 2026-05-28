import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { CheckCircle2, XCircle, Clock, AlertCircle } from 'lucide-react'
import { publicApi, asPublicError } from '../../lib/publicApi'
import { pickOrgName, useI18n } from './i18n'
import { LangSwitcher } from './LangSwitcher'

interface VerifyResponse {
  org_name: string
  org_name_translations?: Record<string, string>
  reference_no: string
  status: 'pending' | 'completed' | 'cancelled' | 'no_show'
  topic: string
  phone_masked: string
  source: 'kiosk' | 'online'
  created_at: string
}

export default function QabulVerifyPage() {
  const { token = '' } = useParams<{ token: string }>()
  const { lang, t } = useI18n()

  const { data, isLoading, error } = useQuery({
    queryKey: ['public-verify', token],
    queryFn: async () =>
      (
        await publicApi.get<VerifyResponse>(
          `/api/public/appointments/verify/${token}`,
        )
      ).data,
    retry: false,
  })

  if (isLoading) {
    return (
      <Shell>
        <div className="px-6 py-12 text-center text-ink-muted">
          {t('verifyLoading')}
        </div>
      </Shell>
    )
  }

  if (error || !data) {
    return (
      <Shell>
        <div className="mx-auto max-w-xl rounded-tile border border-rose-200 bg-rose-50 p-8">
          <XCircle className="mb-3 h-10 w-10 text-rose-600" />
          <div className="text-lg font-bold text-rose-700">
            {t('verifyNotFoundTitle')}
          </div>
          <div className="mt-2 text-sm text-rose-700/80">
            {asPublicError(error).message || t('verifyNotFoundDesc')}
          </div>
        </div>
      </Shell>
    )
  }

  const orgTitle = pickOrgName(data.org_name_translations, data.org_name, lang)

  return (
    <Shell title={orgTitle}>
      <div className="mx-auto max-w-2xl space-y-6">
        <StatusBanner status={data.status} />

        <div className="overflow-hidden rounded-tile border border-line bg-card shadow-card">
          <div className="bg-brand px-8 py-6 text-center text-white">
            <div className="text-xs font-semibold uppercase tracking-widest text-white/70">
              {t('talonHeader')}
            </div>
            <div className="mt-2 text-4xl font-bold tracking-wide">
              {data.reference_no}
            </div>
            <div className="mt-1 text-xs font-medium uppercase tracking-widest text-white/70">
              {t('queueLabel')}
            </div>
          </div>

          <div className="space-y-1 px-8 py-6">
            <Row label={t('rowPhone')} value={data.phone_masked} mono />
            <Row label={t('rowTopic')} value={data.topic} />
            <Row
              label={t('verifySourceLabel')}
              value={
                data.source === 'kiosk'
                  ? t('verifySourceKiosk')
                  : t('verifySourceOnline')
              }
            />
            <Row
              label={t('verifyCreatedLabel')}
              value={new Date(data.created_at).toLocaleString()}
            />
          </div>
        </div>
      </div>
    </Shell>
  )
}

function StatusBanner({ status }: { status: VerifyResponse['status'] }) {
  const { t } = useI18n()
  if (status === 'completed') {
    return (
      <Banner
        icon={<CheckCircle2 className="h-6 w-6" />}
        cls="border-emerald-200 bg-emerald-50 text-emerald-700"
        title={t('verifyStatusCompletedTitle')}
        desc={t('verifyStatusCompletedDesc')}
      />
    )
  }
  if (status === 'cancelled') {
    return (
      <Banner
        icon={<XCircle className="h-6 w-6" />}
        cls="border-line bg-surface text-ink-muted"
        title={t('verifyStatusCancelledTitle')}
        desc={t('verifyStatusCancelledDesc')}
      />
    )
  }
  if (status === 'no_show') {
    return (
      <Banner
        icon={<AlertCircle className="h-6 w-6" />}
        cls="border-rose-200 bg-rose-50 text-rose-700"
        title={t('verifyStatusNoShowTitle')}
        desc={t('verifyStatusNoShowDesc')}
      />
    )
  }
  return (
    <Banner
      icon={<Clock className="h-6 w-6" />}
      cls="border-accent/40 bg-tile-accent text-accent-dark"
      title={t('verifyStatusPendingTitle')}
      desc={t('verifyStatusPendingDesc')}
    />
  )
}

function Banner({
  icon,
  cls,
  title,
  desc,
}: {
  icon: ReactNode
  cls: string
  title: string
  desc: string
}) {
  return (
    <div
      className={`flex items-start gap-3 rounded-card border px-5 py-4 ${cls}`}
    >
      {icon}
      <div>
        <div className="font-bold">{title}</div>
        <div className="text-sm opacity-80">{desc}</div>
      </div>
    </div>
  )
}

function Row({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="flex justify-between gap-4 py-1.5 text-sm">
      <span className="text-ink-muted">{label}</span>
      <span
        className={'text-right text-ink ' + (mono ? 'font-mono' : 'font-medium')}
      >
        {value}
      </span>
    </div>
  )
}

function Shell({
  title,
  children,
}: {
  title?: string
  children: ReactNode
}) {
  const { t } = useI18n()
  return (
    <div className="flex min-h-screen flex-col bg-surface text-ink">
      <header className="border-b border-line bg-gradient-to-b from-white to-surface px-6 py-5">
        <div className="mx-auto flex max-w-5xl items-center gap-4">
          <img
            src="/gerb.png"
            alt=""
            className="h-12 w-12 shrink-0 object-contain"
          />
          <div className="min-w-0 flex-1">
            <div className="text-[11px] font-semibold uppercase tracking-widest text-ink-muted">
              {t('regionLabel')}
            </div>
            <div className="truncate text-lg font-bold text-brand">
              {title ?? t('orgDefault')}
            </div>
          </div>
          <LangSwitcher />
        </div>
      </header>
      <main className="flex-1 px-6 py-10">{children}</main>
      <footer className="bg-brand-dark px-6 py-4 text-center text-xs text-white/70">
        © {new Date().getFullYear()} {t('footer')}
      </footer>
    </div>
  )
}
