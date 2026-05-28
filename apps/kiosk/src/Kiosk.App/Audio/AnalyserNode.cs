using System;

namespace Kiosk.App.Audio;

/// <summary>
/// Mirrors the Web Audio API's AnalyserNode. The 3D robot animation port
/// (slice 8) is a 1:1 translation of TypeScript that calls
/// `analyser.getByteFrequencyData(...)` — keeping the same shape here means
/// the animation math stays untouched.
///
/// Behavior:
///   - Maintains a ring buffer of the most recent `FftSize` samples.
///   - On each `GetByteFrequencyData` call: applies a Hann window, runs an
///     in-place FFT, computes per-bin magnitude in dB, exponentially smooths
///     each bin (`SmoothingTimeConstant`), maps [`MinDecibels`, `MaxDecibels`]
///     onto a 0–255 byte.
/// </summary>
public sealed class AnalyserNode
{
    public int FftSize { get; }
    public int FrequencyBinCount => FftSize / 2;
    public float SmoothingTimeConstant { get; set; } = 0.8f;
    public float MinDecibels { get; set; } = -100f;
    public float MaxDecibels { get; set; } = -30f;

    private readonly float[] _ring;
    private readonly float[] _smoothedDb;
    private readonly float[] _hann;
    private int _writeIdx;
    private readonly object _lock = new();

    public AnalyserNode(int fftSize = 256)
    {
        if (fftSize <= 0 || (fftSize & (fftSize - 1)) != 0)
            throw new ArgumentException("fftSize must be a power of two", nameof(fftSize));
        FftSize = fftSize;
        _ring = new float[fftSize];
        _smoothedDb = new float[FrequencyBinCount];
        _hann = new float[fftSize];
        for (int i = 0; i < fftSize; i++)
            _hann[i] = 0.5f * (1f - MathF.Cos(2f * MathF.PI * i / (fftSize - 1)));
        for (int i = 0; i < FrequencyBinCount; i++)
            _smoothedDb[i] = MinDecibels;
    }

    /// <summary>Writes new samples into the ring (Int16 PCM, will be normalized to [-1, 1]).</summary>
    public void Feed(ReadOnlySpan<short> samples)
    {
        lock (_lock)
        {
            for (int i = 0; i < samples.Length; i++)
            {
                _ring[_writeIdx] = samples[i] / 32768f;
                _writeIdx = (_writeIdx + 1) % FftSize;
            }
        }
    }

    /// <summary>
    /// Fills `dest` with current frequency-bin magnitudes mapped to 0–255.
    /// `dest.Length` must be at least `FrequencyBinCount`.
    /// </summary>
    public void GetByteFrequencyData(byte[] dest)
    {
        if (dest.Length < FrequencyBinCount) throw new ArgumentException("dest too small", nameof(dest));

        var window = new float[FftSize];
        lock (_lock)
        {
            // Read in chronological order, oldest first.
            for (int i = 0; i < FftSize; i++)
                window[i] = _ring[(_writeIdx + i) % FftSize] * _hann[i];
        }

        var (re, im) = Fft.Forward(window);
        var range = MaxDecibels - MinDecibels;
        var alpha = SmoothingTimeConstant;
        var beta = 1f - alpha;

        for (int i = 0; i < FrequencyBinCount; i++)
        {
            var mag = MathF.Sqrt(re[i] * re[i] + im[i] * im[i]) / (FftSize / 2f);
            var db = 20f * MathF.Log10(mag + 1e-10f);
            _smoothedDb[i] = alpha * _smoothedDb[i] + beta * db;
            var norm = (_smoothedDb[i] - MinDecibels) / range;
            if (norm < 0f) norm = 0f; else if (norm > 1f) norm = 1f;
            dest[i] = (byte)(norm * 255f);
        }
    }
}
