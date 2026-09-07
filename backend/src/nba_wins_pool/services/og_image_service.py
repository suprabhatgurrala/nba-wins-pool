"""Render the pool share-preview card as a 1200x630 PNG."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Aura dark-mode tokens from PrimeVue's default preset.
PALETTE = {
    "bg": "#09090b",
    "divider": "#27272a",
    "text": "#ffffff",
    "muted": "#a1a1aa",
    "accent": "#10b981",
}

CARD_W = 1200
CARD_H = 630
OUTER_PAD = 64
HEADER_TO_HAIRLINE = 80
HAIRLINE_TO_BODY = 16
FOOTER_RESERVED = 32
ROWS_PER_COL = 4
MAX_SLOTS = ROWS_PER_COL * 2  # 8

_FONT_PATH = Path(__file__).parent.parent / "assets" / "fonts" / "Inter-Variable.ttf"


@dataclass(frozen=True)
class LeaderboardEntry:
    name: str
    # wins/losses are optional so callers can render a roster list without
    # standings (e.g. when NBA data is unavailable). Both must be set together.
    wins: int | None = None
    losses: int | None = None

    @property
    def has_record(self) -> bool:
        return self.wins is not None and self.losses is not None


@dataclass(frozen=True)
class _RowStyle:
    """Font and spacing choices for one leaderboard row. Depends on layout density."""

    cols: int
    rank_font: ImageFont.FreeTypeFont
    name_font: ImageFont.FreeTypeFont
    record_font: ImageFont.FreeTypeFont
    rank_col_w: int
    rank_to_name_gap: int
    name_to_record_gap: int
    col_gutter: int


def render_pool_card(
    pool_name: str,
    season_label: str,
    rows: list[LeaderboardEntry],
    total_rosters: int,
) -> bytes:
    """Render a 1200x630 pool leaderboard preview PNG. Returns raw PNG bytes."""
    img = Image.new("RGB", (CARD_W, CARD_H), PALETTE["bg"])
    draw = ImageDraw.Draw(img)

    visible = rows[:MAX_SLOTS]
    style = _row_style_for(len(visible))

    hairline_y = _draw_header(draw, pool_name, season_label)
    _draw_body(draw, visible, style, hairline_y)
    _draw_footer(draw, total_rosters)

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _draw_header(draw: ImageDraw.ImageDraw, pool_name: str, season_label: str) -> int:
    """Draw the pool title, season label, and accent hairline. Returns the hairline y."""
    title_font = _font(56, 700)
    season_font = _font(40, 600)

    season_w = draw.textlength(season_label, font=season_font)
    draw.text(
        (CARD_W - OUTER_PAD - season_w, OUTER_PAD + 8),
        season_label,
        font=season_font,
        fill=PALETTE["text"],
    )

    title_max_w = CARD_W - 2 * OUTER_PAD - season_w - 32
    display_name = _truncate(draw, pool_name, title_font, title_max_w)
    draw.text((OUTER_PAD, OUTER_PAD), display_name, font=title_font, fill=PALETTE["text"])

    hairline_y = OUTER_PAD + HEADER_TO_HAIRLINE
    draw.rectangle(
        (OUTER_PAD, hairline_y, CARD_W - OUTER_PAD, hairline_y + 2),
        fill=PALETTE["accent"],
    )
    return hairline_y


def _draw_body(
    draw: ImageDraw.ImageDraw,
    entries: list[LeaderboardEntry],
    style: _RowStyle,
    hairline_y: int,
) -> None:
    """Draw the leaderboard rows using column-major fill (top-to-bottom, left-to-right)."""
    body_top = hairline_y + HAIRLINE_TO_BODY
    body_bottom = CARD_H - OUTER_PAD - FOOTER_RESERVED
    row_h = (body_bottom - body_top) // ROWS_PER_COL

    rows_used = min(ROWS_PER_COL, len(entries))
    rows_top = body_top + ((body_bottom - body_top) - row_h * rows_used) // 2

    col_w = (CARD_W - 2 * OUTER_PAD - style.col_gutter * (style.cols - 1)) // style.cols
    col_area_start = OUTER_PAD + (CARD_W - 2 * OUTER_PAD - col_w) // 2 if style.cols == 1 else OUTER_PAD

    for i, entry in enumerate(entries):
        col_idx, row_idx = divmod(i, ROWS_PER_COL)
        col_start = col_area_start + col_idx * (col_w + style.col_gutter)
        row_center_y = rows_top + row_h * row_idx + row_h // 2
        _draw_row(draw, entry, i + 1, style, col_start, col_w, row_center_y)

        rows_in_col = min(ROWS_PER_COL, max(0, len(entries) - col_idx * ROWS_PER_COL))
        if row_idx < rows_in_col - 1:
            divider_y = rows_top + row_h * (row_idx + 1)
            divider_left = col_start if not entry.has_record else col_start + style.rank_col_w + style.rank_to_name_gap
            draw.rectangle(
                (divider_left, divider_y - 1, col_start + col_w, divider_y),
                fill=PALETTE["divider"],
            )


def _draw_row(
    draw: ImageDraw.ImageDraw,
    entry: LeaderboardEntry,
    rank: int,
    style: _RowStyle,
    col_start: int,
    col_w: int,
    center_y: float,
) -> None:
    col_end = col_start + col_w

    if not entry.has_record:
        # Standings unavailable — drop rank + record and give the name full width.
        display_name = _truncate(draw, entry.name, style.name_font, col_w)
        _draw_text_vcentered(draw, display_name, style.name_font, col_start, center_y, PALETTE["text"])
        return

    rank_text = str(rank)
    _draw_text_vcentered(
        draw,
        rank_text,
        style.rank_font,
        col_start + style.rank_col_w / 2 - draw.textlength(rank_text, font=style.rank_font) / 2,
        center_y,
        PALETTE["accent"],
    )

    record_text = f"{entry.wins}–{entry.losses}"
    record_w = draw.textlength(record_text, font=style.record_font)
    _draw_text_vcentered(
        draw, record_text, style.record_font, col_end - record_w, center_y, PALETTE["text"]
    )

    name_x = col_start + style.rank_col_w + style.rank_to_name_gap
    name_max_w = col_end - record_w - style.name_to_record_gap - name_x
    display_name = _truncate(draw, entry.name, style.name_font, name_max_w)
    _draw_text_vcentered(draw, display_name, style.name_font, name_x, center_y, PALETTE["text"])


def _draw_footer(draw: ImageDraw.ImageDraw, total_rosters: int) -> None:
    font = _font(22, 500)
    if total_rosters > MAX_SLOTS:
        extra = total_rosters - MAX_SLOTS
        noun = "roster" if extra == 1 else "rosters"
        text = f"…and {extra} more {noun}"
    else:
        text = "NBA Wins Pool"
    _draw_text_vcentered(draw, text, font, OUTER_PAD, CARD_H - OUTER_PAD - font.size / 2, PALETTE["muted"])


def _row_style_for(entry_count: int) -> _RowStyle:
    """Denser two-column layout for 5-8 rosters; larger single centered column for <=4."""
    if entry_count <= ROWS_PER_COL:
        return _RowStyle(
            cols=1,
            rank_font=_font(52, 700),
            name_font=_font(52, 600),
            record_font=_font(52, 700),
            rank_col_w=68,
            rank_to_name_gap=24,
            name_to_record_gap=24,
            col_gutter=0,
        )
    return _RowStyle(
        cols=2,
        rank_font=_font(40, 700),
        name_font=_font(40, 600),
        record_font=_font(40, 700),
        rank_col_w=48,
        rank_to_name_gap=16,
        name_to_record_gap=20,
        col_gutter=32,
    )


def _font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(_FONT_PATH), size=size)
    # Inter[opsz,wght] axis order: [opsz, wght]. Clamp opsz to the axis range.
    opsz = max(14, min(32, size))
    font.set_variation_by_axes([opsz, weight])
    return font


def _draw_text_vcentered(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    x: float,
    center_y: float,
    fill: str,
) -> None:
    _, top, _, bottom = font.getbbox(text)
    draw.text((x, center_y - (bottom - top) / 2 - top), text, font=font, fill=fill)


def _truncate(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if draw.textlength(text[:mid] + ellipsis, font=font) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ellipsis
