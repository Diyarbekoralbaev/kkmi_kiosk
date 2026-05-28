import { useEffect } from 'react'
import { PageHeader } from '../PageHeader'
import { useSession } from '../../state/session'

interface Props {
  onBack: () => void
}

/**
 * Submit page — voice-driven dialog mode.
 * The AI drives a 4-step conversation (topic → details → confirm → done).
 * When the AI speaks a confirmation-phrase final transcript, the UI marks
 * the submission done which the App root will show as the success modal.
 */
export function SubmitPage({ onBack }: Props) {
  const aiText = useSession((s) => s.currentAiText)
  const userText = useSession((s) => s.currentUserText)
  const submitDone = useSession((s) => s.submitDone)
  const setSubmitDone = useSession((s) => s.setSubmitDone)

  // Heuristic: final AI transcript contains "qabil etildi" or "jiberildi" → mark done
  useEffect(() => {
    if (submitDone) return
    const t = aiText.toLowerCase()
    if (
      t.includes('qabıl etildi') ||
      t.includes('qabil etildi') ||
      t.includes('jiberildi') ||
      t.includes('juwap beriledi')
    ) {
      setSubmitDone(true)
    }
  }, [aiText, submitDone, setSubmitDone])

  const currentStep = !aiText
    ? 1
    : userText && aiText.includes('batlaq')
    ? 2
    : aiText.includes('Durıs') || aiText.includes('jiberip')
    ? 3
    : submitDone
    ? 4
    : 1

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
            {aiText || 'Dialogni baslaw ushın mikrofondı qoslaw kerek...'}
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col min-w-0">
        <PageHeader
          title="Murájaat jollaw"
          subtitle="Dawıs penen"
          onBack={onBack}
        />

        {/* Step indicator */}
        <div className="mt-6 flex items-center gap-3">
          {['Mavzu', 'Batlaq', 'Tastıqlaw', 'Jiberiw'].map((label, i) => {
            const step = i + 1
            const active = step === currentStep
            const done = step < currentStep
            return (
              <div key={label} className="flex items-center gap-3 flex-1">
                <div className="flex items-center gap-2.5">
                  <div
                    className="w-9 h-9 rounded-full flex items-center justify-center font-bold text-sm border-2 transition-all"
                    style={{
                      borderColor: active || done ? '#7ee3a8' : 'rgba(255,255,255,0.2)',
                      background: done
                        ? '#7ee3a820'
                        : active
                        ? '#7ee3a810'
                        : 'transparent',
                      color: active || done ? '#7ee3a8' : 'rgba(255,255,255,0.5)',
                      boxShadow: active ? '0 0 20px rgba(126,227,168,0.5)' : 'none',
                    }}
                  >
                    {done ? '✓' : step}
                  </div>
                  <span
                    className="text-sm font-semibold tracking-wide uppercase"
                    style={{
                      color: active
                        ? '#ffffff'
                        : done
                        ? 'rgba(126,227,168,0.9)'
                        : 'rgba(255,255,255,0.4)',
                    }}
                  >
                    {label}
                  </span>
                </div>
                {step < 4 && (
                  <div
                    className="flex-1 h-px"
                    style={{
                      background: done
                        ? '#7ee3a860'
                        : 'rgba(255,255,255,0.12)',
                    }}
                  />
                )}
              </div>
            )
          })}
        </div>

        {/* Dialog transcript */}
        <div
          className="mt-6 flex-1 flex flex-col gap-4 p-6 rounded-2xl border border-white/10 overflow-y-auto"
          style={{
            background: 'rgba(5, 18, 34, 0.6)',
            backdropFilter: 'blur(8px)',
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04)',
          }}
        >
          <div className="text-[10px] tracking-[0.3em] uppercase text-kk-blueLight/60 font-mono">
            Dialog
          </div>

          {aiText && (
            <div className="flex gap-3">
              <span
                className="font-mono font-bold text-sm shrink-0 pt-1"
                style={{ color: '#7ee3a8', textShadow: '0 0 12px #7ee3a860' }}
              >
                AI ›
              </span>
              <div
                className="text-white text-lg leading-relaxed"
                style={{ textShadow: '0 0 14px rgba(64,176,224,0.25)' }}
              >
                {aiText}
              </div>
            </div>
          )}

          {userText && (
            <div className="flex gap-3">
              <span
                className="font-mono font-bold text-sm shrink-0 pt-1"
                style={{ color: '#40b0e0', textShadow: '0 0 12px #40b0e060' }}
              >
                SIZ ›
              </span>
              <div className="text-white/85 text-lg leading-relaxed">
                {userText}
              </div>
            </div>
          )}

          {!aiText && !userText && (
            <div className="text-white/50 italic">
              Mikrofondı basıp, "Qaysı másele boyınsha..." sorawın kútiń.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
