import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'

interface Props {
  open: boolean
  onDone: () => void
}

export function SubmitSuccessModal({ open, onDone }: Props) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!open) {
      setVisible(false)
      return
    }
    // Slight delay so the fade-in plays even for fast state transitions
    const showId = window.setTimeout(() => setVisible(true), 50)
    const doneId = window.setTimeout(() => onDone(), 4000)
    return () => {
      clearTimeout(showId)
      clearTimeout(doneId)
    }
  }, [open, onDone])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center backdrop-blur-md"
      style={{
        background: 'rgba(5, 22, 38, 0.85)',
        opacity: visible ? 1 : 0,
        transition: 'opacity 0.4s ease',
      }}
    >
      <div
        className="flex flex-col items-center gap-8 p-16 rounded-3xl border border-green-400/40"
        style={{
          background:
            'radial-gradient(ellipse at center, rgba(32,156,58,0.2) 0%, rgba(8,30,16,0.8) 80%)',
          boxShadow: '0 0 120px rgba(32,156,58,0.5)',
          transform: visible ? 'scale(1)' : 'scale(0.85)',
          transition: 'transform 0.5s cubic-bezier(0.2, 0.9, 0.3, 1.2)',
        }}
      >
        <div
          className="w-32 h-32 rounded-full flex items-center justify-center"
          style={{
            background: 'radial-gradient(circle, #26c85c, #13812f 70%)',
            boxShadow:
              '0 0 60px #26c85c, inset 0 2px 24px rgba(255,255,255,0.25)',
          }}
        >
          <Check
            className="w-20 h-20 text-white"
            strokeWidth={3.5}
            style={{
              filter: 'drop-shadow(0 4px 12px rgba(0,0,0,0.3))',
            }}
          />
        </div>

        <div className="text-center">
          <div className="text-white text-4xl font-bold tracking-wide mb-3">
            Jiberildi ✓
          </div>
          <div className="text-green-200/90 text-lg max-w-md leading-snug">
            Raxmet! Murájaatıńız qabıl etildi, tez arada juwap beriledi.
          </div>
        </div>

        <div className="text-green-300/50 text-xs font-mono tracking-[0.3em] uppercase">
          4 sekund ishinde bas sahifaǵa qaytamız…
        </div>
      </div>
    </div>
  )
}
