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


class RepetitionGuardTests(HintEngineTestCase):
    """Hints avoid moves that lead back to a position already seen (D3a)."""

    def two_aces_board(self) -> None:
        """Put A♥ on the waste and A♠ alone in column 1, plus one hidden card."""

        self.game.waste = [up("hearts", 1)]
        self.game.tableau[0] = [up("spades", 1)]
        self.game.tableau[1] = [down("clubs", 9), up("diamonds", 4)]

    def test_state_changes_remember_the_position_they_leave(self) -> None:
        """Draws and moves record the board they started from."""

        self.game.stock = [down("clubs", 5)]
        self.two_aces_board()
        start = self.game.position_key()
        self.game.draw_from_stock()
        self.assertIn(start, self.game._seen_positions)

        after_draw = self.game.position_key()
        selection = self.game.selection_from_tableau(0, 0)
        assert selection is not None
        self.assertTrue(self.game.move_selection_to_foundation(selection, FOUNDATION_SUITS.index("spades")))
        self.assertIn(after_draw, self.game._seen_positions)

    def test_position_after_matches_the_played_move(self) -> None:
        """Simulating a hint gives exactly the key the real move produces."""

        self.game.stock = [down("hearts", 1), down("clubs", 7), down("spades", 12)]
        self.game.tableau[0] = [down("clubs", 9), up("diamonds", 13)]
        self.game.tableau[1] = [down("spades", 3), up("hearts", 6), up("clubs", 5)]
        self.game.tableau[2] = [up("diamonds", 7)]
        for move in self.game.current_legal_moves() + self.game.future_waste_moves():
            with self.subTest(hint=move.description):
                saved = self.game.snapshot()
                predicted = self.game.position_after(move)
                for _ in range(move.stock_clicks):
                    self.game.draw_from_stock()
                selection = (
                    self.game.selection_from_waste()
                    if move.source_type == "future_waste"
                    else self.game.selection_from_hint(move)
                )
                assert selection is not None
                if move.destination_type == "foundation":
                    self.game.move_selection_to_foundation(selection, move.destination_index)
                else:
                    self.game.move_selection_to_tableau(selection, move.destination_index)
                self.assertEqual(self.game.position_key(), predicted)
                self.game.restore_snapshot(saved)

    def test_hint_skips_a_move_back_to_a_seen_position(self) -> None:
        """When the best move repeats a position, the next-best one is shown."""

        self.two_aces_board()
        best = self.game.find_best_move()
        assert best is not None
        self.assertEqual(best.source_type, "waste")
        self.game._seen_positions.add(self.game.position_after(best))

        move = self.game.find_best_move()

        assert move is not None
        self.assertEqual(move.source_type, "tableau")
        self.assertEqual(move.cards[0].label(), "A\u2660")

    def test_hint_falls_back_to_a_repeat_rather_than_a_loss(self) -> None:
        """If every candidate repeats a position, the best one is still offered."""

        self.two_aces_board()
        for candidate in self.game.current_legal_moves():
            self.game._seen_positions.add(self.game.position_after(candidate))

        move = self.game.find_best_move()

        assert move is not None
        self.assertEqual(move.source_type, "waste")

    def test_undo_forgets_undone_positions(self) -> None:
        """Restoring a snapshot also restores the set of seen positions."""

        self.game.stock = [down("clubs", 5), down("hearts", 8)]
        saved = self.game.snapshot()
        seen_before = set(self.game._seen_positions)
        self.game.draw_from_stock()
        self.game.draw_from_stock()
        self.assertNotEqual(self.game._seen_positions, seen_before)

        self.game.restore_snapshot(saved)

        self.assertEqual(self.game._seen_positions, seen_before)

    def test_new_game_starts_with_no_seen_positions(self) -> None:
        """A fresh deal forgets every position from the previous game."""

        self.game.stock = [down("clubs", 5)]
        self.game.draw_from_stock()
        self.assertTrue(self.game._seen_positions)

        self.game.new_game()

        self.assertEqual(self.game._seen_positions, set())


if __name__ == "__main__":
    unittest.main()
