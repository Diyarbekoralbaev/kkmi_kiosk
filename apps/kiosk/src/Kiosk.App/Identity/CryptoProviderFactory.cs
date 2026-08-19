using System;
using System.Runtime.InteropServices;

namespace Kiosk.App.Identity;

/// <summary>
/// Picks the right <see cref="ICryptoProvider"/> for the machine.
///
///   Windows + TPM 2.0  → <see cref="TpmCryptoProvider"/>       (preferred)
///   Windows, no TPM    → <see cref="WindowsSoftwareCryptoProvider"/>
///   Linux / macOS      → <see cref="SoftCryptoProvider"/>       (dev only)
///
/// The Windows fallback is deliberate, not an oversight. The original rule was
/// "no TPM, no enrollment", on the reasoning that an operator hitting it would
/// go change a BIOS setting. That assumption broke on the institute's lobby
/// unit: an embedded LVDS board whose AMI firmware exposes no PTT or Trusted
/// Computing page at all, in a machine with no keyboard attached. There was
/// nothing to turn on and no way to turn it on, so the hard failure meant a
/// permanently dead kiosk rather than a stronger one.
///
/// The fallback is still CNG with a non-exportable persisted key — it gives up
/// hardware binding, not key hygiene — and it reports `tpm_attested: false` at
/// enrollment so the audit log says which units are hardware-backed.
/// </summary>
public static class CryptoProviderFactory
{
    private static ICryptoProvider? _instance;

    public static ICryptoProvider Current => _instance ??= Create();

    private static ICryptoProvider Create()
    {
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            return new SoftCryptoProvider();

#pragma warning disable CA1416 // Validate platform compatibility
        // An enrolled kiosk keeps the key it enrolled with. If a box later
        // gains a TPM, switching to it would start signing with a key the
        // server has never seen: every request 401s and the visitor gets the
        // red revoked overlay. Upgrading to the TPM is a re-enrollment, which
        // is an operator's decision to make, not a side effect of a reboot.
        if (WindowsSoftwareCryptoProvider.KeyExists())
        {
            Console.Error.WriteLine(
                "[security] using the existing software-backed device key. " +
                "If this machine now has TPM 2.0, re-enroll to move onto it.");
            return new WindowsSoftwareCryptoProvider();
        }

        if (TpmCryptoProvider.IsAvailable())
            return new TpmCryptoProvider();

        Console.Error.WriteLine(
            "[security] TPM 2.0 not present — using a DPAPI-protected software key.");
        return new WindowsSoftwareCryptoProvider();
#pragma warning restore CA1416
    }

    /// <summary>Swap a TPM provider out for the software one after the TPM has
    /// failed for real. <see cref="TpmCryptoProvider.IsAvailable"/> only proves
    /// the provider is registered; a box can still refuse the key creation
    /// itself. Enrollment calls this once on that failure so the operator gets
    /// a working kiosk instead of a second trip to a machine they cannot type
    /// on. Returns the provider now in force.</summary>
    public static ICryptoProvider DemoteToSoftware()
    {
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            return Current;
        if (_instance is not TpmCryptoProvider) return Current;

        Console.Error.WriteLine(
            "[security] TPM keypair creation failed — falling back to a software key.");
        (_instance as IDisposable)?.Dispose();
#pragma warning disable CA1416
        ICryptoProvider soft = new WindowsSoftwareCryptoProvider();
#pragma warning restore CA1416
        _instance = soft;
        return soft;
    }
}
