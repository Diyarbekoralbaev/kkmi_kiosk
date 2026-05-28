using System;
using Avalonia.OpenGL;
using Silk.NET.Core.Contexts;

namespace Kiosk.App.Robot;

/// <summary>
/// Bridges Avalonia's GlInterface (which only exposes a few framebuffer methods directly)
/// to Silk.NET's INativeContext, so we can call <c>GL.GetApi(bridge)</c> and use the
/// full Silk.NET binding surface for our PBR pipeline.
/// </summary>
internal sealed class GlInterfaceBridge : INativeContext
{
    private readonly GlInterface _gl;

    public GlInterfaceBridge(GlInterface gl) => _gl = gl;

    public nint GetProcAddress(string proc, int? slot = null)
        => _gl.GetProcAddress(proc);

    public bool TryGetProcAddress(string proc, out nint addr, int? slot = null)
    {
        addr = _gl.GetProcAddress(proc);
        return addr != 0;
    }

    public void Dispose() { }
}
