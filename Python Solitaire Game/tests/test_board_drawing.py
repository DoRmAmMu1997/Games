"""Drawing and layout tests for ``SolitaireApp`` that never open a window.

The app is built with ``object.__new__`` and given a mock canvas, so every
drawing call is just recorded. The tests then check the arguments of those
``create_*`` calls (positions, colours, fonts) rather than rendered pixels,
which keeps them independent of the fonts installed on a machine.
"""

from __future__ import annotations

import itertools
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
    CARD_HEIGHT,
    CARD_WIDTH,
    EMPTY_OUTLINE,
    FOUNDATION_COUNT,
    HINT_COLOR,
    PLACEHOLDER_FILL,
    TABLEAU_COLUMNS,
    TABLEAU_Y,
    TOP_ROW_Y,
    WINDOW_WIDTH,
    Card,
    HintMove,
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


# Half the height of a 10pt label, rounded up generously: real fonts differ
# between machines, so every clearance below keeps a few pixels to spare.
LABEL_HALF_HEIGHT = 8
CLEARANCE = 2
# Card shadows are drawn this far below each card.
SHADOW_DROP = 5


def calls_named(canvas: mock.Mock, name: str) -> list:
    """Return every recorded canvas call of one kind, such as ``create_text``."""

    return [call for call in canvas.method_calls if call[0] == name]


class TopBandTests(DrawingTestCase):
    """P3: the top band leaves room for pile names and card counts."""

    def test_felt_ovals_are_painted_before_the_top_band(self) -> None:
        """The decorative ovals sit underneath the band, never over it."""

        self.app.draw_table_surface()

        names = [call[0] for call in self.canvas.method_calls]
        last_oval = max(index for index, name in enumerate(names) if name == "create_oval")
        rectangles = [index for index, name in enumerate(names) if name == "create_rectangle"]
        self.assertGreater(len(rectangles), 1)
        self.assertTrue(all(index > last_oval for index in rectangles[1:]))

    def band_and_divider(self) -> tuple[float, float]:
        """Return the bottom of the top band and the bottom of the divider."""

        self.app.draw_table_surface()
        rectangles = [call[1] for call in calls_named(self.canvas, "create_rectangle")]
        band, divider = rectangles[1], rectangles[2]
        return band[3], divider[3]

    def test_pile_names_clear_the_canvas_edge_and_cards(self) -> None:
        """Every pile name fits between the canvas top and the top row of cards."""

        self.app.draw_top_labels()

        for call in calls_named(self.canvas, "create_text"):
            with self.subTest(label=call[2]["text"]):
                y = call[1][1]
                self.assertGreaterEqual(y - LABEL_HALF_HEIGHT, CLEARANCE)
                self.assertLessEqual(y + LABEL_HALF_HEIGHT, TOP_ROW_Y - CLEARANCE)

    def test_card_counts_clear_the_cards_and_the_divider(self) -> None:
        """The "N cards" counts sit below the card shadows and above the divider."""

        divider_top = self.band_and_divider()[0]
        self.canvas.reset_mock()
        self.game.waste = [self.game.stock.pop()]
        self.app.draw_stock()
        self.app.draw_waste()

        counts = [call for call in calls_named(self.canvas, "create_text") if "cards" in call[2]["text"]]
        self.assertEqual(len(counts), 2)
        for call in counts:
            y = call[1][1]
            self.assertGreaterEqual(y - LABEL_HALF_HEIGHT, TOP_ROW_Y + CARD_HEIGHT + SHADOW_DROP)
            self.assertLessEqual(y + LABEL_HALF_HEIGHT, divider_top - CLEARANCE)

    def test_divider_clears_the_tableau(self) -> None:
        """The band's divider line ends well above the first tableau card."""

        divider_bottom = self.band_and_divider()[1]

        self.assertLessEqual(divider_bottom, TABLEAU_Y - 4)


class CardBackTests(DrawingTestCase):
    """P4: card-back stripes stay inside the inner frame and are evenly spaced."""

    def stripes(self) -> list[tuple[float, float, float, float]]:
        """Draw the pattern at (100, 200) and return each stripe's end points."""

        self.app.draw_card_back_pattern(100, 200)
        return [tuple(call[1][:4]) for call in calls_named(self.canvas, "create_line")]

    def test_stripes_stay_inside_the_inner_frame(self) -> None:
        """No stripe reaches the 5 px inner frame or the rounded card corners."""

        lines = self.stripes()
        self.assertGreater(len(lines), 5)
        for x1, y1, x2, y2 in lines:
            for x, y in ((x1, y1), (x2, y2)):
                self.assertGreater(x, 100 + 5)
                self.assertLess(x, 100 + CARD_WIDTH - 5)
                self.assertGreater(y, 200 + 5)
                self.assertLess(y, 200 + CARD_HEIGHT - 5)

    def test_stripes_are_evenly_spaced(self) -> None:
        """Neighbouring 45-degree stripes are all the same distance apart."""

        offsets = sorted(round(x1 - y1, 6) for x1, y1, _, _ in self.stripes())
        gaps = {round(b - a, 6) for a, b in itertools.pairwise(offsets)}
        self.assertEqual(len(gaps), 1)


class CardFaceTests(DrawingTestCase):
    """P5/P6: the corner index of a face-up card."""

    def corner_texts(self, anchor: str) -> list:
        """Draw Q♥ face up at (100, 200) and return its corner texts with ``anchor``."""

        self.app.draw_card(100, 200, Card("hearts", 12, face_up=True), face_up=True, selected=False)
        return [call for call in calls_named(self.canvas, "create_text") if call[2].get("anchor") == anchor]

    def test_top_corner_index_sits_four_pixels_down(self) -> None:
        """The rank starts 4 px below the card top, clear of the next card's outline."""

        label = next(call for call in self.corner_texts("nw") if call[2]["text"] == "Q\u2665")
        self.assertEqual(label[1][1], 200 + 4)

    def test_bottom_corner_index_mirrors_the_top(self) -> None:
        """The bottom-right index sits 4 px above the card bottom."""

        label = next(call for call in self.corner_texts("se") if call[2]["text"] == "Q\u2665")
        self.assertEqual(label[1][1], 200 + CARD_HEIGHT - 4)

    def test_each_corner_prints_the_suit_once(self) -> None:
        """A corner shows "Q♥" and no second, separate suit pip (P6)."""

        for anchor in ("nw", "se"):
            with self.subTest(corner=anchor):
                self.canvas.reset_mock()
                texts = [call[2]["text"] for call in self.corner_texts(anchor)]
                self.assertEqual(texts, ["Q\u2665"])


def relative_luminance(colour: str) -> float:
    """Return the WCAG relative luminance of a "#RRGGBB" colour."""

    channels = [int(colour[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: str, second: str) -> float:
    """Return the WCAG contrast ratio between two colours."""

    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class EmptyPileTests(DrawingTestCase):
    """P7: empty-pile placeholders are readable and hint like cards do."""

    def setUp(self) -> None:
        """Start from an empty board so every pile draws its placeholder."""

        super().setUp()
        self.game.stock = []
        self.game.waste = []
        self.game.foundations = [[] for _ in range(FOUNDATION_COUNT)]
        self.game.tableau = [[] for _ in range(TABLEAU_COLUMNS)]

    def test_foundation_suit_symbols_use_the_light_placeholder_colour(self) -> None:
        """Empty foundations print their suit in the light, high-contrast colour."""

        self.app.draw_foundations()

        fills = {call[2]["fill"] for call in calls_named(self.canvas, "create_text")}
        self.assertEqual(fills, {EMPTY_OUTLINE})
        self.assertGreaterEqual(contrast_ratio(EMPTY_OUTLINE, PLACEHOLDER_FILL), 4.5)

    def test_reset_and_waste_words_are_fourteen_point(self) -> None:
        """The words on the empty stock and waste use a 14pt font so they fit."""

        self.app.draw_stock()
        self.app.draw_waste()

        sizes = {call[2]["text"]: call[2]["font"][1] for call in calls_named(self.canvas, "create_text")}
        self.assertEqual(sizes, {"Reset": 14, "Waste": 14})

    def hinted_outline(self, destination_type: str, destination_index: int) -> dict:
        """Hint an empty pile, draw it, and return the options of its outline polygon."""

        self.app.hint_move = HintMove("waste", 0, 0, [Card("spades", 13, True)], destination_type,
                                      destination_index, 0, "Hint")
        if destination_type == "foundation":
            self.app.draw_foundations()
        else:
            self.app.draw_tableau()
        outlines = [call[2] for call in calls_named(self.canvas, "create_polygon")
                    if call[2].get("outline") == HINT_COLOR]
        self.assertEqual(len(outlines), 1)
        return outlines[0]

    def test_hinted_empty_piles_get_the_solid_hint_outline(self) -> None:
        """A hinted empty foundation or column has the same solid 4 px outline as a card."""

        for destination in (("foundation", 1), ("tableau", 2)):
            with self.subTest(destination=destination):
                self.canvas.reset_mock()
                options = self.hinted_outline(*destination)
                self.assertEqual(options["width"], 4)
                self.assertFalse(options.get("dash"))


if __name__ == "__main__":
    unittest.main()
