"""Input-handler tests for ``SolitaireApp`` that never open a window.

The app is built with ``object.__new__`` so ``__init__`` (which creates real
tkinter widgets) never runs. The root window, canvas and message boxes are
mocks, and the label variables are tiny stand-ins, so the handlers run
headless against a real ``KlondikeGame``.
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
    CARD_HEIGHT,
    CARD_WIDTH,
    FOUNDATION_COUNT,
    TABLEAU_COLUMNS,
    AnimationState,
    Card,
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


def make_app(tmp_dir: str, seed: int = 7) -> SolitaireApp:
    """Build a headless SolitaireApp around a seeded game and mock widgets."""

    app = object.__new__(SolitaireApp)
    app.root = mock.Mock()
    app.canvas = mock.Mock()
    app.game = KlondikeGame(str(Path(tmp_dir) / "scores.json"), rng=random.Random(seed))
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


def click_at(x: float, y: float) -> mock.Mock:
    """Return a fake mouse event at the given canvas point."""

    event = mock.Mock()
    event.x = int(x)
    event.y = int(y)
    return event


class AppHandlerTestCase(unittest.TestCase):
    """Shared setup: a headless app with message boxes patched out."""

    def setUp(self) -> None:
        """Create the app in a temp save folder and patch ``solitaire.messagebox``."""

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch("solitaire.messagebox")
        self.messagebox = patcher.start()
        self.addCleanup(patcher.stop)
        self.app = make_app(self.tmp.name)
        self.game = self.app.game

    def clear_board(self) -> None:
        """Empty every pile so a test can craft an exact board."""

        self.game.stock = []
        self.game.waste = []
        self.game.foundations = [[] for _ in range(FOUNDATION_COUNT)]
        self.game.tableau = [[] for _ in range(TABLEAU_COLUMNS)]

    def stock_click(self) -> mock.Mock:
        """Return an event in the middle of the stock pile."""

        x1, y1, _, _ = self.app.stock_rect()
        return click_at(x1 + CARD_WIDTH / 2, y1 + CARD_HEIGHT / 2)

    def tableau_click(self, column_index: int, card_index: int) -> mock.Mock:
        """Return an event on the visible strip of one tableau card."""

        y = self.app.tableau_positions(column_index)[card_index]
        return click_at(self.app.tableau_x(column_index) + CARD_WIDTH / 2, y + 5)


class DoubleClickTests(AppHandlerTestCase):
    """Double-clicks that do not send a card home act like a normal click (D5)."""

    def test_stock_double_click_draws(self) -> None:
        """The second click of a fast double-click on the stock still draws."""

        waste_before = len(self.game.waste)

        self.app.on_canvas_double_click(self.stock_click())

        self.assertEqual(len(self.game.waste), waste_before + 1)

    def test_won_board_double_click_explains_itself(self) -> None:
        """A double-click on a won board says why nothing happens."""

        self.game.won = True

        self.app.on_canvas_double_click(self.stock_click())

        self.assertEqual(self.app.status_var.get(), "You already won. Click New Game to play again.")

    def test_busy_board_double_click_explains_itself(self) -> None:
        """A double-click during a card animation asks the player to wait."""

        self.app.animation = AnimationState([], [], [], "tableau", 0, "done")

        self.app.on_canvas_double_click(self.stock_click())

        self.assertEqual(self.app.status_var.get(), "Please wait for the card animation to finish.")

    def test_quick_second_click_on_selected_card_deselects_it(self) -> None:
        """Clicking a selected card twice quickly clears the selection."""

        self.clear_board()
        self.game.tableau[0] = [Card("spades", 9, face_up=True)]
        self.game.tableau[1] = [Card("clubs", 13, face_up=True)]
        self.game.stock = [Card("hearts", 13, face_up=False)]
        self.app.on_canvas_click(self.tableau_click(0, 0))
        self.assertIsNotNone(self.app.selection)

        self.app.on_canvas_double_click(self.tableau_click(0, 0))

        self.assertIsNone(self.app.selection)
        self.assertEqual(self.app.status_var.get(), "Selection cleared.")

    def test_double_click_still_sends_a_card_home(self) -> None:
        """A double-click on a card that fits a foundation starts that move."""

        self.clear_board()
        self.game.tableau[0] = [Card("hearts", 1, face_up=True)]
        self.game.stock = [Card("hearts", 13, face_up=False)]

        self.app.on_canvas_double_click(self.tableau_click(0, 0))

        self.assertEqual(len(self.game.foundations[0]), 1)
        self.assertIsNotNone(self.app.animation)


if __name__ == "__main__":
    unittest.main()
