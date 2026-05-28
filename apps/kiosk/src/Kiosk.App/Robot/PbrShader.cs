using System;
using System.Numerics;
using Silk.NET.OpenGL;

namespace Kiosk.App.Robot;

/// <summary>
/// Compiles + binds the kiosk_ui-style PBR-lite shader: hemisphere fill, 3 directional
/// lights, 1 audio-driven chest point light, Reinhard-ish tone map + gamma 2.2.
/// Matches the lighting setup from RobotScene.tsx (lines 67–98) so the C# port
/// looks like the original WebGL scene.
/// </summary>
public sealed class PbrShader : IDisposable
{
    // Same shader source in both variants — only the header (#version +
    // precision) differs so it compiles on both desktop WGL (`330 core`)
    // and ANGLE/GLES backends (`300 es` + explicit float precision).
    private const string VertBody = @"
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNormal;
layout(location=2) in vec2 aUv;
uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProj;
out vec3 vWorldPos;
out vec3 vNormal;
out vec2 vUv;
void main() {
    vec4 wp = uModel * vec4(aPos, 1.0);
    vWorldPos = wp.xyz;
    vNormal = mat3(uModel) * aNormal;
    vUv = aUv;
    gl_Position = uProj * uView * wp;
}";

    private const string FragBody = @"
in vec3 vWorldPos;
in vec3 vNormal;
in vec2 vUv;
out vec4 fragColor;

uniform sampler2D uBaseColorMap;
uniform int uHasBaseColorMap;          // 0 = no texture, 1 = sample uBaseColorMap
uniform vec3 uBaseColorFactor;          // multiplied into texture (or used alone)

uniform vec3 uHemiSky;
uniform vec3 uHemiGround;
uniform float uHemiIntensity;

uniform vec3 uDir1Dir;   uniform vec3 uDir1Color;
uniform vec3 uDir2Dir;   uniform vec3 uDir2Color;
uniform vec3 uDir3Dir;   uniform vec3 uDir3Color;

uniform vec3 uChestPos;
uniform vec3 uChestColor;
uniform float uChestIntensity;

void main() {
    vec3 N = normalize(vNormal);

    vec3 albedo = uBaseColorFactor;
    if (uHasBaseColorMap == 1) {
        vec4 tex = texture(uBaseColorMap, vUv);
        // glTF stores BaseColor in sRGB; convert to linear for the lighting math.
        albedo *= pow(tex.rgb, vec3(2.2));
    }

    float hemiW = N.y * 0.5 + 0.5;
    vec3 hemi = mix(uHemiGround, uHemiSky, hemiW) * uHemiIntensity;

    float d1 = max(dot(N, uDir1Dir), 0.0);
    float d2 = max(dot(N, uDir2Dir), 0.0);
    float d3 = max(dot(N, uDir3Dir), 0.0);
    vec3 directional = d1 * uDir1Color + d2 * uDir2Color + d3 * uDir3Color;

    vec3 toChest = uChestPos - vWorldPos;
    float dist = length(toChest);
    vec3 toChestN = toChest / max(dist, 0.0001);
    float chestD = max(dot(N, toChestN), 0.0);
    float falloff = 1.0 / (1.0 + 0.5 * dist + 0.3 * dist * dist);
    vec3 chest = chestD * uChestColor * uChestIntensity * falloff;

    vec3 lit = (hemi + directional + chest) * albedo;
    lit = lit / (lit + vec3(0.5));               // simple tone map
    fragColor = vec4(pow(lit, vec3(1.0 / 2.2)), 1.0);
}";

    private readonly GL _gl;
    public uint Program { get; }

    private readonly int _uModel, _uView, _uProj;
    private readonly int _uHemiSky, _uHemiGround, _uHemiIntensity;
    private readonly int _uDir1Dir, _uDir1Color, _uDir2Dir, _uDir2Color, _uDir3Dir, _uDir3Color;
    private readonly int _uChestPos, _uChestColor, _uChestIntensity;
    private readonly int _uBaseColorFactor, _uHasBaseColorMap, _uBaseColorMap;

    public PbrShader(GL gl, bool isGles = false)
    {
        _gl = gl;
        // GLES 3.0 (ANGLE) and desktop GL 3.3 (WGL) share the language but
        // need different headers. Fragment shader also requires an explicit
        // float precision declaration under ES.
        var header = isGles
            ? "#version 300 es\nprecision highp float;\n"
            : "#version 330 core\n";
        var vs = Compile(GLEnum.VertexShader, header + VertBody);
        var fs = Compile(GLEnum.FragmentShader, header + FragBody);
        Program = gl.CreateProgram();
        gl.AttachShader(Program, vs);
        gl.AttachShader(Program, fs);
        gl.LinkProgram(Program);
        gl.GetProgram(Program, GLEnum.LinkStatus, out int linked);
        if (linked == 0)
            throw new InvalidOperationException("PBR shader link failed: " + gl.GetProgramInfoLog(Program));
        gl.DeleteShader(vs);
        gl.DeleteShader(fs);

        _uModel = gl.GetUniformLocation(Program, "uModel");
        _uView = gl.GetUniformLocation(Program, "uView");
        _uProj = gl.GetUniformLocation(Program, "uProj");
        _uHemiSky = gl.GetUniformLocation(Program, "uHemiSky");
        _uHemiGround = gl.GetUniformLocation(Program, "uHemiGround");
        _uHemiIntensity = gl.GetUniformLocation(Program, "uHemiIntensity");
        _uDir1Dir = gl.GetUniformLocation(Program, "uDir1Dir");
        _uDir1Color = gl.GetUniformLocation(Program, "uDir1Color");
        _uDir2Dir = gl.GetUniformLocation(Program, "uDir2Dir");
        _uDir2Color = gl.GetUniformLocation(Program, "uDir2Color");
        _uDir3Dir = gl.GetUniformLocation(Program, "uDir3Dir");
        _uDir3Color = gl.GetUniformLocation(Program, "uDir3Color");
        _uChestPos = gl.GetUniformLocation(Program, "uChestPos");
        _uChestColor = gl.GetUniformLocation(Program, "uChestColor");
        _uChestIntensity = gl.GetUniformLocation(Program, "uChestIntensity");
        _uBaseColorFactor = gl.GetUniformLocation(Program, "uBaseColorFactor");
        _uHasBaseColorMap = gl.GetUniformLocation(Program, "uHasBaseColorMap");
        _uBaseColorMap = gl.GetUniformLocation(Program, "uBaseColorMap");

        // BaseColor sampler always reads texture unit 0.
        gl.UseProgram(Program);
        gl.Uniform1(_uBaseColorMap, 0);
    }

    private uint Compile(GLEnum stage, string src)
    {
        uint sh = _gl.CreateShader(stage);
        _gl.ShaderSource(sh, src);
        _gl.CompileShader(sh);
        _gl.GetShader(sh, GLEnum.CompileStatus, out int ok);
        if (ok == 0)
            throw new InvalidOperationException($"shader compile ({stage}): {_gl.GetShaderInfoLog(sh)}");
        return sh;
    }

    public void Use() => _gl.UseProgram(Program);

    public unsafe void SetMatrices(Matrix4x4 model, Matrix4x4 view, Matrix4x4 proj)
    {
        _gl.UniformMatrix4(_uModel, 1, false, (float*)&model);
        _gl.UniformMatrix4(_uView, 1, false, (float*)&view);
        _gl.UniformMatrix4(_uProj, 1, false, (float*)&proj);
    }

    public void SetLights(
        Vector3 hemiSky, Vector3 hemiGround, float hemiIntensity,
        Vector3 dir1Dir, Vector3 dir1Col,
        Vector3 dir2Dir, Vector3 dir2Col,
        Vector3 dir3Dir, Vector3 dir3Col,
        Vector3 chestPos, Vector3 chestCol, float chestIntensity)
    {
        _gl.Uniform3(_uHemiSky, hemiSky.X, hemiSky.Y, hemiSky.Z);
        _gl.Uniform3(_uHemiGround, hemiGround.X, hemiGround.Y, hemiGround.Z);
        _gl.Uniform1(_uHemiIntensity, hemiIntensity);
        _gl.Uniform3(_uDir1Dir, dir1Dir.X, dir1Dir.Y, dir1Dir.Z);
        _gl.Uniform3(_uDir1Color, dir1Col.X, dir1Col.Y, dir1Col.Z);
        _gl.Uniform3(_uDir2Dir, dir2Dir.X, dir2Dir.Y, dir2Dir.Z);
        _gl.Uniform3(_uDir2Color, dir2Col.X, dir2Col.Y, dir2Col.Z);
        _gl.Uniform3(_uDir3Dir, dir3Dir.X, dir3Dir.Y, dir3Dir.Z);
        _gl.Uniform3(_uDir3Color, dir3Col.X, dir3Col.Y, dir3Col.Z);
        _gl.Uniform3(_uChestPos, chestPos.X, chestPos.Y, chestPos.Z);
        _gl.Uniform3(_uChestColor, chestCol.X, chestCol.Y, chestCol.Z);
        _gl.Uniform1(_uChestIntensity, chestIntensity);
    }

    /// <summary>Sets the per-primitive base colour. If <paramref name="hasTexture"/>
    /// is true, the shader samples uBaseColorMap at texture unit 0 and multiplies
    /// it by <paramref name="factor"/>; otherwise <paramref name="factor"/> is the
    /// final albedo.</summary>
    public void SetBaseColor(Vector3 factor, bool hasTexture)
    {
        _gl.Uniform3(_uBaseColorFactor, factor.X, factor.Y, factor.Z);
        _gl.Uniform1(_uHasBaseColorMap, hasTexture ? 1 : 0);
    }

    public void Dispose() => _gl.DeleteProgram(Program);
}
