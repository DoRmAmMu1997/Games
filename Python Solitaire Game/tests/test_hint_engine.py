"""Hint-engine and loss-detection tests for the Tk-free ``KlondikeGame``.

The hint engine also decides when a deal is lost, so a filter that is too
strict turns into a false "no more moves" verdict. These tests craft exact
boards and check which move is suggested, that real progress is never
declared a loss, and that hint play does not loop forever.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from solitaire import (
    FOUNDATION_COUNT,
    FOUNDATION_SUITS,
    TABLEAU_COLUMNS,
    Card,
    KlondikeGame,
)


def make_game(tmp_dir: str) -> KlondikeGame:
    """Create a game whose score file lives in a throwaway folder."""

    return KlondikeGame(high_score_path=str(Path(tmp_dir) / "scores.json"))


def clear_board(game: KlondikeGame) -> None:
    """Empty every pile so a test can craft an exact board."""

    game.stock = []
    game.waste = []
    game.foundations = [[] for _ in range(FOUNDATION_COUNT)]
    game.tableau = [[] for _ in range(TABLEAU_COLUMNS)]
    game.score = 0


def up(suit: str, rank: int) -> Card:
    """Return a face-up card."""

    return Card(suit, rank, face_up=True)


def down(suit: str, rank: int) -> Card:
    """Return a face-down card."""

    return Card(suit, rank, face_up=False)


def foundation_run(suit: str, top_rank: int) -> list[Card]:
    """Return a foundation pile built from the Ace up to ``top_rank``."""

    return [up(suit, rank) for rank in range(1, top_rank + 1)]


class HintEngineTestCase(unittest.TestCase):
    """Shared setup: a game with an empty board in a temporary save folder."""

    def setUp(self) -> None:
        """Create a game with an empty board whose save file lives in a temp folder."""

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game = make_game(self.tmp.name)
        clear_board(self.game)


class EquivalentDestinationTests(HintEngineTestCase):
    """Two identical destinations must not hide the move from the hint engine."""

    def test_opening_with_two_equal_tens_is_not_a_loss(self) -> None:
        """A 9 with two black 10s to choose from still counts as a move (D2).

        The legal opening deal below has 9♥ alone in column 1, with 10♠ and
        10♣ both exposed and K♦ sitting on three hidden cards. Moving the 9
        empties column 1 for the King, so the deal must not be declared lost.
        """

        tops = [up("hearts", 9), up("spades", 10), up("clubs", 10), up("diamonds", 13),
                up("spades", 13), up("hearts", 13), up("clubs", 13)]
        must_hide = [Card(suit, 1) for suit in FOUNDATION_SUITS]
        must_hide += [Card(suit, 12) for suit in FOUNDATION_SUITS]
        must_hide += [Card("spades", 8), Card("clubs", 8), Card("diamonds", 9)]
        used = {(card.suit, card.rank) for card in tops + must_hide}
        rest = [Card(suit, rank) for suit in FOUNDATION_SUITS for rank in range(1, 14) if (suit, rank) not in used]
        hidden_pool = must_hide + rest[: 21 - len(must_hide)]
        self.game.stock = rest[21 - len(must_hide):]
        for column_index in range(TABLEAU_COLUMNS):
            buried = [hidden_pool.pop() for _ in range(column_index)]
            self.game.tableau[column_index] = [*buried, tops[column_index]]
        self.assertEqual(len(self.game.stock), 24)

        move = self.game.find_best_move()

        self.assertIsNotNone(move)
        assert move is not None
        self.assertEqual(move.cards[0].label(), "9♥")
        self.assertEqual(move.destination_index, 1)


if __name__ == "__main__":
    unittest.main()
