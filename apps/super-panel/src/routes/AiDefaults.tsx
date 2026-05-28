import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api, asApiError } from '../lib/api'

interface SectionDef {
  section_key: string
  content: string
  order: number
}

interface DefaultsResp {
  model: string
  voice: string
  temperature: number
  top_p: number
  top_k: number
  max_output_tokens: number
  response_modalities: string
  default_sections: SectionDef[]
  default_tools: { tool_key: string; enabled: boolean }[]
  default_officials: unknown[]
}

const SECTION_TITLES: Record<string, string> = {
  identity: 'Identity — kim ekani',
  language: 'Language — qaysi tilda gapirish',
  tone: 'Tone — qanday gapirish + greeting',
  tools: 'Tools — tool flow qoidalari',
  guardrails: 'Guardrails — non-negotiable qoidalar',
  knowledge_base: 'Knowledge Base — q&a (pasport, bola puli, yer va h.k.)',
}

export function AiDefaultsPage() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['ai-defaults'],
    queryFn: async () => (await api.get<DefaultsResp>('/api/super/ai-defaults')).data,
  })
  const [draft, setDraft] = useState<DefaultsResp | null>(null)
  useEffect(() => {
    if (data) setDraft(data)
  }, [data])

  // Tuning + tools live on the full PATCH endpoint. Section edits use the
  // per-section endpoint so the request payload stays small and the audit
  // log records which section changed.
  const saveTuning = useMutation({
    mutationFn: async (payload: Partial<DefaultsResp>) => api.patch('/api/super/ai-defaults', payload),
    onSuccess: () => {
      toast.success('Saqlandi')
      qc.invalidateQueries({ queryKey: ['ai-defaults'] })
    },
    onError: (err) => toast.error(asApiError(err).message),
  })

  const saveSection = useMutation({
    mutationFn: async ({ key, content }: { key: string; content: string }) =>
      api.patch(`/api/super/ai-defaults/sections/${key}`, { content }),
    onSuccess: () => {
      toast.success('Saqlandi')
      qc.invalidateQueries({ queryKey: ['ai-defaults'] })
    },
    onError: (err) => toast.error(asApiError(err).message),
  })

  if (isLoading || !draft) {
    return (
      <Layout>
        <PageHeader title="AI Prompt (global)" />
        <div className="px-8 py-6 text-slate-400">Loading...</div>
      </Layout>
    )
  }

  return (
    <Layout>
      <PageHeader
        title="AI Prompt (global)"
        description="Prompt va tuning hamma orglar uchun yagona. O'zgartirgan zahoti keyingi kiosk WS sessiyada yangi prompt qo'llaniladi."
        actions={
          <button
            onClick={() =>
              saveTuning.mutate({
                model: draft.model,
                voice: draft.voice,
                temperature: draft.temperature,
                top_p: draft.top_p,
                top_k: draft.top_k,
                max_output_tokens: draft.max_output_tokens,
                response_modalities: draft.response_modalities,
                default_tools: draft.default_tools,
              })
            }
            disabled={saveTuning.isPending}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
          >
            {saveTuning.isPending ? '...' : 'Tuning saqlash'}
          </button>
        }
      />
      <div className="px-8 py-6 space-y-8 max-w-4xl">
        <Card title="Model & voice">
          <Grid>
            <Labeled label="Model">
              <input className="input" value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} />
            </Labeled>
            <Labeled label="Voice">
              <input className="input" value={draft.voice} onChange={(e) => setDraft({ ...draft, voice: e.target.value })} />
            </Labeled>
            <Labeled label="Temperature">
              <input type="number" step="0.05" min={0} max={2} className="input" value={draft.temperature} onChange={(e) => setDraft({ ...draft, temperature: parseFloat(e.target.value) })} />
            </Labeled>
            <Labeled label="Top-P">
              <input type="number" step="0.05" min={0} max={1} className="input" value={draft.top_p} onChange={(e) => setDraft({ ...draft, top_p: parseFloat(e.target.value) })} />
            </Labeled>
            <Labeled label="Top-K">
              <input type="number" min={1} max={200} className="input" value={draft.top_k} onChange={(e) => setDraft({ ...draft, top_k: parseInt(e.target.value, 10) })} />
            </Labeled>
            <Labeled label="Max output tokens">
              <input type="number" min={64} max={131072} className="input" value={draft.max_output_tokens} onChange={(e) => setDraft({ ...draft, max_output_tokens: parseInt(e.target.value, 10) })} />
            </Labeled>
          </Grid>
        </Card>
        <Card title="Prompt sections">
          <p className="mb-3 text-xs text-slate-500">
            Section'lar promptga ketma-ket (order bo'yicha) yopishtiriladi. Har section alohida saqlanadi.
          </p>
          <div className="space-y-4">
            {[...draft.default_sections]
              .sort((a, b) => a.order - b.order)
              .map((s, idx) => (
                <SectionEditor
                  key={s.section_key}
                  section={s}
                  title={SECTION_TITLES[s.section_key] ?? s.section_key}
                  onChange={(content) => {
                    const arr = [...draft.default_sections]
                    const i = arr.findIndex((x) => x.section_key === s.section_key)
                    if (i >= 0) arr[i] = { ...arr[i], content }
                    setDraft({ ...draft, default_sections: arr })
                  }}
                  onSave={(content) => saveSection.mutate({ key: s.section_key, content })}
                  saving={saveSection.isPending}
                  original={data?.default_sections.find((x) => x.section_key === s.section_key)?.content ?? ''}
                  idx={idx}
                />
              ))}
          </div>
        </Card>
        <Card title="Tools">
          <p className="mb-3 text-xs text-slate-500">Agentga ruxsat berilgan tool chaqiriqlari.</p>
          <div className="grid grid-cols-2 gap-2">
            {draft.default_tools.map((t, idx) => (
              <label key={t.tool_key} className="flex items-center gap-2 text-sm rounded-lg border border-slate-800 px-3 py-2">
                <input
                  type="checkbox"
                  checked={t.enabled}
                  onChange={(e) => {
                    const arr = [...draft.default_tools]
                    arr[idx] = { ...t, enabled: e.target.checked }
                    setDraft({ ...draft, default_tools: arr })
                  }}
                />
                <span className="font-mono text-xs">{t.tool_key}</span>
              </label>
            ))}
          </div>
        </Card>
      </div>
      <style>{`
        .input { width: 100%; background: rgb(15 23 42); border: 1px solid rgb(51 65 85); color: white; padding: 8px 12px; border-radius: 8px; outline: none; }
        .input:focus { border-color: rgb(99 102 241); }
      `}</style>
    </Layout>
  )
}

function SectionEditor({
  section,
  title,
  onChange,
  onSave,
  saving,
  original,
  idx,
}: {
  section: SectionDef
  title: string
  onChange: (content: string) => void
  onSave: (content: string) => void
  saving: boolean
  original: string
  idx: number
}) {
  const dirty = section.content !== original
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500">#{idx + 1}</span>
          <code className="text-xs uppercase tracking-widest text-slate-400">{section.section_key}</code>
          <span className="text-sm text-slate-300">{title}</span>
        </div>
        <button
          onClick={() => onSave(section.content)}
          disabled={!dirty || saving}
          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-40"
        >
          {saving ? '...' : 'Saqlash'}
        </button>
      </div>
      <textarea
        rows={4}
        className="input resize-y font-mono text-xs"
        value={section.content}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/30 p-6">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-slate-400">{title}</h2>
      {children}
    </section>
  )
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs uppercase tracking-widest text-slate-500 mb-1">{label}</span>
      {children}
    </label>
  )
}

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-4">{children}</div>
}
