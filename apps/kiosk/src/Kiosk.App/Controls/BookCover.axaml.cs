using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Kiosk.App.Net;

namespace Kiosk.App.Controls;

/// <summary>A book's jacket: the stored image when there is one, a drawn cover
/// when there is not.
///
/// The drawn cover is not a placeholder. Most cards will have no image for a
/// while — Open Library only answers for an ISBN and the librarians are still
/// entering those — so "no image" is the normal case, not the error case, and
/// it has to look deliberate. Colour comes from the shelf section, which makes
/// it useful as well as presentable: the anatomy books stay findable by colour
/// once you have seen them.</summary>
public partial class BookCover : UserControl
{
    /// <summary>One colour per shelf section, chosen to stay distinguishable
    /// side by side on a shelf listing and to sit under white text. Keys match
    /// domain/library.SECTIONS.</summary>
    private static readonly Dictionary<string, (string Field, string Spine)> Palette = new()
    {
        ["anatomy"] = ("#8c2f39", "#6d1f28"),
        ["physiology"] = ("#1f6f6b", "#155450"),
        ["biochemistry"] = ("#4b5d2a", "#39471f"),
        ["pharmacology"] = ("#7a4a1e", "#5d3714"),
        ["pathology"] = ("#5a2d5c", "#432145"),
        ["microbiology"] = ("#1c5b7d", "#134459"),
        ["internal_medicine"] = ("#2f4b7c", "#22385c"),
        ["surgery"] = ("#93331f", "#722617"),
        ["pediatrics"] = ("#20674a", "#164e37"),
        ["obstetrics"] = ("#8a3b5e", "#6a2c48"),
        ["psychiatry"] = ("#3a3566", "#2a264d"),
        ["dentistry"] = ("#2b6070", "#1f4753"),
        ["nursing"] = ("#5d4a86", "#463769"),
        ["public_health"] = ("#3f6135", "#2e4827"),
        ["reference"] = ("#4a4f57", "#363a41"),
        ["other"] = ("#3d4a5c", "#2c3644"),
    };

    public static readonly StyledProperty<BookDto?> BookProperty =
        AvaloniaProperty.Register<BookCover, BookDto?>(nameof(Book));

    public BookDto? Book
    {
        get => GetValue(BookProperty);
        set => SetValue(BookProperty, value);
    }

    public BookCover()
    {
        InitializeComponent();
    }

    protected override void OnPropertyChanged(AvaloniaPropertyChangedEventArgs change)
    {
        base.OnPropertyChanged(change);
        // The list virtualises, so one control is reused across many books.
        if (change.Property == BookProperty) Render();
    }

    private void Render()
    {
        var book = Book;
        if (book is null) return;

        var (field, spine) = Palette.TryGetValue(book.Section, out var p)
            ? p : Palette["other"];
        Field.Background = SolidBrushFrom(field);
        Spine.Background = SolidBrushFrom(spine);
        Initials.Text = InitialsFor(book.Title);
        TitleLine.Text = book.Title;

        Jacket.IsVisible = false;
        Drawn.IsVisible = true;
        if (book.HasCover) _ = LoadJacketAsync(book.Id);
    }

    private static IBrush SolidBrushFrom(string hex) =>
        new SolidColorBrush(Color.Parse(hex));

    /// <summary>Up to four letters from the first words of the title. Cyrillic
    /// titles work as well as Latin ones — the library holds both — so this
    /// takes characters rather than assuming an alphabet.</summary>
    private static string InitialsFor(string title)
    {
        var words = (title ?? "").Split(
            new[] { ' ', '-', ':', '.', ',', '/' },
            StringSplitOptions.RemoveEmptyEntries);
        if (words.Length == 0) return "?";
        if (words.Length == 1)
            return words[0][..Math.Min(4, words[0].Length)].ToUpperInvariant();
        return string.Concat(words.Take(3).Select(w => w[0])).ToUpperInvariant();
    }

    /// <summary>Fetch the stored jacket. A failure is not an error state — the
    /// drawn cover is already on screen and simply stays.</summary>
    private async System.Threading.Tasks.Task LoadJacketAsync(string bookId)
    {
        try
        {
            var bytes = await KioskApi.GetBookCoverAsync(bookId);
            if (bytes is null || bytes.Length == 0) return;
            using var ms = new MemoryStream(bytes);
            var bitmap = new Bitmap(ms);
            Dispatcher.UIThread.Post(() =>
            {
                // The book may have scrolled away and been recycled onto a
                // different card while the fetch was in flight.
                if (Book?.Id != bookId) return;
                Jacket.Source = bitmap;
                Jacket.IsVisible = true;
                Drawn.IsVisible = false;
            });
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[cover] {bookId}: {ex.Message}");
        }
    }
}
