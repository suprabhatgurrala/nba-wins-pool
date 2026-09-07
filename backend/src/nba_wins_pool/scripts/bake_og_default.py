#!/usr/bin/env python3
"""Bake the default site-wide OG preview image into frontend/public/og-default.png.

Rendered composition: a tinted sticker-bomb of 🏀 and 🏆 emojis behind a
centered "NBA Wins Pool" wordmark. This image is the fallback social embed for
URLs that don't have a pool-specific card (e.g. the homepage and the pool list).

macOS-only: emoji rendering uses Apple Color Emoji from /System/Library/Fonts.
Cross-platform baking would require bundling a ~10 MB color emoji font, which
isn't worth it for a script that runs only when the default image needs to be
regenerated. The resulting PNG ships in the frontend build and is served
statically at /og-default.png.
"""

import logging
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from nba_wins_pool.services.og_image_service import CARD_H, CARD_W, PALETTE, _font

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("bake_og_default")

APPLE_EMOJI_PATH = Path("/System/Library/Fonts/Apple Color Emoji.ttc")
OUTPUT_PATH = Path(__file__).resolve().parents[4] / "frontend" / "public" / "og-default.png"

WORDMARK = "NBA Wins Pool"
BASKETBALL = "🏀"
TROPHY = "🏆"

# Composition tuned during design iteration; adjust here if the visual changes.
STEP_X = 175
STEP_Y = 155
STICKER_SIZE = 100
TEXT_SIZE = 150
STICKER_OPACITY = 0.55
ROTATION_RANGE = (-25, 25)
JITTER_X = 20
JITTER_Y = 16
RNG_SEED = 42

# Apple Color Emoji ships fixed-size bitmaps; 160 is the largest and we
# downscale to the target STICKER_SIZE for a crisp result.
EMOJI_NATIVE_SIZE = 160


def _make_tile(emoji_font: ImageFont.FreeTypeFont, emoji: str) -> Image.Image:
    """Render one emoji at native size and downscale it to STICKER_SIZE."""
    tile = Image.new("RGBA", (EMOJI_NATIVE_SIZE, EMOJI_NATIVE_SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(tile).text((0, 0), emoji, font=emoji_font, embedded_color=True)
    return tile.resize((STICKER_SIZE, STICKER_SIZE), Image.Resampling.LANCZOS)


def _tile_stickers(emoji_font: ImageFont.FreeTypeFont) -> Image.Image:
    """Compose the scattered rotated emoji background at STICKER_OPACITY."""
    stickers = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    rng = random.Random(RNG_SEED)
    hoop = _make_tile(emoji_font, BASKETBALL)
    trophy = _make_tile(emoji_font, TROPHY)

    for row in range(-1, CARD_H // STEP_Y + 2):
        for col in range(-1, CARD_W // STEP_X + 2):
            # Stagger every other row for a brick-like pattern instead of a grid.
            offset_x = (STEP_X // 2) if row % 2 else 0
            cx = col * STEP_X + offset_x + rng.randint(-JITTER_X, JITTER_X)
            cy = row * STEP_Y + rng.randint(-JITTER_Y, JITTER_Y)
            tile = hoop if (row + col) % 2 == 0 else trophy
            rotated = tile.rotate(rng.uniform(*ROTATION_RANGE), resample=Image.Resampling.BICUBIC, expand=True)
            stickers.alpha_composite(rotated, (cx - rotated.width // 2, cy - rotated.height // 2))

    r, g, b, a = stickers.split()
    a = a.point(lambda v: int(v * STICKER_OPACITY))
    return Image.merge("RGBA", (r, g, b, a))


def _render() -> Image.Image:
    emoji_font = ImageFont.truetype(str(APPLE_EMOJI_PATH), size=EMOJI_NATIVE_SIZE)
    text_font = _font(TEXT_SIZE, 800)

    base = Image.new("RGBA", (CARD_W, CARD_H), PALETTE["bg"])
    base.alpha_composite(_tile_stickers(emoji_font))

    # Center the wordmark using its ink bounds so ascender/descender padding
    # doesn't shift the visual center.
    left, top, right, bottom = text_font.getbbox(WORDMARK)
    x = (CARD_W - (right - left)) / 2 - left
    y = CARD_H / 2 - (top + bottom) / 2
    ImageDraw.Draw(base).text((x, y), WORDMARK, font=text_font, fill=PALETTE["text"])
    return base.convert("RGB")


def main() -> None:
    if not APPLE_EMOJI_PATH.exists():
        logger.error("Apple Color Emoji not found at %s. This script is macOS-only.", APPLE_EMOJI_PATH)
        sys.exit(1)

    logger.info("Rendering default OG image...")
    img = _render()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT_PATH, format="PNG", optimize=True)
    logger.info("Wrote %s (%d bytes)", OUTPUT_PATH, OUTPUT_PATH.stat().st_size)


if __name__ == "__main__":
    main()
