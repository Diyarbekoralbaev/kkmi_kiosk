/**
 * 24kHz PCM16 gapless playback via AudioBufferSourceNode scheduling.
 */
export class PcmPlayer {
  private ctx: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private gain: GainNode | null = null
  private nextPlayTime = 0

  async init() {
    if (this.ctx) return
    this.ctx = new AudioContext({ sampleRate: 24000 })
    if (this.ctx.state === 'suspended') await this.ctx.resume()
    this.gain = this.ctx.createGain()
    this.gain.gain.value = 1.0
    this.analyser = this.ctx.createAnalyser()
    this.analyser.fftSize = 1024
    this.analyser.smoothingTimeConstant = 0.6
    this.gain.connect(this.analyser)
    this.analyser.connect(this.ctx.destination)
    this.nextPlayTime = this.ctx.currentTime
  }

  getAnalyser(): AnalyserNode | null {
    return this.analyser
  }

  getContext(): AudioContext | null {
    return this.ctx
  }

  /** Enqueue raw Int16 PCM at 24kHz mono. */
  feed(buf: ArrayBuffer) {
    if (!this.ctx || !this.gain) return
    const int16 = new Int16Array(buf)
    if (int16.length === 0) return

    const float = new Float32Array(int16.length)
    for (let i = 0; i < int16.length; i++) float[i] = int16[i] / 0x8000

    const audioBuf = this.ctx.createBuffer(1, float.length, 24000)
    audioBuf.copyToChannel(float, 0)

    const src = this.ctx.createBufferSource()
    src.buffer = audioBuf
    src.connect(this.gain)

    const now = this.ctx.currentTime
    const start = Math.max(now, this.nextPlayTime)
    src.start(start)
    this.nextPlayTime = start + audioBuf.duration
  }

  /** Clear scheduled audio (for barge-in / reset). */
  reset() {
    if (this.ctx) this.nextPlayTime = this.ctx.currentTime
  }

  async close() {
    try {
      this.gain?.disconnect()
      this.analyser?.disconnect()
      await this.ctx?.close()
    } catch {
      // ignore
    }
    this.ctx = null
    this.gain = null
    this.analyser = null
    this.nextPlayTime = 0
  }
}
