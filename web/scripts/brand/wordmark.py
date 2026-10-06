import sys
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

font = TTFont(sys.argv[1])
font = instantiateVariableFont(font, {"wght": int(sys.argv[3])})
gs = font.getGlyphSet()
cmap = font.getBestCmap()
upm = font["head"].unitsPerEm
text = sys.argv[2]
track = float(sys.argv[4]) * upm  # letter spacing in em
size = 1.0
x = 0
pen = SVGPathPen(gs)
for i, ch in enumerate(text):
    g = cmap[ord(ch)]
    tp = TransformPen(pen, (1, 0, 0, -1, x, 0))
    gs[g].draw(tp)
    x += gs[g].width + (track if i < len(text) - 1 else 0)
asc = font["OS/2"].sCapHeight
print(f"upm={upm} width={x} cap={asc}")
print(pen.getCommands())
