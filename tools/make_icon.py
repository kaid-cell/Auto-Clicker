"""Regenerates assets/icon.ico (requires Pillow: pip install pillow).

The generated icon is committed, so this is only needed to change the artwork.
"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZE = 1024  # drawn large, then downsampled for smooth edges
OUT = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
VIOLET, CYAN = (124, 92, 255), (0, 212, 255)


def gradient(size: int) -> Image.Image:
    """Diagonal violet -> cyan gradient."""
    g = Image.new("RGB", (size, size))
    px = g.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(VIOLET, CYAN))
    return g


def draw() -> Image.Image:
    s = SIZE / 256
    small = gradient(128).resize((SIZE, SIZE), Image.BICUBIC)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((8 * s, 8 * s, 248 * s, 248 * s), radius=60 * s, fill=255)
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    img.paste(small, (0, 0), mask)

    d = ImageDraw.Draw(img)
    # Click ripples around the pointer tip
    cx, cy = 96 * s, 92 * s
    for r, a in ((62, 120), (40, 190)):
        d.arc((cx - r * s, cy - r * s, cx + r * s, cy + r * s), 195, 345,
              fill=(255, 255, 255, a), width=int(11 * s))
    # Pointer with soft shadow
    arrow = [(96, 92), (96, 210), (125, 182), (146, 228), (170, 217), (149, 172), (190, 172)]
    pts = [(x * s, y * s) for x, y in arrow]
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(x + 6 * s, y + 8 * s) for x, y in pts], fill=(20, 10, 60, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(8 * s))
    shadow.putalpha(ImageChops.multiply(shadow.getchannel("A"), mask))
    img = Image.alpha_composite(img, shadow)
    ImageDraw.Draw(img).polygon(pts, fill=(255, 255, 255, 255))
    return img.resize((256, 256), Image.LANCZOS)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    draw().save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Wrote {OUT}")
