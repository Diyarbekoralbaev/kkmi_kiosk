using System;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.Threading.Tasks;

namespace Kiosk.App.Identity;

/// <summary>
/// Windows-only ECDSA P-256 backed by the TPM via Microsoft Platform Crypto
/// Provider (the standard NCrypt KSP that targets TPM 2.0).
///
/// What the TPM gives us: the private key is generated INSIDE the TPM chip
/// and is non-exportable. Even a kernel-mode attacker cannot read the bytes
/// — it's not in OS memory. Signing happens via NCryptSignHash; the TPM
/// returns a signature without ever exposing the key.
///
/// Constraints:
/// - Requires Windows 10+ with TPM 2.0 (Win11 mandates it; most Win10 since
///   2016 has it as fTPM in the CPU).
/// - On TPM-less hardware <see cref="EnsureKeypair"/> throws
///   <see cref="TpmNotAvailableException"/>. There is no fallback by design.
///
/// Naming: keys are persisted under "kiosk-{deviceId}". Idempotent open-or-
/// create — we never silently overwrite an existing key.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class TpmCryptoProvider : ICryptoProvider, IDisposable
{
    private const string ProviderName = "Microsoft Platform Crypto Provider";
    private const string KeyName = "kiosk-device-key";
    private CngKey? _key;

    public bool HasKey => _key is not null;

    public void EnsureKeypair()
    {
        var provider = new CngProvider(ProviderName);

        // Probe the provider first. If MSPCP isn't registered (no TPM), this
        // throws CryptographicException with HResult NTE_PROV_TYPE_NOT_DEF
        // or NTE_NOT_FOUND depending on the failure mode.
        bool exists;
        try
        {
            exists = CngKey.Exists(KeyName, provider);
        }
        catch (CryptographicException ex)
        {
            throw new TpmNotAvailableException(
                "TPM 2.0 talab qilinadi. Bul mashinada TPM joq yamasa óshirilgen.",
                ex);
        }

        if (exists)
        {
            _key = CngKey.Open(KeyName, provider);
            return;
        }

        var creationParams = new CngKeyCreationParameters
        {
            Provider = provider,
            // Keys belong to the local user account. MachineKey would require
            // admin to create and is overkill — the kiosk app runs as the
            // dedicated `kiosk` user.
            KeyCreationOptions = CngKeyCreationOptions.None,
            // Hard non-exportable. Even with admin rights, NCryptExportKey
            // refuses for keys created with this policy.
            ExportPolicy = CngExportPolicies.None,
        };
        // Force ECDSA P-256 by setting the algorithm group + curve.
        creationParams.Parameters.Add(
            new CngProperty(
                "ECCCurveName",
                System.Text.Encoding.Unicode.GetBytes("nistP256\0"),
                CngPropertyOptions.None));

        try
        {
            _key = CngKey.Create(CngAlgorithm.ECDsaP256, KeyName, creationParams);
        }
        catch (CryptographicException ex)
        {
            throw new TpmNotAvailableException(
                "TPM keypair'ni hosil qilıp bolmadı. TPM 2.0 mavjud bólıwı kerek.",
                ex);
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
        // Lazy-init: persisted TPM key is process-shared, the CngKey handle
        // is per-process. Open it on first sign if not already loaded.
        if (_key is null) EnsureKeypair();
        using var ecdsa = new ECDsaCng(_key!);
        // Rfc3279DerSequence: SEQUENCE { INTEGER r, INTEGER s }, the same
        // encoding Python's cryptography.hazmat ECDSA verify expects.
        var sig = ecdsa.SignData(data, HashAlgorithmName.SHA256, DSASignatureFormat.Rfc3279DerSequence);
        return Task.FromResult(sig);
    }

    public void DeleteKey()
    {
        if (_key is not null)
        {
            // CngKey.Delete is the managed wrapper for NCryptDeleteKey —
            // removes the persisted key from the TPM/KSP entirely.
            _key.Delete();
            _key = null;
        }
        else
        {
            try
            {
                using var k = CngKey.Open(KeyName, new CngProvider(ProviderName));
                k.Delete();
            }
            catch { }
        }
    }

    public void Dispose()
    {
        _key?.Dispose();
        _key = null;
    }
}
