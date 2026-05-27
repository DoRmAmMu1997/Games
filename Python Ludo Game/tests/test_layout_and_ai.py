"""Tests for generated polygon boards and heuristic AI choices."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from ai import choose_move
from board import BoardLayout
from game import LudoGame, LudoRules


def make_game(total_players: int = 4) -> LudoGame:
    players = [(f"P{i + 1}", i == 0) for i in range(total_players)]
    return LudoGame(players, LudoRules(total_players=total_players), seed=21)


class LayoutTests(unittest.TestCase):
    def test_player_counts_generate_expected_polygon_shapes(self) -> None:
        self.assertEqual(BoardLayout.for_player_count(4).polygon_sides, 4)
        self.assertEqual(BoardLayout.for_player_count(5).polygon_sides, 5)
        self.assertEqual(BoardLayout.for_player_count(6).polygon_sides, 6)

    def test_layout_has_generalized_track_home_and_safe_cells(self) -> None:
        for count in (4, 5, 6):
            layout = BoardLayout.for_player_count(count)

            self.assertEqual(len(layout.track_positions), count * 13)
            self.assertEqual(len(layout.home_lanes), count)
            self.assertTrue(all(len(lane) == 6 for lane in layout.home_lanes))
            self.assertEqual(layout.start_indices, tuple(i * 13 for i in range(count)))
            self.assertEqual(layout.safe_indices, tuple((i * 13 + 8) % (count * 13) for i in range(count)))


class AiChoiceTests(unittest.TestCase):
    def test_ai_prefers_finishing_move(self) -> None:
        game = make_game()
        game.current = 1
        game.players[1].tokens[0].steps = game.layout.finish_steps - 1
        game.players[1].tokens[1].steps = 7

        move = choose_move(game, "tactical", 1)

        self.assertEqual(move.token_index, 0)

    def test_ai_prefers_capture_over_neutral_progress(self) -> None:
        game = make_game()
        game.current = 1
        game.players[1].tokens[0].steps = 0
        game.players[1].tokens[1].steps = 10
        landing = game.layout.track_index(1, 4)
        game.players[0].tokens[0].steps = game.layout.steps_to_reach(0, landing)

        move = choose_move(game, "aggressive", 4)

        self.assertEqual(move.token_index, 0)

    def test_ai_choice_is_deterministic_for_same_seed(self) -> None:
        game_a = make_game()
        game_b = make_game()
        for game in (game_a, game_b):
            game.current = 2
            game.players[2].tokens[0].steps = 3
            game.players[2].tokens[1].steps = 3

        self.assertEqual(
            choose_move(game_a, "defensive", 2).token_index,
            choose_move(game_b, "defensive", 2).token_index,
        )


if __name__ == "__main__":
    unittest.main()
