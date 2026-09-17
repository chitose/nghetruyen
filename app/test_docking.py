import unittest

from docking import dock, page_bounds


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self, *args):
        for handler in self.handlers:
            handler(*args)


class FakeEvents:
    def __init__(self):
        for name in ("shown", "moved", "resized", "maximized"):
            setattr(self, name, FakeEvent())


class FakeWindow:
    def __init__(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height
        self.events = FakeEvents()
        self.moves = []
        self.sizes = []

    def move(self, x, y):
        self.moves.append((x, y))

    def resize(self, width, height):
        self.sizes.append((width, height))


class TestPageBounds(unittest.TestCase):
    def test_sits_directly_above_the_strip_at_the_same_width(self):
        self.assertEqual(
            page_bounds((10, 620, 800, 140), (0, 0, 1920, 1080), 600),
            (10, 20, 800, 600),
        )

    def test_pins_to_the_screen_top_on_a_maximized_strip(self):
        self.assertEqual(
            page_bounds((0, 0, 1920, 1080), (0, 0, 1920, 1080), 600),
            (0, 0, 1920, 600),
        )

    def test_uses_the_screen_it_is_given(self):
        self.assertEqual(
            page_bounds((1920, 620, 800, 140), (1920, 0, 1920, 1080), 600),
            (1920, 20, 800, 600),
        )


class TestDock(unittest.TestCase):
    def setUp(self):
        self.strip = FakeWindow(10, 620, 800, 150)
        self.page = FakeWindow(10, 20, 800, 600)
        self.screen = (0, 0, 1920, 1080)
        self.dock_state = dock(self.strip, self.page, lambda x, y: self.screen)

    def test_reposition_places_and_sizes_the_reader(self):
        self.dock_state.reposition()
        self.assertEqual(self.page.moves[-1], (10, 20))
        self.assertEqual(self.page.sizes[-1], (800, 600))

    def test_follows_the_strip_when_it_moves(self):
        self.strip.x, self.strip.y = 300, 700
        self.strip.events.moved.fire(300, 700)
        self.assertEqual(self.page.moves[-1], (300, 100))

    def test_follows_the_strip_when_it_resizes(self):
        self.strip.width, self.strip.height = 1000, 200
        self.strip.events.resized.fire(1000, 200)
        self.assertEqual(self.page.moves[-1], (10, 20))
        self.assertEqual(self.page.sizes[-1], (1000, 600))

    def test_pins_the_reader_when_the_strip_is_maximized(self):
        self.strip.x, self.strip.y = 0, 0
        self.strip.width, self.strip.height = 1920, 1080
        self.strip.events.maximized.fire()
        self.assertEqual(self.page.moves[-1], (0, 0))

    def test_reshown_reader_resyncs(self):
        self.page.events.shown.fire()
        self.assertEqual(self.page.sizes[-1], (800, 600))

    def test_a_manual_reader_resize_snaps_its_width_back_to_the_strips(self):
        self.page.width, self.page.height = 900, 500
        self.page.events.resized.fire(900, 500)
        self.assertEqual(self.page.sizes[-1], (800, 500))  # width corrected, height kept

    def test_without_screen_info_it_still_docks_above(self):
        strip = FakeWindow(50, 460, 700, 60)
        page = FakeWindow(0, 0, 700, 400)
        dock_state = dock(strip, page, lambda x, y: None)
        dock_state.reposition()
        self.assertEqual(page.moves[-1], (50, 60))


class TestDockWhilePageHidden(unittest.TestCase):
    """pywebview's Windows backend moves/resizes a window with
    SWP_SHOWWINDOW, which un-hides it as a side effect -- page_visible is
    what stops a strip move from bringing a Hide-page'd reader back."""

    def setUp(self):
        self.strip = FakeWindow(10, 620, 800, 150)
        self.page = FakeWindow(10, 20, 800, 600)
        self.visible = {"value": False}
        self.dock_state = dock(
            self.strip, self.page, lambda x, y: (0, 0, 1920, 1080),
            page_visible=lambda: self.visible["value"],
        )

    def test_a_strip_move_does_not_touch_the_hidden_reader(self):
        self.strip.x, self.strip.y = 300, 700
        self.strip.events.moved.fire(300, 700)
        self.assertEqual(self.page.moves, [])
        self.assertEqual(self.page.sizes, [])

    def test_reposition_is_a_noop_while_hidden(self):
        self.dock_state.reposition()
        self.assertEqual(self.page.moves, [])

    def test_it_resumes_once_visible_again(self):
        self.strip.events.moved.fire()
        self.visible["value"] = True
        self.dock_state.reposition()
        self.assertEqual(self.page.moves[-1], (10, 20))


if __name__ == "__main__":
    unittest.main()
