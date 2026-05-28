using System;
using System.Collections.Generic;
using System.IO;
using System.Numerics;
using Silk.NET.OpenGL;
using SharpGLTF.Schema2;

namespace Kiosk.App.Robot;

/// <summary>
/// Loads a .glb file and uploads its primitives into an interleaved
/// position+normal+UV vertex buffer, plus the BaseColor texture from each
/// material. Static rendering (no skinning, no morph) — audio reactivity drives
/// scene-level transforms instead of bone/morph deltas.
///
/// Auto-scales the loaded model so its tallest dimension equals
/// <see cref="TargetHeight"/> (matches RobotScene.tsx line 130) and re-centers
/// horizontally with feet on Y=0.
/// </summary>
public sealed class GltfMesh : IDisposable
{
    public const float TargetHeight = 2.4f;
    private const int FloatsPerVertex = 8; // pos.xyz + normal.xyz + uv.xy

    public sealed class Primitive : IDisposable
    {
        public uint Vao, Vbo, Ibo;
        public int IndexCount;
        public Vector3 BaseColorFactor = new(1f, 1f, 1f);
        public GlTexture? BaseColorTexture;

        private readonly GL _gl;
        public Primitive(GL gl) => _gl = gl;
        public void Dispose()
        {
            _gl.DeleteVertexArray(Vao);
            _gl.DeleteBuffer(Vbo);
            _gl.DeleteBuffer(Ibo);
            BaseColorTexture?.Dispose();
        }
    }

    public List<Primitive> Primitives { get; } = new();
    public Vector3 BoundingMin { get; private set; }
    public Vector3 BoundingMax { get; private set; }
    public float ModelHeight { get; private set; }
    public float NormalizationScale { get; private set; }
    public Vector3 RecenterOffset { get; private set; }

    private readonly GL _gl;

    private GltfMesh(GL gl) { _gl = gl; }

    public static unsafe GltfMesh Load(GL gl, string glbPath)
    {
        var model = ModelRoot.Load(glbPath);
        var mesh = new GltfMesh(gl);

        // Cache decoded textures — many primitives often share the same material.
        var textureCache = new Dictionary<int, GlTexture>();

        // First pass: measure bounding box across all primitives in their bind pose.
        var bbMin = new Vector3(float.PositiveInfinity);
        var bbMax = new Vector3(float.NegativeInfinity);

        foreach (var node in model.LogicalNodes)
        {
            if (node.Mesh is null) continue;
            var nodeXform = node.WorldMatrix;
            foreach (var prim in node.Mesh.Primitives)
            {
                var posAccessor = prim.GetVertexAccessor("POSITION");
                if (posAccessor is null) continue;
                foreach (var p in posAccessor.AsVector3Array())
                {
                    var w = Vector3.Transform(p, nodeXform);
                    bbMin = Vector3.Min(bbMin, w);
                    bbMax = Vector3.Max(bbMax, w);
                }
            }
        }

        var size = bbMax - bbMin;
        var maxDim = MathF.Max(size.X, MathF.Max(size.Y, size.Z));
        if (maxDim <= 0f) maxDim = 1f;
        var scale = TargetHeight / maxDim;
        var center = (bbMin + bbMax) * 0.5f;
        var offset = new Vector3(-center.X, -bbMin.Y, -center.Z);

        mesh.BoundingMin = bbMin;
        mesh.BoundingMax = bbMax;
        mesh.ModelHeight = size.Y * scale;
        mesh.NormalizationScale = scale;
        mesh.RecenterOffset = offset;

        // Second pass: upload geometry + textures.
        foreach (var node in model.LogicalNodes)
        {
            if (node.Mesh is null) continue;
            var world = node.WorldMatrix;
            foreach (var prim in node.Mesh.Primitives)
            {
                var posAcc = prim.GetVertexAccessor("POSITION");
                if (posAcc is null) continue;
                var positions = posAcc.AsVector3Array();
                var normalsAcc = prim.GetVertexAccessor("NORMAL");
                IList<Vector3>? normals = normalsAcc?.AsVector3Array();
                var uvAcc = prim.GetVertexAccessor("TEXCOORD_0");
                IList<Vector2>? uvs = uvAcc?.AsVector2Array();

                var vCount = positions.Count;
                var vbo = new float[vCount * FloatsPerVertex];
                for (int i = 0; i < vCount; i++)
                {
                    var p = Vector3.Transform(positions[i], world);
                    p = (p + offset) * scale;
                    vbo[i * FloatsPerVertex + 0] = p.X;
                    vbo[i * FloatsPerVertex + 1] = p.Y;
                    vbo[i * FloatsPerVertex + 2] = p.Z;

                    Vector3 n = normals is not null ? normals[i] : Vector3.UnitY;
                    n = Vector3.TransformNormal(n, world);
                    if (n.LengthSquared() > 0) n = Vector3.Normalize(n);
                    vbo[i * FloatsPerVertex + 3] = n.X;
                    vbo[i * FloatsPerVertex + 4] = n.Y;
                    vbo[i * FloatsPerVertex + 5] = n.Z;

                    Vector2 uv = uvs is not null ? uvs[i] : Vector2.Zero;
                    vbo[i * FloatsPerVertex + 6] = uv.X;
                    vbo[i * FloatsPerVertex + 7] = uv.Y;
                }

                var indicesEnumerable = prim.GetIndices();
                var indices = new uint[indicesEnumerable.Count];
                for (int i = 0; i < indicesEnumerable.Count; i++)
                    indices[i] = indicesEnumerable[i];

                var p1 = new Primitive(gl)
                {
                    IndexCount = indices.Length,
                    BaseColorFactor = ExtractBaseColorFactor(prim),
                    BaseColorTexture = LoadBaseColorTexture(gl, prim, textureCache),
                };
                p1.Vao = gl.GenVertexArray();
                p1.Vbo = gl.GenBuffer();
                p1.Ibo = gl.GenBuffer();

                gl.BindVertexArray(p1.Vao);
                gl.BindBuffer(GLEnum.ArrayBuffer, p1.Vbo);
                fixed (float* vp = vbo)
                    gl.BufferData(GLEnum.ArrayBuffer, (nuint)(vbo.Length * sizeof(float)), vp, GLEnum.StaticDraw);

                gl.BindBuffer(GLEnum.ElementArrayBuffer, p1.Ibo);
                fixed (uint* ip = indices)
                    gl.BufferData(GLEnum.ElementArrayBuffer, (nuint)(indices.Length * sizeof(uint)), ip, GLEnum.StaticDraw);

                int stride = FloatsPerVertex * sizeof(float);
                gl.EnableVertexAttribArray(0);
                gl.VertexAttribPointer(0, 3, GLEnum.Float, false, (uint)stride, (void*)0);
                gl.EnableVertexAttribArray(1);
                gl.VertexAttribPointer(1, 3, GLEnum.Float, false, (uint)stride, (void*)(3 * sizeof(float)));
                gl.EnableVertexAttribArray(2);
                gl.VertexAttribPointer(2, 2, GLEnum.Float, false, (uint)stride, (void*)(6 * sizeof(float)));

                gl.BindVertexArray(0);

                mesh.Primitives.Add(p1);
            }
        }

        return mesh;
    }

    private static Vector3 ExtractBaseColorFactor(MeshPrimitive prim)
    {
        var mat = prim.Material;
        if (mat is null) return new Vector3(0.55f, 0.62f, 0.7f);
        var ch = mat.FindChannel("BaseColor");
        if (!ch.HasValue) return new Vector3(0.55f, 0.62f, 0.7f);
        // Some materials have a texture but no scalar color in the channel —
        // SharpGLTF throws on .Color in that case. Default to white when so.
        try
        {
            var c = ch.Value.Color;
            return new Vector3(c.X, c.Y, c.Z);
        }
        catch
        {
            return Vector3.One;
        }
    }

    private static GlTexture? LoadBaseColorTexture(GL gl, MeshPrimitive prim, Dictionary<int, GlTexture> cache)
    {
        var mat = prim.Material;
        if (mat is null) return null;
        var ch = mat.FindChannel("BaseColor");
        if (!ch.HasValue || ch.Value.Texture is null) return null;
        var image = ch.Value.Texture.PrimaryImage;
        if (image is null) return null;
        var imgIndex = image.LogicalIndex;
        if (cache.TryGetValue(imgIndex, out var existing)) return existing;
        var bytes = image.Content.Content.ToArray();
        var tex = new GlTexture(gl, bytes);
        cache[imgIndex] = tex;
        return tex;
    }

    public unsafe void Draw(GL gl)
    {
        foreach (var p in Primitives)
        {
            p.BaseColorTexture?.Bind(0);
            gl.BindVertexArray(p.Vao);
            gl.DrawElements(GLEnum.Triangles, (uint)p.IndexCount, GLEnum.UnsignedInt, (void*)0);
        }
        gl.BindVertexArray(0);
    }

    public void Dispose()
    {
        foreach (var p in Primitives) p.Dispose();
        Primitives.Clear();
    }
}
