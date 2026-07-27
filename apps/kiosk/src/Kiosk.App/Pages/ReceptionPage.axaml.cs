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
/// Touch flow for booking a reception: official → name → phone → reason →
/// review. The voice flow lands on Review via reception_preview.
///
/// Reception day/time are never entered here — they come from the chosen
/// official's own record, which is what makes this a booking rather than a
/// scheduling problem.
/// </summary>
public partial class ReceptionPage : UserControl
{
    private const int PhoneDigits = 9;

    /// <summary>True when the agent produced the review card. Confirm then
    /// hands back through `user_text` so the agent runs submit_reception itself
    /// and stays consistent with what was actually filed.</summary>
    private bool _fromVoice;

    public ReceptionPage()
    {
        InitializeComponent();
        DataContext = SessionStore.Current;
        NameKeyboard.TargetTextBox = NameInput;
        ReasonKeyboard.TargetTextBox = ReasonInput;
        PhoneKeypad.TargetTextBox = PhoneInput;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private async void OnLoaded(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.PropertyChanged -= OnSessionChanged;
        SessionStore.Current.PropertyChanged += OnSessionChanged;
        ApplyStep();

        if (SessionStore.Current.Leadership.Count > 0) return;
        try
        {
            var items = await KioskApi.GetOfficialsAsync();
            var s = SessionStore.Current;
            s.Leadership.Clear();
            if (items is not null)
            {
                foreach (var o in items) s.Leadership.Add(o);
            }
            NoOfficials.IsVisible = s.Leadership.Count == 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[reception] officials: {ex.Message}");
            NoOfficials.IsVisible = true;
        }
    }

    private void OnUnloaded(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.PropertyChanged -= OnSessionChanged;

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SessionStore.SubmitStep)
            || e.PropertyName == nameof(SessionStore.ReceptionOfficialName))
        {
            Dispatcher.UIThread.Post(ApplyStep);
        }
    }

    private void ApplyStep()
    {
        var s = SessionStore.Current;
        var step = s.SubmitStep;
        if (step == SubmitStep.Idle)
        {
            _fromVoice = false;
            NameInput.Text = "";
            PhoneInput.Text = "";
            ReasonInput.Text = "";
            SubmitStatus.IsVisible = false;
        }
        if (step == SubmitStep.Review && ReasonInput.Text?.Trim() is not { Length: > 0 })
            _fromVoice = true;

        OfficialStep.IsVisible = step == SubmitStep.Idle;
        NameStep.IsVisible = step == SubmitStep.Name;
        PhoneStep.IsVisible = step == SubmitStep.Phone;
        ReasonStep.IsVisible = step == SubmitStep.Text;
        ReviewStep.IsVisible = step is SubmitStep.Review or SubmitStep.Done;

        Breadcrumb.Text = step == SubmitStep.Idle ? "" : s.ReceptionOfficialName;
        WhenValue.Text = string.Join(
            "  ·  ",
            new[]
            {
                LocalizationService.FormatDay(s.ReceptionDay, LocalizationService.Current),
                s.ReceptionTime,
            }.Where(x => !string.IsNullOrWhiteSpace(x)));
    }

    // ── Steps ────────────────────────────────────────────────────────────────

    private void OnOfficialClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is not OfficialDto o) return;
        var s = SessionStore.Current;
        s.ReceptionOfficialId = o.Id;
        s.ReceptionOfficialName = o.Name;
        s.ReceptionOfficialPosition = o.Position;
        s.ReceptionDay = o.ReceptionDay;
        s.ReceptionTime = o.ReceptionTime;
        s.SubmitStep = SubmitStep.Name;
    }

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
        SessionStore.Current.SubmitPhone = digits[^PhoneDigits..];
        SessionStore.Current.SubmitStep = SubmitStep.Text;
    }

    private void OnReasonNext(object? sender, RoutedEventArgs e)
    {
        var reason = (ReasonInput.Text ?? "").Trim();
        ReasonError.IsVisible = reason.Length < 5;
        if (ReasonError.IsVisible) return;
        SessionStore.Current.ReceptionReason = reason;
        SessionStore.Current.SubmitStep = SubmitStep.Review;
    }

    private void OnEdit(object? sender, RoutedEventArgs e)
    {
        NameInput.Text = SessionStore.Current.SubmitName;
        ReasonInput.Text = SessionStore.Current.ReceptionReason;
        _fromVoice = false;
        SessionStore.Current.SubmitStep = SubmitStep.Name;
    }

    private async void OnConfirm(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;

        if (_fromVoice)
        {
            var rt = KioskRuntime.Current;
            if (rt is not null)
            {
                await rt.SendUserTextAsync(LocalizationService.Get("MurojatVoiceConfirmPhrase"));
                return;
            }
        }

        ConfirmButton.IsEnabled = false;
        SubmitStatus.IsVisible = false;
        try
        {
            var resp = await KioskApi.SubmitReceptionAsync(new ReceptionRequest
            {
                OfficialId = s.ReceptionOfficialId,
                FullName = s.SubmitName,
                Phone = s.SubmitPhone,
                Reason = s.ReceptionReason,
            });
            if (resp is null)
            {
                SubmitStatus.Text = LocalizationService.Get("MurojatSubmitError");
                SubmitStatus.IsVisible = true;
                return;
            }
            s.OnReceptionSubmitted(new ReceptionSubmittedMessage
            {
                Reference = resp.Reference,
                VerifyUrl = resp.VerifyUrl,
            });
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[reception] submit: {ex.Message}");
            SubmitStatus.Text = LocalizationService.Get("MurojatSubmitError");
            SubmitStatus.IsVisible = true;
        }
        finally
        {
            ConfirmButton.IsEnabled = true;
        }
    }
}
