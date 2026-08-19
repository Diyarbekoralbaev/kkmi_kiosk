using System;
using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.Threading.Tasks;

namespace Kiosk.App.Identity;

/// <summary>
/// Windows fallback for boxes whose firmware exposes no TPM 2.0.
///
/// Same CNG shape as <see cref="TpmCryptoProvider"/> — persisted ECDSA P-256
/// key, non-exportable, signed via NCrypt — but backed by the Microsoft
/// Software Key Storage Provider instead of the TPM. The private key lives in
/// the user's CNG key store (%APPDATA%\Microsoft\Crypto\Keys), encrypted at
/// rest by DPAPI under the kiosk account.
///
/// Weaker than the TPM in exactly one way that matters: the key is protected
/// by software, so anyone who can run code as that user AND recover their
/// DPAPI master key can extract it. The TPM makes that impossible even for
/// SYSTEM. It is still far better than a plaintext PEM on disk, which is what
/// <see cref="SoftCryptoProvider"/> writes — that one stays Linux-dev-only.
///
/// Why it exists: the institute's lobby unit is an embedded LVDS board whose
/// AMI firmware ships no PTT/Trusted Computing page at all — there is no
/// setting to turn on, and the box has no physical keyboard for a BIOS visit
/// anyway. Refusing to enroll would have left the kiosk permanently dead.
///
/// Devices enrolled through this provider report `tpm_attested: false`, so the
/// audit log records which units are hardware-backed and which are not. That
/// flag is the whole point of keeping this a distinct type rather than
/// parameterising TpmCryptoProvider — see EnrollmentService.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class WindowsSoftwareCryptoProvider : ICryptoProvider, IDisposable
{
    private const string ProviderName = "Microsoft Software Key Storage Provider";
    // Deliberately NOT the TPM's "kiosk-device-key": the two stores are
    // separate, and a box that later gains a TPM must not silently sign with
    // one key while the server holds the other's public half.
    private const string KeyName = "kiosk-device-key-soft";

    private CngKey? _key;

    public bool HasKey => _key is not null;

    /// <summary>True when a software key was already persisted by an earlier
    /// run. The factory uses this to keep an enrolled kiosk on the key it
    /// actually enrolled with, even if a TPM appears later.</summary>
    public static bool KeyExists()
    {
        try { return CngKey.Exists(KeyName, new CngProvider(ProviderName)); }
        catch { return false; }
    }

    public void EnsureKeypair()
    {
        var provider = new CngProvider(ProviderName);
        if (CngKey.Exists(KeyName, provider))
        {
            _key = CngKey.Open(KeyName, provider);
            return;
        }

        Console.Error.WriteLine(
            "[security] no TPM 2.0 on this machine — generating a DPAPI-protected " +
            "software keypair. Enrollment will report tpm_attested=false.");

        // ECDSA_P256 already names its curve, so the ECCCurveName property the
        // TPM provider sets alongside it is redundant here — and worse than
        // redundant: the software KSP rejects the property on a fixed-curve
        // algorithm and NCrypt surfaces it as ERROR_INVALID_HANDLE, which is
        // what the first build of this class died on. The Platform Crypto
        // Provider tolerates the same line, which is why it survived there.
        _key = TryCreate(CngAlgorithm.ECDsaP256, provider, curveName: null)
               // Some KSP builds want the generic algorithm with the curve
               // named separately instead. Same key either way; try both
               // before giving up, because the alternative is a locked-out
               // kiosk and another trip to a machine with no keyboard.
               ?? TryCreate(new CngAlgorithm("ECDSA"), provider, curveName: "nistP256")
               ?? throw _lastCreateError!;
    }

    private CryptographicException? _lastCreateError;

    /// <summary>One key-creation attempt. Returns null on a CNG refusal so the
    /// caller can try the other spelling; the exception is kept so the final
    /// failure reports the real reason rather than a generic one.</summary>
    private CngKey? TryCreate(CngAlgorithm algorithm, CngProvider provider, string? curveName)
    {
        var creationParams = new CngKeyCreationParameters
        {
            Provider = provider,
            KeyCreationOptions = CngKeyCreationOptions.None,
            // NCryptExportKey refuses for keys created with this policy, so the
            // private half cannot be copied out through the normal API even
            // though it is software-held. Both attempts keep it: a key that
            // enrolls but can be exported is not the trade we are making.
            ExportPolicy = CngExportPolicies.None,
        };
        if (curveName is not null)
        {
            creationParams.Parameters.Add(
                new CngProperty(
                    "ECCCurveName",
                    System.Text.Encoding.Unicode.GetBytes(curveName + "\0"),
                    CngPropertyOptions.None));
        }

        try
        {
            return CngKey.Create(algorithm, KeyName, creationParams);
        }
        catch (CryptographicException ex)
        {
            _lastCreateError = ex;
            Console.Error.WriteLine(
                $"[security] key creation with {algorithm.Algorithm} refused: {ex.Message}");
            return null;
        }
    }

    public string GetPublicKeyPem()
    {
        if (_key is null) throw new InvalidOperationException("call EnsureKeypair first");
        using var ecdsa = new ECDsaCng(_key);
        return ecdsa.ExportSubjectPublicKeyInfoPem();
    }

    public Task<byte[]> SignAsync(byte[] data)
    {
        // Same lazy-open as the TPM provider: the key is persisted per-machine
        // but the CngKey handle is per-process.
        if (_key is null) EnsureKeypair();
        using var ecdsa = new ECDsaCng(_key!);
        var sig = ecdsa.SignData(data, HashAlgorithmName.SHA256, DSASignatureFormat.Rfc3279DerSequence);
        return Task.FromResult(sig);
    }

    public void DeleteKey()
    {
        if (_key is not null)
        {
            _key.Delete();
            _key = null;
            return;
        }
        try
        {
            using var k = CngKey.Open(KeyName, new CngProvider(ProviderName));
            k.Delete();
        }
        catch { }
    }

    public void Dispose()
    {
        _key?.Dispose();
        _key = null;
    }
}
