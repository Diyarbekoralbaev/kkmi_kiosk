using System;
using Silk.NET.OpenGL;
using StbImageSharp;

namespace Kiosk.App.Robot;

/// <summary>
/// Decodes an image (JPEG / PNG) from raw bytes via stb_image and uploads it
/// as an OpenGL 2D texture. Used for the GLB BaseColor map — without this the
/// robot was rendered against a flat white factor and looked uniformly pale.
/// </summary>
public sealed class GlTexture : IDisposable
{
    private readonly GL _gl;
    public uint Handle { get; }
    public int Width { get; }
    public int Height { get; }

    public unsafe GlTexture(GL gl, byte[] imageBytes)
    {
        _gl = gl;

        // glTF UVs and OpenGL texture data already line up if we upload the
        // image as stored (top row first). stb_image's default does that.
        // Flipping vertically here would invert V in the shader and produce
        // the patchwork look where parts of one body region get sampled from
        // the wrong half of the texture sheet.
        StbImage.stbi_set_flip_vertically_on_load(0);
        var img = ImageResult.FromMemory(imageBytes, ColorComponents.RedGreenBlueAlpha);
        Width = img.Width;
        Height = img.Height;

        Handle = gl.GenTexture();
        gl.BindTexture(TextureTarget.Texture2D, Handle);
        fixed (byte* p = img.Data)
        {
            gl.TexImage2D(TextureTarget.Texture2D, 0,
                InternalFormat.Rgba8, (uint)Width, (uint)Height, 0,
                PixelFormat.Rgba, PixelType.UnsignedByte, p);
        }
        gl.GenerateMipmap(TextureTarget.Texture2D);
        gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMinFilter,
            (int)GLEnum.LinearMipmapLinear);
        gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureMagFilter,
            (int)GLEnum.Linear);
        gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapS, (int)GLEnum.Repeat);
        gl.TexParameter(TextureTarget.Texture2D, TextureParameterName.TextureWrapT, (int)GLEnum.Repeat);
        gl.BindTexture(TextureTarget.Texture2D, 0);
    }

    public void Bind(uint unit = 0)
    {
        _gl.ActiveTexture(TextureUnit.Texture0 + (int)unit);
        _gl.BindTexture(TextureTarget.Texture2D, Handle);
    }

    public void Dispose() => _gl.DeleteTexture(Handle);
}
