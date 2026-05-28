import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { CheckCircle2, GitBranch, RotateCcw, Trash2, Upload as UploadIcon } from 'lucide-react'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api, asApiError } from '../lib/api'

const CHANNELS = ['stable', 'rc', 'dev'] as const
type Channel = (typeof CHANNELS)[number]

interface Release {
  id: string
  version: string
  channel: Channel
  status: 'draft' | 'published' | 'unpublished'
  file_name: string
  file_sha256: string
  file_size: number
  release_notes: string
  mandatory: boolean
  published_at: string | null
  source: 'manual' | 'github'
  github_release_id: string | null
  created_at: string
  updated_at: string
}

export function ReleasesPage() {
  const qc = useQueryClient()
  const [showUpload, setShowUpload] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['releases'],
    queryFn: async () => (await api.get<{ items: Release[]; total: number }>('/api/super/releases')).data,
  })

  const publish = useMutation({
    mutationFn: async (id: string) => api.post(`/api/super/releases/${id}/publish`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['releases'] }),
    onError: (e) => toast.error(asApiError(e).message),
  })
  const unpublish = useMutation({
    mutationFn: async (id: string) => api.post(`/api/super/releases/${id}/unpublish`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['releases'] }),
    onError: (e) => toast.error(asApiError(e).message),
  })
  const remove = useMutation({
    mutationFn: async (id: string) => api.delete(`/api/super/releases/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['releases'] }),
    onError: (e) => toast.error(asApiError(e).message),
  })
  const syncGithub = useMutation({
    mutationFn: async () =>
      api.post<{ pulled: Release | null; skipped_reason: string | null }>(
        '/api/super/releases/sync-github',
        { channel: 'stable' },
      ),
    onSuccess: (r) => {
      if (r.data.skipped_reason) {
        toast.info(`GitHub sync: ${r.data.skipped_reason}`)
      } else {
        toast.success(`GitHub'dan ${r.data.pulled?.version} olindi`)
      }
      qc.invalidateQueries({ queryKey: ['releases'] })
    },
    onError: (e) => toast.error(asApiError(e).message),
  })

  return (
    <Layout>
      <PageHeader
        title="Kiosk yangilanishlari"
        description="Windows binarni yuklash → publish → har kioskda startup'da auto-update."
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={() => syncGithub.mutate()}
              disabled={syncGithub.isPending}
              className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
            >
              <GitBranch className="w-4 h-4" /> {syncGithub.isPending ? 'Sinkronlash...' : "GitHub'dan sync"}
            </button>
            <button
              onClick={() => setShowUpload(true)}
              className="flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-500"
            >
              <UploadIcon className="w-4 h-4" /> Yangi yuklash
            </button>
          </div>
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
                  <Th>Versiya</Th>
                  <Th>Kanal</Th>
                  <Th>Holat</Th>
                  <Th>Hajmi</Th>
                  <Th>Manba</Th>
                  <Th>Yaratilgan</Th>
                  <Th>Amallar</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {data?.items.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-900/40">
                    <Td>
                      <div className="font-mono font-semibold text-slate-100">{r.version}</div>
                      <div className="text-xs text-slate-500 font-mono">{r.file_name}</div>
                      <div className="text-[10px] text-slate-600 font-mono">sha {r.file_sha256.slice(0, 12)}…</div>
                    </Td>
                    <Td className="text-slate-300">{r.channel}</Td>
                    <Td>
                      <span className={statusClass(r.status)}>{r.status}</span>
                      {r.mandatory && (
                        <span className="ml-1 rounded-full border border-rose-500/40 bg-rose-500/15 px-2 py-0.5 text-[10px] text-rose-300">
                          mandatory
                        </span>
                      )}
                    </Td>
                    <Td className="text-slate-400 font-mono">{formatBytes(r.file_size)}</Td>
                    <Td className="text-slate-400">{r.source}</Td>
                    <Td className="text-slate-500">{new Date(r.created_at).toLocaleString()}</Td>
                    <Td>
                      <div className="flex gap-2">
                        {r.status !== 'published' ? (
                          <button
                            onClick={() => publish.mutate(r.id)}
                            disabled={publish.isPending}
                            className="rounded border border-emerald-700 bg-emerald-900/30 px-2 py-1 text-xs text-emerald-300 hover:bg-emerald-900/50 flex items-center gap-1"
                          >
                            <CheckCircle2 className="w-3 h-3" /> Publish
                          </button>
                        ) : (
                          <button
                            onClick={() => unpublish.mutate(r.id)}
                            disabled={unpublish.isPending}
                            className="rounded border border-amber-700 bg-amber-900/30 px-2 py-1 text-xs text-amber-300 hover:bg-amber-900/50 flex items-center gap-1"
                          >
                            <RotateCcw className="w-3 h-3" /> Unpublish
                          </button>
                        )}
                        <button
                          onClick={() => {
                            if (confirm(`O'chirmoqchimisiz: ${r.version}?`)) remove.mutate(r.id)
                          }}
                          disabled={remove.isPending || r.status === 'published'}
                          className="rounded border border-rose-700 bg-rose-900/20 px-2 py-1 text-xs text-rose-300 hover:bg-rose-900/40 flex items-center gap-1 disabled:opacity-30"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    </Td>
                  </tr>
                ))}
                {(!data || data.items.length === 0) && (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-slate-500">
                      Hech qanday release yo'q. "Yangi yuklash" yoki "GitHub'dan sync" tugmasini bosing.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showUpload && <UploadModal onClose={() => setShowUpload(false)} />}
    </Layout>
  )
}

function UploadModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [version, setVersion] = useState('')
  const [channel, setChannel] = useState<Channel>('stable')
  const [notes, setNotes] = useState('')
  const [mandatory, setMandatory] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const upload = useMutation({
    mutationFn: async () => {
      const f = fileRef.current?.files?.[0]
      if (!f) throw new Error('select a file')
      const fd = new FormData()
      fd.append('file', f)
      fd.append('version', version)
      fd.append('channel', channel)
      fd.append('release_notes', notes)
      fd.append('mandatory', String(mandatory))
      return api.post('/api/super/releases/upload', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },
    onSuccess: () => {
      toast.success('Yuklandi (draft holatida)')
      qc.invalidateQueries({ queryKey: ['releases'] })
      onClose()
    },
    onError: (e) => toast.error(asApiError(e).message),
  })

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="w-[640px] rounded-xl border border-slate-700 bg-slate-900 p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-semibold text-white">Yangi release yuklash</h3>

        <div>
          <label className="block text-xs uppercase tracking-widest text-slate-500 mb-1">Fayl</label>
          <input ref={fileRef} type="file" accept=".exe,.nupkg,.zip" className="text-slate-200 text-sm" />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs uppercase tracking-widest text-slate-500 mb-1">Versiya</label>
            <input
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              placeholder="0.2.0"
              className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-white font-mono"
            />
          </div>
          <div>
            <label className="block text-xs uppercase tracking-widest text-slate-500 mb-1">Kanal</label>
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value as Channel)}
              className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-white"
            >
              {CHANNELS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="block text-xs uppercase tracking-widest text-slate-500 mb-1">Release notes</label>
          <textarea
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-white"
          />
        </div>

        <label className="flex items-center gap-2 text-sm text-slate-200">
          <input type="checkbox" checked={mandatory} onChange={(e) => setMandatory(e.target.checked)} />
          Majburiy (kiosklar voice'ni bloklab yangilanadi)
        </label>

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300">
            Bekarlash
          </button>
          <button
            onClick={() => upload.mutate()}
            disabled={upload.isPending || !version}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {upload.isPending ? 'Yuklanmoqda...' : 'Yuklash'}
          </button>
        </div>
      </div>
    </div>
  )
}

function statusClass(s: Release['status']) {
  const map = {
    draft: 'rounded-full border border-slate-500/40 bg-slate-500/15 text-slate-300 px-2 py-0.5 text-xs',
    published: 'rounded-full border border-emerald-500/40 bg-emerald-500/15 text-emerald-300 px-2 py-0.5 text-xs',
    unpublished: 'rounded-full border border-amber-500/40 bg-amber-500/15 text-amber-300 px-2 py-0.5 text-xs',
  }
  return map[s] ?? map.draft
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-3 text-left text-xs uppercase tracking-widest font-medium">{children}</th>
}
function Td({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <td className={`px-4 py-3 ${className}`}>{children}</td>
}
