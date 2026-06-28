using Avalonia.Controls;

namespace Kiosk.App.Pages;

/// <summary>AI voice murajat preview. Read-only — the agent pushes the draft
/// (text + phone, plus name for a new citizen) over the WS and the bound
/// SessionStore fields render it. Submission is driven by voice.</summary>
public partial class SubmitPage : UserControl
{
    public SubmitPage()
    {
        InitializeComponent();
    }
}
