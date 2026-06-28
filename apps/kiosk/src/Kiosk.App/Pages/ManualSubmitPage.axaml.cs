using System;
using System.ComponentModel;
using System.Linq;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Kiosk.App.Localization;
using Kiosk.App.Net;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>Manual touch-driven murajat flow. Phone → (lookup) → confirm
/// identity OR full personal form → appeal text → preview → submit. All
/// alphanumeric input is on the on-screen keyboard; phone uses NumericKeypad.
/// Reads/writes the shared SessionStore Submit* fields and drives its own
/// section visibility off <see cref="SubmitStep"/>. Backend calls:
/// KioskApi.LookupPersonalAsync, GetLocationsAsync, SubmitAppealAsync.</summary>
public partial class ManualSubmitPage : UserControl
{
    private const string EmptyPhoneFormat = "+998 __ - ___ - __ - __";

    private bool _keyboardsWired;
    // Re-entrancy guard: setting PhoneBox.Text inside OnPhoneTextChanged
    // re-fires TextChanged. Without this flag FormatPhone would keep absorbing
    // the "+998" prefix as if it were typed digits.
    private bool _formattingPhone;
    private DispatcherTimer? _successDismissTimer;

    public ManualSubmitPage()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
        SessionStore.Current.PropertyChanged += OnStateChanged;
    }

    private async void OnLoaded(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        // Fresh start every entry — wipe whatever a prior session left.
        s.SubmitText = "";
        s.SubmitPhone = "";
        s.SubmitConfirmed = false;
        s.SubmitFirstName = "";
        s.SubmitLastName = "";
        s.SubmitBirthDate = "";
        s.SubmitAddress = "";
        s.SubmitGender = null;
        s.SubmitDistrictId = null;
        s.SubmitQuarterId = null;
        s.LookupExists = false;
        s.LookupPersonal = null;
        s.AppealNumber = "";
        s.ShowSubmitSuccess = false;
        s.SubmitStep = SubmitStep.Phone;
        PhoneBox.Text = EmptyPhoneFormat;

        if (!_keyboardsWired)
        {
            PhoneKeypad.TargetTextBox = PhoneBox;
            PhoneKeypad.Cleared += (_, _) => PhoneBox.Text = EmptyPhoneFormat;
            PhoneBox.TextChanged += OnPhoneTextChanged;

            // Form keyboard is shared across the personal fields — it retargets
            // to whichever box just got focus.
            FirstNameBox.GotFocus += (_, _) => FormKeyboard.TargetTextBox = FirstNameBox;
            LastNameBox.GotFocus += (_, _) => FormKeyboard.TargetTextBox = LastNameBox;
            BirthDateBox.GotFocus += (_, _) => FormKeyboard.TargetTextBox = BirthDateBox;
            AddressBox.GotFocus += (_, _) => FormKeyboard.TargetTextBox = AddressBox;
            FormKeyboard.TargetTextBox = FirstNameBox;
            FormKeyboard.Cleared += (_, _) =>
            {
                if (FormKeyboard.TargetTextBox is { } box) box.Text = "";
            };

            TextKeyboard.TargetTextBox = AppealTextBox;
            TextKeyboard.Cleared += (_, _) => AppealTextBox.Text = "";

            _keyboardsWired = true;
        }

        PhoneStatus.IsVisible = false;
        FormStatus.IsVisible = false;
        TextStatus.IsVisible = false;
        PreviewStatus.IsVisible = false;
        UpdateVisibility();

        // Load the districts/quarters reference once. If it fails the lists
        // stay empty — the form still renders, just without selectable rows.
        if (!s.LocationsLoaded)
        {
            var resp = await KioskApi.GetLocationsAsync();
            if (resp is not null) s.SetLocations(resp);
            UpdateVisibility();
        }
    }

    private void OnUnloaded(object? sender, RoutedEventArgs e)
    {
        _successDismissTimer?.Stop();
        _successDismissTimer = null;
    }

    private void OnStateChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SessionStore.SubmitStep)
            || e.PropertyName == nameof(SessionStore.ShowSubmitSuccess))
        {
            Dispatcher.UIThread.Post(UpdateVisibility);
        }
    }

    private void UpdateVisibility()
    {
        var s = SessionStore.Current;
        var step = s.SubmitStep;
        SectionPhone.IsVisible = step == SubmitStep.Phone;
        SectionConfirm.IsVisible = step == SubmitStep.Confirm;
        SectionForm.IsVisible = step == SubmitStep.Form;
        SectionText.IsVisible = step == SubmitStep.Text;
        SectionPreview.IsVisible = step == SubmitStep.Review;
        // Done → the shared SubmitSuccessOverlay (MainWindow) covers the screen.

        if (step == SubmitStep.Confirm)
        {
            var name = s.LookupPersonal?.FullName ?? "";
            ConfirmQuestion.Text = string.Format(
                LocalizationService.Get("MurajatConfirmQuestion"), name);
        }
        if (step == SubmitStep.Form)
        {
            BuildDistrictList();
            BuildQuarterList(s.SubmitDistrictId);
            UpdateGenderHighlight();
        }
        if (step == SubmitStep.Review)
        {
            var showName = !s.SubmitConfirmed
                && (!string.IsNullOrWhiteSpace(s.SubmitFirstName)
                    || !string.IsNullOrWhiteSpace(s.SubmitLastName));
            PreviewNameBlock.IsVisible = showName;
            PreviewName.Text = $"{s.SubmitFirstName} {s.SubmitLastName}".Trim();
            PreviewText.Text = s.SubmitText ?? "";
            PreviewPhone.Text = FormatPhonePretty(s.SubmitPhone ?? "");
            PreviewStatus.IsVisible = false;
            PreviewStatus.Foreground = Avalonia.Media.Brush.Parse("#dc2626");
            PreviewStatus.Text = LocalizationService.Get("ManualMurajatSubmitError");
            SubmitButton.IsEnabled = true;
        }
    }

    // ── Phone step ──────────────────────────────────────────────────

    private void OnPhoneTextChanged(object? sender, TextChangedEventArgs e)
    {
        if (PhoneBox is null) return;
        if (_formattingPhone) return;
        _formattingPhone = true;
        try
        {
            PhoneBox.Text = FormatPhone(PhoneBox.Text ?? "");
            PhoneBox.CaretIndex = (PhoneBox.Text ?? "").Length;
        }
        finally { _formattingPhone = false; }
    }

    private static string FormatPhone(string raw)
    {
        var digits = new string(raw.Where(char.IsDigit).ToArray());
        if (digits.StartsWith("998")) digits = digits[3..];
        if (digits.Length > 9) digits = digits[..9];
        var p = digits.PadRight(9, '_');
        return $"+998 {p[0]}{p[1]} - {p[2]}{p[3]}{p[4]} - {p[5]}{p[6]} - {p[7]}{p[8]}";
    }

    private static string ExtractPhoneDigits(string raw)
    {
        var digits = new string(raw.Where(char.IsDigit).ToArray());
        if (digits.StartsWith("998")) digits = digits[3..];
        return digits;
    }

    private static string FormatPhonePretty(string e164)
    {
        var d = ExtractPhoneDigits(e164);
        if (d.Length == 12 && d.StartsWith("998")) d = d.Substring(3);
        if (d.Length != 9) return e164;
        return $"+998 {d[0]}{d[1]} - {d[2]}{d[3]}{d[4]} - {d[5]}{d[6]} - {d[7]}{d[8]}";
    }

    private async void OnPhoneContinue(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        var digits = ExtractPhoneDigits(PhoneBox.Text ?? "");
        if (digits.Length != 9)
        {
            PhoneStatus.IsVisible = true;
            return;
        }
        PhoneStatus.IsVisible = false;
        var phone = "+998" + digits;
        s.SubmitPhone = phone;

        PhoneContinueButton.IsEnabled = false;
        try
        {
            var resp = await KioskApi.LookupPersonalAsync(phone);
            if (resp is not null && resp.Exists && resp.Personal is not null)
            {
                s.LookupExists = true;
                s.LookupPersonal = resp.Personal;
                s.SubmitConfirmed = false;
                s.SubmitStep = SubmitStep.Confirm;
            }
            else
            {
                s.LookupExists = false;
                s.LookupPersonal = null;
                s.SubmitConfirmed = false;
                s.SubmitStep = SubmitStep.Form;
            }
        }
        finally
        {
            PhoneContinueButton.IsEnabled = true;
        }
    }

    // ── Confirm identity ────────────────────────────────────────────

    private void OnConfirmYes(object? sender, RoutedEventArgs e)
    {
        // Existing citizen confirmed — phone + text only, no personal fields.
        SessionStore.Current.SubmitConfirmed = true;
        SessionStore.Current.SubmitStep = SubmitStep.Text;
    }

    private void OnConfirmNo(object? sender, RoutedEventArgs e)
    {
        // «Men emas» — collect a fresh full set of personal details.
        var s = SessionStore.Current;
        s.SubmitConfirmed = false;
        s.SubmitFirstName = "";
        s.SubmitLastName = "";
        s.SubmitBirthDate = "";
        s.SubmitAddress = "";
        s.SubmitGender = null;
        s.SubmitDistrictId = null;
        s.SubmitQuarterId = null;
        s.SubmitStep = SubmitStep.Form;
    }

    // ── Full personal form ──────────────────────────────────────────

    private void OnGenderMale(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.SubmitGender = 1;
        UpdateGenderHighlight();
    }

    private void OnGenderFemale(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.SubmitGender = 0;
        UpdateGenderHighlight();
    }

    private void UpdateGenderHighlight()
    {
        var g = SessionStore.Current.SubmitGender;
        SetSelected(GenderMale, g == 1);
        SetSelected(GenderFemale, g == 0);
    }

    private static void SetSelected(Button b, bool on)
    {
        if (on)
        {
            if (!b.Classes.Contains("selected")) b.Classes.Add("selected");
        }
        else
        {
            b.Classes.Remove("selected");
        }
    }

    private static string LocName(string qq, string uz, string ru)
    {
        if (!string.IsNullOrWhiteSpace(qq)) return qq;
        if (!string.IsNullOrWhiteSpace(uz)) return uz;
        return ru ?? "";
    }

    private void BuildDistrictList()
    {
        var s = SessionStore.Current;
        DistrictList.Children.Clear();
        foreach (var d in s.Districts)
        {
            var btn = new Button { Content = LocName(d.NameQq, d.NameUz, d.NameRu), Tag = d.Id };
            btn.Classes.Add("locitem");
            if (s.SubmitDistrictId == d.Id) btn.Classes.Add("selected");
            btn.Click += OnDistrictClick;
            DistrictList.Children.Add(btn);
        }
    }

    private void OnDistrictClick(object? sender, RoutedEventArgs e)
    {
        if (sender is not Button b || b.Tag is not int id) return;
        var s = SessionStore.Current;
        s.SubmitDistrictId = id;
        s.SubmitQuarterId = null;
        BuildDistrictList();
        BuildQuarterList(id);
    }

    private void BuildQuarterList(int? districtId)
    {
        QuarterList.Children.Clear();
        if (districtId is null) return;
        var s = SessionStore.Current;
        foreach (var q in s.QuartersForDistrict(districtId.Value))
        {
            var btn = new Button { Content = LocName(q.NameQq, q.NameUz, q.NameRu), Tag = q.Id };
            btn.Classes.Add("locitem");
            if (s.SubmitQuarterId == q.Id) btn.Classes.Add("selected");
            btn.Click += OnQuarterClick;
            QuarterList.Children.Add(btn);
        }
    }

    private void OnQuarterClick(object? sender, RoutedEventArgs e)
    {
        if (sender is not Button b || b.Tag is not int id) return;
        SessionStore.Current.SubmitQuarterId = id;
        BuildQuarterList(SessionStore.Current.SubmitDistrictId);
    }

    private void OnFormBack(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.SubmitStep = SubmitStep.Phone;
    }

    private void OnFormContinue(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        var firstOk = (s.SubmitFirstName ?? "").Trim().Length >= 1;
        var lastOk = (s.SubmitLastName ?? "").Trim().Length >= 1;
        var birthOk = (s.SubmitBirthDate ?? "").Trim().Length >= 4;
        var addressOk = (s.SubmitAddress ?? "").Trim().Length >= 1;
        if (!firstOk || !lastOk || !birthOk || s.SubmitGender is null
            || s.SubmitDistrictId is null || s.SubmitQuarterId is null || !addressOk)
        {
            FormStatus.IsVisible = true;
            return;
        }
        FormStatus.IsVisible = false;
        s.SubmitStep = SubmitStep.Text;
    }

    // ── Appeal text ─────────────────────────────────────────────────

    private void OnTextBack(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        s.SubmitStep = s.SubmitConfirmed ? SubmitStep.Confirm : SubmitStep.Form;
    }

    private void OnTextContinue(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        if ((s.SubmitText ?? "").Trim().Length < 5)
        {
            TextStatus.IsVisible = true;
            return;
        }
        TextStatus.IsVisible = false;
        s.SubmitStep = SubmitStep.Review;
    }

    // ── Preview / Submit ────────────────────────────────────────────

    private void OnPreviewEdit(object? sender, RoutedEventArgs e)
    {
        // Back to the appeal-text step to tweak the body.
        SessionStore.Current.SubmitStep = SubmitStep.Text;
    }

    private async void OnPreviewConfirm(object? sender, RoutedEventArgs e)
    {
        var s = SessionStore.Current;
        var text = (s.SubmitText ?? "").Trim();
        var phone = (s.SubmitPhone ?? "").Trim();
        if (text.Length < 5 || ExtractPhoneDigits(phone).Length != 9)
        {
            PreviewStatus.IsVisible = true;
            return;
        }

        SubmitButton.IsEnabled = false;
        PreviewStatus.Foreground = Avalonia.Media.Brushes.SlateGray;
        PreviewStatus.Text = LocalizationService.Get("ManualMurajatSubmitting");
        PreviewStatus.IsVisible = true;

        AppealRequest req;
        if (s.SubmitConfirmed)
        {
            req = new AppealRequest { Phone = phone, Text = text, Confirmed = true };
        }
        else
        {
            req = new AppealRequest
            {
                Phone = phone,
                Text = text,
                Confirmed = false,
                FirstName = (s.SubmitFirstName ?? "").Trim(),
                LastName = (s.SubmitLastName ?? "").Trim(),
                BirthDate = string.IsNullOrWhiteSpace(s.SubmitBirthDate) ? null : s.SubmitBirthDate.Trim(),
                Gender = s.SubmitGender,
                DistrictId = s.SubmitDistrictId,
                QuarterId = s.SubmitQuarterId,
                Address = string.IsNullOrWhiteSpace(s.SubmitAddress) ? null : s.SubmitAddress.Trim(),
            };
        }

        var result = await KioskApi.SubmitAppealAsync(req);
        if (result is null)
        {
            PreviewStatus.Foreground = Avalonia.Media.Brush.Parse("#dc2626");
            PreviewStatus.Text = LocalizationService.Get("ManualMurajatSubmitError");
            SubmitButton.IsEnabled = true;
            return;
        }

        s.AppealNumber = result.AppealNumber;
        s.ShowSubmitSuccess = true;
        s.SubmitStep = SubmitStep.Done;
        StartSuccessDismissTimer();
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
}
