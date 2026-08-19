using System;
using System.Threading.Tasks;

namespace Kiosk.App.Identity;

/// <summary>
/// Abstracts the device's per-device ECDSA P-256 keypair.
///
/// Three implementations:
/// - <see cref="TpmCryptoProvider"/>: Windows with TPM 2.0. Keys live inside
///   the TPM via Microsoft Platform Crypto Provider (NCrypt). Private key
///   NEVER leaves the chip — even SYSTEM-level extraction is blocked.
/// - <see cref="WindowsSoftwareCryptoProvider"/>: Windows without TPM 2.0.
///   Non-exportable CNG key in the software KSP, DPAPI-encrypted at rest.
///   Chosen only when the firmware exposes no TPM at all.
/// - <see cref="SoftCryptoProvider"/>: Linux DEV ONLY. Plaintext PEM on disk.
///   Never selected on Windows.
///
/// Usage shape:
///   1. <see cref="EnsureKeypair"/> at first run → generates the keypair
///      under a stable name. Idempotent — subsequent runs reuse it.
///   2. <see cref="GetPublicKeyPem"/> for the enrollment request.
///   3. <see cref="SignAsync"/> for each per-request nonce signature.
///   4. <see cref="DeleteKey"/> when the device is revoked — wipes the key.
/// </summary>
public interface ICryptoProvider
{
    /// <summary>Idempotent: creates the persisted keypair if missing, otherwise no-op.
    /// The keypair is per-machine, not per-device — there is exactly one kiosk install
    /// per box, so a fixed key name suffices.</summary>
    /// <exception cref="TpmNotAvailableException">Thrown by
    /// <see cref="TpmCryptoProvider"/> when the TPM is gone. The factory
    /// normally picks a provider that cannot raise it; enrollment catches it
    /// as a last resort and demotes to software.</exception>
    void EnsureKeypair();

    /// <summary>SubjectPublicKeyInfo PEM ("-----BEGIN PUBLIC KEY-----..."). Server stores this.</summary>
    string GetPublicKeyPem();

    /// <summary>ECDSA P-256 SHA-256 over <paramref name="data"/>. Returns RFC 3279 DER signature
    /// (the same encoding Python's cryptography lib expects for ec.ECDSA(SHA256)).</summary>
    Task<byte[]> SignAsync(byte[] data);

    /// <summary>Wipes the persisted key. Called on revocation so the kiosk can't sign anything
    /// further until it re-enrolls and gets a brand-new keypair.</summary>
    void DeleteKey();

    /// <summary>True iff the keypair currently exists on disk/TPM.</summary>
    bool HasKey { get; }
}

public sealed class TpmNotAvailableException : Exception
{
    public TpmNotAvailableException(string message, Exception? inner = null)
        : base(message, inner) { }
}
