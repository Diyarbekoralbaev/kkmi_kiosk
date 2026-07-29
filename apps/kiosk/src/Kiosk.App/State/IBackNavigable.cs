namespace Kiosk.App.State;

/// <summary>A page that has steps inside it and wants the Back button to walk
/// them before the kiosk leaves the page.
///
/// Every page is one tap from Home, so "back" at the top of a page IS Home —
/// which is why Back and Home used to be wired to the same handler. That was
/// wrong everywhere a page has depth: on the timetable, Back from a lesson list
/// threw away the faculty and group the visitor had just drilled through, so
/// getting to the neighbouring group meant starting over. NavBar now offers
/// Back to the page first and only falls through to Home if nothing consumed
/// it.</summary>
public interface IBackNavigable
{
    /// <summary>Step back one level. Return false when already at the page's
    /// top, which lets NavBar send the visitor Home instead.</summary>
    bool TryGoBack();
}
