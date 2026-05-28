import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api } from '../api/client'

export default function SettingsPage() {
  const [envText, setEnvText] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api
      .get('/config/env')
      .then((r) => {
        const content = r.data.content || r.data.env || r.data || ''
        setEnvText(typeof content === 'string' ? content : JSON.stringify(content, null, 2))
      })
      .catch((err) => toast.error(err.response?.data?.detail || 'Failed to load .env'))
      .finally(() => setLoading(false))
  }, [])

  async function save() {
    setSaving(true)
    try {
      await api.post('/config/env', { content: envText })
      toast.success('.env saved. Restart admin_ui to apply.')
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
          <h1 className="text-2xl font-semibold text-white">Settings</h1>
          <p className="text-sm text-neutral-500 mt-1">Environment variables (.env)</p>
        </div>
        <button
          onClick={save}
          disabled={saving || loading}
          className="bg-accent hover:bg-accent/90 disabled:opacity-50 text-white rounded-md px-4 py-2 text-sm font-medium transition"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>

      <div className="mt-6 bg-panel border border-border rounded-lg p-4">
        {loading ? (
          <div className="p-4 text-sm text-neutral-500">Loading…</div>
        ) : (
          <textarea
            value={envText}
            onChange={(e) => setEnvText(e.target.value)}
            className="w-full h-[60vh] bg-bg border border-border rounded-md p-3 text-sm font-mono text-neutral-300 focus:outline-none focus:border-accent resize-none"
            spellCheck={false}
          />
        )}
      </div>
    </div>
  )
}
