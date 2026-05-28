import { OfficialCard } from '../OfficialCard'
import { PageHeader } from '../PageHeader'
import { OFFICIALS, todayIndex } from '../../data/officials'
import { useSession } from '../../state/session'

interface Props {
  onBack: () => void
}

export function ReceptionPage({ onBack }: Props) {
  const today = todayIndex()
  const aiText = useSession((s) => s.currentAiText)

  return (
    <div className="flex-1 flex gap-6 px-6 pb-36 pt-6 min-h-0">
      {/* Left sidebar — robot slot */}
      <div className="w-[320px] shrink-0 flex flex-col gap-4">
        <div className="h-[60%] rounded-2xl border border-white/10 bg-white/[0.02] pointer-events-none" />

        <div
          className="flex-1 min-h-0 p-5 rounded-2xl border border-white/10 overflow-y-auto"
          style={{
            background: 'rgba(8, 28, 50, 0.5)',
            backdropFilter: 'blur(8px)',
          }}
        >
          <div className="text-[10px] tracking-[0.3em] uppercase text-kk-blueLight/70 font-mono mb-2">
            Jardemshi
          </div>
          <div className="text-white/95 text-[15px] leading-relaxed min-h-[3em]">
            {aiText || 'Sóylesiw ushın mikrofondı basıń...'}
          </div>
        </div>
      </div>

      {/* Right side — page content */}
      <div className="flex-1 flex flex-col min-w-0">
        <PageHeader
          title="Qabıllaw kúnleri"
          subtitle="Hákim hám orınbasarları"
          onBack={onBack}
        />

        <div className="mt-6 grid grid-cols-2 xl:grid-cols-3 gap-5 overflow-y-auto pr-2">
          {OFFICIALS.map((o) => (
            <OfficialCard
              key={o.id}
              official={o}
              isToday={o.dayIndex === today}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
