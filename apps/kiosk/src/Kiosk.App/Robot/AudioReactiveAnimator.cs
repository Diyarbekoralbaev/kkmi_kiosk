using System;
using Kiosk.App.Audio;

namespace Kiosk.App.Robot;

/// <summary>
/// Computes per-frame animation state from the playback FFT. 1:1 port of the
/// audio-reactivity loop in RobotScene.tsx (lines 243–305):
///
///   intensity  = mean(fft[0..60]) / 255
///   smoothed += (intensity - smoothed) * (1 - exp(-dt * 8))
///
/// The original drives head-bone tilt + morph-target lerp + chest glow + Y-bob
/// + scene rotation. The static-mesh port (slice 7) keeps the scene-level
/// pieces (chest glow, Y-bob, idle/active rotation); head tilt and mouth morph
/// require skinning + morph targets — deferred to a later polish pass.
/// </summary>
public sealed class AudioReactiveAnimator
{
    private const int UsableBins = 60;

    public AnalyserNode? Analyser { get; set; }

    public float Smoothed { get; private set; }
    public float Bob { get; private set; }
    public float SceneRotationY { get; private set; }
    public float ChestIntensity { get; private set; }
    public float ChestHueShift { get; private set; } // 0..1, shifts color toward cyan

    private readonly byte[] _bins = new byte[256];
    private float _elapsed;

    /// <summary>If true, scene rotation uses the slow turntable; otherwise gentle sway.</summary>
    public bool IsIdle { get; set; } = true;

    public void Tick(float dt)
    {
        _elapsed += dt;

        float intensity = 0f;
        if (Analyser is not null)
        {
            Analyser.GetByteFrequencyData(_bins);
            int n = Math.Min(UsableBins, Analyser.FrequencyBinCount);
            int sum = 0;
            for (int i = 0; i < n; i++) sum += _bins[i];
            intensity = (sum / (float)n) / 255f;
        }

        // Exponential smoothing: smoothed += (intensity - smoothed) * (1 - exp(-dt*8))
        var alpha = 1f - MathF.Exp(-dt * 8f);
        Smoothed += (intensity - Smoothed) * alpha;

        ChestIntensity = 0.4f + Smoothed * 6.0f;
        ChestHueShift = Smoothed * 0.05f;
        Bob = Smoothed * 0.04f;

        SceneRotationY = IsIdle
            ? MathF.Sin(_elapsed * 0.25f) * 0.35f
            : MathF.Sin(_elapsed * 0.6f) * 0.08f;
    }
}
