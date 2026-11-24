"""Regression coverage for the core Ludo rules engine."""

from __future__ import annotations

import copy
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

        game.record_roll(6)
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
        game.record_roll(2)
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

        game.record_roll(3)
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

        game.record_roll(2)
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

    def test_apply_move_rejects_a_move_before_any_roll(self) -> None:
        """A move offered by legal_moves cannot be played until the die is rolled."""

        game = make_game()
        move = game.legal_moves(6)[0]

        with self.assertRaises(ValueError):
            game.apply_move(move)
        self.assertEqual(game.players[0].tokens[0].steps, -1)

    def test_apply_move_rejects_a_move_for_a_different_die(self) -> None:
        """A move computed for another die value is refused, even if legal for that die."""

        game = make_game()
        game.players[0].tokens[0].steps = 0
        game.record_roll(3)
        stale = next(move for move in game.legal_moves(6) if move.enters_board)

        with self.assertRaises(ValueError):
            game.apply_move(stale)
        self.assertEqual(game.players[0].tokens[stale.token_index].steps, -1)

    def test_blockade_on_the_start_square_stops_yard_entry(self) -> None:
        """An opponent pair on a player's start square blocks tokens leaving the yard.

        Beginner note: with blockades on, two same-colour tokens on one square
        form a wall nobody else may pass or land on. Entering the board lands
        on the start square, so a wall there must keep the yard shut.
        """

        players = [(f"P{i + 1}", i == 0) for i in range(4)]
        game = LudoGame(players, LudoRules(total_players=4, blockades=True), seed=11)
        start = game.layout.start_indices[0]
        for token in game.players[1].tokens[:2]:
            token.steps = game.layout.steps_to_reach(1, start)

        self.assertEqual([move for move in game.legal_moves(6) if move.enters_board], [])

        game.players[1].tokens[1].steps = -1
        self.assertEqual(len([move for move in game.legal_moves(6) if move.enters_board]), 4)

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


class ForcedMoveTests(unittest.TestCase):
    """``forced_move`` finds the roll whose every legal move ends the same way.

    Beginner note: "only one move" means only one OUTCOME. Four yard tokens on
    a 6 are four legal moves, but whichever token you pick, one token leaves
    the yard onto the start square, so the choice is not a real choice.
    """

    def test_a_single_legal_move_is_forced(self) -> None:
        """One token on the board and a non-6 roll leaves exactly one move."""

        game = make_game()
        game.players[0].tokens[0].steps = 4
        game.record_roll(3)
        move = game.forced_move(3)
        self.assertEqual(move, game.legal_moves(3)[0])

    def test_interchangeable_yard_tokens_count_as_one_move(self) -> None:
        """A 6 with every token in the yard forces a token out."""

        game = make_game()
        game.record_roll(6)
        self.assertEqual(len(game.legal_moves(6)), 4)
        move = game.forced_move(6)
        self.assertIsNotNone(move)
        assert move is not None
        self.assertTrue(move.enters_board)

    def test_a_real_choice_is_not_forced(self) -> None:
        """Two tokens on different squares give the player a real choice."""

        game = make_game()
        game.players[0].tokens[0].steps = 4
        game.players[0].tokens[1].steps = 10
        game.record_roll(2)
        self.assertIsNone(game.forced_move(2))

    def test_no_legal_move_is_not_forced(self) -> None:
        """With nothing playable there is no move to make for the player."""

        game = make_game()
        game.record_roll(3)
        self.assertIsNone(game.forced_move(3))


class EngineEventTests(unittest.TestCase):
    """The engine queues one event kind per sound-worthy moment, for the shell to drain.

    Every check drains the queue after setting up the board, so it sees only
    the events of the action under test.
    """

    def test_a_new_game_has_no_events(self) -> None:
        """Nothing has happened yet, so draining returns an empty list."""

        self.assertEqual(make_game().drain_events(), [])

    def test_drain_returns_the_events_in_order_and_empties_the_queue(self) -> None:
        """A roll with no move queues roll, no_move, turn_change; a second drain is empty."""

        game = make_game()
        game.record_roll(3)
        game.note_no_move(3)
        self.assertEqual(game.drain_events(), ["roll", "no_move", "turn_change"])
        self.assertEqual(game.drain_events(), [])

    def test_every_roll_is_announced_even_a_repeated_value(self) -> None:
        """Two rolls of the same value in a row both queue a roll event."""

        game = make_game()
        game.record_roll(2)
        game.note_no_move(2)
        game.record_roll(2)
        self.assertEqual(game.drain_events(), ["roll", "no_move", "turn_change", "roll"])

    def test_roll_die_announces_its_roll(self) -> None:
        """The engine's own dice go through record_roll, so they queue a roll too."""

        game = make_game()
        game.roll_die()
        self.assertEqual(game.drain_events()[0], "roll")

    def test_a_six_is_announced_after_the_roll(self) -> None:
        """Rolling a 6 queues roll then rolled_six."""

        game = make_game()
        game.record_roll(6)
        self.assertEqual(game.drain_events(), ["roll", "rolled_six"])

    def test_third_six_announces_the_penalty_and_the_turn_change(self) -> None:
        """The forfeited third 6 queues roll, rolled_six, three_sixes, turn_change."""

        game = make_game()
        game.record_roll(6)
        game.apply_move(game.legal_moves(6)[0])
        game.record_roll(6)
        game.apply_move(next(move for move in game.legal_moves(6) if move.token_index == 0))
        game.drain_events()

        self.assertTrue(game.record_roll(6))
        self.assertEqual(game.drain_events(), ["roll", "rolled_six", "three_sixes", "turn_change"])

    def test_entering_the_board_leaves_the_yard_and_earns_a_bonus(self) -> None:
        """A yard entry on a 6 queues leave_yard then bonus_turn (no plain move)."""

        game = make_game()
        game.record_roll(6)
        game.drain_events()
        game.apply_move(game.legal_moves(6)[0])
        self.assertEqual(game.drain_events(), ["leave_yard", "bonus_turn"])

    def test_a_plain_move_passes_the_turn(self) -> None:
        """An ordinary move queues move then turn_change."""

        game = make_game()
        game.players[0].tokens[0].steps = 0
        game.record_roll(3)
        game.drain_events()
        game.apply_move(game.legal_moves(3)[0])
        self.assertEqual(game.drain_events(), ["move", "turn_change"])

    def test_capture_is_announced_with_its_bonus(self) -> None:
        """Capturing queues move, capture, bonus_turn; without the bonus rule the turn passes."""

        for bonus in (True, False):
            with self.subTest(bonus_on_capture=bonus):
                players = [(f"P{i + 1}", i == 0) for i in range(4)]
                game = LudoGame(players, LudoRules(total_players=4, bonus_on_capture=bonus), seed=11)
                game.players[0].tokens[0].steps = 0
                landing = game.layout.track_index(0, 3)
                assert landing is not None
                game.players[1].tokens[0].steps = game.layout.steps_to_reach(1, landing)
                game.record_roll(3)
                game.drain_events()
                game.apply_move(game.legal_moves(3)[0])
                last = "bonus_turn" if bonus else "turn_change"
                self.assertEqual(game.drain_events(), ["move", "capture", last])

    def test_reaching_home_is_announced_with_its_bonus(self) -> None:
        """A token reaching home queues move, home, bonus_turn."""

        game = make_game()
        game.players[0].tokens[0].steps = game.layout.finish_steps - 2
        game.record_roll(2)
        game.drain_events()
        game.apply_move(game.legal_moves(2)[0])
        self.assertEqual(game.drain_events(), ["move", "home", "bonus_turn"])

    def test_winning_move_announces_the_win_and_nothing_after_it(self) -> None:
        """The last token home queues move, home, game_won: no bonus and no turn change."""

        game = make_game()
        for token in game.players[0].tokens[1:]:
            token.steps = game.layout.finish_steps
        game.players[0].tokens[0].steps = game.layout.finish_steps - 2
        game.record_roll(2)
        game.drain_events()
        game.apply_move(game.legal_moves(2)[0])
        self.assertEqual(game.drain_events(), ["move", "home", "game_won"])

    def test_six_with_no_move_keeps_the_turn(self) -> None:
        """A 6 that cannot be played queues no_move but no turn change."""

        game = make_game()
        for token in game.players[0].tokens:
            token.steps = game.layout.finish_steps - 2
        game.record_roll(6)
        game.drain_events()
        game.note_no_move(6)
        self.assertEqual(game.drain_events(), ["no_move"])

    def test_end_turn_announces_the_turn_change(self) -> None:
        """Passing the turn by hand queues turn_change."""

        game = make_game()
        game.end_turn()
        self.assertEqual(game.drain_events(), ["turn_change"])

    def test_nobody_left_to_play_ends_the_game(self) -> None:
        """When every seat has finished, advancing the turn queues game_won instead."""

        game = make_game()
        for player in game.players:
            for token in player.tokens:
                token.steps = game.layout.finish_steps
        game.end_turn()
        self.assertEqual(game.drain_events(), ["game_won"])

    def test_events_are_never_saved_or_loaded(self) -> None:
        """to_dict leaves the queue out, and a loaded game starts with an empty queue."""

        game = make_game()
        game.record_roll(6)
        data = game.to_dict()
        self.assertNotIn("events", data)
        data["events"] = ["capture", "game_won"]
        self.assertEqual(LudoGame.from_dict(data).drain_events(), [])
        self.assertEqual(game.drain_events(), ["roll", "rolled_six"])


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


class CorruptSaveTests(unittest.TestCase):
    """from_dict refuses save data that would crash or wedge a resumed game."""

    def test_corrupt_saves_raise_value_error(self) -> None:
        """Each kind of damaged save is rejected with ValueError, never loaded."""

        valid = make_game().to_dict()
        finish = make_game().layout.finish_steps

        def damaged(change) -> dict:
            """Return a deep copy of the valid save with ``change`` applied to it."""

            data = copy.deepcopy(valid)
            change(data)
            return data

        cases = {
            "current out of range": damaged(lambda data: data.update(current=4)),
            "unknown awaiting": damaged(lambda data: data.update(awaiting="dancing")),
            "phase game_over": damaged(lambda data: data.update(phase="game_over")),
            "choose_move with no roll": damaged(lambda data: data.update(awaiting="choose_move", last_roll=None)),
            "missing token": damaged(lambda data: data["players"][0]["tokens"].pop()),
            "steps past home": damaged(lambda data: data["players"][1]["tokens"][0].update(steps=finish + 1)),
            "top-level list": [valid],
            "top-level null": None,
            "top-level string": "savegame",
            "top-level number": 42,
        }
        for name, data in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                LudoGame.from_dict(data)  # type: ignore[arg-type]

    def test_a_choose_move_save_with_no_legal_move_resolves_like_live_play(self) -> None:
        """A save waiting for a move nobody can make is resolved on load, not stuck.

        All of P1's tokens are in the yard and the saved roll is a 3, so no
        move is legal. A human resuming this save would get no Roll button and
        nothing to click. Loading now resolves it exactly as ``note_no_move``
        does in play: a 3 passes the turn to P2.
        """

        data = make_game().to_dict()
        data.update(awaiting="choose_move", last_roll=3)
        restored = LudoGame.from_dict(data)
        self.assertEqual(restored.awaiting, "pre_roll")
        self.assertEqual(restored.current, 1)
        self.assertEqual(restored.drain_events(), [])

    def test_a_stuck_six_keeps_its_bonus_roll_on_load(self) -> None:
        """With no legal move on a saved 6, the same player rolls again, as in play."""

        game = make_game()
        for token in game.players[0].tokens:
            token.steps = game.layout.finish_steps
        game.players[0].tokens[0].steps = game.layout.finish_steps - 2
        data = game.to_dict()
        data.update(awaiting="choose_move", last_roll=6)
        restored = LudoGame.from_dict(data)
        self.assertEqual(restored.awaiting, "pre_roll")
        self.assertEqual(restored.current, 0)

    def test_valid_choose_move_save_still_loads(self) -> None:
        """A save taken mid-turn, with a real die roll waiting, still resumes."""

        game = make_game()
        game.record_roll(6)
        restored = LudoGame.from_dict(game.to_dict())
        self.assertEqual(restored.awaiting, "choose_move")
        self.assertEqual(restored.last_roll, 6)


if __name__ == "__main__":
    unittest.main()
