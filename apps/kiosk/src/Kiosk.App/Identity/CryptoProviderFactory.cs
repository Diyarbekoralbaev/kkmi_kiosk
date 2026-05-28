using System;
using System.Runtime.InteropServices;

namespace Kiosk.App.Identity;

/// <summary>
/// Picks the right <see cref="ICryptoProvider"/> for the current OS.
///
/// Windows → TPM-bound (production). Linux → software-backed (dev only).
/// We deliberately do not provide a software fallback on Windows: if the
/// target machine has no TPM 2.0, the kiosk fails enrollment with a clear
/// message so the operator knows to use different hardware.
/// </summary>
public static class CryptoProviderFactory
{
    private static ICryptoProvider? _instance;

    public static ICryptoProvider Current => _instance ??= Create();

    private static ICryptoProvider Create()
    {
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
#pragma warning disable CA1416 // Validate platform compatibility
            return new TpmCryptoProvider();
#pragma warning restore CA1416
        }
        return new SoftCryptoProvider();
    }
}
