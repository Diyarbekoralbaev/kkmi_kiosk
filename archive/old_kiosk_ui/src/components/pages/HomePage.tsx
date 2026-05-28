import { CalendarDays, FileEdit, PhoneCall } from 'lucide-react'
import { Tile } from '../Tile'
import type { Screen } from '../../data/screens'
import { useSession } from '../../state/session'

interface Props {
  onNavigate: (s: Screen) => void
}

export function HomePage({ onNavigate }: Props) {
  const status = useSession((s) => s.status)
  const aiText = useSession((s) => s.currentAiText)

  const hint =
    status === 'idle'
      ? 'Basla ushın "Mikrofondı qoslaw" túymesin basıń yaki ekranda tańlań'
      : status === 'connecting'
      ? 'Jalanıp atır...'
      : aiText ||
        'Qalay járdem berewim kerek — qabıllaw, murájaat yaki baylanıs?'

  return (
    <div className="relative flex-1 flex flex-col items-center justify-center gap-10 px-6 pb-40 pt-6">
      {/* Robot lives at the top center — absolute on the parent */}
      <div className="h-[44%] w-full max-w-3xl pointer-events-none" />

      {/* Speech bubble / hint */}
      <div
        className="max-w-3xl text-center px-8 py-4 rounded-2xl border border-white/10"
        style={{
          background: 'rgba(8, 28, 50, 0.6)',
          backdropFilter: 'blur(10px)',
          boxShadow: '0 12px 48px rgba(0,0,0,0.3)',
          minHeight: '72px',
        }}
      >
        <div
          className="text-white text-xl font-medium leading-snug"
          style={{ textShadow: '0 0 18px rgba(64,176,224,0.35)' }}
        >
          {hint}
        </div>
      </div>

      {/* Tiles */}
      <div className="flex items-center justify-center gap-8">
        <Tile
          icon={<CalendarDays className="w-12 h-12" />}
          label="Qabıllaw kúnleri"
          sublabel="Hákim · orınbasarlar"
          accent="#f7bd29"
          onClick={() => onNavigate('reception')}
        />
        <Tile
          icon={<FileEdit className="w-12 h-12" />}
          label="Murájaat jollaw"
          sublabel="Dawıs penen"
          accent="#7ee3a8"
          onClick={() => onNavigate('submit')}
        />
        <Tile
          icon={<PhoneCall className="w-12 h-12" />}
          label="Baylanıs"
          sublabel="Telefon nomerleri"
          accent="#40b0e0"
          onClick={() => onNavigate('contacts')}
        />
      </div>
    </div>
  )
}
