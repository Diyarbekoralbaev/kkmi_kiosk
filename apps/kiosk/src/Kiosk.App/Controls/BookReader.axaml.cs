using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Markup.Xaml;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Kiosk.App.Localization;
using Kiosk.App.Net;
using Kiosk.App.State;

namespace Kiosk.App.Controls;

/// <summary>
/// Reads a scanned book one rendered page at a time.
///
/// Only the current page is ever decoded. A page is ~1400×2000, which is about
/// 11 MB once it is a bitmap, and these machines have little to spare — so the
/// next page is held as the JPEG bytes it arrived as and decoded only when the
/// visitor actually turns to it. That keeps forward paging instant, which is
/// the direction people read in, without carrying a book's worth of bitmaps.
/// </summary>
public partial class BookReader : UserControl
{
    private BookDto? _book;
    private int _page;
    private Bitmap? _current;

    /// <summary>The page held in <see cref="_aheadBytes"/>, or 0 when nothing
    /// is prefetched. Kept beside the bytes so a stale prefetch from a previous
    /// book can never be shown as this one's page.</summary>
    private int _aheadPage;
    private byte[]? _aheadBytes;

    /// <summary>Cancels the in-flight fetch when the visitor pages on before it
    /// lands, so a slow page cannot arrive after a faster one and overwrite it.</summary>
    private CancellationTokenSource? _inFlight;

    public BookReader()
    {
        InitializeComponent();
        CloseButton.Click += (_, _) => Close();
        PrevButton.Click += (_, _) => _ = GoAsync(_page - 1);
        NextButton.Click += (_, _) => _ = GoAsync(_page + 1);
    }

    private void InitializeComponent() => AvaloniaXamlLoader.Load(this);

    public void Open(BookDto book)
    {
        if (book.Pages <= 0) return;
        _book = book;
        TitleText.Text = book.Title;
        IsVisible = true;
        SessionStore.Current.IsReadingBook = true;
        _ = GoAsync(1);
    }

    public void Close()
    {
        _inFlight?.Cancel();
        _inFlight = null;
        IsVisible = false;
        SessionStore.Current.IsReadingBook = false;
        PageImage.Source = null;
        _current?.Dispose();
        _current = null;
        _aheadBytes = null;
        _aheadPage = 0;
        _book = null;
    }

    private async Task GoAsync(int page)
    {
        var book = _book;
        if (book is null || page < 1 || page > book.Pages) return;

        _inFlight?.Cancel();
        var cts = new CancellationTokenSource();
        _inFlight = cts;

        _page = page;
        PageText.Text = $"{page} / {book.Pages}";
        PrevButton.IsEnabled = page > 1;
        NextButton.IsEnabled = page < book.Pages;

        byte[]? bytes = null;
        if (_aheadBytes is not null && _aheadPage == page)
        {
            bytes = _aheadBytes;
            _aheadBytes = null;
            _aheadPage = 0;
        }

        if (bytes is null)
        {
            StatusText.IsVisible = true;
            StatusText.Text = LocalizationService.Get("ReaderLoading");
            bytes = await KioskApi.GetBookPageAsync(book.Id, page);
        }

        if (cts.IsCancellationRequested) return;

        if (bytes is null)
        {
            StatusText.IsVisible = true;
            StatusText.Text = LocalizationService.Get("ReaderFailed");
            return;
        }

        try
        {
            var bmp = new Bitmap(new MemoryStream(bytes));
            PageImage.Source = bmp;
            _current?.Dispose();
            _current = bmp;
            StatusText.IsVisible = false;
        }
        catch (Exception ex)
        {
            // A page that will not decode is one page, not a broken reader.
            Console.Error.WriteLine($"[reader] decode page {page}: {ex.Message}");
            StatusText.IsVisible = true;
            StatusText.Text = LocalizationService.Get("ReaderFailed");
            return;
        }

        _ = PrefetchAsync(book, page + 1, cts.Token);
    }

    private async Task PrefetchAsync(BookDto book, int page, CancellationToken ct)
    {
        if (page > book.Pages) return;
        var bytes = await KioskApi.GetBookPageAsync(book.Id, page);
        if (ct.IsCancellationRequested || bytes is null) return;
        await Dispatcher.UIThread.InvokeAsync(() =>
        {
            // Re-check on the UI thread: the visitor may have closed the reader
            // or jumped elsewhere while this was in flight.
            if (_book?.Id != book.Id) return;
            _aheadBytes = bytes;
            _aheadPage = page;
        });
    }
}
