export interface MicCapture {
  stop: () => Promise<void>
  context: AudioContext
  analyser: AnalyserNode
}

export interface MicOptions {
  deviceId?: string
  onPcm16: (buf: ArrayBuffer) => void
  onLevel?: (rms: number) => void
}

export async function startMic(opts: MicOptions): Promise<MicCapture> {
  const constraints: MediaStreamConstraints = {
    audio: {
      deviceId: opts.deviceId ? { exact: opts.deviceId } : undefined,
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  }
  const stream = await navigator.mediaDevices.getUserMedia(constraints)

  const ctx = new AudioContext({ sampleRate: 16000 })
  if (ctx.state === 'suspended') await ctx.resume()

  const src = ctx.createMediaStreamSource(stream)
  const analyser = ctx.createAnalyser()
  analyser.fftSize = 512
  analyser.smoothingTimeConstant = 0.7

  // ScriptProcessorNode is deprecated but still the simplest reliable path
  // for int16 PCM at a fixed size. AudioWorklet would be better — defer.
  const proc = ctx.createScriptProcessor(2048, 1, 1)

  src.connect(analyser)
  src.connect(proc)
  proc.connect(ctx.destination)

  const levelData = new Uint8Array(analyser.frequencyBinCount)

  proc.onaudioprocess = (e) => {
    const input = e.inputBuffer.getChannelData(0)
    const out = new Int16Array(input.length)
    for (let i = 0; i < input.length; i++) {
      const s = Math.max(-1, Math.min(1, input[i]))
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff
    }
    opts.onPcm16(out.buffer)

    if (opts.onLevel) {
      analyser.getByteTimeDomainData(levelData)
      let sum = 0
      for (let i = 0; i < levelData.length; i++) {
        const v = (levelData[i] - 128) / 128
        sum += v * v
      }
      opts.onLevel(Math.sqrt(sum / levelData.length))
    }
  }

  return {
    context: ctx,
    analyser,
    stop: async () => {
      try {
        proc.disconnect()
        src.disconnect()
        analyser.disconnect()
      } catch {
        // ignore
      }
      stream.getTracks().forEach((t) => t.stop())
      try {
        await ctx.close()
      } catch {
        // ignore
      }
    },
  }
}
