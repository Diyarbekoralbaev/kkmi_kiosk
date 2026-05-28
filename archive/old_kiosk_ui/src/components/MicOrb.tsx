import { useSession } from '../state/session'
import { kk } from '../strings/kk'
import { Mic, Square, Loader2 } from 'lucide-react'

interface Props {
  onClick: () => void
}

export function MicOrb({ onClick }: Props) {
  const status = useSession((s) => s.status)
  const level = useSession((s) => s.micLevel)

  const active = status === 'active'
  const connecting = status === 'connecting' || status === 'disconnecting'
  const pulse = active ? 1 + Math.min(0.35, level * 2.5) : 1

  const label =
    status === 'idle' || status === 'error'
      ? kk.pressToStart
      : status === 'connecting'
      ? kk.connecting
      : status === 'disconnecting'
      ? kk.disconnecting
      : kk.pressToStop

  return (
    <div className="flex flex-col items-center gap-4">
      <button
        onClick={onClick}
        disabled={connecting}
        className="relative w-28 h-28 rounded-full flex items-center justify-center shadow-2xl transition-transform disabled:opacity-70"
        style={{
          transform: `scale(${pulse})`,
          background: active
            ? 'radial-gradient(circle at 30% 30%, #7ee3ff, #008eb7 55%, #00384a)'
            : 'radial-gradient(circle at 30% 30%, rgba(64,176,224,0.35), rgba(10,30,51,0.85) 65%, rgba(2,8,18,0.9))',
          border: '1px solid rgba(64,176,224,0.5)',
          boxShadow: active
            ? '0 0 60px rgba(64,176,224,0.7), 0 0 120px rgba(0,142,183,0.4), inset 0 0 20px rgba(126,227,255,0.3)'
            : '0 0 30px rgba(0,142,183,0.3), inset 0 0 20px rgba(64,176,224,0.15)',
        }}
      >
        {connecting ? (
          <Loader2 className="w-10 h-10 text-kk-blueLight animate-spin" />
        ) : active ? (
          <Square className="w-9 h-9 text-white" fill="white" />
        ) : (
          <Mic className="w-10 h-10 text-kk-blueLight" />
        )}
        {active && (
          <div
            className="absolute inset-0 rounded-full pointer-events-none"
            style={{
              boxShadow: `0 0 0 ${8 + level * 80}px rgba(0,142,183,0.12)`,
              transition: 'box-shadow 0.08s linear',
            }}
          />
        )}
      </button>
      <div className="text-kk-blueLight/80 text-sm font-mono tracking-[0.25em] uppercase">
        {label}
      </div>
    </div>
  )
}
