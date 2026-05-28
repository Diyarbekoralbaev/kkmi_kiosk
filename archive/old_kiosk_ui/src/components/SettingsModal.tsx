import { useEffect, useState } from 'react'
import { kk } from '../strings/kk'
import { X } from 'lucide-react'

interface Props {
  open: boolean
  onClose: () => void
}

const AVATARS = [
  { name: 'avatarsdk (erkek)', url: 'https://cdn.jsdelivr.net/gh/met4citizen/TalkingHead@main/avatars/avatarsdk.glb' },
  { name: 'avaturn (erkek)', url: 'https://cdn.jsdelivr.net/gh/met4citizen/TalkingHead@main/avatars/avaturn.glb' },
  { name: 'brunette (hayal)', url: 'https://cdn.jsdelivr.net/gh/met4citizen/TalkingHead@main/avatars/brunette.glb' },
  { name: 'mpfb (erkek)', url: 'https://cdn.jsdelivr.net/gh/met4citizen/TalkingHead@main/avatars/mpfb.glb' },
  { name: 'vroid (anime)', url: 'https://cdn.jsdelivr.net/gh/met4citizen/TalkingHead@main/avatars/vroid.glb' },
]

export function SettingsModal({ open, onClose }: Props) {
  const [mics, setMics] = useState<MediaDeviceInfo[]>([])
  const [micId, setMicId] = useState<string>(() => localStorage.getItem('kiosk_mic_id') || '')
  const [wsUrl, setWsUrl] = useState<string>(() => localStorage.getItem('kiosk_ws_url') || '')
  const [avatar, setAvatar] = useState<string>(() => localStorage.getItem('kiosk_avatar_url') || AVATARS[0].url)

  useEffect(() => {
    if (!open) return
    ;(async () => {
      try {
        await navigator.mediaDevices.getUserMedia({ audio: true }).then((s) => {
          s.getTracks().forEach((t) => t.stop())
        })
      } catch {
        // ignore
      }
      const devs = await navigator.mediaDevices.enumerateDevices()
      setMics(devs.filter((d) => d.kind === 'audioinput'))
    })()
  }, [open])

  if (!open) return null

  const save = () => {
    if (micId) localStorage.setItem('kiosk_mic_id', micId)
    else localStorage.removeItem('kiosk_mic_id')
    if (wsUrl) localStorage.setItem('kiosk_ws_url', wsUrl)
    else localStorage.removeItem('kiosk_ws_url')
    localStorage.setItem('kiosk_avatar_url', avatar)
    onClose()
    // Reload to re-init avatar/audio with new settings
    location.reload()
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-8 relative"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-kk-inkSoft hover:text-kk-ink"
        >
          <X className="w-5 h-5" />
        </button>
        <h2 className="text-2xl font-semibold text-kk-ink mb-6">{kk.settings}</h2>

        <div className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-kk-inkSoft mb-2">
              {kk.mic}
            </label>
            <select
              value={micId}
              onChange={(e) => setMicId(e.target.value)}
              className="w-full px-4 py-3 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-kk-blue"
            >
              <option value="">(default)</option>
              {mics.map((m) => (
                <option key={m.deviceId} value={m.deviceId}>
                  {m.label || m.deviceId.slice(0, 10)}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-kk-inkSoft mb-2">
              {kk.avatar}
            </label>
            <select
              value={avatar}
              onChange={(e) => setAvatar(e.target.value)}
              className="w-full px-4 py-3 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-kk-blue"
            >
              {AVATARS.map((a) => (
                <option key={a.url} value={a.url}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-kk-inkSoft mb-2">
              {kk.serverUrl}
            </label>
            <input
              type="text"
              placeholder="ws://localhost:3003/ws/kiosk/voice"
              value={wsUrl}
              onChange={(e) => setWsUrl(e.target.value)}
              className="w-full px-4 py-3 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-kk-blue"
            />
          </div>
        </div>

        <div className="flex gap-3 mt-8">
          <button
            onClick={onClose}
            className="flex-1 px-5 py-3 rounded-lg border border-gray-200 text-kk-inkSoft hover:bg-gray-50"
          >
            {kk.cancel}
          </button>
          <button
            onClick={save}
            className="flex-1 px-5 py-3 rounded-lg bg-kk-blue text-white font-medium hover:bg-kk-blueLight"
          >
            {kk.save}
          </button>
        </div>
      </div>
    </div>
  )
}
