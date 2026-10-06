"""Build SUNSCRYPT brand assets (SVG + PNG) from code.

    pip install fonttools cairosvg
    python brand/build_brand.py            # writes brand/assets/* and web/public/brand/*

The wordmark is converted to outlines (no font needed to display the logo).
Fonts are downloaded from google/fonts (OFL) into brand/.fonts/ on first run.
"""
from __future__ import annotations

import io
import os
import shutil
import urllib.request

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets")
WEB = os.path.join(HERE, "..", "web", "public", "brand")
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/unbounded/Unbounded%5Bwght%5D.ttf"

# ---- palette (also mirrored in web/src/app/globals.css) -------------------------------------------
INK = "#0D1320"      # night sky
SOLAR = "#FFB21A"    # sun, top
FLARE = "#FF5A36"    # sun, horizon
DAWN = "#FFF3DE"     # light ground / text on dark
SLATE = "#7D879A"    # secondary text


def font() -> TTFont:
    os.makedirs(os.path.join(HERE, ".fonts"), exist_ok=True)
    path = os.path.join(HERE, ".fonts", "Unbounded.ttf")
    if not os.path.exists(path):
        with urllib.request.urlopen(FONT_URL, timeout=60) as r, open(path, "wb") as f:
            f.write(r.read())
    f = TTFont(path)
    return instantiateVariableFont(f, {"wght": 700})


UP = "#1F9D6B"       # green candle
DOWN = "#D93F45"     # red candle


def wordmark_path(text: str, tracking: float = 0.03, skip: str = "N") -> tuple[str, float, float, list]:
    """SVG path of `text` in Unbounded Bold, baseline at y=0, cap height normalised to 100 units.

    Letters in `skip` are left out; their ink boxes (x0, x1, stem) are returned so candles can replace them.
    """
    f = font()
    gs, cmap, hmtx = f.getGlyphSet(), f.getBestCmap(), f["hmtx"]
    upm = f["head"].unitsPerEm
    cap = f["OS/2"].sCapHeight or 0.7 * upm
    scale = 100 / cap
    pen = SVGPathPen(gs)
    x = 0.0
    holes = []
    stem_box = BoundsPen(gs)
    gs[cmap[ord("I")]].draw(stem_box)
    stem = (stem_box.bounds[2] - stem_box.bounds[0]) * scale
    for ch in text:
        g = cmap[ord(ch)]
        if ch in skip:
            bp = BoundsPen(gs)
            gs[g].draw(bp)
            holes.append((x + bp.bounds[0] * scale, x + bp.bounds[2] * scale, stem))
        else:
            gs[g].draw(TransformPen(pen, (scale, 0, 0, -scale, x, 0)))
        x += (hmtx[g][0] + tracking * upm) * scale
    width = x - tracking * upm * scale
    bp = BoundsPen(gs)
    gs[cmap[ord(text[0])]].draw(bp)
    left = (bp.bounds[0] if bp.bounds else 0) * scale
    return pen.getCommands(), width, left, holes


def candle_n(x0: float, x1: float, stem: float, bg: str) -> str:
    """Letter N as three candles: green up, red down (the diagonal), green up. Baseline y=0, cap y=-100."""
    top, bot, wick = -93.0, -7.0, 5.0           # bodies fill the cap height; wicks poke just past it
    gap = 3.2                                   # background-coloured outline that separates the candles

    def green(xl: float) -> str:
        cx = xl + stem / 2
        return (f'<rect x="{cx - wick / 2:.2f}" y="-106" width="{wick}" height="112" rx="{wick / 2}" fill="{UP}"/>'
                f'<rect x="{xl:.2f}" y="{top}" width="{stem:.2f}" height="{bot - top}" rx="3" fill="{UP}" '
                f'stroke="{bg}" stroke-width="{gap}" paint-order="stroke"/>')

    # red body: parallelogram from the top of the left stem to the bottom of the right stem
    a, b = x0 + stem * 0.1, x0 + stem * 1.45
    c, d = x1 - stem * 1.45, x1 - stem * 0.1
    red = f'<path d="M{a:.2f} {top}H{b:.2f}L{d:.2f} {bot}H{c:.2f}Z" fill="{DOWN}"/>'
    return f"<g>{red}{green(x0)}{green(x1 - stem)}</g>"


def _slice(cx: float, cy: float, r: float, y0: float, y1: float) -> str:
    """Path of the horizontal band of a circle between y0 < y1 (arcs on both sides)."""
    def x(y: float) -> float:
        return max(r * r - (y - cy) ** 2, 0) ** 0.5

    a, b = x(y0), x(y1)
    return (f"M{cx - a:.3f} {y0:.3f}H{cx + a:.3f}A{r} {r} 0 0 1 {cx + b:.3f} {y1:.3f}"
            f"H{cx - b:.3f}A{r} {r} 0 0 1 {cx - a:.3f} {y0:.3f}Z")


SUN = (32.0, 31.0, 21.0)                                   # cx, cy, r on a 64x64 grid
GAPS = [(36.5, 2.2), (41.4, 2.8), (46.8, 3.4)]             # slits widen toward the horizon


def sun_path() -> str:
    """The sun cut by three horizontal slits, as plain paths (no masks: renders the same everywhere)."""
    cx, cy, r = SUN
    edges, y = [], cy - r
    for g0, h in GAPS:
        edges.append((y, g0))
        y = g0 + h
    edges.append((y, cy + r))
    return "".join(_slice(cx, cy, r, a, b) for a, b in edges)


def mark(size: int = 64, tile: str | None = None, uid: str = "m") -> str:
    """The sun over a sliced horizon. Drawn on a 64x64 grid; `tile` adds a rounded background."""
    bg = f'<rect width="64" height="64" rx="14" fill="{tile}"/>' if tile else ""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{size}" height="{size}">
  <defs>
    <linearGradient id="{uid}g" x1="0" y1="10" x2="0" y2="52" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{SOLAR}"/><stop offset="1" stop-color="{FLARE}"/>
    </linearGradient>
  </defs>
  {bg}
  <path d="{sun_path()}" fill="url(#{uid}g)"/>
</svg>'''


def inner(svg: str) -> str:
    return svg.split(">", 1)[1].rsplit("</svg>", 1)[0]


def logo(text_color: str, uid: str, bg: str) -> str:
    """Horizontal lockup: mark + outlined wordmark with the candle N."""
    d, w, left, holes = wordmark_path("SUNSCRYPT")
    n = "".join(candle_n(*h, bg) for h in holes)
    s = 0.36                                     # cap height 100 -> 36 px, matches the 64 px mark
    gap = 18
    total_w = 64 + gap + w * s
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w:.1f} 64" height="64">
  <g>{inner(mark(64, uid=uid))}</g>
  <g transform="translate({64 + gap - left * s:.2f} 50) scale({s})"><path d="{d}" fill="{text_color}"/>{n}</g>
</svg>'''


def wordmark(text_color: str, bg: str) -> str:
    d, w, left, holes = wordmark_path("SUNSCRYPT")
    n = "".join(candle_n(*h, bg) for h in holes)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="{left:.1f} -100 {w - left:.1f} 100" height="100">
  <path d="{d}" fill="{text_color}"/>{n}
</svg>'''


def write(name: str, svg: str) -> None:
    for root in (OUT, WEB):
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, name), "w") as f:
            f.write(svg)


def png(name: str, svg: str, size: int) -> None:
    import cairosvg

    data = cairosvg.svg2png(bytestring=svg.encode(), output_width=size, output_height=size)
    for root in (OUT, WEB):
        with open(os.path.join(root, name), "wb") as f:
            f.write(data)


def main() -> None:
    write("mark.svg", mark(64, uid="a"))
    write("logo-light.svg", logo(INK, "b", DAWN))          # for light backgrounds
    write("logo-dark.svg", logo(DAWN, "c", INK))          # for dark backgrounds
    write("wordmark-light.svg", wordmark(INK, DAWN))
    write("wordmark-dark.svg", wordmark(DAWN, INK))
    tile = mark(64, tile=INK, uid="t")
    write("icon.svg", tile)
    png("favicon-32.png", tile, 32)
    png("apple-touch-icon.png", tile, 180)
    png("icon-512.png", tile, 512)
    # Telegram avatar: Telegram crops to a circle, so the sun sits centred on a full-bleed square.
    avatar = mark(64, uid="v").replace('<path', f'<rect width="64" height="64" fill="{INK}"/>\n  <path', 1)
    png("telegram-avatar-640.png", avatar, 640)
    # web app icon used by Next.js (src/app/icon.svg)
    shutil.copy(os.path.join(OUT, "icon.svg"), os.path.join(HERE, "..", "web", "src", "app", "icon.svg"))
    print("brand assets written to", OUT)


if __name__ == "__main__":
    main()
