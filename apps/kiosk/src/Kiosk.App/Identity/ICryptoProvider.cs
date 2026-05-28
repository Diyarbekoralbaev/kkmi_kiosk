using System;
using System.Threading.Tasks;

namespace Kiosk.App.Identity;

/// <summary>
/// Abstracts the device's per-device ECDSA P-256 keypair.
///
/// Two implementations:
/// - <see cref="TpmCryptoProvider"/>: Windows. Keys live inside the TPM via
///   Microsoft Platform Crypto Provider (NCrypt). Private key NEVER leaves
///   the chip — even SYSTEM-level extraction is blocked by the TPM.
/// - <see cref="SoftCryptoProvider"/>: Linux DEV ONLY. File-stored key. Used
///   so we can develop on Ubuntu; production is Windows + TPM.
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
    /// <exception cref="TpmNotAvailableException">Production-only: TPM is required and missing.</exception>
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
