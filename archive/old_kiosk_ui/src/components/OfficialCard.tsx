import type { Official } from '../data/officials'

interface Props {
  official: Official
  isToday: boolean
}

export function OfficialCard({ official, isToday }: Props) {
  return (
    <div
      className="relative flex flex-col rounded-2xl border overflow-hidden transition-all"
      style={{
        borderColor: isToday ? `${official.accent}80` : 'rgba(255,255,255,0.1)',
        background: isToday
          ? `linear-gradient(180deg, ${official.accent}18 0%, ${official.accent}04 100%)`
          : 'rgba(255,255,255,0.03)',
        boxShadow: isToday
          ? `0 0 32px ${official.accent}35, inset 0 1px 0 rgba(255,255,255,0.08)`
          : '0 4px 24px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04)',
      }}
    >
      {isToday && (
        <div
          className="absolute top-3 right-3 px-2.5 py-1 rounded-full text-[10px] font-bold tracking-widest uppercase"
          style={{
            background: official.accent,
            color: '#0a1628',
            boxShadow: `0 0 16px ${official.accent}80`,
          }}
        >
          BÚGIN
        </div>
      )}

      <div className="flex items-center gap-4 p-5">
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center text-xl font-bold shrink-0"
          style={{
            background: `${official.accent}20`,
            border: `1.5px solid ${official.accent}60`,
            color: official.accent,
            textShadow: `0 0 12px ${official.accent}80`,
          }}
        >
          {official.initials}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-white font-semibold text-lg leading-tight truncate">
            {official.fullName}
          </div>
          <div className="text-white/60 text-xs mt-1 font-mono tracking-wider uppercase">
            {official.titleKk}
          </div>
        </div>
      </div>

      <div className="px-5 pb-4 text-white/70 text-sm leading-snug line-clamp-2">
        {official.roleKk}
      </div>

      <div
        className="mt-auto px-5 py-3 flex items-center justify-between border-t"
        style={{ borderColor: 'rgba(255,255,255,0.08)' }}
      >
        <div className="flex flex-col">
          <span className="text-[10px] tracking-widest uppercase text-white/40 font-mono">
            Qabıllaw kúni
          </span>
          <span
            className="font-semibold text-sm capitalize"
            style={{ color: official.accent }}
          >
            {official.dayNameKk}
          </span>
        </div>
        <div className="flex flex-col items-end">
          <span className="text-[10px] tracking-widest uppercase text-white/40 font-mono">
            Waqıt
          </span>
          <span className="font-mono font-semibold text-white text-sm">
            {official.timeKk}
          </span>
        </div>
      </div>
    </div>
  )
}
