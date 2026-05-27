"""Regression coverage for the core Ludo rules engine."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from game import LudoGame, LudoRules


def make_game(total_players: int = 4) -> LudoGame:
    players = [(f"P{i + 1}", i == 0) for i in range(total_players)]
    return LudoGame(players, LudoRules(total_players=total_players), seed=11)


class EngineRuleTests(unittest.TestCase):
    def test_six_can_enter_a_token_from_yard(self) -> None:
        game = make_game()

        moves = game.legal_moves(6)
        self.assertEqual(len(moves), 4)

        result = game.apply_move(moves[0])

        self.assertEqual(game.players[0].tokens[0].steps, 0)
        self.assertFalse(result.capture)
        self.assertTrue(result.extra_turn)

    def test_non_six_cannot_move_when_every_token_is_in_yard(self) -> None:
        game = make_game()

        self.assertEqual(game.legal_moves(3), [])
        game.note_no_move(3)

        self.assertEqual(game.current, 1)
        self.assertEqual(game.awaiting, "pre_roll")

    def test_exact_home_roll_is_required(self) -> None:
        game = make_game()
        game.players[0].tokens[0].steps = game.layout.finish_steps - 2

        self.assertEqual(game.legal_moves(3), [])
        moves = game.legal_moves(2)
        result = game.apply_move(moves[0])

        self.assertTrue(result.home)
        self.assertTrue(game.players[0].tokens[0].finished)

    def test_capture_sends_opponent_home_and_grants_bonus(self) -> None:
        game = make_game()
        game.players[0].tokens[0].steps = 0
        game.players[1].tokens[0].steps = game.layout.steps_to_reach(1, game.layout.track_index(0, 3))

        result = game.apply_move(game.legal_moves(3)[0])

        self.assertTrue(result.capture)
        self.assertEqual(game.players[1].tokens[0].steps, -1)
        self.assertEqual(game.players[0].captures, 1)
        self.assertTrue(result.extra_turn)

    def test_safe_square_prevents_capture(self) -> None:
        game = make_game()
        safe_index = game.layout.safe_indices[1]
        game.players[0].tokens[0].steps = game.layout.steps_to_reach(0, game.layout.previous_index(safe_index, 2))
        game.players[1].tokens[0].steps = game.layout.steps_to_reach(1, safe_index)

        result = game.apply_move(game.legal_moves(2)[0])

        self.assertFalse(result.capture)
        self.assertNotEqual(game.players[1].tokens[0].steps, -1)
        self.assertEqual(game.current, 1)

    def test_three_consecutive_sixes_forfeit_the_third_roll_only(self) -> None:
        game = make_game()
        game.record_roll(6)
        game.apply_move(game.legal_moves(6)[0])
        game.record_roll(6)
        second_move = next(move for move in game.legal_moves(6) if move.token_index == 0)
        game.apply_move(second_move)

        forfeited = game.record_roll(6)

        self.assertTrue(forfeited)
        self.assertEqual(game.players[0].tokens[0].steps, 6)
        self.assertEqual(game.players[0].tokens[1].steps, -1)
        self.assertEqual(game.current, 1)

    def test_save_load_round_trip_keeps_rule_and_player_state(self) -> None:
        game = make_game(total_players=5)
        game.players[0].tokens[0].steps = 4
        game.players[2].tokens[1].steps = 10
        game.players[0].captures = 2
        game.turns_taken = 17
        game.last_roll = 6

        restored = LudoGame.from_dict(game.to_dict())

        self.assertEqual(restored.rules.total_players, 5)
        self.assertEqual(restored.players[0].tokens[0].steps, 4)
        self.assertEqual(restored.players[2].tokens[1].steps, 10)
        self.assertEqual(restored.players[0].captures, 2)
        self.assertEqual(restored.turns_taken, 17)
        self.assertEqual(restored.last_roll, 6)


if __name__ == "__main__":
    unittest.main()
