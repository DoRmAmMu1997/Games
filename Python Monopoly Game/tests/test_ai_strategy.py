"""AI strategy regressions: title valuation, trade memory and simulation counts.

These tests pin decisions the heuristic AI makes from constructed boards,
so a change to the valuation or trade logic shows up as a readable failure
instead of a quiet shift in seeded simulation batches.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from test_engine_regressions import rig_rolls
from test_foundation_improvements import give_group, make_game

import ai
import simulation
from game import MonopolyGame


def plain_street_value(game, position: int) -> int:
    """Return a street's value with no group premium, under the game's profile."""
    space = game.board[position]
    profile = ai._profile(game)
    raw = (space.price + space.rent[-1] * ai.STREET_TOP_RENT_WEIGHT) * profile.value_scale
    return max(space.mortgage, round(raw))


class OwnedTitleValuationTests(unittest.TestCase):
    """The AI values titles it already owns by the group it actually holds."""

    def test_lone_owned_title_gets_no_monopoly_or_partial_premium(self) -> None:
        """Owning a title alone does not count as owning (or completing) its group.

        A lone brown title used to look like it "completed" the two-title
        group, and a lone light-blue one like a partial group, purely
        because the evaluated title itself was counted as already owned.
        """
        for position in (1, 6):
            with self.subTest(position=position):
                game = make_game()
                player = game.players[1]
                give_group(game, player.index, (position,))

                value = ai.property_value(game, player, position)

                self.assertEqual(value, plain_street_value(game, position))

    def test_title_inside_held_monopoly_is_worth_more_than_a_lone_one(self) -> None:
        """A title that is part of a held monopoly carries the completion premium."""
        lone = make_game()
        give_group(lone, 1, (1,))
        held = make_game()
        give_group(held, 1, (1, 3))

        lone_value = ai.property_value(lone, lone.players[1], 1)
        held_value = ai.property_value(held, held.players[1], 1)

        self.assertGreater(held_value, lone_value)
        self.assertEqual(held_value, round(plain_street_value(held, 1) * ai.GROUP_COMPLETION_MULT))


class SimulationMetricTests(unittest.TestCase):
    """The tuning simulation reports what actually happened in a game."""

    def test_simulation_counts_back_to_back_bankruptcy_auctions(self) -> None:
        """Two Bank auctions in a row count as two, even with no gap between them.

        The first AI lands on Income Tax with two titles and no cash, goes
        bankrupt to the Bank, and both titles are auctioned to cash-less
        opponents who all pass. The second auction opens in the same
        action that closes the first, so a "was there an auction before?"
        check missed it; counting by auction identity does not.
        """

        def rigged_game(specs, seed=None, ai_profile="standard"):
            """Build the simulation's game, then set up the bankruptcy."""
            game = MonopolyGame(specs, seed=seed, ai_profile=ai_profile)
            give_group(game, 0, (1, 3))
            for player in game.players:
                player.cash = 0
            rig_rolls(game, 1, 3)      # GO + 4 = Income Tax
            return game

        with mock.patch.object(simulation, "MonopolyGame", rigged_game):
            metrics = simulation.run_ai_game(seed=1, max_actions=7)

        self.assertEqual(metrics["auction_count"], 2)


if __name__ == "__main__":
    unittest.main()
