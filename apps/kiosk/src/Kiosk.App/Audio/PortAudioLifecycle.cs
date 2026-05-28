using PortAudioSharp;

namespace Kiosk.App.Audio;

/// <summary>
/// PortAudio.Initialize/Terminate are global; ref-count so capture and playback
/// can both initialize without tearing each other down.
/// </summary>
internal static class PortAudioLifecycle
{
    private static int s_refCount;
    private static readonly object s_lock = new();

    public static void Init()
    {
        lock (s_lock)
        {
            if (s_refCount++ == 0) PortAudio.Initialize();
        }
    }

    public static void Terminate()
    {
        lock (s_lock)
        {
            if (--s_refCount == 0) PortAudio.Terminate();
        }
    }
}
