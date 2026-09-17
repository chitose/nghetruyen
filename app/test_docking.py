import unittest

from docking import (
    MAX_CONTROLS_HEIGHT,
    MIN_CONTROLS_HEIGHT,
    controls_bounds,
    dock,
)


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


class TestControlsBounds(unittest.TestCase):
    def test_sits_directly_below_the_reader_at_the_same_width(self):
        self.assertEqual(
            controls_bounds((10, 20, 800, 600), (0, 0, 1920, 1080), 140),
            (10, 620, 800, 140),
        )

    def test_pins_to_the_screen_bottom_on_a_maximized_reader(self):
        self.assertEqual(
            controls_bounds((0, 0, 1920, 1080), (0, 0, 1920, 1080), 140),
            (0, 1080 - 140, 1920, 140),
        )

    def test_uses_the_screen_it_is_given(self):
        self.assertEqual(
            controls_bounds((1920, 20, 800, 600), (1920, 0, 1920, 1080), 140),
            (1920, 620, 800, 140),
        )


class TestDock(unittest.TestCase):
    def setUp(self):
        self.content = FakeWindow(10, 20, 800, 600)
        self.controls = FakeWindow(10, 620, 800, 150)
        self.screen = (0, 0, 1920, 1080)
        self.dock_state = dock(self.content, self.controls, lambda x, y: self.screen, height=140)

    def test_reposition_places_and_sizes_the_controls_window(self):
        self.dock_state.reposition()
        self.assertEqual(self.controls.moves[-1], (10, 620))
        self.assertEqual(self.controls.sizes[-1], (800, 140))

    def test_follows_the_reader_when_it_moves(self):
        self.content.x, self.content.y = 300, 100
        self.content.events.moved.fire(300, 100)
        self.assertEqual(self.controls.moves[-1], (300, 700))

    def test_follows_the_reader_when_it_resizes(self):
        self.content.width, self.content.height = 1000, 500
        self.content.events.resized.fire(1000, 500)
        self.assertEqual(self.controls.moves[-1], (10, 520))
        self.assertEqual(self.controls.sizes[-1], (1000, 140))

    def test_pins_the_controls_window_when_the_reader_is_maximized(self):
        self.content.x, self.content.y = 0, 0
        self.content.width, self.content.height = 1920, 1080
        self.content.events.maximized.fire()
        self.assertEqual(self.controls.moves[-1], (0, 1080 - 140))

    def test_reshown_controls_window_resyncs(self):
        self.controls.events.shown.fire()
        self.assertEqual(self.controls.sizes[-1], (800, 140))

    def test_without_screen_info_it_still_docks_below(self):
        dock_state = dock(self.content, self.controls, lambda x, y: None, height=140)
        self.content.x, self.content.y = 50, 60
        self.content.width, self.content.height = 700, 400
        dock_state.reposition()
        self.assertEqual(self.controls.moves[-1], (50, 460))

    # --- the reader's drag grip ---------------------------------------------

    def test_set_height_resizes_and_remembers(self):
        self.dock_state.set_height(260)
        self.assertEqual(self.dock_state.height, 260)
        self.assertEqual(self.controls.sizes[-1], (800, 260))

    def test_set_height_keeps_the_strip_docked(self):
        self.dock_state.set_height(260)
        self.assertEqual(self.controls.moves[-1], (10, 620))

    def test_set_height_clamps_to_the_limits(self):
        self.dock_state.set_height(10)
        self.assertEqual(self.dock_state.height, MIN_CONTROLS_HEIGHT)
        self.dock_state.set_height(100000)
        self.assertEqual(self.dock_state.height, MAX_CONTROLS_HEIGHT)

    def test_set_height_ignores_garbage(self):
        self.dock_state.set_height("not a number")
        self.assertEqual(self.dock_state.height, 140)

    # --- the title bar ------------------------------------------------------

    def test_move_by_offsets_from_the_drag_origin(self):
        self.dock_state.begin_move()
        self.dock_state.move_by(40, -25)
        self.assertEqual(self.controls.moves[-1], (50, 595))  # (10, 620) + delta

    def test_begin_move_uses_the_windows_current_position(self):
        self.controls.x, self.controls.y = 300, 400
        self.dock_state.begin_move()
        self.dock_state.move_by(10, 10)
        self.assertEqual(self.controls.moves[-1], (310, 410))

    def test_move_by_without_begin_move_is_a_noop(self):
        self.dock_state.move_by(40, -25)
        self.assertEqual(self.controls.moves, [])

    def test_move_by_ignores_garbage(self):
        self.dock_state.begin_move()
        self.dock_state.move_by("x", "y")
        self.assertEqual(self.controls.moves, [])

    def test_end_move_stops_further_movement(self):
        self.dock_state.begin_move()
        self.dock_state.end_move()
        self.dock_state.move_by(40, -25)
        self.assertEqual(self.controls.moves, [])

    def test_resizing_after_a_manual_move_keeps_the_strip_where_it_is(self):
        self.dock_state.begin_move()
        self.dock_state.move_by(0, -200)  # dragged up
        self.controls.moves.clear()
        self.dock_state.set_height(240)
        self.assertEqual(self.controls.sizes[-1], (self.controls.width, 240))
        self.assertEqual(self.controls.moves, [])  # not re-docked to the bottom

    def test_a_reader_move_re_attaches_a_floating_strip(self):
        self.dock_state.begin_move()
        self.dock_state.move_by(0, -200)
        self.content.x, self.content.y = 50, 60
        self.content.events.moved.fire()
        self.assertEqual(self.controls.moves[-1], (50, 660))

    def test_a_floating_strip_still_remembers_the_new_height(self):
        self.dock_state.begin_move()
        self.dock_state.move_by(0, -200)
        self.dock_state.set_height(300)
        self.content.x, self.content.y = 50, 60
        self.content.events.moved.fire()
        self.assertEqual(self.controls.sizes[-1], (800, 300))

    def test_a_later_reposition_keeps_the_dragged_height(self):
        self.dock_state.set_height(260)
        self.content.x, self.content.y = 300, 100
        self.content.events.moved.fire(300, 100)
        self.assertEqual(self.controls.sizes[-1], (800, 260))
        self.assertEqual(self.controls.moves[-1], (300, 700))


if __name__ == "__main__":
    unittest.main()
