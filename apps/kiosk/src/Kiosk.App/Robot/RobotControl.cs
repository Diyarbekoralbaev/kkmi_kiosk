using System;
using System.Diagnostics;
using System.IO;
using System.Numerics;
using Avalonia;
using Avalonia.OpenGL;
using Avalonia.OpenGL.Controls;
using Kiosk.App.Audio;
using Silk.NET.OpenGL;

namespace Kiosk.App.Robot;

/// <summary>
/// 3D robot scene host. Static mesh + scene-level animations driven by the
/// playback FFT. The mesh, lights, and tone-map mirror RobotScene.tsx so the
/// kiosk_ui look ports cleanly. Head/mouth animations (which require skinning
/// + morph targets) are out of scope for this slice; the chest glow, vertical
/// bob, and scene rotation provide the "robot is alive" cue when the agent
/// speaks.
/// </summary>
public sealed class RobotControl : OpenGlControlBase
{
    public static readonly StyledProperty<AnalyserNode?> AnalyserProperty =
        AvaloniaProperty.Register<RobotControl, AnalyserNode?>(nameof(Analyser));

    public AnalyserNode? Analyser
    {
        get => GetValue(AnalyserProperty);
        set => SetValue(AnalyserProperty, value);
    }

    private GL? _gl;
    private GlInterfaceBridge? _bridge;
    private PbrShader? _shader;
    private GltfMesh? _mesh;
    private readonly AudioReactiveAnimator _animator = new();
    private Stopwatch? _clock;
    private float _lastSec;
    private string _initStatus = "(not initialized)";

    private static readonly Vector3 HemiSky = HexToLinear(0xa8d8ff);
    private static readonly Vector3 HemiGround = HexToLinear(0x081424);
    private const float HemiIntensity = 0.6f;

    private static readonly Vector3 KeyLightDir = Vector3.Normalize(new Vector3(4f, 6f, 6f));
    private static readonly Vector3 KeyLightColor = HexToLinear(0xffffff) * 1.0f;

    private static readonly Vector3 RimBlueDir = Vector3.Normalize(new Vector3(-5f, 3f, -3f));
    private static readonly Vector3 RimBlueColor = HexToLinear(0x40b0e0) * 0.8f;

    private static readonly Vector3 RimCyanDir = Vector3.Normalize(new Vector3(5f, 1f, -4f));
    private static readonly Vector3 RimCyanColor = HexToLinear(0x7ee3ff) * 0.6f;

    private static readonly Vector3 ChestPos = new(0f, 1.25f, 0.25f);
    private static readonly Vector3 ChestBaseColor = HexToLinear(0x40b0e0);

    protected override void OnOpenGlInit(GlInterface gl)
    {
        // ALL diagnostic output goes to the kiosk's crash.log so a Windows
        // deploy with no console attached can still report why the robot is
        // (or isn't) rendering. Every step is wrapped because OnOpenGlInit
        // exceptions are silently swallowed by Avalonia's compositor — the
        // surface just stays blank, leaking the parent Border's background.
        try
        {
            _bridge = new GlInterfaceBridge(gl);
            _gl = GL.GetApi(_bridge);

            var version = _gl.GetStringS(StringName.Version) ?? "(null)";
            var vendor = _gl.GetStringS(StringName.Vendor) ?? "(null)";
            var renderer = _gl.GetStringS(StringName.Renderer) ?? "(null)";
            var glsl = _gl.GetStringS(StringName.ShadingLanguageVersion) ?? "(null)";
            LogLine($"GL init: version={version} vendor={vendor} renderer={renderer} glsl={glsl}");

            _gl.Enable(GLEnum.DepthTest);
            _gl.Enable(GLEnum.CullFace);
            _gl.CullFace(GLEnum.Back);
            _gl.ClearColor(0.039f, 0.098f, 0.161f, 1f);

            try
            {
                _shader = new PbrShader(_gl, isGles: version.Contains("OpenGL ES", StringComparison.OrdinalIgnoreCase));
                LogLine("GL init: shader compiled OK");
            }
            catch (Exception ex)
            {
                _initStatus = $"shader: {ex.Message}";
                LogLine($"GL init: SHADER FAILED — {ex}");
                _shader = null;
            }

            var glbPath = Path.Combine(AppContext.BaseDirectory, "Assets", "robot.glb");
            if (File.Exists(glbPath))
            {
                try
                {
                    _mesh = GltfMesh.Load(_gl, glbPath);
                    LogLine($"GL init: mesh loaded from {glbPath} ({new FileInfo(glbPath).Length} bytes)");
                }
                catch (Exception ex)
                {
                    _initStatus = $"mesh: {ex.Message}";
                    LogLine($"GL init: MESH LOAD FAILED — {ex}");
                    _mesh = null;
                }
            }
            else
            {
                _initStatus = "mesh: robot.glb missing";
                LogLine($"GL init: robot.glb NOT FOUND at {glbPath}");
            }

            _clock = Stopwatch.StartNew();
            _lastSec = 0f;
            if (_shader is not null && _mesh is not null)
                _initStatus = "ok";
        }
        catch (Exception ex)
        {
            _initStatus = $"init: {ex.Message}";
            LogLine($"GL init: TOP-LEVEL FAILED — {ex}");
        }
    }

    /// <summary>Append a timestamped line to crash.log next to settings.json.
    /// Same file the AppDomain unhandled-exception handler writes to so the
    /// operator can grab a single log from %APPDATA%\Kiosk\crash.log when
    /// debugging a black/white robot panel on real hardware.</summary>
    private static void LogLine(string msg)
    {
        try
        {
            var settingsPath = Kiosk.App.Settings.KioskSettings.SettingsPath;
            var dir = Path.GetDirectoryName(settingsPath) ?? ".";
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, "crash.log");
            File.AppendAllText(path, $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] [robot] {msg}\n");
        }
        catch { /* logging must never crash the render path */ }
        Console.Error.WriteLine($"[robot] {msg}");
    }

    protected override void OnOpenGlDeinit(GlInterface gl)
    {
        _mesh?.Dispose();
        _mesh = null;
        _shader?.Dispose();
        _shader = null;
        _gl?.Dispose();
        _gl = null;
        _bridge?.Dispose();
        _bridge = null;
    }

    protected override void OnOpenGlRender(GlInterface gl, int fb)
    {
        if (_gl is null)
        {
            // No GL context at all — Avalonia fell back to software or
            // failed to init the WGL/ANGLE surface. Nothing we can clear;
            // the parent Border's background will show through.
            RequestNextFrameRendering();
            return;
        }

        var w = (int)Bounds.Width;
        var h = (int)Bounds.Height;
        if (w <= 0 || h <= 0) { RequestNextFrameRendering(); return; }

        // Always bind + clear, even if the shader/mesh failed to load. This
        // way the operator gets a visible navy panel (instead of leaking the
        // Border's white through a transparent GL surface) — they can tell
        // immediately that GL is alive but the model didn't compile, which
        // matches the diagnostic line in crash.log.
        _gl.BindFramebuffer(GLEnum.Framebuffer, (uint)fb);
        _gl.Viewport(0, 0, (uint)w, (uint)h);
        _gl.Clear((uint)(ClearBufferMask.ColorBufferBit | ClearBufferMask.DepthBufferBit));

        if (_shader is null) { RequestNextFrameRendering(); return; }

        var now = (float)(_clock!.Elapsed.TotalSeconds);
        var dt = now - _lastSec;
        _lastSec = now;

        _animator.Analyser = Analyser;
        _animator.Tick(dt);

        if (_mesh is null)
        {
            // Asset missing — pulse the clear color so the operator notices.
            var pulse = (MathF.Sin(now * 1.5f) + 1f) * 0.5f * 0.06f;
            _gl.ClearColor(0.039f + pulse, 0.098f + pulse * 0.3f, 0.161f, 1f);
            RequestNextFrameRendering();
            return;
        }

        var modelHeight = _mesh.ModelHeight;
        var camPos = new Vector3(0f, modelHeight * 0.55f, 4.2f);
        var camTgt = new Vector3(0f, modelHeight * 0.5f, 0f);
        var view = Matrix4x4.CreateLookAt(camPos, camTgt, Vector3.UnitY);
        var aspect = w / (float)h;
        var proj = Matrix4x4.CreatePerspectiveFieldOfView(
            MathF.PI * 35f / 180f, aspect, 0.1f, 200f);

        var bobMatrix = Matrix4x4.CreateTranslation(0f, _animator.Bob, 0f);
        var rotMatrix = Matrix4x4.CreateRotationY(_animator.SceneRotationY);
        var model = rotMatrix * bobMatrix;

        _shader.Use();
        _shader.SetMatrices(model, view, proj);

        // Animator shifts the chest light hue toward cyan with intensity.
        var chestColor = HexToLinear(0x40b0e0);
        _shader.SetLights(
            HemiSky, HemiGround, HemiIntensity,
            KeyLightDir, KeyLightColor,
            RimBlueDir, RimBlueColor,
            RimCyanDir, RimCyanColor,
            ChestPos, chestColor, _animator.ChestIntensity);

        // Per-primitive: bind BaseColor texture (if any) + factor, then draw.
        foreach (var p in _mesh.Primitives)
        {
            _shader.SetBaseColor(p.BaseColorFactor, p.BaseColorTexture is not null);
            p.BaseColorTexture?.Bind(0);

            _gl.BindVertexArray(p.Vao);
            unsafe { _gl.DrawElements(GLEnum.Triangles, (uint)p.IndexCount, GLEnum.UnsignedInt, (void*)0); }
        }
        _gl.BindVertexArray(0);

        RequestNextFrameRendering();
    }

    private static Vector3 HexToLinear(uint rgb)
    {
        // sRGB → linear (gamma 2.2 inverse)
        float r = ((rgb >> 16) & 0xff) / 255f;
        float g = ((rgb >> 8) & 0xff) / 255f;
        float b = (rgb & 0xff) / 255f;
        return new Vector3(MathF.Pow(r, 2.2f), MathF.Pow(g, 2.2f), MathF.Pow(b, 2.2f));
    }
}
