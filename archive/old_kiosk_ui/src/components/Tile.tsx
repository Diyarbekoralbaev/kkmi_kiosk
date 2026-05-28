import type { ReactNode } from 'react'

interface Props {
  icon: ReactNode
  label: string
  sublabel?: string
  accent?: string
  onClick: () => void
}

export function Tile({ icon, label, sublabel, accent = '#40b0e0', onClick }: Props) {
  return (
    <button
      onClick={onClick}
      className="group relative flex flex-col items-center justify-center gap-4 w-64 h-64 rounded-3xl border border-white/10 bg-white/[0.04] backdrop-blur-sm overflow-hidden transition-all duration-300 hover:scale-[1.03] hover:border-white/25 active:scale-[0.98]"
      style={{
        boxShadow: `0 8px 40px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.08)`,
      }}
    >
      {/* Hover glow */}
      <div
        className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"
        style={{
          background: `radial-gradient(circle at 50% 30%, ${accent}25, transparent 70%)`,
        }}
      />

      {/* Icon */}
      <div
        className="relative w-24 h-24 rounded-2xl flex items-center justify-center"
        style={{
          background: `${accent}12`,
          border: `1px solid ${accent}35`,
          boxShadow: `0 0 32px ${accent}20`,
        }}
      >
        <div className="text-white" style={{ color: accent }}>
          {icon}
        </div>
      </div>

      {/* Label */}
      <div className="relative text-center px-4">
        <div className="text-white font-semibold text-xl leading-tight tracking-wide">
          {label}
        </div>
        {sublabel && (
          <div className="text-white/55 text-sm mt-1 font-mono tracking-wider uppercase">
            {sublabel}
          </div>
        )}
      </div>

      {/* Bottom accent line */}
      <div
        className="absolute bottom-0 left-[15%] right-[15%] h-px opacity-40 group-hover:opacity-100 transition-opacity"
        style={{
          background: `linear-gradient(90deg, transparent, ${accent}, transparent)`,
        }}
      />
    </button>
  )
}
