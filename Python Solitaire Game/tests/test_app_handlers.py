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
        # Keep a typed handle on the mock root so tests can inspect `after`.
        self.root = mock.Mock()
        self.app.root = self.root

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


class GameOverTests(AppHandlerTestCase):
    """Undo and the win celebration once a game has ended (D7)."""

    def finish_with_one_move_left(self) -> None:
        """Craft a board one foundation move from winning and play it via the app."""

        self.clear_board()
        suits = ["hearts", "diamonds", "clubs", "spades"]
        for index, suit in enumerate(suits):
            self.game.foundations[index] = [Card(suit, rank, face_up=True) for rank in range(1, 14)]
        king = self.game.foundations[3].pop()
        self.game.tableau[0] = [king]
        self.app.on_canvas_double_click(self.tableau_click(0, 0))
        assert self.app.animation is not None
        self.app.animation.frame = self.app.animation.steps
        self.app.advance_animation()

    def test_undo_is_refused_after_a_win(self) -> None:
        """A won game stays won: Undo explains itself and changes nothing."""

        self.finish_with_one_move_left()
        self.assertTrue(self.game.won)
        wins = self.game.wins
        history_length = len(self.app.history)

        self.app.undo_last_action()

        self.assertTrue(self.game.won)
        self.assertEqual(self.game.wins, wins)
        self.assertEqual(len(self.app.history), history_length)
        self.assertEqual(self.app.status_var.get(), "You already won. Click New Game to play again.")

    def test_undo_is_allowed_after_a_loss(self) -> None:
        """Undo after a loss takes the loss back and reopens the game."""

        self.clear_board()
        self.game.tableau[0] = [Card("spades", 4, face_up=False), Card("hearts", 9, face_up=True)]
        self.game.tableau[1] = [Card("clubs", 10, face_up=True)]
        self.game.tableau[2] = [Card("hearts", 13, face_up=False), Card("diamonds", 2, face_up=True)]
        self.app.on_canvas_click(self.tableau_click(0, 1))
        self.app.on_canvas_click(self.tableau_click(1, 0))
        assert self.app.animation is not None
        self.app.animation.frame = self.app.animation.steps
        self.app.advance_animation()
        self.assertTrue(self.game.lost)
        self.assertEqual(self.game.losses, 1)

        self.app.undo_last_action()

        self.assertFalse(self.game.lost)
        self.assertEqual(self.game.losses, 0)
        self.assertEqual(self.game.tableau[0][-1].label(), "9\u2665")

    def test_new_game_during_confetti_stops_the_celebration(self) -> None:
        """Starting a new game mid-celebration cancels the stale win dialog."""

        on_finished = mock.Mock()
        self.game.won = True
        self.app._play_win_celebration(on_finished)
        step = self.root.after.call_args[0][1]
        self.root.after.reset_mock()

        self.game.won = False
        step()

        on_finished.assert_not_called()
        self.root.after.assert_not_called()

    def test_celebration_finishes_with_the_dialog(self) -> None:
        """Left alone, the celebration runs its frames and then shows the dialog."""

        on_finished = mock.Mock()
        self.game.won = True
        self.app._play_win_celebration(on_finished)
        for _ in range(500):
            if not self.root.after.called:
                break
            step = self.root.after.call_args[0][1]
            self.root.after.reset_mock()
            step()

        on_finished.assert_called_once()


if __name__ == "__main__":
    unittest.main()
