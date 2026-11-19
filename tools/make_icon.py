"""Generates assets/LiveCaption.ico (and a PNG preview).

Same family as LiveCue, LiveSlides and LiveCount (same dark tile, palette and proportions):
a light speech bubble holding caption lines - green for what is being said, amber for the
second speaker / translation, dim for the line still being written. Small sizes (<= 32 px)
use a simplified drawing so it stays readable in the taskbar and title bar.

Usage: python tools/make_icon.py   (needs Pillow)
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT_ICO = ROOT / "assets" / "LiveCaption.ico"
OUT_PNG = ROOT / "assets" / "LiveCaption.png"

SUPERSAMPLE = 1024

# Palette shared with LiveCue, LiveSlides and LiveCount.
TILE_TOP = (52, 57, 66)
TILE_BOTTOM = (22, 24, 28)
DIM = (98, 106, 122)
AMBER = (255, 179, 0)
GO_TOP = (102, 222, 128)
GO_BOTTOM = (34, 160, 70)
LIGHT = (235, 238, 242)


def vertical_gradient(size, top, bottom):
    gradient = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / (size - 1)
        gradient.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    return gradient.resize((size, size))


def rounded_mask(size, box, radius):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    return mask


def draw(simplified: bool) -> Image.Image:
    s = SUPERSAMPLE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    margin = s * 0.03
    tile_box = (margin, margin, s - margin, s - margin)
    img.paste(vertical_gradient(s, TILE_TOP, TILE_BOTTOM), (0, 0), rounded_mask(s, tile_box, s * 0.2))
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return (s * x0, s * y0, s * x1, s * y1)

    if simplified:
        bubble = (0.10, 0.14, 0.90, 0.72)
        tail = [(0.22, 0.66), (0.44, 0.66), (0.20, 0.88)]
        lines = [((0.22, 0.29, 0.78, 0.40), "go"), ((0.22, 0.47, 0.60, 0.58), AMBER)]
        corner = 0.12
    else:
        bubble = (0.12, 0.15, 0.88, 0.68)
        tail = [(0.24, 0.62), (0.42, 0.62), (0.22, 0.83)]
        lines = [((0.22, 0.25, 0.78, 0.32), "go"),
                 ((0.22, 0.375, 0.66, 0.445), "go"),
                 ((0.22, 0.50, 0.50, 0.57), AMBER),
                 ((0.535, 0.50, 0.63, 0.57), DIM)]
        corner = 0.09

    d.rounded_rectangle(box(*bubble), radius=s * corner, fill=LIGHT)
    d.polygon([(s * x, s * y) for x, y in tail], fill=LIGHT)

    go = vertical_gradient(s, GO_TOP, GO_BOTTOM)
    for (x0, y0, x1, y1), color in lines:
        b = box(x0, y0, x1, y1)
        r = s * (y1 - y0) / 2
        if color == "go":
            img.paste(go, (0, 0), rounded_mask(s, b, r))
        else:
            d.rounded_rectangle(b, radius=r, fill=color)
    return img


def main():
    full = draw(simplified=False)
    small = draw(simplified=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    frames = [(small if size <= 32 else full).resize((size, size), Image.LANCZOS) for size in sizes]
    OUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(OUT_ICO, format="ICO", sizes=[(f.width, f.height) for f in frames], append_images=frames[:-1])
    full.resize((512, 512), Image.LANCZOS).save(OUT_PNG)
    print(f"Wrote {OUT_ICO} and {OUT_PNG}")


if __name__ == "__main__":
    main()
