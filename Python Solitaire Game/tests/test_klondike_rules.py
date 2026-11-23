"""Rules tests for the Tk-free ``KlondikeGame`` model in ``solitaire.py``.

``KlondikeGame`` never touches tkinter, so these tests run headless: they
deal boards, craft specific pile layouts, and check the classic Klondike
rules, scoring, undo snapshots, and the hint engine's judgement.
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


class DealTests(unittest.TestCase):
    """The standard Klondike opening layout."""

    def setUp(self) -> None:
        """Deal a fresh game whose score file lives in a throwaway folder."""

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game = make_game(self.tmp.name)

    def test_deal_shape_matches_klondike(self) -> None:
        """Columns hold 1..7 cards, 24 remain in stock, foundations start empty."""

        for column_index, column in enumerate(self.game.tableau):
            self.assertEqual(len(column), column_index + 1)
            for row_index, card in enumerate(column):
                self.assertEqual(card.face_up, row_index == column_index)
        self.assertEqual(len(self.game.stock), 24)
        self.assertTrue(all(not card.face_up for card in self.game.stock))
        self.assertTrue(all(not pile for pile in self.game.foundations))
        self.assertEqual(self.game.score, 0)

    def test_deck_is_a_complete_52_card_pack(self) -> None:
        """Every suit/rank combination appears exactly once across all piles."""

        cards = list(self.game.stock)
        for column in self.game.tableau:
            cards.extend(column)
        identities = {(card.suit, card.rank) for card in cards}
        self.assertEqual(len(cards), 52)
        self.assertEqual(len(identities), 52)

    def test_draw_and_recycle_cycle(self) -> None:
        """Drawing empties the stock into the waste, then recycling reverses it."""

        drawn = 0
        while self.game.stock:
            self.assertEqual(self.game.draw_from_stock(), "draw")
            drawn += 1
            self.assertTrue(self.game.waste[-1].face_up)
        self.assertEqual(drawn, 24)

        self.assertEqual(self.game.draw_from_stock(), "reset")
        self.assertEqual(len(self.game.stock), 24)
        self.assertEqual(self.game.waste, [])
        self.assertTrue(all(not card.face_up for card in self.game.stock))

    def test_same_seed_deals_the_same_board(self) -> None:
        """Two games given equally seeded RNGs deal identical tableaux and stocks."""

        def deal(seed: int) -> tuple[list, list]:
            """Deal one game from a seeded RNG and return its tableau and stock."""
            game = KlondikeGame(str(Path(self.tmp.name) / "seeded.json"), rng=random.Random(seed))
            tableau = [[(card.suit, card.rank) for card in column] for column in game.tableau]
            stock = [(card.suit, card.rank) for card in game.stock]
            return tableau, stock

        self.assertEqual(deal(2026), deal(2026))
        self.assertNotEqual(deal(2026), deal(2027))


class MoveRuleTests(unittest.TestCase):
    """Tableau and foundation placement legality."""

    def setUp(self) -> None:
        """Start each test from an empty board in a throwaway folder, ready to be hand-crafted."""

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game = make_game(self.tmp.name)
        clear_board(self.game)

    def test_tableau_requires_alternating_colors_descending(self) -> None:
        """A red 6 fits a black 7; same color or wrong rank is rejected."""

        black_seven = [Card("spades", 7, face_up=True)]
        self.assertTrue(self.game.can_move_to_tableau_cards([Card("hearts", 6, True)], black_seven))
        self.assertFalse(self.game.can_move_to_tableau_cards([Card("clubs", 6, True)], black_seven))
        self.assertFalse(self.game.can_move_to_tableau_cards([Card("hearts", 5, True)], black_seven))

    def test_only_kings_start_empty_columns(self) -> None:
        """An empty tableau column accepts a king and nothing else."""

        self.assertTrue(self.game.can_move_to_tableau_cards([Card("hearts", 13, True)], []))
        self.assertFalse(self.game.can_move_to_tableau_cards([Card("hearts", 12, True)], []))

    def test_foundations_build_up_by_suit_from_the_ace(self) -> None:
        """Foundation piles demand the right suit and sequential ranks."""

        hearts = FOUNDATION_SUITS.index("hearts")
        self.assertTrue(self.game.can_move_to_foundation(Card("hearts", 1, True), hearts))
        self.assertFalse(self.game.can_move_to_foundation(Card("spades", 1, True), hearts))
        self.assertFalse(self.game.can_move_to_foundation(Card("hearts", 2, True), hearts))

        self.game.foundations[hearts] = [Card("hearts", 1, True)]
        self.assertTrue(self.game.can_move_to_foundation(Card("hearts", 2, True), hearts))
        self.assertFalse(self.game.can_move_to_foundation(Card("hearts", 3, True), hearts))

    def test_foundation_move_scores_and_reveal_scores(self) -> None:
        """Foundation plays and card reveals both award their point values."""

        hearts = FOUNDATION_SUITS.index("hearts")
        self.game.tableau[0] = [Card("spades", 9, face_up=False), Card("hearts", 1, face_up=True)]

        selection = self.game.selection_from_tableau(0, 1)
        assert selection is not None
        moved = self.game.move_selection_to_foundation(selection, hearts)

        self.assertTrue(moved)
        # Moving to the foundation also revealed the buried spade beneath.
        self.assertTrue(self.game.tableau[0][-1].face_up)
        self.assertEqual(
            self.game.score, self.game.FOUNDATION_POINTS + self.game.REVEAL_POINTS
        )

    def test_foundation_round_trips_are_score_neutral(self) -> None:
        """Pulling a card off a foundation gives back its 10 points (D4).

        Without the refund a player could farm points forever by moving the
        same card down to the tableau and back up again.
        """

        hearts = FOUNDATION_SUITS.index("hearts")
        self.game.foundations[hearts] = [Card("hearts", rank, True) for rank in range(1, 6)]
        self.game.tableau[0] = [Card("spades", 6, face_up=True)]
        self.game.score = 40
        high_score = self.game.high_score

        for _ in range(50):
            down_move = self.game.selection_from_foundation(hearts)
            assert down_move is not None
            self.assertTrue(self.game.move_selection_to_tableau(down_move, 0))
            up_move = self.game.selection_from_tableau(0, 1)
            assert up_move is not None
            self.assertTrue(self.game.move_selection_to_foundation(up_move, hearts))

        self.assertEqual(self.game.score, 40)
        self.assertEqual(self.game.high_score, max(high_score, 40))

    def test_has_won_requires_full_foundations(self) -> None:
        """The win check demands 13 cards on all four foundations."""

        self.assertFalse(self.game.has_won())
        for index, suit in enumerate(FOUNDATION_SUITS):
            self.game.foundations[index] = [Card(suit, rank, True) for rank in range(1, 14)]
        self.assertTrue(self.game.has_won())


class SaveFileTests(unittest.TestCase):
    """Damaged or wrong-shaped score files load as zeros instead of crashing (D6)."""

    def setUp(self) -> None:
        """Create a temporary folder to hold the hand-written score files."""

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_wrong_shaped_saves_load_as_zeros(self) -> None:
        """Every malformed file below loads a zero high score, wins and losses."""

        bad_files = [
            "[]",
            "null",
            '"abc"',
            "7",
            "Infinity",
            "1e400",
            "-Infinity",
            "NaN",
            "[" * 100000,
            '{"high_score": Infinity, "wins": 1e400, "losses": -Infinity}',
            '{"high_score": NaN, "wins": [], "losses": null}',
        ]
        for index, text in enumerate(bad_files):
            with self.subTest(save=text[:40]):
                path = Path(self.tmp.name) / f"bad_{index}.json"
                path.write_text(text, encoding="utf-8")
                game = KlondikeGame(str(path), rng=random.Random(index))
                self.assertEqual((game.high_score, game.wins, game.losses), (0, 0, 0))


class ScoreSavingTests(unittest.TestCase):
    """The score file is rewritten only when the high score rises (D8)."""

    def setUp(self) -> None:
        """Create a game whose best score so far is 100."""

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game = make_game(self.tmp.name)
        self.game.high_score = 100
        self.game.score = 0

    def test_points_below_the_record_do_not_write(self) -> None:
        """Ordinary scoring under the high score never touches the disk."""

        with mock.patch.object(self.game, "save_high_score") as save:
            for _ in range(9):
                self.game.add_score(10)

        save.assert_not_called()
        self.assertEqual(self.game.score, 90)

    def test_crossing_the_record_writes_exactly_once(self) -> None:
        """Passing the high score saves it once, at the moment it rises."""

        self.game.score = 95
        with mock.patch.object(self.game, "save_high_score") as save:
            self.game.add_score(10)
            self.game.add_score(-20)
            self.game.add_score(10)

        save.assert_called_once()
        self.assertEqual(self.game.high_score, 105)


class ErrorLogTests(unittest.TestCase):
    """A failed save is written to error.log beside the score file (D9)."""

    def setUp(self) -> None:
        """Create a game whose score file lives in a temporary folder."""

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game = make_game(self.tmp.name)

    def test_failed_save_is_logged_to_error_log(self) -> None:
        """An OSError during the save lands in error.log instead of crashing."""

        with mock.patch("solitaire.os.replace", side_effect=OSError("disk full")):
            self.game.save_high_score()

        log_path = Path(self.tmp.name) / "error.log"
        self.assertTrue(log_path.exists())
        self.assertIn("disk full", log_path.read_text(encoding="utf-8"))
        self.assertFalse((Path(self.tmp.name) / "save_error.log").exists())


class UndoTests(unittest.TestCase):
    """Snapshot/restore powers the undo stack."""

    def setUp(self) -> None:
        """Deal a fresh game whose score file lives in a throwaway folder."""

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game = make_game(self.tmp.name)

    def test_snapshot_round_trip_restores_the_board(self) -> None:
        """A move followed by a restore puts every pile and score back."""

        before = self.game.snapshot()
        self.game.draw_from_stock()
        self.game.add_score(25)

        self.game.restore_snapshot(before)

        after = self.game.snapshot()
        for key in ("score", "stock", "waste", "foundations", "tableau", "won", "lost"):
            self.assertEqual(after[key], before[key])


class HintEngineTests(unittest.TestCase):
    """The hint pipeline: generate, filter, rank."""

    def setUp(self) -> None:
        """Start each test from an empty board in a throwaway folder, ready to be hand-crafted."""

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.game = make_game(self.tmp.name)
        clear_board(self.game)

    def test_hint_prefers_the_move_that_reveals_a_hidden_card(self) -> None:
        """Uncovering a face-down card outranks everything else."""

        self.game.tableau[0] = [Card("diamonds", 9, face_up=False), Card("hearts", 6, face_up=True)]
        self.game.tableau[1] = [Card("spades", 7, face_up=True)]

        move = self.game.find_best_move()

        assert move is not None
        self.assertEqual(move.source_type, "tableau")
        self.assertEqual(move.source_index, 0)
        self.assertEqual(move.destination_type, "tableau")
        self.assertEqual(move.destination_index, 1)

    def test_hint_translates_back_into_a_legal_selection(self) -> None:
        """A produced hint always maps to a live, legal selection."""

        self.game.waste = [Card("hearts", 1, face_up=True)]

        move = self.game.find_best_move()

        assert move is not None
        self.assertEqual(move.destination_type, "foundation")
        selection = self.game.selection_from_hint(move)
        assert selection is not None
        self.assertTrue(
            self.game.can_move_to_foundation(selection.cards[0], move.destination_index)
        )

    def test_pointless_king_shuffle_is_not_suggested(self) -> None:
        """Sliding a bare king between empty columns is filtered out entirely."""

        self.game.tableau[0] = [Card("spades", 13, face_up=True)]
        # Every other column stays empty, so the king shuffle is the only
        # legal move -- and the filter should still reject it, meaning the
        # deal is correctly judged as having no useful moves.
        self.assertIsNone(self.game.find_best_move())


if __name__ == "__main__":
    unittest.main()
