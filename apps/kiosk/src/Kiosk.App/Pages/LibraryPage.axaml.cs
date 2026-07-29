using System;
using System.ComponentModel;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Threading;
using Kiosk.App.Localization;
using Kiosk.App.Net;
using Kiosk.App.State;

namespace Kiosk.App.Pages;

/// <summary>The institute's book catalogue: shelf sections → list → one card.
///
/// Everything on screen came from a row a librarian typed into the gov panel —
/// this is the only kiosk screen backed by a table we own rather than the HEMIS
/// mirror. The agent's find_book / show_books write into the same SessionStore
/// collections, so a visitor who asks out loud and one who taps end up looking
/// at the same thing.</summary>
public partial class LibraryPage : UserControl, IBackNavigable
{
    public LibraryPage()
    {
        InitializeComponent();
        DataContext = SessionStore.Current;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private static string Locale() =>
        LocalizationService.LangCode(LocalizationService.Current);

    private async void OnLoaded(object? sender, RoutedEventArgs e)
    {
        SessionStore.Current.PropertyChanged -= OnSessionChanged;
        SessionStore.Current.PropertyChanged += OnSessionChanged;
        Render();

        // The agent may already have pushed results; don't refetch over them.
        var s = SessionStore.Current;
        if (s.Books.Count > 0 || s.BookSections.Count > 0) return;
        await LoadSectionsAsync();
    }

    private void OnUnloaded(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.PropertyChanged -= OnSessionChanged;

    private void OnSessionChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SessionStore.SelectedBook)
            || e.PropertyName == nameof(SessionStore.BookListCaption))
        {
            Dispatcher.UIThread.Post(Render);
        }
    }

    // ── Rendering ────────────────────────────────────────────────────────────

    private void Render()
    {
        var s = SessionStore.Current;
        var book = s.SelectedBook;
        var listing = book is null && (s.Books.Count > 0 || s.BookListCaption.Length > 0);

        DetailPanel.IsVisible = book is not null;
        ListPanel.IsVisible = listing;
        SectionPanel.IsVisible = !listing && book is null;

        if (book is not null) { RenderDetail(book); return; }

        Breadcrumb.Text = listing
            ? s.BookListCaption
            : LocalizationService.Get("LibraryBrowseHint");
        EmptyState.IsVisible = listing && s.Books.Count == 0;
    }

    /// <summary>An empty field is "not recorded yet", not "unknown" — the
    /// librarians are still filling the cards in. Showing a dash and saying so
    /// is honest; leaving the row blank reads as a rendering bug, and guessing
    /// a shelf sends someone to the wrong part of the room.</summary>
    private static string OrDash(string value) =>
        string.IsNullOrWhiteSpace(value)
            ? LocalizationService.Get("LibraryNotRecorded")
            : value;

    private void RenderDetail(BookDto b)
    {
        Breadcrumb.Text = b.SectionLabel;
        DetailCover.Book = b;
        DetailTitle.Text = b.Title;
        DetailAuthors.Text = OrDash(b.Authors);
        DetailSection.Text = b.SectionLabel;
        DetailLanguage.Text = LocalizationService.Get($"LibraryLang_{b.Language}");
        DetailShelf.Text = OrDash(b.Shelf);
        DetailCopies.Text = b.Copies.ToString();
        DetailYear.Text = b.Year is { } y ? y.ToString() : OrDash("");
        DetailPublisher.Text = OrDash(b.Publisher);
        DetailIsbn.Text = OrDash(b.Isbn);
        DetailDescription.Text = b.Description;
        DescriptionCard.IsVisible = !string.IsNullOrWhiteSpace(b.Description);
    }

    // ── Loading ──────────────────────────────────────────────────────────────

    private async Task LoadSectionsAsync()
    {
        try
        {
            var resp = await KioskApi.GetBookSectionsAsync(Locale());
            var s = SessionStore.Current;
            s.BookSections.Clear();
            foreach (var sec in resp?.Items ?? new()) s.BookSections.Add(sec);
            Render();
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[library] sections: {ex.Message}");
        }
    }

    private async Task LoadBooksAsync(string? section, string? query, string caption)
    {
        try
        {
            var resp = await KioskApi.GetBooksAsync(Locale(), section, query);
            var s = SessionStore.Current;
            s.Books.Clear();
            foreach (var b in resp?.Items ?? new()) s.Books.Add(b);
            s.SelectedBook = null;
            // Setting the caption last is what drives Render() through
            // PropertyChanged — the collections are not observable properties.
            s.BookListCaption = caption;
            Render();
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[library] books: {ex.Message}");
        }
    }

    // ── Handlers ─────────────────────────────────────────────────────────────

    private async void OnSectionClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is not BookSectionDto sec) return;
        await LoadBooksAsync(sec.Section, null, sec.Label);
    }

    private void OnBookClick(object? sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is BookDto b) SessionStore.Current.SelectedBook = b;
    }

    private async void OnSearchClick(object? sender, RoutedEventArgs e) => await RunSearch();

    private async void OnSearchKeyUp(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter) await RunSearch();
    }

    private async Task RunSearch()
    {
        var q = (SearchBox.Text ?? "").Trim();
        if (q.Length == 0)
        {
            // Clearing the box goes back to browsing rather than listing the
            // whole catalogue as if it were a result set.
            SessionStore.Current.Books.Clear();
            SessionStore.Current.BookListCaption = "";
            await LoadSectionsAsync();
            return;
        }
        await LoadBooksAsync(null, q, q);
    }

    /// <summary>Card → list → sections.</summary>
    public bool TryGoBack()
    {
        var s = SessionStore.Current;
        if (s.SelectedBook is not null)
        {
            s.SelectedBook = null;
            return true;
        }
        if (s.Books.Count > 0 || s.BookListCaption.Length > 0)
        {
            OnBackToSections(null, new RoutedEventArgs());
            return true;
        }
        return false;
    }

    private async void OnBackToSections(object? sender, RoutedEventArgs e)
    {
        SearchBox.Text = "";
        SessionStore.Current.Books.Clear();
        SessionStore.Current.BookListCaption = "";
        await LoadSectionsAsync();
    }

    private void OnBackToList(object? sender, RoutedEventArgs e) =>
        SessionStore.Current.SelectedBook = null;
}
