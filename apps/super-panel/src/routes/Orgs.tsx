import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Plus } from 'lucide-react'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api, asApiError } from '../lib/api'

interface Org {
  id: string
  slug: string
  name: string
  status: string
  max_devices: number
  locale: string
  devices_count: number
  applications_count: number
  created_at: string
}

interface OrgListResponse {
  items: Org[]
  total: number
}

interface OrgCreatedResponse extends Org {
  credentials_username: string
  credentials_password: string
}

export function OrgsPage() {
  const [showCreate, setShowCreate] = useState(false)
  const [createdCreds, setCreatedCreds] = useState<OrgCreatedResponse | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['orgs'],
    queryFn: async () => (await api.get<OrgListResponse>('/api/super/orgs')).data,
  })

  return (
    <Layout>
      <PageHeader
        title="Organizations"
        description="Hokimiyatlar (orgs). Yangi yarating, kredentsiallarni boshqaring."
        actions={
          <button onClick={() => setShowCreate(true)} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500">
            <Plus className="w-4 h-4" /> Yangi org
          </button>
        }
      />
      <div className="px-8 py-6">
        {isLoading ? (
          <div className="text-slate-400">Loading...</div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <table className="min-w-full divide-y divide-slate-800 text-sm">
              <thead className="bg-slate-900/60 text-slate-400">
                <tr>
                  <Th>Name</Th>
                  <Th>Slug</Th>
                  <Th>Status</Th>
                  <Th>Devices</Th>
                  <Th>Applications</Th>
                  <Th>Created</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {data?.items.map((o) => (
                  <tr key={o.id} className="hover:bg-slate-900/40">
                    <Td>
                      <Link to={`/orgs/${o.id}`} className="font-medium text-indigo-400 hover:text-indigo-300">
                        {o.name}
                      </Link>
                    </Td>
                    <Td className="font-mono text-slate-400">{o.slug}</Td>
                    <Td>
                      <StatusBadge status={o.status} />
                    </Td>
                    <Td>{o.devices_count} / {o.max_devices}</Td>
                    <Td>{o.applications_count}</Td>
                    <Td className="text-slate-400">{new Date(o.created_at).toLocaleDateString()}</Td>
                  </tr>
                ))}
                {(!data || data.items.length === 0) && (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-slate-500">
                      Hech qanday org yo'q. Yangi yaratib ko'ring.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {showCreate && (
        <CreateOrgModal
          onClose={() => setShowCreate(false)}
          onCreated={(c) => {
            setCreatedCreds(c)
            setShowCreate(false)
          }}
        />
      )}
      {createdCreds && (
        <CredentialsModal
          credentials={{ username: createdCreds.credentials_username, password: createdCreds.credentials_password }}
          orgName={createdCreds.name}
          onClose={() => setCreatedCreds(null)}
        />
      )}
    </Layout>
  )
}

function CreateOrgModal({ onClose, onCreated }: { onClose: () => void; onCreated: (c: OrgCreatedResponse) => void }) {
  const qc = useQueryClient()
  const [nameUz, setNameUz] = useState('')
  const [nameKk, setNameKk] = useState('')
  const [nameRu, setNameRu] = useState('')
  const [slug, setSlug] = useState('')
  const [maxDevices, setMaxDevices] = useState(10)
  const [locale, setLocale] = useState<'uz' | 'kk' | 'ru'>('kk')
  const [includeOfficials, setIncludeOfficials] = useState(false)
  const [addrUz, setAddrUz] = useState('')
  const [addrKk, setAddrKk] = useState('')
  const [addrRu, setAddrRu] = useState('')
  const [hrsUz, setHrsUz] = useState('')
  const [hrsKk, setHrsKk] = useState('')
  const [hrsRu, setHrsRu] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')

  const create = useMutation({
    mutationFn: async () => {
      const translations = { uz: nameUz.trim(), kk: nameKk.trim(), ru: nameRu.trim() }
      // Canonical name follows the chosen default locale so the legacy
      // `name` column lands in something the operator picked, not whatever
      // happened to be first.
      const canonical = translations[locale]
      const res = await api.post<OrgCreatedResponse>('/api/super/orgs', {
        name: canonical,
        name_translations: translations,
        slug: slug || undefined,
        max_devices: maxDevices,
        locale,
        include_default_officials: includeOfficials,
        address_translations: { uz: addrUz.trim(), kk: addrKk.trim(), ru: addrRu.trim() },
        work_hours_translations: { uz: hrsUz.trim(), kk: hrsKk.trim(), ru: hrsRu.trim() },
        email: email.trim(),
        helpline_phone: phone.trim(),
      })
      return res.data
    },
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ['orgs'] })
      onCreated(c)
    },
    onError: (err) => toast.error(asApiError(err).message),
  })

  const allFilled = nameUz.trim() && nameKk.trim() && nameRu.trim()

  return (
    <Modal onClose={onClose} title="Yangi org yaratish">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (!allFilled) {
            toast.error('Org nomini 3 tilda ham to\'ldiring (Uz / Kk / Ru).')
            return
          }
          create.mutate()
        }}
        className="space-y-4"
      >
        <div>
          <Label>Org nomi — Uzbek</Label>
          <input
            className="input"
            value={nameUz}
            onChange={(e) => setNameUz(e.target.value)}
            placeholder="Nukus shahar hokimiyati"
            required
          />
        </div>
        <div>
          <Label>Org nomi — Karakalpak (Cyrillic)</Label>
          <input
            className="input"
            value={nameKk}
            onChange={(e) => setNameKk(e.target.value)}
            placeholder="Нөкис қаласы ҳәкимияты"
            required
          />
        </div>
        <div>
          <Label>Org nomi — Russian</Label>
          <input
            className="input"
            value={nameRu}
            onChange={(e) => setNameRu(e.target.value)}
            placeholder="Хакимият города Нукуса"
            required
          />
        </div>
        <div>
          <Label>Default locale (canonical name'ni qaysidan oladi)</Label>
          <select
            className="input"
            value={locale}
            onChange={(e) => setLocale(e.target.value as 'uz' | 'kk' | 'ru')}
          >
            <option value="kk">Karakalpak (kk)</option>
            <option value="uz">Uzbek (uz)</option>
            <option value="ru">Russian (ru)</option>
          </select>
        </div>
        <div>
          <Label>Slug (optional — auto-generated from canonical name)</Label>
          <input
            className="input font-mono"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="tashkent-hokimiyat"
          />
        </div>
        <div>
          <Label>Max devices</Label>
          <input
            type="number"
            min={1}
            max={1000}
            className="input"
            value={maxDevices}
            onChange={(e) => setMaxDevices(parseInt(e.target.value, 10))}
          />
        </div>
        <div className="pt-2 border-t border-slate-800">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">
            Kontakt ma'lumotlari (kiosk Контактлар sahifasi uchun)
          </h3>
          <p className="mb-3 text-xs text-slate-500">
            Bo'sh qoldirishingiz mumkin — keyin OrgDetail sahifasidan to'ldiriladi.
          </p>
        </div>
        <div>
          <Label>Manzil — Uzbek</Label>
          <input className="input" value={addrUz} onChange={(e) => setAddrUz(e.target.value)} placeholder="Nukus sh., Berdaq ko'chasi 1" />
        </div>
        <div>
          <Label>Manzil — Karakalpak</Label>
          <input className="input" value={addrKk} onChange={(e) => setAddrKk(e.target.value)} placeholder="Нөкис қ., Бердақ гүзәри, 1-үй" />
        </div>
        <div>
          <Label>Manzil — Russian</Label>
          <input className="input" value={addrRu} onChange={(e) => setAddrRu(e.target.value)} placeholder="г. Нукус, ул. Бердака 1" />
        </div>
        <div>
          <Label>Ish vaqti — Uzbek</Label>
          <input className="input" value={hrsUz} onChange={(e) => setHrsUz(e.target.value)} placeholder="Du–Ju 09:00 – 18:00" />
        </div>
        <div>
          <Label>Ish vaqti — Karakalpak</Label>
          <input className="input" value={hrsKk} onChange={(e) => setHrsKk(e.target.value)} placeholder="Дү–Жу 09:00 – 18:00" />
        </div>
        <div>
          <Label>Ish vaqti — Russian</Label>
          <input className="input" value={hrsRu} onChange={(e) => setHrsRu(e.target.value)} placeholder="Пн–Пт 09:00 – 18:00" />
        </div>
        <div>
          <Label>Email</Label>
          <input type="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="info@nukushokimiyat.uz" />
        </div>
        <div>
          <Label>Yordam telefon raqami</Label>
          <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+998 61 222 33 44" />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={includeOfficials}
            onChange={(e) => setIncludeOfficials(e.target.checked)}
          />
          Default Nukus officials seedini ham qo'shish (test uchun)
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button disabled={create.isPending || !allFilled} className="btn-primary">
            {create.isPending ? '...' : 'Create'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

function CredentialsModal({
  credentials,
  orgName,
  onClose,
}: {
  credentials: { username: string; password: string }
  orgName: string
  onClose: () => void
}) {
  return (
    <Modal onClose={onClose} title={`Kredentsiallar: ${orgName}`}>
      <div className="space-y-4">
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
          ⚠️ Bu paról FAQAT BIR MARTA ko'rsatiladi. Hoziroq nusxa olib qo'ying. Gap qaytmaydi.
        </div>
        <div>
          <Label>Username</Label>
          <code className="block rounded bg-slate-900 border border-slate-800 px-3 py-2 font-mono text-sm text-slate-200">
            {credentials.username}
          </code>
        </div>
        <div>
          <Label>Password</Label>
          <code className="block rounded bg-slate-900 border border-slate-800 px-3 py-2 font-mono text-sm text-slate-200">
            {credentials.password}
          </code>
        </div>
        <div className="flex justify-end pt-2">
          <button onClick={onClose} className="btn-primary">
            Saqladim, yoping
          </button>
        </div>
      </div>
    </Modal>
  )
}

function Modal({ children, onClose, title }: { children: React.ReactNode; onClose: () => void; title: string }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 px-4">
      <div className="w-full max-w-md rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">{title}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            ✕
          </button>
        </div>
        {children}
      </div>
      <style>{`
        .input { width: 100%; background: rgb(15 23 42); border: 1px solid rgb(51 65 85); color: white; padding: 8px 12px; border-radius: 8px; outline: none; }
        .input:focus { border-color: rgb(99 102 241); }
        .btn-primary { background: rgb(99 102 241); color: white; padding: 8px 14px; border-radius: 8px; font-weight: 600; }
        .btn-primary:hover { background: rgb(79 70 229); }
        .btn-primary:disabled { opacity: 0.5; }
        .btn-secondary { color: rgb(148 163 184); padding: 8px 14px; border-radius: 8px; }
        .btn-secondary:hover { color: white; }
      `}</style>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <span className="block text-xs uppercase tracking-widest text-slate-500 mb-1">{children}</span>
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-3 text-left text-xs uppercase tracking-widest font-medium">{children}</th>
}

function Td({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <td className={`px-4 py-3 ${className}`}>{children}</td>
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === 'active'
      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40'
      : 'bg-amber-500/15 text-amber-300 border-amber-500/40'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs ${cls}`}>{status}</span>
  )
}
