export type WsEvent =
  | { type: 'binary'; data: ArrayBuffer }
  | { type: 'transcript'; text: string; final: boolean; speaker: 'user' | 'assistant' }
  | { type: 'audio_done' }
  | { type: 'disconnected'; reason?: string }
  | { type: 'barge_in' }
  | { type: 'navigate'; screen: 'home' | 'reception' | 'submit' | 'contacts' }
  | { type: 'application_preview'; topic: string; body: string; phone: string }
  | { type: 'application_submitted'; id: number; topic: string; body: string; phone: string }
  | { type: 'open' }
  | { type: 'close' }
  | { type: 'error'; message: string }

export type WsHandler = (ev: WsEvent) => void

export class KioskWs {
  private ws: WebSocket | null = null
  private handler: WsHandler
  private url: string

  constructor(url: string, handler: WsHandler) {
    this.url = url
    this.handler = handler
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        const ws = new WebSocket(this.url)
        ws.binaryType = 'arraybuffer'
        this.ws = ws
        ws.onopen = () => {
          this.handler({ type: 'open' })
          resolve()
        }
        ws.onmessage = (ev) => {
          if (ev.data instanceof ArrayBuffer) {
            this.handler({ type: 'binary', data: ev.data })
            return
          }
          try {
            const msg = JSON.parse(String(ev.data))
            // eslint-disable-next-line no-console
            console.log('[ws]', msg)
            if (msg.type === 'transcript') {
              const speaker: 'user' | 'assistant' =
                msg.speaker === 'user' ? 'user' : 'assistant'
              this.handler({
                type: 'transcript',
                text: msg.text ?? '',
                final: !!msg.final,
                speaker,
              })
            } else if (msg.type === 'audio_done') {
              this.handler({ type: 'audio_done' })
            } else if (msg.type === 'navigate') {
              const s = msg.screen
              if (s === 'home' || s === 'reception' || s === 'submit' || s === 'contacts') {
                this.handler({ type: 'navigate', screen: s })
              }
            } else if (msg.type === 'application_preview') {
              this.handler({
                type: 'application_preview',
                topic: msg.topic ?? '',
                body: msg.body ?? '',
                phone: msg.phone ?? '',
              })
            } else if (msg.type === 'application_submitted') {
              this.handler({
                type: 'application_submitted',
                id: msg.id ?? 0,
                topic: msg.topic ?? '',
                body: msg.body ?? '',
                phone: msg.phone ?? '',
              })
            } else if (msg.type === 'disconnected') {
              this.handler({ type: 'disconnected', reason: msg.reason })
            } else if (msg.type === 'barge_in') {
              this.handler({ type: 'barge_in' })
            }
          } catch {
            // ignore
          }
        }
        ws.onerror = () => {
          this.handler({ type: 'error', message: 'websocket error' })
          reject(new Error('websocket error'))
        }
        ws.onclose = () => {
          this.handler({ type: 'close' })
        }
      } catch (e) {
        reject(e)
      }
    })
  }

  sendBinary(buf: ArrayBuffer) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(buf)
    }
  }

  sendJson(obj: unknown) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj))
    }
  }

  isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  close() {
    try {
      this.ws?.close()
    } catch {
      // ignore
    }
    this.ws = null
  }
}

export function buildWsUrl(): string {
  const stored = localStorage.getItem('kiosk_ws_url')
  if (stored) return stored
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws/kiosk/voice`
}
