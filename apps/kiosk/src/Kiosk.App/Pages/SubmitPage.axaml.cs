using System.ComponentModel;
using Avalonia.Controls;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

public partial class SubmitPage : UserControl
{
    public SubmitPage()
    {
        InitializeComponent();
        Loaded += (_, _) =>
        {
            SessionStore.Current.PropertyChanged += OnSessionChanged;
            UpdateStepHighlights();
        };
        Unloaded += (_, _) => SessionStore.Current.PropertyChanged -= OnSessionChanged;
    }

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SessionStore.SubmitStep))
            UpdateStepHighlights();
    }

    private void UpdateStepHighlights()
    {
        // Bind active class to current step. The progression is set by the
        // backend tool calls via OnPreview / OnSubmitted on SessionStore.
        var step = SessionStore.Current.SubmitStep;
        SetStepActive(StepTopic, step >= SubmitStep.Topic);
        SetStepActive(StepBody, step >= SubmitStep.Body);
        SetStepActive(StepReview, step >= SubmitStep.Review);
        SetStepActive(StepDone, step >= SubmitStep.Done);
    }

    private static void SetStepActive(Border b, bool active)
    {
        if (active && !b.Classes.Contains("active")) b.Classes.Add("active");
        else if (!active && b.Classes.Contains("active")) b.Classes.Remove("active");
    }
}
