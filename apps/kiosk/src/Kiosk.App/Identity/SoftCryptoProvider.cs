using System;
using System.IO;
using System.Security.Cryptography;
using System.Threading.Tasks;

namespace Kiosk.App.Identity;

/// <summary>
/// DEV ONLY — Linux/macOS fallback: ECDSA P-256 with the private key stored
/// as PKCS#8 PEM in $XDG_DATA_HOME/joqari-kenes/device-key.pem (mode 0600).
///
/// **Not for production.** Production is Windows + TPM. This exists so we
/// can develop and test on Ubuntu without a TPM emulator. The build pipeline
/// (publish.win.sh) ships only the Windows binary, so this code path never
/// executes in the field.
/// </summary>
public sealed class SoftCryptoProvider : ICryptoProvider, IDisposable
{
    private static readonly string KeyPath = ResolveKeyPath();
    private ECDsa? _ecdsa;

    public bool HasKey => _ecdsa is not null;

    public void EnsureKeypair()
    {
        if (File.Exists(KeyPath))
        {
            var pem = File.ReadAllText(KeyPath);
            _ecdsa = ECDsa.Create();
            _ecdsa.ImportFromPem(pem);
            return;
        }

        Console.Error.WriteLine(
            "[security] DEV mode — generating SOFT ECDSA keypair on disk. " +
            "PRODUCTION must use Windows TPM via TpmCryptoProvider.");

        _ecdsa = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var pkcs8 = _ecdsa.ExportPkcs8PrivateKeyPem();
        Directory.CreateDirectory(Path.GetDirectoryName(KeyPath)!);
        File.WriteAllText(KeyPath, pkcs8);
        // Best-effort 0600 on Unix; on Windows this isn't reachable in dev,
        // but guard anyway since the file path resolves on any OS.
        if (!OperatingSystem.IsWindows())
        {
            try
            {
                File.SetUnixFileMode(KeyPath, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            }
            catch { }
        }
    }

    public string GetPublicKeyPem()
    {
        if (_ecdsa is null) throw new InvalidOperationException("call EnsureKeypair first");
        return _ecdsa.ExportSubjectPublicKeyInfoPem();
    }

    public Task<byte[]> SignAsync(byte[] data)
    {
        // Lazy-init: EnsureKeypair is process-local, but the on-disk PEM is
        // shared across processes (--enroll then --ws-test). Auto-load if a
        // previous run already wrote the key.
        if (_ecdsa is null) EnsureKeypair();
        var sig = _ecdsa!.SignData(data, HashAlgorithmName.SHA256, DSASignatureFormat.Rfc3279DerSequence);
        return Task.FromResult(sig);
    }

    public void DeleteKey()
    {
        _ecdsa?.Dispose();
        _ecdsa = null;
        try { File.Delete(KeyPath); } catch { }
    }

    public void Dispose()
    {
        _ecdsa?.Dispose();
        _ecdsa = null;
    }

    private static string ResolveKeyPath()
    {
        var xdg = Environment.GetEnvironmentVariable("XDG_DATA_HOME");
        var baseDir = !string.IsNullOrEmpty(xdg)
            ? xdg
            : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share");
        return Path.Combine(baseDir, "joqari-kenes", "device-key.pem");
    }
}
