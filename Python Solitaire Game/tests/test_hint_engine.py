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


class FoundationReturnTests(HintEngineTestCase):
    """When taking a card back off a foundation counts as useful (D3b)."""

    def play(self, move) -> None:
        """Play a current (non-stock) hint move on the real board."""

        selection = self.game.selection_from_hint(move)
        assert selection is not None
        if move.destination_type == "foundation":
            self.assertTrue(self.game.move_selection_to_foundation(selection, move.destination_index))
        else:
            self.assertTrue(self.game.move_selection_to_tableau(selection, move.destination_index))

    def test_return_that_empties_a_column_for_a_king(self) -> None:
        """4♠ comes back onto 5♦ so 3♥ can follow and free a column for K♣.

        Foundations hold ♠A-4 and ♥A, column 1 is a lone 3♥ and K♣ sits on
        hidden cards. The only way forward is 4♠ back down, 3♥ onto it, then
        K♣ into the emptied column, revealing a card.
        """

        spades = FOUNDATION_SUITS.index("spades")
        hearts = FOUNDATION_SUITS.index("hearts")
        self.game.foundations[spades] = foundation_run("spades", 4)
        self.game.foundations[hearts] = foundation_run("hearts", 1)
        self.game.tableau[0] = [up("hearts", 3)]
        self.game.tableau[1] = [down("clubs", 9), up("diamonds", 5)]
        self.game.tableau[2] = [down("hearts", 2), down("spades", 7), up("clubs", 13)]
        # Bystander columns whose tops neither move nor accept anything.
        self.game.tableau[3] = [down("spades", 12), up("diamonds", 9)]
        self.game.tableau[4] = [down("clubs", 12), up("hearts", 9)]
        self.game.tableau[5] = [down("spades", 11), up("diamonds", 7)]
        self.game.tableau[6] = [down("clubs", 11), up("hearts", 11)]

        first = self.game.find_best_move()
        assert first is not None, "a reachable column-emptying line was declared a loss"
        self.assertEqual((first.source_type, first.cards[0].label(), first.destination_index),
                         ("foundation", "4\u2660", 1))
        self.play(first)

        second = self.game.find_best_move()
        assert second is not None
        self.assertEqual((second.source_index, second.cards[0].label(), second.destination_index),
                         (0, "3\u2665", 1))
        self.play(second)

        third = self.game.find_best_move()
        assert third is not None
        self.assertEqual((third.source_index, third.cards[0].label(), third.destination_index),
                         (2, "K\u2663", 0))
        hidden_before = sum(not card.face_up for column in self.game.tableau for card in column)
        self.play(third)
        hidden_after = sum(not card.face_up for column in self.game.tableau for card in column)
        self.assertEqual(hidden_after, hidden_before - 1)

    def test_return_that_gives_a_stuck_talon_card_a_home(self) -> None:
        """7♣ may come back down when the waiting 6♥ cannot go anywhere else."""

        clubs = FOUNDATION_SUITS.index("clubs")
        self.game.foundations[clubs] = foundation_run("clubs", 7)
        self.game.tableau[0] = [down("spades", 13), up("diamonds", 8)]
        self.game.stock = [down("hearts", 6)]

        move = self.game.find_best_move()

        assert move is not None
        self.assertEqual((move.source_type, move.cards[0].label(), move.destination_index),
                         ("foundation", "7\u2663", 0))

    def test_talon_card_with_a_foundation_home_does_not_justify_a_return(self) -> None:
        """REV-SOL-1: 6♦ goes up to its foundation; 7♣ stays where it is."""

        clubs = FOUNDATION_SUITS.index("clubs")
        diamonds = FOUNDATION_SUITS.index("diamonds")
        self.game.foundations[clubs] = foundation_run("clubs", 7)
        self.game.foundations[diamonds] = foundation_run("diamonds", 5)
        self.game.tableau[0] = [down("spades", 13), up("hearts", 8)]
        self.game.stock = [down("spades", 2), down("diamonds", 6)]

        move = self.game.find_best_move()

        assert move is not None
        self.assertEqual(move.description, "Hint: Click the stock once, then move 6\u2666 to the Diamonds foundation.")


class FindBestMoveTests(HintEngineTestCase):
    """Ranking and loss detection through ``find_best_move`` (D10)."""

    def test_empty_board_has_no_move(self) -> None:
        """With no cards anywhere there is nothing to suggest."""

        self.assertIsNone(self.game.find_best_move())

    def test_foundation_play_beats_a_plain_tableau_shuffle(self) -> None:
        """A waste card that can go home outranks a non-revealing tableau move."""

        self.game.waste = [up("hearts", 1)]
        self.game.tableau[0] = [up("spades", 13), up("hearts", 12)]
        self.game.tableau[1] = [up("clubs", 13)]

        move = self.game.find_best_move()

        assert move is not None
        self.assertEqual((move.source_type, move.destination_type), ("waste", "foundation"))

    def test_stuck_board_is_a_loss(self) -> None:
        """No legal useful move now or in the stock means the deal is lost."""

        self.game.tableau[0] = [down("spades", 4), up("hearts", 9)]
        self.game.tableau[1] = [down("clubs", 3), up("diamonds", 2)]
        self.game.stock = [down("hearts", 8), down("clubs", 6)]

        self.assertIsNone(self.game.find_best_move())

    def test_moves_remember_the_position_they_leave(self) -> None:
        """A tableau move records its starting position too."""

        self.game.tableau[0] = [down("spades", 4), up("hearts", 9)]
        self.game.tableau[1] = [up("clubs", 10)]
        start = self.game.position_key()
        selection = self.game.selection_from_tableau(0, 1)
        assert selection is not None

        self.assertTrue(self.game.move_selection_to_tableau(selection, 1))

        self.assertIn(start, self.game._seen_positions)


class FutureWasteTests(HintEngineTestCase):
    """The stock look-ahead and its click counting (D10)."""

    def test_counts_clicks_through_the_stock(self) -> None:
        """A playable card three draws deep is three clicks away."""

        self.game.stock = [down("hearts", 1), down("clubs", 5), down("diamonds", 9)]

        move = self.game.find_best_move()

        assert move is not None
        self.assertEqual(move.stock_clicks, 3)
        self.assertEqual(move.description, "Hint: Click the stock 3 times, then move A\u2665 to the Hearts foundation.")

    def test_counts_the_recycle_click(self) -> None:
        """A card buried in the waste needs a recycle click plus a draw."""

        self.game.waste = [up("hearts", 1), up("clubs", 7)]

        move = self.game.find_best_move()

        assert move is not None
        self.assertEqual(move.stock_clicks, 2)
        self.assertEqual(move.cards[0].label(), "A\u2665")

    def test_single_click_wording(self) -> None:
        """One click is described as "once", not "1 times"."""

        self.game.stock = [down("hearts", 1)]

        move = self.game.find_best_move()

        assert move is not None
        self.assertTrue(move.description.startswith("Hint: Click the stock once, then"))

    def test_keeps_the_cheapest_route_to_a_card(self) -> None:
        """The same card reachable on several passes is offered at its fewest clicks."""

        self.game.waste = [up("hearts", 9)]
        self.game.stock = [down("hearts", 1), down("clubs", 5)]

        moves = [move for move in self.game.future_waste_moves() if move.cards[0].rank == 1]

        self.assertEqual([move.stock_clicks for move in moves], [2])

    def test_skips_a_future_move_that_repeats_a_position(self) -> None:
        """The repetition guard also applies to look-ahead moves."""

        self.game.stock = [down("hearts", 1), down("spades", 1)]
        best = self.game.find_best_move()
        assert best is not None
        self.assertEqual(best.cards[0].label(), "A\u2660")
        self.game._seen_positions.add(self.game.position_after(best))

        move = self.game.find_best_move()

        assert move is not None
        self.assertEqual(move.cards[0].label(), "A\u2665")


class AutoSolveSweepTests(HintEngineTestCase):
    """``next_auto_foundation_move`` drives the auto-finish (D10)."""

    def test_waste_card_goes_first(self) -> None:
        """The sweep tries the waste card before the tableau tops."""

        self.game.waste = [up("hearts", 1)]
        self.game.tableau[0] = [up("spades", 1)]

        result = self.game.next_auto_foundation_move()

        assert result is not None
        selection, foundation_index = result
        self.assertEqual(selection.source_type, "waste")
        self.assertEqual(FOUNDATION_SUITS[foundation_index], "hearts")

    def test_tableau_top_goes_when_the_waste_cannot(self) -> None:
        """A tableau top that fits a foundation is found next."""

        self.game.waste = [up("hearts", 5)]
        self.game.tableau[2] = [up("spades", 1)]

        result = self.game.next_auto_foundation_move()

        assert result is not None
        selection, foundation_index = result
        self.assertEqual((selection.source_type, selection.pile_index), ("tableau", 2))
        self.assertEqual(FOUNDATION_SUITS[foundation_index], "spades")

    def test_sweep_plays_a_face_up_board_to_a_win(self) -> None:
        """Repeating the sweep (drawing when stuck) finishes an all-face-up deal."""

        for index, suit in enumerate(FOUNDATION_SUITS):
            self.game.foundations[index] = foundation_run(suit, 10)
        self.game.tableau[0] = [up("spades", 13), up("hearts", 12), up("clubs", 11)]
        self.game.tableau[1] = [up("hearts", 13), up("clubs", 12), up("diamonds", 11)]
        self.game.tableau[2] = [up("diamonds", 13), up("spades", 12)]
        self.game.stock = [down("clubs", 13), down("diamonds", 12), down("hearts", 11), down("spades", 11)]

        for _ in range(200):
            result = self.game.next_auto_foundation_move()
            if result is None:
                self.game.draw_from_stock()
                continue
            selection, foundation_index = result
            self.assertTrue(self.game.move_selection_to_foundation(selection, foundation_index))
            if self.game.has_won():
                break

        self.assertTrue(self.game.has_won())


if __name__ == "__main__":
    unittest.main()
