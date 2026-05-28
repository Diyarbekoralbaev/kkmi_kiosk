import { useCallback, useRef } from 'react'
import { KioskWs, buildWsUrl } from '../lib/ws'
import { PcmPlayer } from '../audio/player'
import { startMic, type MicCapture } from '../audio/mic'
import { useSession } from '../state/session'
import type { Screen } from '../data/screens'

export function useKioskSession() {
  const wsRef = useRef<KioskWs | null>(null)
  const playerRef = useRef<PcmPlayer | null>(null)
  const micRef = useRef<MicCapture | null>(null)

  const sendScreenContext = useCallback((screen: Screen) => {
    const ws = wsRef.current
    if (!ws || !ws.isOpen()) return
    ws.sendJson({ type: 'screen_context', screen })
  }, [])

  const stop = useCallback(async () => {
    useSession.getState().setStatus('disconnecting')
    try {
      wsRef.current?.close()
    } catch {
      // ignore
    }
    try {
      await micRef.current?.stop()
    } catch {
      // ignore
    }
    try {
      await playerRef.current?.close()
    } catch {
      // ignore
    }
    wsRef.current = null
    micRef.current = null
    playerRef.current = null
    useSession.getState().reset()
  }, [])

  const start = useCallback(async () => {
    const session = useSession.getState()
    if (session.status === 'active' || session.status === 'connecting') return
    session.setStatus('connecting')
    session.setAiText('')
    session.setUserText('')

    try {
      const player = new PcmPlayer()
      await player.init()
      playerRef.current = player

      const ws = new KioskWs(buildWsUrl(), (ev) => {
        if (ev.type === 'binary') {
          player.feed(ev.data)
        } else if (ev.type === 'navigate') {
          // AI-driven navigation via Gemini tool call
          useSession.getState().setScreen(ev.screen)
        } else if (ev.type === 'transcript') {
          if (ev.text.trim()) {
            if (ev.speaker === 'user') {
              useSession.getState().setUserText(ev.text)
            } else {
              useSession.getState().setAiText(ev.text)
            }
          }
        } else if (ev.type === 'disconnected') {
          useSession.getState().setStatus('error', ev.reason ?? 'disconnected')
        } else if (ev.type === 'close') {
          const s = useSession.getState().status
          if (s === 'active' || s === 'connecting') {
            useSession.getState().setStatus('idle')
          }
        } else if (ev.type === 'error') {
          useSession.getState().setStatus('error', ev.message)
        }
      })
      wsRef.current = ws
      await ws.connect()

      const deviceId = localStorage.getItem('kiosk_mic_id') || undefined
      const mic = await startMic({
        deviceId,
        onPcm16: (buf) => ws.sendBinary(buf),
        onLevel: (rms) => useSession.getState().setMicLevel(rms),
      })
      micRef.current = mic

      useSession.getState().setStatus('active')

      // Inject initial screen context so AI knows where the user is
      const currentScreen = useSession.getState().screen
      setTimeout(() => sendScreenContext(currentScreen), 300)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      useSession.getState().setStatus('error', msg)
      await stop()
    }
  }, [sendScreenContext, stop])

  const toggle = useCallback(async () => {
    const s = useSession.getState().status
    if (s === 'idle' || s === 'error') {
      await start()
    } else {
      await stop()
    }
  }, [start, stop])

  const navigate = useCallback(
    (screen: Screen) => {
      useSession.getState().setScreen(screen)
      if (useSession.getState().status === 'active') {
        sendScreenContext(screen)
      }
    },
    [sendScreenContext]
  )

  const endSession = useCallback(async () => {
    await stop()
    useSession.getState().setScreen('home')
  }, [stop])

  const getPlayerAnalyser = useCallback(
    () => playerRef.current?.getAnalyser() ?? null,
    []
  )

  return {
    start,
    stop,
    toggle,
    navigate,
    endSession,
    sendScreenContext,
    getPlayerAnalyser,
  }
}
