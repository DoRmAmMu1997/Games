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
from settings import SCREEN_HEIGHT, SCREEN_WIDTH


def make_game(total_players: int = 4) -> LudoGame:
    """Create a deterministic Ludo game for layout and AI tests."""

    players = [(f"P{i + 1}", i == 0) for i in range(total_players)]
    return LudoGame(players, LudoRules(total_players=total_players), seed=21)


class LayoutTests(unittest.TestCase):
    """Checks for generated board geometry."""

    def test_player_counts_generate_expected_polygon_shapes(self) -> None:
        """Player count should directly choose square, pentagon, or hexagon."""

        self.assertEqual(BoardLayout.for_player_count(4).polygon_sides, 4)
        self.assertEqual(BoardLayout.for_player_count(5).polygon_sides, 5)
        self.assertEqual(BoardLayout.for_player_count(6).polygon_sides, 6)

    def test_layout_has_generalized_track_home_and_safe_cells(self) -> None:
        """Every supported board should expose track, home, and safe cells."""

        for count in (4, 5, 6):
            layout = BoardLayout.for_player_count(count)

            self.assertEqual(len(layout.track_positions), count * 13)
            self.assertEqual(len(layout.home_lanes), count)
            self.assertTrue(all(len(lane) == 6 for lane in layout.home_lanes))
            self.assertEqual(layout.start_indices, tuple(i * 13 for i in range(count)))
            self.assertEqual(layout.safe_indices, tuple((i * 13 + 8) % (count * 13) for i in range(count)))

    def test_board_layout_pixels_are_the_headless_fallback(self) -> None:
        """BoardLayout's own pixel fields place every token inside the window.

        The renderer's DisplayLayout owns the real on-screen coordinates, but
        BoardLayout keeps a plain polygon as the headless fallback for code
        that runs before (or without) a renderer. That fallback must still map
        each kind of step onto its own field and onto the canvas.
        """

        for count in (4, 5, 6):
            with self.subTest(total_players=count):
                layout = BoardLayout.for_player_count(count)
                self.assertEqual(layout.position_for(1, -1, 2), layout.yard_positions[1][2])
                track_index = layout.track_index(1, 5)
                assert track_index is not None
                self.assertEqual(layout.position_for(1, 5), layout.track_positions[track_index])
                self.assertEqual(layout.position_for(1, layout.lap_length + 2), layout.home_lanes[1][2])
                self.assertEqual(layout.position_for(1, layout.finish_steps), layout.home_lanes[1][-1])
                points = [point for lane in layout.home_lanes for point in lane]
                points += list(layout.track_positions)
                points += [point for yard in layout.yard_positions for point in yard]
                for x, y in points:
                    self.assertTrue(0 <= x <= SCREEN_WIDTH and 0 <= y <= SCREEN_HEIGHT, (x, y))


class AiChoiceTests(unittest.TestCase):
    """Checks for important heuristic AI priorities."""

    def test_ai_prefers_finishing_move(self) -> None:
        """A finishing move should outrank ordinary progress."""

        game = make_game()
        game.current = 1
        game.players[1].tokens[0].steps = game.layout.finish_steps - 1
        game.players[1].tokens[1].steps = 7

        move = choose_move(game, "tactical", 1)

        assert move is not None
        self.assertEqual(move.token_index, 0)

    def test_ai_prefers_capture_over_neutral_progress(self) -> None:
        """Aggressive AI should take an available capture."""

        game = make_game()
        game.current = 1
        game.players[1].tokens[0].steps = 0
        game.players[1].tokens[1].steps = 10
        landing = game.layout.track_index(1, 4)
        assert landing is not None
        game.players[0].tokens[0].steps = game.layout.steps_to_reach(0, landing)

        move = choose_move(game, "aggressive", 4)

        assert move is not None
        self.assertEqual(move.token_index, 0)

    def test_ai_choice_is_deterministic_for_same_seed(self) -> None:
        """Equivalent game states should produce the same AI decision."""

        game_a = make_game()
        game_b = make_game()
        for game in (game_a, game_b):
            game.current = 2
            game.players[2].tokens[0].steps = 3
            game.players[2].tokens[1].steps = 3

        move_a = choose_move(game_a, "defensive", 2)
        move_b = choose_move(game_b, "defensive", 2)

        assert move_a is not None and move_b is not None
        self.assertEqual(move_a.token_index, move_b.token_index)


if __name__ == "__main__":
    unittest.main()
