export type Screen = 'home' | 'reception' | 'submit' | 'contacts'

export const SCREEN_LABELS: Record<Screen, { kk: string; short: string }> = {
  home: { kk: 'Bas sahifa', short: 'HOME' },
  reception: { kk: 'Qabıllaw kúnleri', short: 'RECEPTION' },
  submit: { kk: 'Murájaat jollaw', short: 'SUBMIT' },
  contacts: { kk: 'Baylanıs', short: 'CONTACTS' },
}
