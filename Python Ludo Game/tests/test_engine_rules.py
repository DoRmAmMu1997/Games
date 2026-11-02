"""Regression coverage for the core Ludo rules engine."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from board import BoardLayout
from game import LAP_VERSION, LudoGame, LudoRules


def make_game(total_players: int = 4) -> LudoGame:
    """Create a deterministic game used by engine tests."""

    players = [(f"P{i + 1}", i == 0) for i in range(total_players)]
    return LudoGame(players, LudoRules(total_players=total_players), seed=11)


class EngineRuleTests(unittest.TestCase):
    """Focused checks for rules that are easy to regress."""

    def test_six_can_enter_a_token_from_yard(self) -> None:
        """A 6 should offer yard-entry moves and keep the turn alive."""

        game = make_game()

        moves = game.legal_moves(6)
        self.assertEqual(len(moves), 4)

        result = game.apply_move(moves[0])

        self.assertEqual(game.players[0].tokens[0].steps, 0)
        self.assertFalse(result.capture)
        self.assertTrue(result.extra_turn)

    def test_non_six_cannot_move_when_every_token_is_in_yard(self) -> None:
        """A non-6 with all tokens in yard should auto-pass the turn."""

        game = make_game()

        self.assertEqual(game.legal_moves(3), [])
        game.note_no_move(3)

        self.assertEqual(game.current, 1)
        self.assertEqual(game.awaiting, "pre_roll")

    def test_exact_home_roll_is_required(self) -> None:
        """Tokens may finish only with an exact die value."""

        game = make_game()
        game.players[0].tokens[0].steps = game.layout.finish_steps - 2

        self.assertEqual(game.legal_moves(3), [])
        moves = game.legal_moves(2)
        result = game.apply_move(moves[0])

        self.assertTrue(result.home)
        self.assertTrue(game.players[0].tokens[0].finished)

    def test_capture_sends_opponent_home_and_grants_bonus(self) -> None:
        """Landing on an exposed opponent token should capture it."""

        game = make_game()
        game.players[0].tokens[0].steps = 0
        landing = game.layout.track_index(0, 3)
        assert landing is not None
        game.players[1].tokens[0].steps = game.layout.steps_to_reach(1, landing)

        result = game.apply_move(game.legal_moves(3)[0])

        self.assertTrue(result.capture)
        self.assertEqual(game.players[1].tokens[0].steps, -1)
        self.assertEqual(game.players[0].captures, 1)
        self.assertTrue(result.extra_turn)

    def test_safe_square_prevents_capture(self) -> None:
        """Safe squares should protect opponent tokens from capture."""

        game = make_game()
        safe_index = game.layout.safe_indices[1]
        game.players[0].tokens[0].steps = game.layout.steps_to_reach(0, game.layout.previous_index(safe_index, 2))
        game.players[1].tokens[0].steps = game.layout.steps_to_reach(1, safe_index)

        result = game.apply_move(game.legal_moves(2)[0])

        self.assertFalse(result.capture)
        self.assertNotEqual(game.players[1].tokens[0].steps, -1)
        self.assertEqual(game.current, 1)

    def test_three_consecutive_sixes_forfeit_the_third_roll_only(self) -> None:
        """The third 6 should be lost without undoing earlier moves."""

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

    def test_six_with_no_legal_move_keeps_the_turn_without_the_penalty(self) -> None:
        """Every 6 earns another roll, even a third one, when the penalty is off.

        All of seat 0's tokens sit two cells from home, so a 6 can never be
        played. Each 6 must still hand the same player another roll, exactly
        as a played 6 would.
        """

        players = [(f"P{i + 1}", i == 0) for i in range(4)]
        game = LudoGame(players, LudoRules(total_players=4, three_sixes_penalty=False), seed=11)
        for token in game.players[0].tokens:
            token.steps = game.layout.finish_steps - 2

        for round_number in range(3):
            with self.subTest(round=round_number + 1):
                game.record_roll(6)
                self.assertEqual(game.legal_moves(6), [])
                game.note_no_move(6)
                self.assertEqual(game.current, 0)
                self.assertEqual(game.awaiting, "pre_roll")

    def test_save_load_round_trip_keeps_rule_and_player_state(self) -> None:
        """Saving and restoring should preserve rules and progress."""

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


class ClassicLapTests(unittest.TestCase):
    """A lap is one cell shorter than the shared track, as on a real board.

    Beginner note: the classic board has 52 shared squares, but a token never
    visits the square just behind its own start. It turns into its home column
    one square earlier, so it walks 51 shared squares before the column.
    """

    def test_finish_steps_use_the_shortened_lap(self) -> None:
        """A full trip is the 51/64/77-cell lap plus the six home cells, minus one."""

        expected = {4: 56, 5: 69, 6: 82}
        for count, finish in expected.items():
            with self.subTest(total_players=count):
                layout = BoardLayout.for_player_count(count)
                self.assertEqual(layout.lap_length, layout.track_length - 1)
                self.assertEqual(layout.finish_steps, finish)

    def test_lap_skips_the_corner_behind_the_start(self) -> None:
        """No lap step ever lands on the cell just behind the seat's own start."""

        for count in (4, 5, 6):
            layout = BoardLayout.for_player_count(count)
            for seat, start in enumerate(layout.start_indices):
                with self.subTest(total_players=count, seat=seat):
                    corner = layout.previous_index(start, 1)
                    visited = {layout.track_index(seat, steps) for steps in range(layout.lap_length)}
                    self.assertNotIn(corner, visited)
                    self.assertEqual(len(visited), layout.lap_length)
                    self.assertIsNone(layout.track_index(seat, layout.lap_length))

    def test_step_after_the_lap_enters_the_first_home_cell(self) -> None:
        """One step past the lap is home-lane cell 0, reached by a legal 1."""

        game = make_game()
        lap = game.layout.lap_length
        self.assertIsNone(game.layout.home_lane_index(lap - 1))
        self.assertEqual(game.layout.home_lane_index(lap), 0)
        game.players[0].tokens[0].steps = lap - 1
        game.record_roll(1)
        move = game.legal_moves(1)[0]
        self.assertEqual(move.to_steps, lap)
        self.assertIsNone(move.landing_index)

    def test_steps_to_reach_rejects_the_skipped_corner(self) -> None:
        """A seat cannot be asked to reach a cell its lap never visits."""

        layout = BoardLayout.for_player_count(4)
        corner = layout.previous_index(layout.start_indices[1], 1)
        with self.assertRaises(ValueError):
            layout.steps_to_reach(1, corner)
        # Other seats pass over that same cell normally.
        self.assertEqual(layout.steps_to_reach(0, corner), corner)


class LegacySaveMigrationTests(unittest.TestCase):
    """Saves written before the 51-cell lap load onto the new step numbers."""

    def legacy_save(self) -> dict:
        """Return a 4P save dict shaped like one written by the old 52-cell lap."""

        data = make_game().to_dict()
        del data["lap_version"]
        return data

    def test_save_records_the_lap_version(self) -> None:
        """New saves carry the lap version so loaders know which numbering they use."""

        self.assertEqual(make_game().to_dict()["lap_version"], LAP_VERSION)

    def test_legacy_lane_corner_and_finish_steps_shift_down_one(self) -> None:
        """Old corner 51, lane 52 and finish 57 become 50, 51 and 56."""

        data = self.legacy_save()
        for token, old_steps in zip(data["players"][0]["tokens"], (51, 52, 57, 55), strict=True):
            token["steps"] = old_steps
        restored = LudoGame.from_dict(data)
        self.assertEqual([token.steps for token in restored.players[0].tokens], [50, 51, 56, 54])
        self.assertTrue(restored.players[0].tokens[2].finished)

    def test_legacy_yard_and_track_tokens_do_not_move(self) -> None:
        """Yard tokens and tokens still on the lap keep their step values."""

        data = self.legacy_save()
        for token, old_steps in zip(data["players"][1]["tokens"], (-1, 0, 25, 50), strict=True):
            token["steps"] = old_steps
        restored = LudoGame.from_dict(data)
        self.assertEqual([token.steps for token in restored.players[1].tokens], [-1, 0, 25, 50])

    def test_round_trip_does_not_shift_twice(self) -> None:
        """A migrated game saved again and reloaded keeps the migrated steps."""

        data = self.legacy_save()
        data["players"][0]["tokens"][0]["steps"] = 52
        migrated = LudoGame.from_dict(data)
        again = LudoGame.from_dict(migrated.to_dict())
        self.assertEqual(again.players[0].tokens[0].steps, 51)

    def test_current_save_is_not_migrated(self) -> None:
        """A save already on the new numbering loads unchanged."""

        game = make_game()
        game.players[0].tokens[0].steps = game.layout.lap_length
        restored = LudoGame.from_dict(game.to_dict())
        self.assertEqual(restored.players[0].tokens[0].steps, game.layout.lap_length)

    def test_unknown_lap_version_is_rejected(self) -> None:
        """A save from an unknown future numbering is refused, not guessed at."""

        data = make_game().to_dict()
        data["lap_version"] = 3
        with self.assertRaises(ValueError):
            LudoGame.from_dict(data)


if __name__ == "__main__":
    unittest.main()
