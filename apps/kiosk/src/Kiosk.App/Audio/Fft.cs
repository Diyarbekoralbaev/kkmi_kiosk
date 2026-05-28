using System;

namespace Kiosk.App.Audio;

/// <summary>
/// In-place radix-2 Cooley–Tukey FFT for real-valued audio. Used by AnalyserNode.
/// Size must be a power of two. Forward transform only; we never need inverse.
/// </summary>
internal static class Fft
{
    /// <summary>
    /// Computes the FFT of `input`. Returns parallel real/imaginary arrays of length input.Length.
    /// </summary>
    public static (float[] real, float[] imag) Forward(ReadOnlySpan<float> input)
    {
        int n = input.Length;
        if (n <= 0 || (n & (n - 1)) != 0)
            throw new ArgumentException("FFT size must be a positive power of two", nameof(input));

        var re = new float[n];
        var im = new float[n];
        input.CopyTo(re);

        // Bit-reverse permutation
        int j = 0;
        for (int i = 0; i < n - 1; i++)
        {
            if (i < j)
            {
                (re[i], re[j]) = (re[j], re[i]);
                (im[i], im[j]) = (im[j], im[i]);
            }
            int k = n >> 1;
            while (k <= j) { j -= k; k >>= 1; }
            j += k;
        }

        // Butterfly
        for (int len = 2; len <= n; len <<= 1)
        {
            int half = len >> 1;
            float angle = -2f * MathF.PI / len;
            float wStepRe = MathF.Cos(angle);
            float wStepIm = MathF.Sin(angle);
            for (int i = 0; i < n; i += len)
            {
                float wRe = 1f, wIm = 0f;
                for (int k = 0; k < half; k++)
                {
                    int a = i + k;
                    int b = a + half;
                    float bRe = re[b] * wRe - im[b] * wIm;
                    float bIm = re[b] * wIm + im[b] * wRe;
                    re[b] = re[a] - bRe;
                    im[b] = im[a] - bIm;
                    re[a] += bRe;
                    im[a] += bIm;
                    var nextWRe = wRe * wStepRe - wIm * wStepIm;
                    var nextWIm = wRe * wStepIm + wIm * wStepRe;
                    wRe = nextWRe;
                    wIm = nextWIm;
                }
            }
        }
        return (re, im);
    }
}
