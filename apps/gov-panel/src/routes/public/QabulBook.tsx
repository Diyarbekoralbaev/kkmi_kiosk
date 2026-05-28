import { useState, type ReactNode } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { ChevronRight, Printer } from 'lucide-react'
import { publicApi, asPublicError } from '../../lib/publicApi'
import { Avatar, Button, Card, FormField, Input, Textarea } from '../../components/ui'
import { formatDay, pickOrgName, useI18n } from './i18n'
import { LangSwitcher } from './LangSwitcher'

interface PublicOfficial {
  id: string
  name: string
  position: string
  responsibilities: string
  reception_day: string
  reception_time: string
  order: number
  has_photo?: boolean
}

interface PublicOfficialsResponse {
  org_name: string
  org_slug: string
  org_name_translations?: Record<string, string>
  officials: PublicOfficial[]
}

interface BookingResponse {
  appointment_id: string
  official_name: string
  official_position: string
  queue_number: number
  scheduled_date: string
  scheduled_date_human: string
  reception_time: string
  phone_masked: string
  topic: string
  verification_token: string
  verification_url: string
  receipt_pdf_url: string
}

export default function QabulBookPage() {
  const { slug = '' } = useParams<{ slug: string }>()
  const { lang, t } = useI18n()
  const [selected, setSelected] = useState<PublicOfficial | null>(null)
  const [topic, setTopic] = useState('')
  const [phone, setPhone] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<BookingResponse | null>(null)

  const { data, isLoading, error: queryError } = useQuery({
    queryKey: ['public-officials', slug],
    queryFn: async () =>
      (
        await publicApi.get<PublicOfficialsResponse>(
          `/api/public/orgs/${slug}/officials`,
        )
      ).data,
    retry: false,
  })

  const book = useMutation({
    mutationFn: async () => {
      if (!selected) throw new Error('select an official')
      const r = await publicApi.post<BookingResponse>(
        `/api/public/orgs/${slug}/appointments`,
        {
          official_id: selected.id,
          topic: topic.trim(),
          phone: phone.trim(),
        },
      )
      return r.data
    },
    onSuccess: (resp) => {
      setSuccess(resp)
      setError(null)
    },
    onError: (err) => {
      setError(asPublicError(err).message)
    },
  })

  const orgTitle = data
    ? pickOrgName(data.org_name_translations, data.org_name, lang)
    : ''

  if (isLoading) {
    return (
      <PublicShell>
        <div className="px-6 py-12 text-center text-ink-muted">{t('loading')}</div>
      </PublicShell>
    )
  }

  if (queryError || !data) {
    return (
      <PublicShell>
        <div className="mx-auto max-w-xl rounded-card border border-rose-200 bg-rose-50 p-6 text-center text-rose-700">
          {t('bookOrgNotFound')}
        </div>
      </PublicShell>
    )
  }

  if (success) {
    return (
      <PublicShell title={orgTitle}>
        <SuccessCard booking={success} />
      </PublicShell>
    )
  }

  return (
    <PublicShell title={orgTitle}>
      <div className="mx-auto max-w-4xl space-y-8">
        <div className="text-center">
          <h2 className="text-3xl font-bold text-brand">{t('bookHeading')}</h2>
          <p className="mt-2 text-base text-ink-muted">{t('bookSubheading')}</p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {data.officials.map((o) => {
            const active = selected?.id === o.id
            return (
              <button
                key={o.id}
                onClick={() => setSelected(o)}
                className={
                  'group flex w-full items-center gap-4 rounded-tile border-2 bg-card p-5 text-left transition shadow-card hover:border-brand/40 ' +
                  (active ? 'border-brand bg-brand/5' : 'border-line')
                }
              >
                <Avatar
                  src={o.has_photo ? `/api/public/officials/${o.id}/photo.jpg` : null}
                  name={o.name}
                  size={88}
                />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="text-lg font-bold text-ink">{o.name}</div>
                  <div className="text-sm font-semibold text-accent-dark">
                    {o.position}
                  </div>
                  {o.responsibilities && (
                    <div className="line-clamp-2 text-xs text-ink-muted">
                      {o.responsibilities}
                    </div>
                  )}
                  {(o.reception_day || o.reception_time) && (
                    <div className="mt-1 text-xs text-ink-muted">
                      {formatDay(o.reception_day, lang)} · {o.reception_time}
                    </div>
                  )}
                </div>
                <ChevronRight
                  className={
                    'h-6 w-6 shrink-0 transition ' +
                    (active ? 'text-brand' : 'text-ink-muted')
                  }
                />
              </button>
            )
          })}
        </div>

        {selected && (
          <Card padding="loose">
            <div className="space-y-5">
              <div className="flex items-center gap-3 border-b border-line pb-4">
                <Avatar
                  src={selected.has_photo ? `/api/public/officials/${selected.id}/photo.jpg` : null}
                  name={selected.name}
                  size={56}
                />
                <div>
                  <div className="text-lg font-bold text-ink">{selected.name}</div>
                  <div className="text-sm text-accent-dark">
                    {selected.position}
                  </div>
                </div>
              </div>

              <FormField label={t('bookIssueLabel')}>
                <Textarea
                  rows={3}
                  placeholder={t('bookIssuePlaceholder')}
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                />
              </FormField>

              <FormField label={t('bookPhoneLabel')}>
                <Input
                  type="tel"
                  placeholder="+998901234567"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
              </FormField>

              {error && (
                <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">
                  {error}
                </div>
              )}

              <div className="flex justify-end gap-2">
                <Button
                  variant="ghost"
                  onClick={() => {
                    setSelected(null)
                    setTopic('')
                    setPhone('')
                    setError(null)
                  }}
                >
                  {t('bookCancel')}
                </Button>
                <Button
                  size="lg"
                  onClick={() => book.mutate()}
                  loading={book.isPending}
                  disabled={topic.trim().length < 2 || phone.trim().length < 4}
                >
                  {book.isPending ? t('bookSubmitting') : t('bookSubmit')}
                </Button>
              </div>
            </div>
          </Card>
        )}
      </div>
    </PublicShell>
  )
}

function SuccessCard({ booking }: { booking: BookingResponse }) {
  const { t } = useI18n()
  return (
    <div className="mx-auto max-w-xl">
      <div className="overflow-hidden rounded-tile border border-line bg-card shadow-card">
        <div className="bg-brand px-8 py-6 text-center text-white">
          <div className="text-xs font-semibold uppercase tracking-widest text-white/70">
            {t('talonHeader')}
          </div>
          <div className="mt-2 text-6xl font-bold tabular-nums tracking-wide">
            #{String(booking.queue_number).padStart(3, '0')}
          </div>
          <div className="mt-1 text-xs font-medium uppercase tracking-widest text-white/70">
            {t('queueLabel')}
          </div>
        </div>
        <div className="space-y-1 px-8 py-6">
          <Row label={t('rowOfficial')} value={booking.official_name} />
          <Row label={t('rowPosition')} value={booking.official_position} />
          <Row label={t('rowDate')} value={booking.scheduled_date_human} />
          <Row label={t('rowTime')} value={booking.reception_time} />
          <Row label={t('rowPhone')} value={booking.phone_masked} mono />
          <Row label={t('rowTopic')} value={booking.topic} />
        </div>
        <div className="flex flex-col items-center gap-3 border-t border-line bg-surface/60 px-8 py-6">
          <div className="rounded-card bg-white p-2 shadow-sm">
            <img
              src={`/api/public/appointments/qr/${booking.verification_token}.png`}
              alt="QR"
              width={220}
              height={220}
            />
          </div>
          <div className="text-center text-xs text-ink-muted">{t('bookQrHint')}</div>
          <a
            href={booking.receipt_pdf_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-lg bg-brand px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-brand-dark"
          >
            <Printer className="h-4 w-4" />
            {t('bookPdfButton')}
          </a>
        </div>
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

function PublicShell({
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
