using System;
using System.ComponentModel;
using System.Linq;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Kiosk.App.Localization;
using Kiosk.App.Net;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>
/// Touch flow for filing an appeal: name → phone → text → review.
///
/// The voice flow arrives straight at Review — the agent collects the same
/// three values and pushes murojat_preview, which sets SubmitStep. This page
/// follows that property, so one screen serves both paths and neither can show
/// something the other cannot submit.
/// </summary>
public partial class MurojatPage : UserControl
{
    private const int PhoneDigits = 9;
    private const int MinTextLength = 5;

    /// <summary>True when the agent (not this page) produced what is on the
    /// review card. Confirm then hands back to the agent via `user_text` so it
    /// fires submit_murojat itself, rather than this page POSTing behind the
    /// agent's back and leaving it believing nothing was filed.</summary>
    private bool _fromVoice;

    public MurojatPage()
    {
        InitializeComponent();
        DataContext = SessionStore.Current;
        NameKeyboard.TargetTextBox = NameInput;
        TextKeyboard.TargetTextBox = AppealTextInput;
        PhoneKeypad.TargetTextBox = PhoneInput;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private void OnLoaded(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.PropertyChanged -= OnSessionChanged;
        SessionStore.Current.PropertyChanged += OnSessionChanged;
        ApplyStep();
    }

    private void OnUnloaded(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.PropertyChanged -= OnSessionChanged;

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SessionStore.SubmitStep))
            Dispatcher.UIThread.Post(ApplyStep);
    }

    private void ApplyStep()
    {
        var step = SessionStore.Current.SubmitStep;
        if (step == SubmitStep.Idle)
        {
            // Fresh entry from the home tile.
            _fromVoice = false;
            NameInput.Text = "";
            PhoneInput.Text = "";
            AppealTextInput.Text = "";
            SubmitStatus.IsVisible = false;
            step = SubmitStep.Name;
            SessionStore.Current.SubmitStep = step;
        }
        if (step == SubmitStep.Review && SessionStore.Current.SubmitText.Length > 0
            && AppealTextInput.Text?.Trim() is not { Length: > 0 })
        {
            // Review reached without this page collecting anything → the agent
            // filled it in.
            _fromVoice = true;
        }

        NameStep.IsVisible = step == SubmitStep.Name;
        PhoneStep.IsVisible = step == SubmitStep.Phone;
        TextStep.IsVisible = step == SubmitStep.Text;
        ReviewStep.IsVisible = step is SubmitStep.Review or SubmitStep.Done;
    }

    // ── Steps ────────────────────────────────────────────────────────────────

    private void OnNameNext(object? sender, RoutedEventArgs e)
    {
        var name = (NameInput.Text ?? "").Trim();
        NameError.IsVisible = name.Length < 3;
        if (NameError.IsVisible) return;
        SessionStore.Current.SubmitName = name;
        SessionStore.Current.SubmitStep = SubmitStep.Phone;
    }

    private void OnPhoneNext(object? sender, RoutedEventArgs e)
    {
        var digits = new string((PhoneInput.Text ?? "").Where(char.IsDigit).ToArray());
        PhoneError.IsVisible = digits.Length < PhoneDigits;
        if (PhoneError.IsVisible) return;
        // Keep the last 9: a visitor who typed the 998 prefix out of habit
        // should not be told their own number is wrong.
        SessionStore.Current.SubmitPhone = digits[^PhoneDigits..];
        SessionStore.Current.SubmitStep = SubmitStep.Text;
    }

    private void OnTextNext(object? sender, RoutedEventArgs e)
    {
        var text = (AppealTextInput.Text ?? "").Trim();
        TextError.IsVisible = text.Length < MinTextLength;
        if (TextError.IsVisible) return;
        SessionStore.Current.SubmitText = text;
        SessionStore.Current.SubmitStep = SubmitStep.Review;
    }

    private void OnEdit(object? sender, RoutedEventArgs e)
    {
        // Editing an agent-drafted appeal restarts the touch flow, prefilled.
        NameInput.Text = SessionStore.Current.SubmitName;
        AppealTextInput.Text = SessionStore.Current.SubmitText;
        _fromVoice = false;
        SessionStore.Current.SubmitStep = SubmitStep.Name;
    }

    private async void OnConfirm(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;

        if (_fromVoice)
        {
            // Hand the confirmation to the agent as if spoken, so it runs
            // submit_murojat and keeps its own state consistent.
            var rt = KioskRuntime.Current;
            if (rt is not null)
            {
                await rt.SendUserTextAsync(LocalizationService.Get("MurojatVoiceConfirmPhrase"));
                return;
            }
            // Voice runtime gone (session dropped) — fall through and POST.
        }

        ConfirmButton.IsEnabled = false;
        SubmitStatus.IsVisible = false;
        try
        {
            var resp = await KioskApi.SubmitAppealAsync(new AppealRequest
            {
                FullName = s.SubmitName,
                Phone = s.SubmitPhone,
                Text = s.SubmitText,
            });
            if (resp is null)
            {
                SubmitStatus.Text = LocalizationService.Get("MurojatSubmitError");
                SubmitStatus.IsVisible = true;
                return;
            }
            s.OnMurojatSubmitted(new MurojatSubmittedMessage
            {
                Reference = resp.Reference,
                FullName = s.SubmitName,
            });
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[murojat] submit: {ex.Message}");
            SubmitStatus.Text = LocalizationService.Get("MurojatSubmitError");
            SubmitStatus.IsVisible = true;
        }
        finally
        {
            ConfirmButton.IsEnabled = true;
        }
    }
}
