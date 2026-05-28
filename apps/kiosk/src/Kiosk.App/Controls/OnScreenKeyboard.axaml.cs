using System;
using System.Collections.Generic;
using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.LogicalTree;

namespace Kiosk.App.Controls;

/// <summary>Touch keyboard for the manual flows on the fullscreen
/// kiosk. Modeled after <see cref="NumericKeypad"/>: set
/// <see cref="TargetTextBox"/> and every alphanumeric key is inserted
/// at the textbox's caret. Action keys handle caps-lock, Cyrillic↔Latin
/// toggle, backspace, space, and clear.
///
/// Layout is fixed (5 rows × 12 columns) in XAML; the code-behind
/// rewrites letter button Content when the user toggles mode or caps.
/// Letter buttons carry Tag="L:row,col" so we can address them by
/// grid position without per-key x:Name attributes.
/// </summary>
public partial class OnScreenKeyboard : UserControl
{
    public TextBox? TargetTextBox { get; set; }

    /// <summary>Fired when the close (✕) key is pressed. The host
    /// typically uses this to hide the keyboard. The text box value
    /// is left intact — same semantics as NumericKeypad.</summary>
    public event EventHandler? Cleared;

    private bool _capsOn;
    private bool _latinMode;

    // Cached map of letter buttons, keyed by their L:row,col tag.
    // Populated once in OnAttachedToLogicalTree so we don't re-walk
    // the visual tree on every toggle. Key: "row,col" string.
    private readonly Dictionary<string, Button> _letterButtons = new();

    // Letter layout — 4 rows, varying column counts to match the XAML
    // grid. Position [r-1][c] in this array maps to the button with
    // Tag="L:r,c" in the grid. Row 0 (numbers/punctuation) is NOT in
    // these arrays — those keys are static and don't toggle.
    private static readonly string[][] CyrillicLower =
    {
        new[] { "й", "ц", "у", "к", "е", "н", "г", "ш", "щ", "з", "х", "ъ" },
        new[] { "ф", "ы", "в", "а", "п", "р", "о", "л", "д", "ж", "э" },
        new[] { "я", "ч", "с", "м", "и", "т", "ь", "б", "ю", "ё" },
        new[] { "қ", "ў", "ғ", "ҳ", "ң", "ө", "ү", "ә", "і" },
    };

    private static readonly string[][] LatinLower =
    {
        new[] { "q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "[", "]" },
        new[] { "a", "s", "d", "f", "g", "h", "j", "k", "l", ":", ";" },
        new[] { "z", "x", "c", "v", "b", "n", "m", "!", "?", "'" },
        // Row 4 in Latin mode swaps the Karakalpak Cyrillic specials
        // for Uzbek-Latin special chars + a few common
        // punctuation/symbol keys. Position-by-position with the
        // Cyrillic layout so the grid never reshuffles.
        new[] { "ʻ", "ʼ", "-", "=", "/", "\\", "(", ")", "_" },
    };

    public OnScreenKeyboard()
    {
        InitializeComponent();
        AddHandler(Button.ClickEvent, OnAnyButtonClick);
    }

    protected override void OnAttachedToLogicalTree(LogicalTreeAttachmentEventArgs e)
    {
        base.OnAttachedToLogicalTree(e);
        if (_letterButtons.Count > 0) return;
        // Walk the logical tree once and cache letter buttons by their
        // grid position. Avoids visual-tree walks on every toggle.
        foreach (var descendant in this.GetLogicalDescendants())
        {
            if (descendant is not Button btn) continue;
            if (btn.Tag is not string t || !t.StartsWith("L:")) continue;
            _letterButtons[t.Substring(2)] = btn;
        }
    }

    private void OnAnyButtonClick(object? sender, RoutedEventArgs e)
    {
        if (e.Source is not Button b) return;
        var tag = b.Tag as string ?? "";

        if (tag.StartsWith("A:"))
        {
            HandleAction(tag.Substring(2));
            return;
        }
        if (tag.StartsWith("L:") || tag.StartsWith("N:"))
        {
            // Letter / number key — type its current Content verbatim.
            // For letters, Content already reflects mode + caps state
            // (RefreshLetters keeps it in sync).
            var ch = b.Content as string ?? "";
            if (!string.IsNullOrEmpty(ch)) InsertChar(ch);
        }
    }

    private void HandleAction(string action)
    {
        switch (action)
        {
            case "back":
                Backspace();
                break;
            case "space":
                InsertChar(" ");
                break;
            case "clear":
                Cleared?.Invoke(this, EventArgs.Empty);
                break;
            case "caps":
                _capsOn = !_capsOn;
                ToggleClass(CapsKey, "on", _capsOn);
                RefreshLetters();
                break;
            case "mode":
                _latinMode = !_latinMode;
                if (ModeKey is { } mode)
                {
                    mode.Content = _latinMode ? "АБВ" : "ABC";
                    ToggleClass(mode, "on", _latinMode);
                }
                RefreshLetters();
                break;
        }
    }

    private static void ToggleClass(Button? btn, string className, bool on)
    {
        if (btn is null) return;
        if (on)
        {
            if (!btn.Classes.Contains(className)) btn.Classes.Add(className);
        }
        else
        {
            btn.Classes.Remove(className);
        }
    }

    private void InsertChar(string ch)
    {
        if (TargetTextBox is not { } box) return;
        var idx = Math.Max(0, box.SelectionStart);
        var current = box.Text ?? "";
        if (idx > current.Length) idx = current.Length;
        box.Text = current.Insert(idx, ch);
        box.SelectionStart = idx + ch.Length;
        box.SelectionEnd = box.SelectionStart;
    }

    private void Backspace()
    {
        if (TargetTextBox is not { } box) return;
        var current = box.Text ?? "";
        if (current.Length == 0) return;
        var idx = Math.Clamp(box.SelectionStart, 0, current.Length);
        if (idx == 0) return;
        box.Text = current.Remove(idx - 1, 1);
        box.SelectionStart = idx - 1;
        box.SelectionEnd = box.SelectionStart;
    }

    /// <summary>Rewrite every cached letter button's Content based on
    /// current mode + caps state. Cheap — ~50 buttons.</summary>
    private void RefreshLetters()
    {
        var layout = _latinMode ? LatinLower : CyrillicLower;
        foreach (var (key, btn) in _letterButtons)
        {
            var parts = key.Split(',');
            if (parts.Length != 2) continue;
            if (!int.TryParse(parts[0], out var row)) continue;
            if (!int.TryParse(parts[1], out var col)) continue;
            var arrayRow = row - 1;
            if (arrayRow < 0 || arrayRow >= layout.Length) continue;
            var rowArr = layout[arrayRow];
            if (col < 0 || col >= rowArr.Length) continue;
            var glyph = rowArr[col];
            btn.Content = _capsOn ? glyph.ToUpper() : glyph;
        }
    }
}
