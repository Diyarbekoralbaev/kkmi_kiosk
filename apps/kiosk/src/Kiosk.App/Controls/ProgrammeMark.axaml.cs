using System;
using System.Collections.Generic;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Kiosk.App.Net;

namespace Kiosk.App.Controls;

/// <summary>The visual identity of a degree programme, derived rather than
/// supplied.
///
/// Colour comes from the faculty and the letter from the degree level, so the
/// mark carries two true facts about the programme instead of decorating it.
/// The faculty is hashed rather than mapped to a fixed table: HEMIS renames
/// and renumbers faculties, and a lookup keyed on the exact string would
/// silently fall back to grey the day "1-Tibbiyot fakulteti" gains or loses a
/// trailing space — which it has, in the live data.</summary>
public partial class ProgrammeMark : UserControl
{
    /// <summary>Deep, saturated hues that carry white text and stay apart from
    /// one another in a scrolling list. Deliberately not the brand navy — that
    /// is the chrome's colour, and a mark that matches the header stops being
    /// a mark.</summary>
    private static readonly (string Plate, string Corner)[] Hues =
    {
        ("#8c2f39", "#6d1f28"),
        ("#1f6f6b", "#155450"),
        ("#2f4b7c", "#22385c"),
        ("#7a4a1e", "#5d3714"),
        ("#5a2d5c", "#432145"),
        ("#20674a", "#164e37"),
    };

    public static readonly StyledProperty<DirectionDto?> ProgrammeProperty =
        AvaloniaProperty.Register<ProgrammeMark, DirectionDto?>(nameof(Programme));

    public DirectionDto? Programme
    {
        get => GetValue(ProgrammeProperty);
        set => SetValue(ProgrammeProperty, value);
    }

    public ProgrammeMark() => InitializeComponent();

    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);
        if (change.Property == ProgrammeProperty) Render();
    }

    private void Render()
    {
        var p = Programme;
        if (p is null) return;
        var (plate, corner) = HueFor(p.Faculty);
        Plate.Background = new SolidColorBrush(Color.Parse(plate));
        Corner.Background = new SolidColorBrush(Color.Parse(corner));
        Letter.Text = LevelLetter(p.EducationType);
    }

    /// <summary>Stable across runs and across languages: the same faculty always
    /// lands on the same hue, and nothing has to be maintained when HEMIS adds
    /// one. Trimmed and case-folded because the live data is inconsistent about
    /// both.</summary>
    private static (string, string) HueFor(string faculty)
    {
        var key = (faculty ?? "").Trim().ToLowerInvariant();
        if (key.Length == 0) return Hues[^1];
        var hash = key.Aggregate(17, (acc, ch) => unchecked(acc * 31 + ch));
        return Hues[Math.Abs(hash) % Hues.Length];
    }

    /// <summary>First letter of the degree level as HEMIS names it — B for
    /// Bakalavr, M for Magistr, O for Ordinatura, D for Doktorantura. Taking
    /// the letter from the data means a level we have never seen still gets a
    /// sensible mark instead of a blank.</summary>
    private static string LevelLetter(string educationType)
    {
        var t = (educationType ?? "").Trim();
        return t.Length == 0 ? "•" : t[..1].ToUpperInvariant();
    }
}
