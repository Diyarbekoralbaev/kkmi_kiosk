namespace Kiosk.App;

/// <summary>
/// Compile-time switch surfaced to XAML via the <c>x:Static</c> markup so we
/// can hide debug-only UI (the top-right nav bar) in Release builds without
/// shipping the same XAML twice.
///
/// `IsDebugBuild` flips with the standard `DEBUG` symbol — true in `dotnet
/// build -c Debug`, false under `-c Release` (which is what publish.win.sh
/// uses). The constant is folded by the compiler so there is no runtime
/// conditional in the AOT'd binary.
/// </summary>
public static class DebugFlags
{
#if DEBUG
    public const bool IsDebugBuild = true;
#else
    public const bool IsDebugBuild = false;
#endif
}
