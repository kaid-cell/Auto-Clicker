"""Regenerates assets/icon.ico (requires Pillow: pip install pillow).

The generated icon is committed, so this is only needed to change the artwork.
"""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
OUT = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"


def draw(size: int = SIZE) -> Image.Image:
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Rounded blue tile
    d.rounded_rectangle((8 * s, 8 * s, 248 * s, 248 * s), radius=52 * s, fill=(0, 103, 192, 255))
    # Click "ripples"
    cx, cy = 104 * s, 100 * s
    for r, w in ((70, 10), (44, 10)):
        d.arc((cx - r * s, cy - r * s, cx + r * s, cy + r * s), 200, 340,
              fill=(255, 255, 255, 150), width=max(1, int(w * s)))
    # Mouse pointer arrow
    arrow = [(104, 100), (104, 214), (132, 186), (152, 232), (174, 222), (154, 177), (194, 177)]
    d.polygon([(x * s, y * s) for x, y in arrow], fill=(255, 255, 255, 255),
              outline=(20, 40, 70, 255), width=max(1, int(6 * s)))
    return img


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    draw().save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Wrote {OUT}")
