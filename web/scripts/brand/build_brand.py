"""Генерирует SVG бренда SUNSCRYPT в web/public/brand и web/src/app."""
import re, sys, pathlib

root = pathlib.Path(sys.argv[1])
wm = (pathlib.Path(sys.argv[2]).read_text().splitlines())
meta = dict(kv.split("=") for kv in wm[0].split())
width_u, cap_u = float(meta["width"]), float(meta["cap"])
d = re.sub(r"-?\d+\.\d+", lambda m: f"{float(m.group()):.0f}", wm[1])

SUN = {"dark": "#F5A524", "light": "#D97A00"}
INK = {"dark": "#F2EFE8", "light": "#14171C"}
# Свечи-лучи: зелёные (рост) и красные (падение), как на графике.
UP = {"dark": "#2BB673", "light": "#1F9D63"}
DOWN = {"dark": "#E5484D", "light": "#D93F45"}
RAYS = ((-60, "up"), (-30, "down"), (0, "up"), (30, "down"), (60, "up"))

def mark(color, bg=None, reflect=True, theme="dark"):
    def ray(a, kind):
        c = (UP if kind == "up" else DOWN)[theme]
        return (f'<g transform="rotate({a} 32 38)"><path d="M32 9.5v11" stroke="{c}" stroke-width="2" stroke-linecap="round"/>'
                f'<rect x="29.5" y="11.5" width="5" height="7" rx="1.5" fill="{c}"/></g>')
    rays = "".join(ray(a, k) for a, k in RAYS)
    return (
        (f'<rect width="64" height="64" fill="{bg}"/>' if bg else "")
        + f'<path d="M20 38a12 12 0 0 1 24 0z" fill="{color}"/>'
        + rays
        + f'<rect x="4" y="41.5" width="56" height="3.5" rx="1.75" fill="{color}"/>'
        + (f'<rect x="14" y="48.5" width="36" height="3" rx="1.5" fill="{color}" opacity=".55"/>'
           f'<rect x="24" y="55" width="16" height="3" rx="1.5" fill="{color}" opacity=".3"/>' if reflect else "")
    )

def svg(w, h, body, title="SUNSCRYPT"):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-label="{title}"><title>{title}</title>{body}</svg>\n')

cap_px = 24
s = cap_px / cap_u
wm_w = width_u * s
x0, base = 78, 32 + cap_px / 2
total_w = round(x0 + wm_w + 2)

out = root / "public" / "brand"
for theme in ("dark", "light"):
    logo = mark(SUN[theme], theme=theme) + (
        f'<path transform="translate({x0} {base}) scale({s:.5f})" fill="{INK[theme]}" d="{d}"/>')
    (out / f"logo-{theme}.svg").write_text(svg(total_w, 64, logo))
    (out / f"mark-{theme}.svg").write_text(svg(64, 64, mark(SUN[theme], theme=theme)))
    wm_only = f'<path transform="translate(1 {cap_px + 1}) scale({s:.5f})" fill="{INK[theme]}" d="{d}"/>'
    (out / f"wordmark-{theme}.svg").write_text(svg(round(wm_w + 2), cap_px + 2, wm_only))

# Значок приложения/аватар: знак на ночном фоне, с полями под круглую обрезку
# Telegram (знак внутри вписанного круга).
def badge(size_note):
    inner = mark(SUN["dark"])
    return svg(64, 64, '<rect width="64" height="64" fill="#0B0D10"/>'
               f'<g transform="translate(32 33) scale(.72) translate(-32 -33)">{inner}</g>')
(out / "avatar.svg").write_text(badge(640))
# favicon: адаптивный — светлый знак на тёмной плашке со скруглением.
(root / "src" / "app" / "icon.svg").write_text(svg(64, 64,
    '<rect width="64" height="64" rx="14" fill="#0B0D10"/>'
    f'<g transform="translate(32 33) scale(1.04) translate(-32 -27)">{mark(SUN["dark"], reflect=False)}</g>'))
print("logo width", total_w)
