import { Power } from 'lucide-react'
import { useSession } from '../state/session'

interface Props {
  onClick: () => void
}

export function EndSessionButton({ onClick }: Props) {
  const status = useSession((s) => s.status)
  const screen = useSession((s) => s.screen)
  // Always visible, but dimmed when idle on home
  const dim = status === 'idle' && screen === 'home'

  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2.5 px-5 py-3 rounded-xl border border-red-500/40 bg-red-950/30 backdrop-blur-sm hover:bg-red-900/50 hover:border-red-400 active:scale-[0.97] transition-all"
      style={{
        opacity: dim ? 0.6 : 1,
      }}
    >
      <Power className="w-5 h-5 text-red-300" />
      <span className="text-red-100 font-medium text-sm tracking-wide">
        Sessiyanı yakunlaw
      </span>
    </button>
  )
}
