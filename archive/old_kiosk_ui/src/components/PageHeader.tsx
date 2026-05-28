import { ArrowLeft } from 'lucide-react'

interface Props {
  title: string
  subtitle?: string
  onBack: () => void
}

export function PageHeader({ title, subtitle, onBack }: Props) {
  return (
    <div className="flex items-center gap-5">
      <button
        onClick={onBack}
        className="w-12 h-12 rounded-xl border border-white/15 bg-white/[0.04] hover:bg-white/10 hover:border-white/30 flex items-center justify-center text-white/80 hover:text-white transition-all active:scale-95"
      >
        <ArrowLeft className="w-6 h-6" />
      </button>
      <div>
        <div className="text-white text-2xl font-semibold leading-tight">
          {title}
        </div>
        {subtitle && (
          <div className="text-kk-blueLight/70 text-sm font-mono tracking-[0.2em] uppercase mt-0.5">
            {subtitle}
          </div>
        )}
      </div>
    </div>
  )
}
