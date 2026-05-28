import { ContactCard } from '../ContactCard'
import { PageHeader } from '../PageHeader'
import { CONTACTS } from '../../data/contacts'
import { useSession } from '../../state/session'

interface Props {
  onBack: () => void
}

export function ContactsPage({ onBack }: Props) {
  const aiText = useSession((s) => s.currentAiText)

  return (
    <div className="flex-1 flex gap-6 px-6 pb-36 pt-6 min-h-0">
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
            {aiText || 'Qaysı baylanıs kerek?'}
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col min-w-0">
        <PageHeader
          title="Baylanıs"
          subtitle="Favqulodda hám hákimiyat"
          onBack={onBack}
        />

        <div className="mt-6 grid grid-cols-2 xl:grid-cols-3 gap-5 overflow-y-auto pr-2">
          {CONTACTS.map((c) => (
            <ContactCard key={c.id} contact={c} />
          ))}
        </div>
      </div>
    </div>
  )
}
