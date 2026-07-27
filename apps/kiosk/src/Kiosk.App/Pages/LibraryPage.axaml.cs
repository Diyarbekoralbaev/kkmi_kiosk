using Avalonia.Controls;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>"Coming soon" screen for the library menu. No voice session is
/// started here: with no catalogue connected the agent has no tools and nothing
/// to say beyond what the page already states, so opening a Gemini session
/// would only burn quota.</summary>
public partial class LibraryPage : UserControl
{
    public LibraryPage()
    {
        InitializeComponent();
        DataContext = SessionStore.Current;
    }
}
