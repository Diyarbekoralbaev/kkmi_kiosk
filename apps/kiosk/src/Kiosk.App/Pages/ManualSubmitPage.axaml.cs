using System;
using System.ComponentModel;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Kiosk.App.Localization;
using Kiosk.App.Net;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>Manual touch-driven murajaat flow. Visitor moves through
/// topic → body → phone → preview → success without using voice. All
/// alphanumeric input is on the custom on-screen keyboard; phone uses
/// the existing NumericKeypad. Backend POST /api/kiosk/applications is
/// the only network call.
///
/// The page reuses <see cref="SessionStore"/> fields SubmitTopic /
/// SubmitBody / SubmitPhone / SubmittedId / ShowSubmitSuccess. The
/// step machine is its own enum (<see cref="ManualSubmitStep"/>) so
/// the AI voice flow's SubmitStep can't accidentally drive this
/// page's visibility.
/// </summary>
public partial class ManualSubmitPage : UserControl
{
    private const string EmptyPhoneFormat = "+998 __ - ___ - __ - __";

    private bool _keyboardsWired;
    // Re-entrancy guard: PhoneBox.Text = formatted inside OnPhoneTextChanged
    // re-fires TextChanged. Without this flag we'd recurse and FormatPhone
    // would keep absorbing the "+998" prefix as if it were typed digits,
    // producing strings like "+998 99 - 899 - 89 - 98" with the user not
    // typing anything. Mirror of QabulPage's _formattingPhone.
    private bool _formattingPhone;
    private DispatcherTimer? _successDismissTimer;

    public ManualSubmitPage()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
        SessionStore.Current.PropertyChanged += OnStateChanged;
    }

    private void OnLoaded(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        // Fresh start every entry — wipe whatever the voice flow may
        // have populated and reset to step 1 (topic).
        s.SubmitTopic = "";
        s.SubmitBody = "";
        s.SubmitPhone = "";
        s.SubmittedId = "";
        s.ShowSubmitSuccess = false;
        s.ManualSubmitStep = ManualSubmitStep.Topic;
        PhoneBox.Text = EmptyPhoneFormat;

        if (!_keyboardsWired)
        {
            TopicKeyboard.TargetTextBox = TopicBox;
            TopicKeyboard.Cleared += (_, _) =>
            {
                SessionStore.Current.SubmitTopic = "";
                TopicStatus.IsVisible = false;
            };
            BodyKeyboard.TargetTextBox = BodyBox;
            BodyKeyboard.Cleared += (_, _) =>
            {
                SessionStore.Current.SubmitBody = "";
                BodyStatus.IsVisible = false;
            };
            PhoneKeypad.TargetTextBox = PhoneBox;
            PhoneKeypad.Cleared += (_, _) => PhoneBox.Text = EmptyPhoneFormat;
            PhoneBox.TextChanged += OnPhoneTextChanged;
            _keyboardsWired = true;
        }

        TopicStatus.IsVisible = false;
        BodyStatus.IsVisible = false;
        PhoneStatus.IsVisible = false;
        PreviewStatus.IsVisible = false;
        UpdateVisibility();
    }

    private void OnUnloaded(object? sender, RoutedEventArgs e)
    {
        _successDismissTimer?.Stop();
        _successDismissTimer = null;
    }

    private void OnStateChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SessionStore.ManualSubmitStep)
            || e.PropertyName == nameof(SessionStore.ShowSubmitSuccess))
        {
            Dispatcher.UIThread.Post(UpdateVisibility);
        }
    }

    private void UpdateVisibility()
    {
        var s = SessionStore.Current;
        var showSuccess = s.ShowSubmitSuccess;
        SectionTopic.IsVisible = !showSuccess && s.ManualSubmitStep == ManualSubmitStep.Topic;
        SectionBody.IsVisible = !showSuccess && s.ManualSubmitStep == ManualSubmitStep.Body;
        SectionPhone.IsVisible = !showSuccess && s.ManualSubmitStep == ManualSubmitStep.Phone;
        SectionPreview.IsVisible = !showSuccess && s.ManualSubmitStep == ManualSubmitStep.Preview;
        SectionSuccess.IsVisible = showSuccess;

        if (SectionPreview.IsVisible)
        {
            PreviewTopic.Text = s.SubmitTopic ?? "";
            PreviewBody.Text = s.SubmitBody ?? "";
            PreviewPhone.Text = FormatPhonePretty(s.SubmitPhone ?? "");
        }
        if (showSuccess)
        {
            SuccessIdText.Text = string.IsNullOrEmpty(s.SubmittedId)
                ? ""
                : string.Format(
                    LocalizationService.Get("ManualMurajatSuccessId"),
                    ShortenId(s.SubmittedId));
            StartSuccessDismissTimer();
        }
    }

    // ── Topic ───────────────────────────────────────────────────────

    private void OnTopicContinue(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        var topic = (s.SubmitTopic ?? "").Trim();
        if (topic.Length < 3)
        {
            TopicStatus.IsVisible = true;
            return;
        }
        s.SubmitTopic = topic;
        TopicStatus.IsVisible = false;
        s.ManualSubmitStep = ManualSubmitStep.Body;
    }

    // ── Body ────────────────────────────────────────────────────────

    private void OnBodyBack(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.ManualSubmitStep = ManualSubmitStep.Topic;
    }

    private void OnBodyContinue(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        var body = (s.SubmitBody ?? "").Trim();
        if (body.Length < 5)
        {
            BodyStatus.IsVisible = true;
            return;
        }
        s.SubmitBody = body;
        BodyStatus.IsVisible = false;
        s.ManualSubmitStep = ManualSubmitStep.Phone;
    }

    // ── Phone ───────────────────────────────────────────────────────

    private void OnPhoneTextChanged(object? sender, TextChangedEventArgs e)
    {
        if (PhoneBox is null) return;
        // Guard against the recursive TextChanged that our own assignment
        // below triggers. Without this, FormatPhone would re-absorb the
        // "+998" prefix as if it were typed digits on every echo.
        if (_formattingPhone) return;
        _formattingPhone = true;
        try
        {
            PhoneBox.Text = FormatPhone(PhoneBox.Text ?? "");
            PhoneBox.CaretIndex = (PhoneBox.Text ?? "").Length;
        }
        finally { _formattingPhone = false; }
    }

    /// <summary>Format the masked phone box the same way QabulPage does.
    /// Strips the "+998" prefix from the digit extraction so we don't
    /// double-count it when the user-entered digits land in the slots.
    /// Verbatim port of QabulPage.FormatPhone.</summary>
    private static string FormatPhone(string raw)
    {
        var digits = new string(raw.Where(char.IsDigit).ToArray());
        if (digits.StartsWith("998")) digits = digits[3..];
        if (digits.Length > 9) digits = digits[..9];
        var p = digits.PadRight(9, '_');
        return $"+998 {p[0]}{p[1]} - {p[2]}{p[3]}{p[4]} - {p[5]}{p[6]} - {p[7]}{p[8]}";
    }

    /// <summary>Pull the 9 visitor-entered digits out of a formatted
    /// mask like "+998 90 - 123 - 45 - 67". Strips the "+998" prefix so
    /// validation against `.Length == 9` works correctly — without the
    /// strip, ExtractPhoneDigits would return 12 digits for any properly
    /// filled mask and OnPhoneContinue's check would always fail. Mirror
    /// of QabulPage.ExtractPhoneDigits.</summary>
    private static string ExtractPhoneDigits(string raw)
    {
        var digits = new string(raw.Where(char.IsDigit).ToArray());
        if (digits.StartsWith("998")) digits = digits[3..];
        return digits;
    }

    private static string FormatPhonePretty(string e164)
    {
        // E.164 +998901234567 → +998 90 - 123 - 45 - 67 for the preview
        var d = ExtractPhoneDigits(e164);
        if (d.Length == 12 && d.StartsWith("998")) d = d.Substring(3);
        if (d.Length != 9) return e164;
        return $"+998 {d[0]}{d[1]} - {d[2]}{d[3]}{d[4]} - {d[5]}{d[6]} - {d[7]}{d[8]}";
    }

    private void OnPhoneBack(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.ManualSubmitStep = ManualSubmitStep.Body;
    }

    private void OnPhoneContinue(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        var digits = ExtractPhoneDigits(PhoneBox.Text ?? "");
        if (digits.Length != 9)
        {
            PhoneStatus.IsVisible = true;
            return;
        }
        s.SubmitPhone = "+998" + digits;
        PhoneStatus.IsVisible = false;
        s.ManualSubmitStep = ManualSubmitStep.Preview;
    }

    // ── Preview / Submit ────────────────────────────────────────────

    private void OnPreviewEdit(object? sender, RoutedEventArgs e)
    {
        // Send the visitor back to the topic step so they can tweak
        // anything. Body and phone are preserved.
        SessionStore.Current.ManualSubmitStep = ManualSubmitStep.Topic;
    }

    private async void OnPreviewConfirm(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        var topic = (s.SubmitTopic ?? "").Trim();
        var body = (s.SubmitBody ?? "").Trim();
        var phone = (s.SubmitPhone ?? "").Trim();
        if (topic.Length < 3 || body.Length < 5 || ExtractPhoneDigits(phone).Length != 9)
        {
            PreviewStatus.IsVisible = true;
            return;
        }

        SubmitButton.IsEnabled = false;
        PreviewStatus.Foreground = Avalonia.Media.Brushes.SlateGray;
        PreviewStatus.Text = LocalizationService.Get("ManualMurajatSubmitting");
        PreviewStatus.IsVisible = true;

        var result = await KioskApi.CreateApplicationAsync(topic, body, phone);
        if (result is null)
        {
            PreviewStatus.Foreground = Avalonia.Media.Brush.Parse("#dc2626");
            PreviewStatus.Text = LocalizationService.Get("ManualMurajatSubmitError");
            SubmitButton.IsEnabled = true;
            return;
        }

        s.SubmittedId = result.ApplicationId;
        s.ShowSubmitSuccess = true;
        s.ManualSubmitStep = ManualSubmitStep.Done;
    }

    // ── Success auto-dismiss ───────────────────────────────────────

    private void StartSuccessDismissTimer()
    {
        _successDismissTimer?.Stop();
        _successDismissTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(6) };
        _successDismissTimer.Tick += (_, _) =>
        {
            _successDismissTimer?.Stop();
            SessionStore.Current.ResetIdle();
        };
        _successDismissTimer.Start();
    }

    /// <summary>Show only the first 8 chars of the UUID so the visitor
    /// has something readable to quote later if they call the helpline.
    /// Full id is in the audit log.</summary>
    private static string ShortenId(string id) =>
        string.IsNullOrEmpty(id) || id.Length < 8 ? id : id.Substring(0, 8);
}
