# app/make_icon.py
"""Turns `assets/nghetruyen-source.png` into the App's icon.

    sidecar\\venv\\Scripts\\python.exe app\\make_icon.py

The source is the artwork: a 1024x1024 rounded tile with the mark on it, sitting
on an opaque white margin. It is the one file to replace when the mark changes
-- generate or draw a new square PNG, drop it in as `nghetruyen-source.png`, and
run this. It writes `nghetruyen.ico` (the icon Windows shows) and
`nghetruyen-256.png` (the preview to look at before trusting the small sizes).

Three things the artwork does not do for you, and this does:

  1. **Crops** to the tile, so the icon is the tile and not the tile plus a
     white border.
  2. **Masks the corners transparent.** Artwork exported from an image tool has
     opaque corners; left alone they show as white notches on a dark taskbar.
  3. **Generates every size.** Windows asks for 16, 24, 32, 48, 64, 128 and 256
     and scales nothing itself, so each is resampled from the artwork and its
     corners re-masked at that size.

The mark itself is white headphones with a cyan play triangle on navy: "listen"
plus "press play". Two shapes and three colours, because 16x16 -- the taskbar --
is the size that decides whether an icon reads at all. See
docs/adr/0015-app-icon.md.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).parent / "assets"
SOURCE_PATH = ASSETS / "nghetruyen-source.png"
ICON_PATH = ASSETS / "nghetruyen.ico"
PREVIEW_PATH = ASSETS / "nghetruyen-256.png"

# The sizes Windows asks for: 16 is the taskbar and the window title bar, 32
# the Alt-Tab switcher, 48/64 the desktop, 128/256 the large-icon views and the
# exe's own thumbnail.
SIZES = (16, 24, 32, 48, 64, 128, 256)

TILE_THRESHOLD = 40  # how far from white a pixel has to be to count as tile
CORNER_RADIUS = 0.195  # of the tile, measured off the artwork
FRINGE_WIDTH = 3  # pixels of blended edge colour grown over before masking


def tile_bounds(image: Image.Image):
    """The bounding box of the tile inside `image`, ignoring its white margin."""
    pixels = image.convert("RGB").load()
    mask = Image.new("L", image.size, 0)
    mask.putdata([
        255 if max(abs(channel - 255) for channel in pixels[x, y]) > TILE_THRESHOLD else 0
        for y in range(image.height) for x in range(image.width)
    ])
    box = mask.getbbox()
    if box is None:
        raise SystemExit(f"{SOURCE_PATH.name}: found no tile in the artwork")
    return box


def crop_tile(image: Image.Image) -> Image.Image:
    """The tile alone, square, with its blended white edge grown over."""
    tile = image.convert("RGB").crop(tile_bounds(image))
    side = min(tile.size)
    if tile.size != (side, side):
        left = (tile.width - side) // 2
        top = (tile.height - side) // 2
        tile = tile.crop((left, top, left + side, top + side))
    # A max filter spreads the interior colours over the last few pixels, which
    # the rounded mask below then cuts back to the true edge. Without it the
    # white the edge blended into survives as a rim -- at 16x16, a whole pixel.
    return tile.filter(ImageFilter.MaxFilter(FRINGE_WIDTH * 2 + 1))


def rounded_mask(size: int, radius: float) -> Image.Image:
    """An antialiased rounded-square alpha mask, drawn oversampled."""
    oversample = 4
    big = Image.new("L", (size * oversample, size * oversample), 0)
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, size * oversample - 1, size * oversample - 1),
        radius * size * oversample, fill=255,
    )
    return big.resize((size, size), Image.LANCZOS)


def bake(target: int, tile: Image.Image) -> Image.Image:
    """One icon size: the tile resampled, then re-masked for that size."""
    baked = tile.resize((target, target), Image.LANCZOS).convert("RGBA")
    baked.putalpha(rounded_mask(target, CORNER_RADIUS))
    return baked


def main() -> int:
    if not SOURCE_PATH.exists():
        print(f"missing {SOURCE_PATH} -- nothing to bake", file=sys.stderr)
        return 1
    source = Image.open(SOURCE_PATH)
    tile = crop_tile(source)
    print(f"{SOURCE_PATH.name} {source.size} -> tile {tile.size}")

    images = {size: bake(size, tile) for size in SIZES}
    # An .ico holds each size as its own image, largest first.
    images[256].save(
        ICON_PATH, format="ICO",
        sizes=[(size, size) for size in SIZES],
        append_images=[images[size] for size in reversed(SIZES[:-1])],
    )
    images[256].save(PREVIEW_PATH, format="PNG")
    print(f"wrote {ICON_PATH} ({', '.join(f'{size}x{size}' for size in SIZES)})")
    print(f"wrote {PREVIEW_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
