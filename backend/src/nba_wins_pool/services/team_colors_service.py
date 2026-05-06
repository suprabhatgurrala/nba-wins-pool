import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).parent.parent / "data" / "nba-team-details.json"

_MIN_LUMINANCE = 0.05  # filters colors too dark to see on a dark background
_MIN_HUE_DIFF = 30.0  # degrees; primary distinguishability criterion
_MIN_SATURATION = 0.15  # below this, hue is meaningless (grays/near-whites)
_MIN_GRAY_CONTRAST = 1.5  # luminance contrast fallback only when both colors are unsaturated
_FALLBACK_COLOR = "#6b7280"


def _relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _hue(hex_color: str) -> tuple[float, float]:
    """Return (hue_degrees, saturation) in HSL space."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    max_c, min_c = max(r, g, b), min(r, g, b)
    d = max_c - min_c
    lightness = (max_c + min_c) / 2
    if d == 0:
        return 0.0, 0.0
    saturation = d / (2 - max_c - min_c) if lightness > 0.5 else d / (max_c + min_c)
    if max_c == r:
        hue = (g - b) / d % 6
    elif max_c == g:
        hue = (b - r) / d + 2
    else:
        hue = (r - g) / d + 4
    return hue * 60, saturation


def _distinguishable(hex1: str, hex2: str) -> bool:
    """Two colors are distinguishable if they differ enough in hue.

    Luminance contrast is only used as a fallback when both colors are unsaturated
    (grays), where hue is meaningless.
    """
    h1, s1 = _hue(hex1)
    h2, s2 = _hue(hex2)
    both_unsaturated = s1 < _MIN_SATURATION and s2 < _MIN_SATURATION
    if both_unsaturated:
        l1, l2 = _relative_luminance(hex1), _relative_luminance(hex2)
        return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05) >= _MIN_GRAY_CONTRAST
    # One or both colors are saturated — hue difference is the decider.
    # A saturated color paired with a gray is always distinguishable.
    if s1 < _MIN_SATURATION or s2 < _MIN_SATURATION:
        return True
    return min(abs(h1 - h2), 360 - abs(h1 - h2)) >= _MIN_HUE_DIFF


_CANDIDATE_LABELS = ["primary", "secondary", "tertiary"]


def _candidate_colors(colors: dict) -> list[tuple[str, str]]:
    """Return (color, label) pairs that pass the minimum luminance threshold."""
    candidates = []
    for label, key in zip(_CANDIDATE_LABELS, ["primaryDark", "secondaryDark", "tertiaryDark"]):
        c = colors.get(key)
        if c and _relative_luminance(c) >= _MIN_LUMINANCE:
            candidates.append((c, label))
    return candidates or [(_FALLBACK_COLOR, "fallback")]


def _best_pair(away: list[tuple[str, str]], home: list[tuple[str, str]]) -> tuple[str, str, str, str]:
    """Return (away_color, away_label, home_color, home_label).

    Pairs are tried by increasing depth (sum of candidate indices) so that changing just
    one team's color is always preferred over changing both.
    """
    for depth in range(len(away) + len(home) - 1):
        for i in range(depth + 1):
            j = depth - i
            if i >= len(away) or j >= len(home):
                continue
            ac, al = away[i]
            hc, hl = home[j]
            if _distinguishable(ac, hc):
                return ac, al, hc, hl
    # Nothing distinguishable by hue — best luminance contrast as last resort
    best_contrast = 0.0
    result = (*away[0], *home[0])
    for ac, al in away:
        for hc, hl in home:
            l1, l2 = _relative_luminance(ac), _relative_luminance(hc)
            c = (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)
            if c > best_contrast:
                best_contrast = c
                result = (ac, al, hc, hl)
    return result


# {away_tricode: {home_tricode: {"away": color, "home": color}}}
_matchup_colors: dict[str, dict[str, dict[str, str]]] = {}
# Same structure but includes label metadata for inspection
_matchup_colors_debug: dict[str, dict[str, dict[str, str]]] = {}


def build_matchup_colors() -> None:
    """Precompute bar colors for every possible matchup. Called once at startup."""
    with open(_DATA_PATH) as f:
        team_details = json.load(f)

    candidates: dict[str, list[tuple[str, str]]] = {
        abbr.upper(): _candidate_colors(details["colors"]) for abbr, details in team_details.items()
    }

    for away_tricode, away_candidates in candidates.items():
        _matchup_colors[away_tricode] = {}
        _matchup_colors_debug[away_tricode] = {}
        for home_tricode, home_candidates in candidates.items():
            ac, al, hc, hl = _best_pair(away_candidates, home_candidates)
            _matchup_colors[away_tricode][home_tricode] = {"away": ac, "home": hc}
            _matchup_colors_debug[away_tricode][home_tricode] = {
                "away": ac,
                "away_label": al,
                "home": hc,
                "home_label": hl,
            }

    logger.info("Precomputed team color pairings for %d teams (%d matchups)", len(candidates), len(candidates) ** 2)


def get_matchup_colors() -> dict[str, dict[str, dict[str, str]]]:
    return _matchup_colors


def get_matchup_colors_debug() -> dict[str, dict[str, dict[str, str]]]:
    return _matchup_colors_debug
