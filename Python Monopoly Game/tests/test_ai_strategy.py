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
from settings import TRADE_RETRY_COOLDOWN_TURNS


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


class TradeMemoryTests(unittest.TestCase):
    """The AI remembers a rejected trade instead of nagging every turn."""

    def test_ai_waits_before_reproposing_a_rejected_trade(self) -> None:
        """A rejected offer for a title is not re-sent until the cooldown passes.

        Iris needs the human's brown title to complete her group. After
        the human rejects her offer she skips that partner and title for
        TRADE_RETRY_COOLDOWN_TURNS turns, then may ask again.
        """
        game = make_game()
        human, iris = game.players[0], game.players[1]
        give_group(game, iris.index, (1,))
        give_group(game, human.index, (3,))
        iris.cash = 5000
        game.current = iris.index

        offer = ai.propose_trade(game, iris)
        assert offer is not None, "precondition: Iris wants the brown title"
        self.assertTrue(game.propose_trade(offer))
        game.respond_trade(False)

        self.assertIsNone(ai.propose_trade(game, iris))
        game.turn_count += TRADE_RETRY_COOLDOWN_TURNS - 1
        self.assertIsNone(ai.propose_trade(game, iris))
        game.turn_count += 1
        self.assertIsNotNone(ai.propose_trade(game, iris))
        self.assertNotIn("_rejected_offers", game.to_dict())


class HousingShortageTests(unittest.TestCase):
    """The AI moves a house to finish a group when the Bank has none left."""

    def test_ai_breaks_housing_shortage_to_reach_hotels(self) -> None:
        """With no houses in the Bank, Iris sells one brown house to build orange.

        Orange sits at 3/4/4 -- one house short of hotels -- and brown is her
        lowest-priority developed group. One AI move sells evenly from brown
        and builds the last orange house; the next builds a hotel, which
        hands four houses back to the Bank.
        """
        game = make_game()
        iris = game.players[1]
        give_group(game, iris.index, (16, 18, 19, 1, 3))
        game.houses = {16: 3, 18: 4, 19: 4, 1: 2, 3: 2}
        game.bank_houses = 0
        iris.cash = 2000
        game.current = iris.index
        game.awaiting = "post_roll"

        ai.take_action(game)

        self.assertEqual([game.houses[pos] for pos in (16, 18, 19)], [4, 4, 4])
        self.assertEqual(sorted(game.houses[pos] for pos in (1, 3)), [1, 2])
        self.assertEqual(game.bank_houses, 0)

        ai.take_action(game)

        self.assertIn(5, [game.houses[pos] for pos in (16, 18, 19)])
        self.assertEqual(game.bank_houses, 4)


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
