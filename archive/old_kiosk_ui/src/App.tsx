import { useEffect, useState } from 'react'
import { MicOrb } from './components/MicOrb'
import { ErrorBanner } from './components/ErrorBanner'
import { SettingsButton } from './components/SettingsButton'
import { SettingsModal } from './components/SettingsModal'
import { EndSessionButton } from './components/EndSessionButton'
import { RobotScene } from './components/RobotScene'
import { SceneBoundary } from './components/SceneBoundary'
import { SubmitSuccessModal } from './components/SubmitSuccessModal'
import { HomePage } from './components/pages/HomePage'
import { ReceptionPage } from './components/pages/ReceptionPage'
import { ContactsPage } from './components/pages/ContactsPage'
import { SubmitPage } from './components/pages/SubmitPage'
import { useKioskSession } from './hooks/useSession'
import { useSession } from './state/session'

export default function App() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { toggle, navigate, endSession, getPlayerAnalyser } = useKioskSession()
  const screen = useSession((s) => s.screen)
  const submitDone = useSession((s) => s.submitDone)
  const setSubmitDone = useSession((s) => s.setSubmitDone)

  // When the submit dialog completes, show the modal; after it closes we go home.
  const [showSuccess, setShowSuccess] = useState(false)
  useEffect(() => {
    if (submitDone && screen === 'submit') {
      setShowSuccess(true)
    }
  }, [submitDone, screen])

  const handleSuccessDone = () => {
    setShowSuccess(false)
    setSubmitDone(false)
    navigate('home')
  }

  // Robot position per screen: center on home, top-left sidebar on other pages
  const robotStyle =
    screen === 'home'
      ? {
          top: '6rem',
          left: '50%',
          transform: 'translateX(-50%)',
          width: 'min(52vw, 640px)',
          height: '44vh',
        }
      : {
          top: '6.5rem',
          left: '1.5rem',
          width: '304px',
          height: 'calc(60vh - 6rem)',
        }

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-[#040e1c] text-white flex flex-col">
      {/* ---------- Background ---------- */}
      <div className="absolute inset-0 pointer-events-none z-0">
        <div
          className="absolute inset-0"
          style={{
            background:
              'radial-gradient(ellipse at 50% 20%, #0e2a44 0%, #071c34 45%, #040e1c 100%)',
          }}
        />
        <div
          className="absolute inset-0 opacity-[0.08]"
          style={{
            backgroundImage:
              'linear-gradient(#40b0e0 1px, transparent 1px), linear-gradient(90deg, #40b0e0 1px, transparent 1px)',
            backgroundSize: '56px 56px',
          }}
        />
        {/* Ambient top glow */}
        <div
          className="absolute top-0 left-1/2 -translate-x-1/2 w-[80%] h-[60%] rounded-full"
          style={{
            background:
              'radial-gradient(ellipse, rgba(64,176,224,0.14), transparent 60%)',
          }}
        />
      </div>

      {/* ---------- Top header ---------- */}
      <div className="relative z-20 flex items-center justify-between px-8 py-5 border-b border-white/5">
        <div>
          <div className="text-[10px] tracking-[0.3em] uppercase text-kk-blueLight/80 font-mono">
            Nókis qalası hákimiyatı
          </div>
          <div className="text-white text-2xl font-semibold leading-tight mt-0.5">
            Sanlıq járdemshi
          </div>
        </div>
        <div className="flex items-center gap-4">
          <SettingsButton onClick={() => setSettingsOpen(true)} />
          <EndSessionButton onClick={endSession} />
        </div>
      </div>

      {/* ---------- Global 3D robot (absolute, single instance) ---------- */}
      <div
        className="absolute z-10 pointer-events-none transition-all duration-500 ease-out"
        style={robotStyle}
      >
        <SceneBoundary>
          <RobotScene getAnalyser={getPlayerAnalyser} />
        </SceneBoundary>
      </div>

      {/* ---------- Screen router (flex-col, absolute robot overlaps where planned) ---------- */}
      <div className="relative z-20 flex-1 flex flex-col min-h-0">
        {screen === 'home' && <HomePage onNavigate={navigate} />}
        {screen === 'reception' && (
          <ReceptionPage onBack={() => navigate('home')} />
        )}
        {screen === 'submit' && <SubmitPage onBack={() => navigate('home')} />}
        {screen === 'contacts' && (
          <ContactsPage onBack={() => navigate('home')} />
        )}
      </div>

      {/* ---------- Mic orb — bottom center, always visible ---------- */}
      <div className="absolute bottom-8 left-0 right-0 flex justify-center z-30">
        <MicOrb onClick={toggle} />
      </div>

      {/* ---------- Overlays ---------- */}
      <ErrorBanner />
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <SubmitSuccessModal open={showSuccess} onDone={handleSuccessDone} />
    </div>
  )
}
