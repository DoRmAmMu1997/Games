"""Drawing and layout tests for ``SolitaireApp`` that never open a window.

The app is built with ``object.__new__`` and given a mock canvas, so every
drawing call is just recorded. The tests then check the arguments of those
``create_*`` calls (positions, colours, fonts) rather than rendered pixels,
which keeps them independent of the fonts installed on a machine.
"""

from __future__ import annotations

import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from solitaire import (
    CARD_WIDTH,
    FOUNDATION_COUNT,
    TABLEAU_COLUMNS,
    WINDOW_WIDTH,
    KlondikeGame,
    SolitaireApp,
)


class FakeVar:
    """A stand-in for ``tk.StringVar`` that just remembers its value."""

    def __init__(self, value: str = "") -> None:
        """Store the starting value."""

        self.value = value

    def set(self, value: str) -> None:
        """Remember a new value."""

        self.value = value

    def get(self) -> str:
        """Return the current value."""

        return self.value


def make_app(tmp_dir: str) -> SolitaireApp:
    """Build a headless SolitaireApp with a mock canvas and a seeded game."""

    app = object.__new__(SolitaireApp)
    app.root = mock.Mock()
    app.canvas = mock.Mock()
    app.game = KlondikeGame(str(Path(tmp_dir) / "scores.json"), rng=random.Random(3))
    app.selection = None
    app.hint_move = None
    app.animation = None
    app.auto_solving = False
    app.auto_solve_seen_states = set()
    app.history = []
    app.score_var = FakeVar()  # type: ignore[assignment]
    app.high_score_var = FakeVar()  # type: ignore[assignment]
    app.time_var = FakeVar()  # type: ignore[assignment]
    app.stats_var = FakeVar()  # type: ignore[assignment]
    app.status_var = FakeVar()  # type: ignore[assignment]
    app.started_at = 0.0
    app.elapsed_seconds = 0
    return app


class DrawingTestCase(unittest.TestCase):
    """Shared setup: a headless app whose canvas records every call."""

    def setUp(self) -> None:
        """Create the app in a temp save folder with a fresh mock canvas."""

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = make_app(self.tmp.name)
        self.canvas = mock.Mock()
        self.app.canvas = self.canvas
        self.game = self.app.game


class HeaderTests(DrawingTestCase):
    """P1: the header row keeps every button visible."""

    def test_buttons_pack_first_and_labels_match_their_font(self) -> None:
        """The button group claims its space before the labels, in the same font."""

        packs: list[tuple[str, object]] = []
        created: list[tuple[str, object, dict]] = []

        def factory(kind: str):
            """Return a fake widget constructor that logs creation and packing."""

            def build(parent: object, *args: object, **kwargs: object) -> mock.Mock:
                """Create one fake widget and record when it is packed."""

                widget = mock.Mock(name=kind)
                created.append((kind, parent, kwargs))
                widget.pack.side_effect = lambda *a, **k: packs.append((kind, widget))
                return widget

            return build

        with mock.patch("solitaire.tk.Frame", side_effect=factory("Frame")), \
                mock.patch("solitaire.tk.Label", side_effect=factory("Label")), \
                mock.patch("solitaire.tk.Button", side_effect=factory("Button")), \
                mock.patch("solitaire.tk.Canvas", side_effect=factory("Canvas")):
            self.app.build_ui()

        frames = [entry for entry in created if entry[0] == "Frame"]
        top_frame_widget = next(widget for kind, widget in packs if kind == "Frame")
        button_frame_parent = frames[1][1]
        self.assertIs(button_frame_parent, top_frame_widget)
        order = [kind for kind, _ in packs]
        self.assertLess(order.index("Frame", 1), order.index("Label"))

        button_fonts = {kwargs["font"] for kind, _, kwargs in created if kind == "Button"}
        header_label_fonts = {
            kwargs["font"] for kind, parent, kwargs in created if kind == "Label" and parent is top_frame_widget
        }
        self.assertEqual(len(button_fonts), 1)
        self.assertEqual(header_label_fonts, button_fonts)


class TableLayoutTests(DrawingTestCase):
    """P2: the board is centred and the foundations line up with the columns."""

    def test_board_is_centred_in_the_window(self) -> None:
        """The gap left of column 1 equals the gap right of column 7."""

        left = self.app.tableau_x(0)
        right = WINDOW_WIDTH - (self.app.tableau_x(TABLEAU_COLUMNS - 1) + CARD_WIDTH)
        self.assertEqual(left, right)
        self.assertEqual(self.app.stock_rect()[0], left)

    def test_foundations_sit_above_the_last_four_columns(self) -> None:
        """Foundation N starts exactly where tableau column 4 + N starts."""

        first_column = TABLEAU_COLUMNS - FOUNDATION_COUNT
        for index in range(FOUNDATION_COUNT):
            with self.subTest(foundation=index):
                self.assertEqual(self.app.foundation_rect(index)[0], self.app.tableau_x(first_column + index))
        self.assertEqual(self.app.waste_rect()[0], self.app.tableau_x(1))


if __name__ == "__main__":
    unittest.main()
