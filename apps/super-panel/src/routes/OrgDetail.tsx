import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { ChevronLeft } from 'lucide-react'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api, asApiError } from '../lib/api'

interface OrgDetail {
  id: string
  slug: string
  name: string
  name_translations: { uz: string; kk: string; ru: string }
  status: string
  max_devices: number
  locale: string
  devices_count: number
  applications_count: number
  address_translations: { uz: string; kk: string; ru: string }
  email: string
  work_hours_translations: { uz: string; kk: string; ru: string }
  helpline_phone: string
  created_at: string
}

const EMPTY_LOCALES = { uz: '', kk: '', ru: '' }

export function OrgDetailPage() {
  const { id } = useParams<{ id: string }>()
  const qc = useQueryClient()
  const [tab, setTab] = useState<'info' | 'devices'>('info')
  const [creds, setCreds] = useState<{ username: string; password: string } | null>(null)

  const orgQ = useQuery({
    queryKey: ['org', id],
    queryFn: async () => (await api.get<OrgDetail>(`/api/super/orgs/${id}`)).data,
    enabled: !!id,
  })

  const regen = useMutation({
    mutationFn: async () =>
      (
        await api.post<{ username: string; password: string }>(
          `/api/super/orgs/${id}/credentials/regenerate`,
        )
      ).data,
    onSuccess: (d) => setCreds(d),
    onError: (err) => toast.error(asApiError(err).message),
  })

  const toggleStatus = useMutation({
    mutationFn: async () =>
      api.patch(`/api/super/orgs/${id}`, {
        status: orgQ.data?.status === 'active' ? 'suspended' : 'active',
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['org', id] }),
    onError: (err) => toast.error(asApiError(err).message),
  })

  if (!orgQ.data) {
    return (
      <Layout>
        <PageHeader title="Loading..." />
      </Layout>
    )
  }
  const org = orgQ.data

  return (
    <Layout>
      <PageHeader
        title={org.name}
        description={`slug: ${org.slug} · ${org.devices_count}/${org.max_devices} devices · ${org.applications_count} applications`}
        actions={
          <>
            <Link to="/orgs" className="text-sm text-slate-400 hover:text-white flex items-center gap-1">
              <ChevronLeft className="w-4 h-4" /> Back
            </Link>
            <button onClick={() => toggleStatus.mutate()} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800">
              {org.status === 'active' ? 'Suspend' : 'Activate'}
            </button>
            <button onClick={() => regen.mutate()} disabled={regen.isPending} className="rounded-lg bg-amber-600 px-3 py-2 text-sm font-semibold text-white hover:bg-amber-500">
              Regenerate creds
            </button>
          </>
        }
      />
      <div className="px-8 pt-4 border-b border-slate-800">
        <div className="flex gap-2">
          {(['info', 'devices'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-2 text-sm rounded-t-lg border-b-2 ${
                tab === t ? 'border-indigo-400 text-white' : 'border-transparent text-slate-400 hover:text-white'
              }`}
            >
              {t === 'info' ? 'Info' : 'Devices'}
            </button>
          ))}
        </div>
      </div>
      <div className="px-8 py-6">
        {tab === 'info' && (
          <div className="space-y-6 max-w-2xl">
            <NameTranslationsEditor org={org} />
            <ContactInfoEditor org={org} />
            <div className="space-y-3 text-sm text-slate-300">
              <Row label="ID">{org.id}</Row>
              <Row label="Slug">{org.slug}</Row>
              <Row label="Status">{org.status}</Row>
              <Row label="Locale">{org.locale}</Row>
              <Row label="Created">{new Date(org.created_at).toLocaleString()}</Row>
              <p className="pt-4 text-xs text-slate-500">
                AI prompt global — barcha orglar uchun bitta. Tahrir uchun <Link to="/ai-defaults" className="text-indigo-400 hover:text-indigo-300">AI Prompt sahifasi</Link>'ga o'ting.
              </p>
            </div>
          </div>
        )}
        {tab === 'devices' && (
          <div className="text-sm text-slate-400">Bu org uchun device ro'yxati kelajakda.</div>
        )}
      </div>
      {creds && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 px-4">
          <div className="w-full max-w-md rounded-xl border border-slate-800 bg-slate-900 p-6 space-y-3">
            <div className="text-lg font-semibold text-white">Yangi kredentsiallar</div>
            <div className="text-sm text-amber-200 bg-amber-500/10 border border-amber-500/40 rounded p-3">
              Faqat 1 marta ko'rsatiladi. Eski paról ishlamaydi.
            </div>
            <code className="block rounded bg-slate-950 border border-slate-800 px-3 py-2 font-mono text-sm">
              {creds.username}
            </code>
            <code className="block rounded bg-slate-950 border border-slate-800 px-3 py-2 font-mono text-sm">
              {creds.password}
            </code>
            <button onClick={() => setCreds(null)} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white w-full">
              Saqladim
            </button>
          </div>
        </div>
      )}
      <style>{`
        .input { width: 100%; background: rgb(15 23 42); border: 1px solid rgb(51 65 85); color: white; padding: 8px 12px; border-radius: 8px; outline: none; }
        .input:focus { border-color: rgb(99 102 241); }
      `}</style>
    </Layout>
  )
}

function NameTranslationsEditor({ org }: { org: OrgDetail }) {
  const qc = useQueryClient()
  const [uz, setUz] = useState(org.name_translations?.uz ?? org.name)
  const [kk, setKk] = useState(org.name_translations?.kk ?? org.name)
  const [ru, setRu] = useState(org.name_translations?.ru ?? org.name)

  // Sync local state if a fresh fetch lands (e.g. after save). Without this,
  // a successful PATCH would invalidate the query and re-render with stale
  // local state until the operator typed something.
  useEffect(() => {
    setUz(org.name_translations?.uz ?? org.name)
    setKk(org.name_translations?.kk ?? org.name)
    setRu(org.name_translations?.ru ?? org.name)
  }, [org.id, org.name_translations?.uz, org.name_translations?.kk, org.name_translations?.ru, org.name])

  const dirty =
    uz.trim() !== (org.name_translations?.uz ?? '') ||
    kk.trim() !== (org.name_translations?.kk ?? '') ||
    ru.trim() !== (org.name_translations?.ru ?? '')

  const save = useMutation({
    mutationFn: async () => {
      const name_translations = { uz: uz.trim(), kk: kk.trim(), ru: ru.trim() }
      await api.patch(`/api/super/orgs/${org.id}`, { name_translations })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['org', org.id] })
      qc.invalidateQueries({ queryKey: ['orgs'] })
      toast.success('Saqlandi')
    },
    onError: (err) => toast.error(asApiError(err).message),
  })

  const allFilled = uz.trim() && kk.trim() && ru.trim()

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/30 p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-slate-400">
          Org nomi (3 til)
        </h2>
        <button
          onClick={() => save.mutate()}
          disabled={!dirty || !allFilled || save.isPending}
          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-40"
        >
          {save.isPending ? '...' : 'Saqlash'}
        </button>
      </div>
      <p className="mb-4 text-xs text-slate-500">
        Kiosk header, talon, va chek — barchasi shu nomlarni ishlatadi. Til
        kiosk UI tilidan tanlanadi. Bo'sh maydon bo'lsa fallback boshqa
        tildan olinadi.
      </p>
      <div className="space-y-3">
        <Field label="Uzbek (uz)">
          <input
            className="input"
            value={uz}
            onChange={(e) => setUz(e.target.value)}
            placeholder="Nukus shahar hokimiyati"
          />
        </Field>
        <Field label="Karakalpak (kk-Cyrl)">
          <input
            className="input"
            value={kk}
            onChange={(e) => setKk(e.target.value)}
            placeholder="Нөкис қаласы ҳәкимияты"
          />
        </Field>
        <Field label="Russian (ru)">
          <input
            className="input"
            value={ru}
            onChange={(e) => setRu(e.target.value)}
            placeholder="Хакимият города Нукуса"
          />
        </Field>
      </div>
    </section>
  )
}

function ContactInfoEditor({ org }: { org: OrgDetail }) {
  const qc = useQueryClient()
  const a = org.address_translations ?? EMPTY_LOCALES
  const h = org.work_hours_translations ?? EMPTY_LOCALES
  const [addrUz, setAddrUz] = useState(a.uz)
  const [addrKk, setAddrKk] = useState(a.kk)
  const [addrRu, setAddrRu] = useState(a.ru)
  const [email, setEmail] = useState(org.email ?? '')
  const [phone, setPhone] = useState(org.helpline_phone ?? '')
  const [hrsUz, setHrsUz] = useState(h.uz)
  const [hrsKk, setHrsKk] = useState(h.kk)
  const [hrsRu, setHrsRu] = useState(h.ru)

  useEffect(() => {
    setAddrUz(a.uz); setAddrKk(a.kk); setAddrRu(a.ru)
    setHrsUz(h.uz); setHrsKk(h.kk); setHrsRu(h.ru)
    setEmail(org.email ?? '')
    setPhone(org.helpline_phone ?? '')
  }, [org.id, a.uz, a.kk, a.ru, h.uz, h.kk, h.ru, org.email, org.helpline_phone])

  const dirty =
    addrUz !== a.uz || addrKk !== a.kk || addrRu !== a.ru ||
    hrsUz !== h.uz || hrsKk !== h.kk || hrsRu !== h.ru ||
    email !== (org.email ?? '') || phone !== (org.helpline_phone ?? '')

  const save = useMutation({
    mutationFn: async () => {
      await api.patch(`/api/super/orgs/${org.id}`, {
        address_translations: { uz: addrUz, kk: addrKk, ru: addrRu },
        work_hours_translations: { uz: hrsUz, kk: hrsKk, ru: hrsRu },
        email: email.trim(),
        helpline_phone: phone.trim(),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['org', org.id] })
      qc.invalidateQueries({ queryKey: ['orgs'] })
      toast.success('Saqlandi')
    },
    onError: (err) => toast.error(asApiError(err).message),
  })

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/30 p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-slate-400">
          Kontakt ma'lumotlari
        </h2>
        <button
          onClick={() => save.mutate()}
          disabled={!dirty || save.isPending}
          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-40"
        >
          {save.isPending ? '...' : 'Saqlash'}
        </button>
      </div>
      <p className="mb-4 text-xs text-slate-500">
        Kiosk &laquo;Контактлар&raquo; sahifasi va footer'dagi yordam liniyasi
        shu maydonlardan oladi. Manzil va ish vaqti 3 tilda alohida — kiosk
        UI tiliga qarab to'g'ri til chiqadi.
      </p>

      <div className="mb-2 text-xs font-semibold uppercase tracking-widest text-slate-500">Manzil</div>
      <div className="space-y-3 mb-5">
        <Field label="Uzbek (uz)">
          <input className="input" value={addrUz} onChange={(e) => setAddrUz(e.target.value)} placeholder="Nukus sh., Berdaq ko'chasi 1" />
        </Field>
        <Field label="Karakalpak (kk-Cyrl)">
          <input className="input" value={addrKk} onChange={(e) => setAddrKk(e.target.value)} placeholder="Нөкис қ., Бердақ гүзәри, 1-үй" />
        </Field>
        <Field label="Russian (ru)">
          <input className="input" value={addrRu} onChange={(e) => setAddrRu(e.target.value)} placeholder="г. Нукус, ул. Бердака 1" />
        </Field>
      </div>

      <div className="mb-2 text-xs font-semibold uppercase tracking-widest text-slate-500">Ish vaqti</div>
      <div className="space-y-3 mb-5">
        <Field label="Uzbek (uz)">
          <input className="input" value={hrsUz} onChange={(e) => setHrsUz(e.target.value)} placeholder="Du–Ju  09:00 – 18:00" />
        </Field>
        <Field label="Karakalpak (kk-Cyrl)">
          <input className="input" value={hrsKk} onChange={(e) => setHrsKk(e.target.value)} placeholder="Дү–Жу 09:00 – 18:00" />
        </Field>
        <Field label="Russian (ru)">
          <input className="input" value={hrsRu} onChange={(e) => setHrsRu(e.target.value)} placeholder="Пн–Пт  09:00 – 18:00" />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Email (yagona)">
          <input
            type="email"
            className="input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="info@nukushokimiyat.uz"
          />
        </Field>
        <Field label="Yordam telefon raqami">
          <input
            className="input"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+998 61 222 33 44"
          />
        </Field>
      </div>
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs uppercase tracking-widest text-slate-500 mb-1">
        {label}
      </span>
      {children}
    </label>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="text-xs uppercase tracking-widest text-slate-500">{label}</span>
      <div className="text-slate-200 font-mono text-xs">{children}</div>
    </div>
  )
}
