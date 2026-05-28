import { create } from 'zustand'
import type { Screen } from '../data/screens'

export type SessionStatus =
  | 'idle'
  | 'connecting'
  | 'active'
  | 'disconnecting'
  | 'error'

interface SessionState {
  status: SessionStatus
  error: string | null
  currentAiText: string
  currentUserText: string
  avatar: unknown | null
  micLevel: number

  // Navigation + submit flow
  screen: Screen
  submitDone: boolean

  setStatus: (s: SessionStatus, err?: string | null) => void
  setAiText: (text: string) => void
  setUserText: (text: string) => void
  appendAiText: (chunk: string) => void
  setAvatar: (a: unknown) => void
  setMicLevel: (v: number) => void
  setScreen: (s: Screen) => void
  setSubmitDone: (v: boolean) => void
  reset: () => void
}

export const useSession = create<SessionState>((set) => ({
  status: 'idle',
  error: null,
  currentAiText: '',
  currentUserText: '',
  avatar: null,
  micLevel: 0,
  screen: 'home',
  submitDone: false,

  setStatus: (status, error = null) => set({ status, error }),
  setAiText: (currentAiText) => set({ currentAiText }),
  setUserText: (currentUserText) => set({ currentUserText }),
  appendAiText: (chunk) =>
    set((s) => ({ currentAiText: (s.currentAiText + chunk).slice(-500) })),
  setAvatar: (avatar) => set({ avatar }),
  setMicLevel: (micLevel) => set({ micLevel }),
  setScreen: (screen) => set({ screen }),
  setSubmitDone: (submitDone) => set({ submitDone }),
  reset: () =>
    set({
      status: 'idle',
      error: null,
      currentAiText: '',
      currentUserText: '',
      micLevel: 0,
      screen: 'home',
      submitDone: false,
    }),
}))
