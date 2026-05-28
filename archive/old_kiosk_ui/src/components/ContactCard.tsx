import { AlertTriangle, Building2, Phone } from 'lucide-react'
import type { Contact } from '../data/contacts'

interface Props {
  contact: Contact
}

const ICONS = {
  emergency: AlertTriangle,
  building: Building2,
  phone: Phone,
}

export function ContactCard({ contact }: Props) {
  const Icon = ICONS[contact.icon]
  const emergency = contact.emergency

  const accent = emergency ? '#e74c3c' : '#40b0e0'
  const accentGlow = emergency ? 'rgba(231,76,60,0.35)' : 'rgba(64,176,224,0.3)'

  return (
    <div
      className="flex flex-col rounded-2xl border overflow-hidden transition-all"
      style={{
        borderColor: emergency
          ? 'rgba(231,76,60,0.45)'
          : 'rgba(255,255,255,0.1)',
        background: emergency
          ? 'linear-gradient(180deg, rgba(231,76,60,0.16) 0%, rgba(231,76,60,0.04) 100%)'
          : 'rgba(255,255,255,0.03)',
        boxShadow: emergency
          ? `0 0 36px ${accentGlow}, inset 0 1px 0 rgba(255,255,255,0.08)`
          : '0 4px 24px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04)',
      }}
    >
      <div className="flex items-start gap-4 p-5">
        <div
          className="w-14 h-14 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: `${accent}20`,
            border: `1.5px solid ${accent}60`,
            boxShadow: `0 0 20px ${accentGlow}`,
          }}
        >
          <Icon className="w-7 h-7" style={{ color: accent }} />
        </div>
        <div className="min-w-0 flex-1 pt-1">
          <div className="text-white font-semibold text-lg leading-tight">
            {contact.labelKk}
          </div>
          {contact.subtitleKk && (
            <div className="text-white/55 text-xs mt-1 uppercase tracking-wider font-mono">
              {contact.subtitleKk}
            </div>
          )}
        </div>
      </div>

      <div
        className="px-5 py-4 border-t"
        style={{
          borderColor: emergency
            ? 'rgba(231,76,60,0.2)'
            : 'rgba(255,255,255,0.08)',
          background: emergency ? 'rgba(231,76,60,0.08)' : 'rgba(0,0,0,0.2)',
        }}
      >
        <div
          className="font-mono font-bold tracking-wider"
          style={{
            fontSize: emergency ? '2.5rem' : '1.5rem',
            color: emergency ? '#ffb9b0' : '#ffffff',
            textShadow: `0 0 20px ${accentGlow}`,
            lineHeight: 1,
          }}
        >
          {contact.phone}
        </div>
      </div>
    </div>
  )
}
