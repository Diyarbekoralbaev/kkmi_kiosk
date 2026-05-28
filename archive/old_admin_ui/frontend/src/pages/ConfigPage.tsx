import { useEffect, useState } from 'react'
import Editor from '@monaco-editor/react'
import { toast } from 'sonner'
import { api } from '../api/client'

export default function ConfigPage() {
  const [yaml, setYaml] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api
      .get('/config/yaml')
      .then((r) => setYaml(r.data.content || r.data || ''))
      .catch((err) => toast.error(err.response?.data?.detail || 'Failed to load config'))
      .finally(() => setLoading(false))
  }, [])

  async function save() {
    setSaving(true)
    try {
      await api.post('/config/yaml', { content: yaml })
      toast.success('Config saved. Restart admin_ui to apply.')
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">Config</h1>
          <p className="text-sm text-neutral-500 mt-1">Edit ai-agent.yaml</p>
        </div>
        <button
          onClick={save}
          disabled={saving || loading}
          className="bg-accent hover:bg-accent/90 disabled:opacity-50 text-white rounded-md px-4 py-2 text-sm font-medium transition"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>

      <div className="mt-6 bg-panel border border-border rounded-lg overflow-hidden">
        {loading ? (
          <div className="p-8 text-sm text-neutral-500">Loading…</div>
        ) : (
          <Editor
            height="70vh"
            language="yaml"
            theme="vs-dark"
            value={yaml}
            onChange={(v) => setYaml(v || '')}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              fontFamily: 'ui-monospace, Consolas, monospace',
              scrollBeyondLastLine: false,
              tabSize: 2,
            }}
          />
        )}
      </div>
    </div>
  )
}
