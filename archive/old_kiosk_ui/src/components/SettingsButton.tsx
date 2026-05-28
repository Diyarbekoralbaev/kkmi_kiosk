import { Settings } from 'lucide-react'

interface Props {
  onClick: () => void
}

export function SettingsButton({ onClick }: Props) {
  return (
    <button
      onClick={onClick}
      className="w-11 h-11 rounded-full border border-kk-blue/30 bg-kk-ink/40 backdrop-blur hover:bg-kk-blue/20 hover:border-kk-blueLight flex items-center justify-center text-kk-blueLight/80 hover:text-white transition-colors"
      aria-label="Settings"
    >
      <Settings className="w-6 h-6" />
    </button>
  )
}
