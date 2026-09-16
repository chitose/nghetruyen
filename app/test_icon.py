"""Tests for the App's icon (`assets/nghetruyen.ico`, baked by make_icon.py).

The icon is only pixels, so what is worth asserting is the files themselves:
that the .ico is committed, that it carries every size Windows asks for, that
the two shapes carrying the meaning -- white headphones and the cyan play
triangle -- are still there, and that it is not stale against the artwork it is
supposed to have been baked from.

The last one is the point of `test_the_icon_is_not_stale`: replacing
`nghetruyen-source.png` and forgetting to re-run make_icon.py is a silent
mistake, since the taskbar just keeps showing the old mark.

The size check reads the .ico's bytes directly and so runs anywhere. The rest
need Pillow, which only the Sidecar's venv has -- run those with
`sidecar\\venv\\Scripts\\python.exe -m unittest test_icon` from this directory.
"""
import struct
import unittest
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # the App's venv deliberately has no Pillow
    Image = None

if Image is not None:
    import make_icon

ICON_PATH = Path(__file__).parent / "assets" / "nghetruyen.ico"
PREVIEW_PATH = Path(__file__).parent / "assets" / "nghetruyen-256.png"
SOURCE_PATH = Path(__file__).parent / "assets" / "nghetruyen-source.png"

# The sizes the icon has to carry: the taskbar and title bar, Alt-Tab, the
# desktop's medium and large icons, and the exe thumbnail.
EXPECTED_SIZES = {16, 24, 32, 48, 64, 128, 256}

needs_pillow = unittest.skipUnless(
    Image is not None, "needs Pillow: run this with the Sidecar's venv",
)


def declared_sizes() -> set:
    """The entries in the .ico directory, read without Pillow.

    Each entry is 16 bytes: width, height (0 meaning 256), colours, reserved,
    planes, bit count, byte size and offset.
    """
    data = ICON_PATH.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0 and kind == 1, "not an icon file"
    sizes = set()
    for index in range(count):
        width, height = struct.unpack("<BB", data[6 + index * 16:8 + index * 16])
        sizes.add((width or 256, height or 256))
    return sizes


class TestIconFile(unittest.TestCase):
    def test_every_size_windows_asks_for_is_embedded(self):
        self.assertEqual({size for size, _ in declared_sizes()}, EXPECTED_SIZES)

    def test_it_is_an_icon_and_not_something_else(self):
        data = ICON_PATH.read_bytes()
        self.assertEqual(data[:6], struct.pack("<HHH", 0, 1, len(EXPECTED_SIZES)))


@needs_pillow
class TestIcon(unittest.TestCase):
    def setUp(self):
        self.icon = Image.open(ICON_PATH)
        self.icon.load()
        self.addCleanup(self.icon.close)

    def test_each_size_is_a_real_drawing(self):
        for size in sorted(EXPECTED_SIZES):
            with self.subTest(size=size):
                frame = self.icon.ico.getimage((size, size)).convert("RGBA")
                colors = frame.getcolors(maxcolors=1 << 16)
                # A blank tile, a solid square or a lost mark all collapse to a
                # handful of colours; the gradient plus two shapes does not.
                self.assertGreater(len(colors), 8)

    def test_the_mark_is_white_headphones_and_a_cyan_triangle(self):
        frame = self.icon.ico.getimage((256, 256)).convert("RGBA")
        colors = [color for _, color in frame.getcolors(maxcolors=1 << 16)]
        self.assertTrue(
            any(r > 240 and g > 240 and b > 240 for r, g, b, _ in colors),
            "no white in the icon: the headphones are missing",
        )
        self.assertTrue(
            any(b > 200 and g > 150 and r < 180 and b > r + 60 for r, g, b, _ in colors),
            "no cyan in the icon: the play triangle is missing",
        )

    def test_the_tile_keeps_transparent_corners(self):
        frame = self.icon.ico.getimage((256, 256)).convert("RGBA")
        corners = [(0, 0), (255, 0), (0, 255), (255, 255)]
        for corner in corners:
            self.assertEqual(frame.getpixel(corner)[3], 0, f"{corner} is not transparent")

    def test_the_tile_is_not_square(self):
        # A rounded tile, not a filled square: the middle of an edge is opaque
        # while the corner is not.
        frame = self.icon.ico.getimage((256, 256)).convert("RGBA")
        self.assertGreater(frame.getpixel((128, 1))[3], 200)
        self.assertEqual(frame.getpixel((1, 1))[3], 0)


@needs_pillow
class TestIconArtwork(unittest.TestCase):
    def test_the_preview_matches_the_icon(self):
        # The PNG is what a reader looks at when deciding whether to trust the
        # .ico; it should be there and be square.
        with Image.open(PREVIEW_PATH) as preview:
            self.assertEqual(preview.size, (256, 256))

    def test_the_source_artwork_is_square_and_has_a_tile(self):
        with Image.open(SOURCE_PATH) as source:
            self.assertEqual(source.width, source.height)
            self.assertGreaterEqual(source.width, 512)
            box = make_icon.tile_bounds(source)
            # The tile fills most of the artwork, with a margin around it --
            # if it filled all of it there would be nothing to crop.
            self.assertLess(box[0], source.width * 0.2)
            self.assertGreater(box[2] - box[0], source.width * 0.6)

    def test_the_icon_is_not_stale(self):
        """The .ico still matches the artwork it was baked from.

        Replacing nghetruyen-source.png without re-running make_icon.py leaves
        the taskbar showing the old mark, and nothing else would notice.
        """
        with Image.open(SOURCE_PATH) as source:
            expected = make_icon.bake(256, make_icon.crop_tile(source))
        with Image.open(ICON_PATH) as icon:
            actual = icon.ico.getimage((256, 256)).convert("RGBA")
        # Baked, saved as ICO and read back, so a couple of levels of
        # difference is rounding rather than a different picture.
        worst = max(
            abs(a - b) for a, b in zip(expected.tobytes(), actual.tobytes())
        )
        self.assertLessEqual(worst, 4, "the .ico does not match the artwork")


if __name__ == "__main__":
    unittest.main()
