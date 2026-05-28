using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using PortAudioSharp;

namespace Kiosk.App.Audio;

/// <summary>One PortAudio device with its host API. On Windows a single
/// physical mic appears once per host API (MME / DirectSound / WASAPI /
/// WDM-KS) — the user-visible <see cref="DisplayName"/> includes the API
/// in brackets so duplicates aren't ambiguous: "Microphone (USB) [WASAPI]"
/// vs the same hardware under "[MME]".</summary>
public sealed record AudioDeviceInfo(
    int Index,
    string Name,
    string HostApiName,
    bool IsInput,
    bool IsOutput)
{
    /// <summary>The string we put in dropdowns + persist to settings.
    /// Embeds the host API so the pin survives reboot, and so two physically
    /// distinct devices with the same name on different APIs don't collide.</summary>
    public string DisplayName => string.IsNullOrEmpty(HostApiName)
        ? Name
        : $"{Name} [{HostApiName}]";
}

/// <summary>
/// Snapshot of the host's PortAudio devices for the admin settings page.
///
/// Lifecycle: PortAudio must be initialised before enumeration. The settings
/// page calls <see cref="EnumerateInputs"/> / <see cref="EnumerateOutputs"/>
/// while the runtime is OFF (or PortAudio was never started), so we
/// init-and-terminate around each call. Cheap on Linux/PipeWire.
/// </summary>
public static class AudioDeviceList
{
    // ── Native PortAudio host-API binding ───────────────────────────────
    // PortAudioSharp2 1.0.6 exposes DeviceInfo.hostApi (an int index) but
    // no way to map that index to a human name. We P/Invoke straight into
    // libportaudio for Pa_GetHostApiInfo. AOT-safe: no reflection.
    [StructLayout(LayoutKind.Sequential)]
    private struct PaHostApiInfoNative
    {
        public int structVersion;
        public int type;
        public IntPtr name;     // const char* — Marshal back to string
        public int deviceCount;
        public int defaultInputDevice;
        public int defaultOutputDevice;
    }

    [DllImport("portaudio", CallingConvention = CallingConvention.Cdecl, EntryPoint = "Pa_GetHostApiInfo")]
    private static extern IntPtr Pa_GetHostApiInfo(int hostApi);

    private static string ResolveHostApiName(int hostApiIndex)
    {
        try
        {
            var ptr = Pa_GetHostApiInfo(hostApiIndex);
            if (ptr == IntPtr.Zero) return "";
            var info = Marshal.PtrToStructure<PaHostApiInfoNative>(ptr);
            return Marshal.PtrToStringAnsi(info.name) ?? "";
        }
        catch
        {
            // Native call missing / library not loaded — degrade silently to
            // unbracketed name. Better to show "Microphone (USB)" than crash
            // the admin window during enumeration.
            return "";
        }
    }

    public static IReadOnlyList<AudioDeviceInfo> EnumerateInputs() => Enumerate(input: true);
    public static IReadOnlyList<AudioDeviceInfo> EnumerateOutputs() => Enumerate(input: false);

    /// <summary>Resolves a persisted DisplayName back to a current PortAudio
    /// index. Falls back to name-only match (for settings saved before the
    /// host-API suffix existed). Returns -1 if nothing matches; callers
    /// should then bail to <c>PortAudio.DefaultInputDevice</c>.</summary>
    public static int FindIndexByDisplayName(string? displayName, bool input)
    {
        if (string.IsNullOrEmpty(displayName)) return -1;
        PortAudioLifecycle.Init();
        try
        {
            for (int i = 0; i < PortAudio.DeviceCount; i++)
            {
                var info = PortAudio.GetDeviceInfo(i);
                var matches = input ? info.maxInputChannels > 0 : info.maxOutputChannels > 0;
                if (!matches) continue;
                var apiName = ResolveHostApiName(info.hostApi);
                var disp = string.IsNullOrEmpty(apiName) ? info.name : $"{info.name} [{apiName}]";
                if (string.Equals(disp, displayName, StringComparison.OrdinalIgnoreCase))
                    return i;
                // Backward-compat for pre-host-API pins.
                if (string.Equals(info.name, displayName, StringComparison.OrdinalIgnoreCase))
                    return i;
            }
            return -1;
        }
        finally
        {
            PortAudioLifecycle.Terminate();
        }
    }

    private static IReadOnlyList<AudioDeviceInfo> Enumerate(bool input)
    {
        PortAudioLifecycle.Init();
        try
        {
            var list = new List<AudioDeviceInfo>();
            for (int i = 0; i < PortAudio.DeviceCount; i++)
            {
                var info = PortAudio.GetDeviceInfo(i);
                var matches = input ? info.maxInputChannels > 0 : info.maxOutputChannels > 0;
                if (!matches) continue;
                // WASAPI on Windows synthesises a "loopback" capture device for
                // every output: same name + maxInputChannels > 0. Visually it
                // shows up next to the real speaker in the input dropdown and
                // when opened it returns dead silence (nothing is playing) —
                // user thinks the mic is broken. Filter these from the input
                // list. Real microphones don't get the "(loopback)" tag.
                if (input && IsLoopbackName(info.name)) continue;
                var apiName = ResolveHostApiName(info.hostApi);
                list.Add(new AudioDeviceInfo(
                    i,
                    info.name,
                    apiName,
                    info.maxInputChannels > 0,
                    info.maxOutputChannels > 0));
            }
            return list;
        }
        finally
        {
            PortAudioLifecycle.Terminate();
        }
    }

    private static bool IsLoopbackName(string name)
    {
        if (string.IsNullOrEmpty(name)) return false;
        // PortAudio WASAPI loopback names typically embed "(loopback)" or
        // "loopback:" — match both case-insensitively. Belt-and-suspenders:
        // some drivers also emit "Stereo Mix" which is a similar output-tap.
        return name.IndexOf("(loopback)", StringComparison.OrdinalIgnoreCase) >= 0
            || name.StartsWith("loopback:", StringComparison.OrdinalIgnoreCase)
            || name.IndexOf("stereo mix", StringComparison.OrdinalIgnoreCase) >= 0
            || name.IndexOf("what u hear", StringComparison.OrdinalIgnoreCase) >= 0;
    }
}
