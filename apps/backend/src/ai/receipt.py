"""Qabul (appointment) receipt rendering — 80mm thermal PDF + QR PNG.

Layout for POS-80 class thermal printers (Xprinter, Gprinter, Zjiang...).
Page width is fixed at 80mm; height is computed from content so a short
receipt doesn't waste paper. The kiosk pipes the PDF to bundled
SumatraPDF.exe — see apps/kiosk/.../Print/ReceiptPrinter.cs.

Fonts: DejaVuSans (Regular/Bold/Oblique) for Cyrillic-safe glyphs.
Helvetica fallback per-face when the apt fonts-dejavu package isn't on
the host (dev/test).
"""
from __future__ import annotations

import io
import textwrap
from datetime import date

import qrcode
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ..domain.ai_config import OrgKbOfficial
from ..domain.appointment import Appointment
from ..domain.organization import Organization

# ── Karakalpak (Latin) date format — still used by WS payloads + legacy ──

WEEKDAY_KK_LATIN = {
    0: "Dúyshembi", 1: "Seyshembi", 2: "Sárshembi", 3: "Beysenbi",
    4: "Juma",      5: "Shembi",    6: "Jeksenbi",
}

MONTH_KK_LATIN = {
    1: "yanvar", 2: "fevral", 3: "mart", 4: "aprel", 5: "may", 6: "iyun",
    7: "iyul", 8: "avgust", 9: "sentyabr", 10: "oktyabr", 11: "noyabr", 12: "dekabr",
}


def format_date_kk(d: date) -> str:
    return f"{WEEKDAY_KK_LATIN[d.weekday()]}, {d.day}-{MONTH_KK_LATIN[d.month]} {d.year}"


# ── Uzbek date format (receipt) ───────────────────────────────────────────

WEEKDAY_UZ = {
    0: "Dushanba", 1: "Seshanba", 2: "Chorshanba", 3: "Payshanba",
    4: "Juma",     5: "Shanba",   6: "Yakshanba",
}

MONTH_UZ = {
    1: "yanvar", 2: "fevral", 3: "mart", 4: "aprel", 5: "may", 6: "iyun",
    7: "iyul", 8: "avgust", 9: "sentyabr", 10: "oktyabr", 11: "noyabr", 12: "dekabr",
}


def format_date_uz(d: date) -> str:
    return f"{d.day}-{MONTH_UZ[d.month]} {d.year}, {WEEKDAY_UZ[d.weekday()]}"


# ── Karakalpak (Cyrillic) date format — matches kiosk's KK-Cyrl UI ───────

WEEKDAY_KK_CYRL = {
    0: "Дүйшемби", 1: "Шейшемби", 2: "Шәршемби", 3: "Пайшемби",
    4: "Жума",     5: "Шемби",    6: "Екшемби",
}

MONTH_KK_CYRL = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май", 6: "июнь",
    7: "июль", 8: "август", 9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}


def format_date_kk_cyrl(d: date) -> str:
    return f"{d.day}-{MONTH_KK_CYRL[d.month]} {d.year}, {WEEKDAY_KK_CYRL[d.weekday()]}"


# ── Russian date format (receipt) — genitive month case for date context ─

WEEKDAY_RU = {
    0: "Понедельник", 1: "Вторник", 2: "Среда", 3: "Четверг",
    4: "Пятница",     5: "Суббота", 6: "Воскресенье",
}

MONTH_RU_GENITIVE = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def format_date_ru(d: date) -> str:
    return f"{d.day} {MONTH_RU_GENITIVE[d.month]} {d.year}, {WEEKDAY_RU[d.weekday()]}"


# ── Locale dispatch ───────────────────────────────────────────────────────

# Maps the kiosk-supplied `ui_language` to the appropriate date formatter.
# Unknown values fall back to KK-Cyrl (matches Organization.locale default).
_DATE_FORMATTERS = {
    "uz": format_date_uz,
    "kk": format_date_kk_cyrl,
    "ru": format_date_ru,
}


def format_date(d: date, locale: str) -> str:
    return _DATE_FORMATTERS.get(locale, format_date_kk_cyrl)(d)


# Per-locale label strings shown on the printed receipt. The translations
# for kk-Cyrl + ru were provided directly by the operator (kiosk owner)
# rather than auto-translated — this is intentional because incorrect
# Karakalpak grammar on a printed government receipt would be a public-
# facing embarrassment. Keep these exactly as supplied unless re-reviewed.
RECEIPT_STRINGS: dict[str, dict[str, str]] = {
    # Standardized glossary across kiosk + receipt + public per operator
    # sign-off (2026-05-14). Same words everywhere — no synonyms drift.
    #   Official: Mansabdor shaxs / Лаўазымлы шахс / Должностное лицо
    #   Ticket:   Navbat          / Наўбет          / Номер
    #   Topic:    Masala          / Мәселе          / Направление
    # Karakalpak (kk) is Karakalpak, NOT Kazakh — "Яқ" (no), "шахс" (person).
    "uz": {
        "subtitle_chief": "Shaxsiy qabul navbati",
        "subtitle_deputy": "O'rinbosar qabul navbati",
        "chipta_label": "Navbat raqami:",
        "mansabdor_label": "Mansabdor shaxs:",
        "masala_label": "Masalasi:",
        "sana_label": "Sana:",
        "vaqt_label": "Vaqti:",
        "navbat_label": "Navbati:",
        "telefon_label": "Telefon:",
        "footer": "Iltimos, belgilangan vaqtda kelishingizni so'raymiz.",
        "org_fallback": "HOKIMIYAT",
    },
    "kk": {
        "subtitle_chief": "Жеке қабыллаў наўбети",
        "subtitle_deputy": "Орынбасар қабыллаў наўбети",
        "chipta_label": "Наўбет номери:",
        "mansabdor_label": "Лаўазымлы шахс:",
        "masala_label": "Мәселеси:",
        "sana_label": "Сәне:",
        "vaqt_label": "Ўақты:",
        "navbat_label": "Наўбети:",
        "telefon_label": "Телефон:",
        "footer": "Илтимас, белгиленген ўақытта келиўиңизди сораймыз.",
        "org_fallback": "ҲӘКИМИЯТ",
    },
    "ru": {
        "subtitle_chief": "Номер на личный приём",
        "subtitle_deputy": "Номер на приём заместителя",
        "chipta_label": "Номер приёма:",
        "mansabdor_label": "Должностное лицо:",
        "masala_label": "Направление:",
        "sana_label": "Дата:",
        "vaqt_label": "Время:",
        "navbat_label": "Номер:",
        "telefon_label": "Телефон:",
        "footer": "Просим вас прийти в назначенное время.",
        "org_fallback": "ХОКИМИЯТ",
    },
}


def _strings(locale: str) -> dict[str, str]:
    return RECEIPT_STRINGS.get(locale) or RECEIPT_STRINGS["kk"]


def mask_phone(phone: str) -> str:
    """No-op pass-through. Used to render "***-**-77" but the operator
    decided masking adds zero value (kiosk is anonymous already, and
    staff need the real number to call the visitor back). Kept as a
    function so we don't have to chase every call site — every
    `phone_masked` field on the wire now carries the raw E.164-ish
    number unchanged."""
    return phone


def _format_phone_pretty(phone: str) -> str:
    """`+998901234567` → `+998 901234567` — country code + space + bare
    local 9-digit run. Matches the operator's reference receipt layout
    exactly (no further inter-digit grouping)."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 12 and digits.startswith("998"):
        return f"+998 {digits[3:]}"
    if len(digits) == 9:
        return f"+998 {digits}"
    return phone


def render_qr_png(verify_url: str, size_px: int = 360) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(verify_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img = img.resize((size_px, size_px))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Font registration ─────────────────────────────────────────────────────

_AVAILABLE: dict[str, bool] = {"regular": False, "bold": False, "italic": False}
_FONTS_TRIED = False


def _ensure_fonts() -> None:
    global _FONTS_TRIED
    if _FONTS_TRIED:
        return
    _FONTS_TRIED = True
    base = "/usr/share/fonts/truetype/dejavu"
    for logical, ttf_name in [
        ("regular", "DejaVuSans"),
        ("bold", "DejaVuSans-Bold"),
        ("italic", "DejaVuSans-Oblique"),
    ]:
        try:
            pdfmetrics.registerFont(TTFont(ttf_name, f"{base}/{ttf_name}.ttf"))
            _AVAILABLE[logical] = True
        except Exception:
            pass


def _font(name: str) -> str:
    fallback = {"regular": "Helvetica", "bold": "Helvetica-Bold", "italic": "Helvetica-Oblique"}
    dejavu = {"regular": "DejaVuSans", "bold": "DejaVuSans-Bold", "italic": "DejaVuSans-Oblique"}
    return dejavu[name] if _AVAILABLE[name] else fallback[name]


# ── Layout constants ──────────────────────────────────────────────────────

PAGE_W = 80 * mm
MARGIN_X = 5 * mm                       # widened slightly so text never hits the edge
MARGIN_TOP = 5 * mm
MARGIN_BOTTOM = 6 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X       # available text width


def _fit_font_size(text: str, font_style: str, max_size: int, min_size: int) -> int:
    """Return the largest font size from [min_size..max_size] at which `text`
    fits within CONTENT_W as a single line. Used for the org header so it
    never overflows the page."""
    for size in range(max_size, min_size - 1, -1):
        w = pdfmetrics.stringWidth(text, _font(font_style), size)
        if w <= CONTENT_W:
            return size
    return min_size


def _wrap_to_width(text: str, font_style: str, size: int) -> list[str]:
    """Greedy word-wrap that respects pixel-width, not just char count.
    Cyrillic glyphs are wider than Latin in DejaVuSans, so a char-count
    wrap (textwrap.wrap) inevitably either underflows for Latin or
    overflows for Cyrillic. Width-based wrap is robust to both."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = cur + " " + w
        if pdfmetrics.stringWidth(trial, _font(font_style), size) <= CONTENT_W:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _build_ops(
    appointment: Appointment,
    official: OrgKbOfficial,
    org: Organization,
    verify_url: str,
    locale: str,
) -> list:
    """Drawing-op list. Each op signature: (c_or_None, y) -> new_y. Passing
    None for c is the measure pass that sizes the page. `locale` selects
    the label strings + date format (`uz` | `kk` | `ru`)."""
    L = _strings(locale)
    ops: list = []

    def line(s: str, *, style: str = "regular", size: int = 9,
             align: str = "left", dy: float | None = None) -> None:
        actual_dy = dy if dy is not None else size * 1.25
        def op(c, y):
            if c is not None:
                c.setFont(_font(style), size)
                if align == "center":
                    c.drawCentredString(PAGE_W / 2, y, s)
                else:
                    c.drawString(MARGIN_X, y, s)
            return y - actual_dy
        ops.append(op)

    def wrapped(s: str, *, style: str = "regular", size: int = 9,
                align: str = "left", dy: float | None = None) -> None:
        for chunk in _wrap_to_width(s, style, size):
            line(chunk, style=style, size=size, align=align, dy=dy)

    def label_value(label: str, value: str, *, size: int = 10,
                    dy: float | None = None) -> None:
        """Draw a bold "Label:" + regular value on one line if it fits, else
        wrap value at word boundaries. Continuation lines are pure regular
        starting at the left margin (no indent) — matches the operator's
        reference receipt where "Mansabdor: Отежанов Жеңгисбай" wraps to a
        bare "Жиенбаевич" on the next line, same left edge."""
        actual_dy = dy if dy is not None else size * 1.25
        label_w = pdfmetrics.stringWidth(label + " ", _font("bold"), size)
        avail_first = CONTENT_W - label_w
        words = (value or "").split()
        # Pack as many value words as fit after the bold label.
        first_value = ""
        idx = 0
        while idx < len(words):
            trial = first_value + (" " if first_value else "") + words[idx]
            if pdfmetrics.stringWidth(trial, _font("regular"), size) <= avail_first:
                first_value = trial
                idx += 1
            else:
                break
        # Remaining words wrap as regular-only lines at CONTENT_W.
        remaining = []
        if idx < len(words):
            cur = ""
            for w in words[idx:]:
                trial = cur + (" " if cur else "") + w
                if pdfmetrics.stringWidth(trial, _font("regular"), size) <= CONTENT_W:
                    cur = trial
                else:
                    if cur:
                        remaining.append(cur)
                    cur = w
            if cur:
                remaining.append(cur)

        # Emit ops: first line draws bold label + regular value (in two passes);
        # continuation lines are plain regular at left margin.
        def first_op(c, y, lbl=label, val=first_value):
            if c is not None:
                c.setFont(_font("bold"), size)
                c.drawString(MARGIN_X, y, lbl)
                if val:
                    c.setFont(_font("regular"), size)
                    c.drawString(
                        MARGIN_X + pdfmetrics.stringWidth(lbl + " ", _font("bold"), size),
                        y, val,
                    )
            return y - actual_dy
        ops.append(first_op)
        for cont in remaining:
            def cont_op(c, y, val=cont):
                if c is not None:
                    c.setFont(_font("regular"), size)
                    c.drawString(MARGIN_X, y, val)
                return y - actual_dy
            ops.append(cont_op)

    def gap(dy: float) -> None:
        ops.append(lambda c, y: y - dy)

    def hrule(*, dash_on: float = 1.6, dash_off: float = 1.6,
              line_w: float = 0.3) -> None:
        """Dashed separator — placed so both gaps (above to the previous
        text's descender, below to the next text's ascender) are ~2mm,
        matching the operator's reference receipt.

        Math: previous text's line() advanced y by its full dy (~4.5mm),
        so the natural "next y" sits well below the previous baseline.
        We back up by 1.8mm so the line lands ~2.7mm below the previous
        baseline (≈ 2mm below its visible descender), then advance 4.8mm
        so the next text's baseline sits ~2mm visually below the line
        (after accounting for the next text's ~2.8mm ascender)."""
        DY_BEFORE = -1 * mm     # gap above the line, slightly relaxed
        DY_AFTER = 5.5 * mm     # gap below the line — both sides ~2-2.5mm visual
        def op(c, y):
            yy = y - DY_BEFORE
            if c is not None:
                c.saveState()
                c.setDash(dash_on, dash_off)
                c.setLineWidth(line_w)
                c.setStrokeGray(0.45)
                c.line(MARGIN_X, yy, PAGE_W - MARGIN_X, yy)
                c.restoreState()
            return yy - DY_AFTER
        ops.append(op)

    def qr(png: bytes, *, size_mm: float, dy_before: float = 2 * mm,
           dy_after: float = 2 * mm) -> None:
        s = size_mm * mm
        def op(c, y):
            top = y - dy_before
            if c is not None:
                c.drawImage(ImageReader(io.BytesIO(png)),
                            (PAGE_W - s) / 2, top - s, s, s,
                            preserveAspectRatio=True)
            return top - s - dy_after
        ops.append(op)

    # ── 1) Header ─────────────────────────────────────────────────────────
    # Auto-shrink so even long org names ("NUKUS SHAHAR HOKIMLIGI") fit
    # within the 80mm canvas. If still too wide at min size, wrap.
    # `localized_name` falls back to org.name when the translations dict is
    # empty so old orgs without translations still print sensibly.
    from ..domain.organization import localized_name as _localized_name
    org_title = (_localized_name(org, locale) or "").upper().strip() or L["org_fallback"]
    header_size = _fit_font_size(org_title, "bold", max_size=15, min_size=11)
    if pdfmetrics.stringWidth(org_title, _font("bold"), header_size) > CONTENT_W:
        for chunk in _wrap_to_width(org_title, "bold", header_size):
            line(chunk, style="bold", size=header_size, align="center",
                 dy=header_size * 1.15)
    else:
        line(org_title, style="bold", size=header_size, align="center",
             dy=header_size * 1.15)
    gap(0.5 * mm)

    subtitle = L["subtitle_chief"] if (official.role or "").lower() == "chief" \
        else L["subtitle_deputy"]
    line(subtitle, style="regular", size=10, align="center", dy=4.5 * mm)

    hrule()

    # ── 2) Body — chipta / mansabdor / position / masala ──────────────────
    # Reference receipt style: bold label, regular value.
    chipta_no = f"O-{appointment.scheduled_date.strftime('%Y%m%d')}-{appointment.queue_number:03d}"
    label_value(L["chipta_label"], chipta_no, size=10, dy=4.5 * mm)

    mansabdor = (official.name or "—").strip()
    label_value(L["mansabdor_label"], mansabdor, size=10, dy=4.5 * mm)

    # Position descriptor in italic — small breathing room first.
    pos_parts = []
    if official.position:
        pos_parts.append(official.position.strip())
    if official.responsibilities:
        pos_parts.append(official.responsibilities.strip())
    pos = " — ".join(pos_parts)
    if pos:
        for chunk in _wrap_to_width(pos, "italic", 9):
            line(chunk, style="italic", size=9, dy=4 * mm)

    topic = (appointment.topic_summary or "").strip()
    if topic:
        label_value(L["masala_label"], topic, size=10, dy=4.5 * mm)

    hrule()

    # ── 3) Date / time / queue ────────────────────────────────────────────
    label_value(L["sana_label"], format_date(appointment.scheduled_date, locale),
                size=10, dy=4.5 * mm)

    rt = (official.reception_time or "").strip()
    start = rt.split("-")[0].strip() if "-" in rt else rt
    if ":" in start and start.count(":") == 1:
        start = f"{start}:00"
    if start:
        label_value(L["vaqt_label"], start, size=10, dy=4.5 * mm)

    label_value(L["navbat_label"], str(appointment.queue_number),
                size=10, dy=4.5 * mm)

    hrule()

    # ── 4) Phone (own section, matches operator's reference) ──────────────
    label_value(L["telefon_label"], _format_phone_pretty(appointment.visitor_phone),
                size=10, dy=4.5 * mm)

    hrule()

    # ── 5) QR + footer ────────────────────────────────────────────────────
    qr_png = render_qr_png(verify_url, size_px=400)
    qr(qr_png, size_mm=32, dy_before=1 * mm, dy_after=3 * mm)

    # Footer message — wrap to two centered lines if it overflows.
    for chunk in _wrap_to_width(L["footer"], "regular", 9):
        line(chunk, style="regular", size=9, align="center", dy=4 * mm)

    return ops


def render_receipt_pdf(
    appointment: Appointment,
    official: OrgKbOfficial,
    org: Organization,
    verify_url: str,
    *,
    locale: str = "kk",
) -> bytes:
    """Render the appointment receipt as 80mm × dynamic-height PDF.

    `locale` selects the printed language. Supported: 'uz' (Latin),
    'kk' (Karakalpak Cyrillic), 'ru' (Russian). Unknown values fall back
    to Karakalpak Cyrillic to match Organization.locale default.
    """
    _ensure_fonts()

    ops = _build_ops(appointment, official, org, verify_url, locale)

    # Pass 1: measure. y decreases; total content = -y_final.
    y = 0.0
    for op in ops:
        y = op(None, y)
    content_h = -y
    page_h = content_h + MARGIN_TOP + MARGIN_BOTTOM

    # Pass 2: draw.
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, page_h))
    y = page_h - MARGIN_TOP
    for op in ops:
        y = op(c, y)
    c.showPage()
    c.save()
    return buf.getvalue()
