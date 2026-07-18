"""Regression tests for the first Monopoly improvement pass."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import ai
from game import MonopolyGame


def make_game(seed: int = 7) -> MonopolyGame:
    """Create a deterministic four-player game with one human."""
    return MonopolyGame(
        [("Human", True), ("Iris", False), ("Knox", False), ("Mira", False)],
        seed=seed,
    )


def give_group(game: MonopolyGame, player_index: int, positions: tuple[int, ...]) -> None:
    """Hand a set of board positions to one player directly."""
    for position in positions:
        game.owners[position] = player_index


class OfficialRuleFoundationTests(unittest.TestCase):
    """Classic-rule fixes: asset actions, bankruptcy auctions, trade interest."""

    def test_asset_actions_explain_what_one_owned_title_can_do(self) -> None:
        """The engine reports allowed actions and blocker reasons per title."""
        game = make_game()
        player = game.current_player
        give_group(game, player.index, (1, 3))

        actions = game.asset_actions_for(player, 1)

        self.assertTrue(actions["build"]["allowed"])
        self.assertTrue(actions["mortgage"]["allowed"])
        self.assertFalse(actions["sell"]["allowed"])
        self.assertIn("No building", actions["sell"]["reason"])
        self.assertFalse(actions["unmortgage"]["allowed"])
        self.assertIn("not mortgaged", actions["unmortgage"]["reason"].lower())

    def test_sell_building_action_respects_even_selling(self) -> None:
        """Buildings must come down evenly across a colour group."""
        game = make_game()
        give_group(game, 0, (1, 3))
        game.houses = {1: 2, 3: 1}

        self.assertTrue(game.can_sell_building(game.current_player, 1))
        self.assertFalse(game.can_sell_building(game.current_player, 3))

        self.assertTrue(game.sell_house(1))
        self.assertEqual(game.houses[1], 1)

    def test_bankruptcy_to_bank_starts_auction_for_released_assets(self) -> None:
        """Titles released by a bank bankruptcy go straight to auction."""
        game = make_game()
        player = game.current_player
        give_group(game, player.index, (1, 3))
        player.cash = 0

        game.charge(player, 100)

        self.assertTrue(player.bankrupt)
        self.assertEqual(game.awaiting, "auction")
        assert game.auction is not None
        self.assertEqual(game.auction["position"], 1)
        self.assertEqual(game.auction["context"], "bankruptcy")
        self.assertIn("Bank bankruptcy auction", game.auction_context_message())
        self.assertEqual(game.bankruptcy_auction_queue, [3])
        self.assertNotIn(1, game.owners)

    def test_bankruptcy_auctions_continue_until_every_bank_asset_is_offered(self) -> None:
        """A queue re-auctions each released title one after another."""
        game = make_game()
        player = game.current_player
        give_group(game, player.index, (1, 3))
        player.cash = 0

        game.charge(player, 100)
        for _ in range(4):
            game.auction_pass()

        self.assertEqual(game.awaiting, "auction")
        assert game.auction is not None
        self.assertEqual(game.auction["position"], 3)

    def test_mortgaged_trade_property_charges_transfer_interest_immediately(self) -> None:
        """Receiving a mortgaged title costs the classic 10% transfer interest."""
        game = make_game()
        game.owners[39] = 0
        game.mortgaged.add(39)
        receiver = game.players[1]
        before = receiver.cash
        offer = {
            "from": 0,
            "to": 1,
            "give": {"props": [39], "cash": 0, "jail": 0},
            "get": {"props": [], "cash": 0, "jail": 0},
        }

        self.assertTrue(game.propose_trade(offer))
        game.respond_trade(True)

        self.assertEqual(game.owners[39], receiver.index)
        self.assertEqual(receiver.cash, before - game.board[39].mortgage // 10)
        self.assertIn(39, game.mortgaged)

    def test_trade_consequence_summary_names_mortgage_interest_before_acceptance(self) -> None:
        """The trade preview warns the receiver about interest due."""
        game = make_game()
        game.owners[39] = 0
        game.mortgaged.add(39)
        offer = {
            "from": 0,
            "to": 1,
            "give": {"props": [39], "cash": 0, "jail": 0},
            "get": {"props": [], "cash": 0, "jail": 0},
        }

        lines = game.trade_consequence_lines(offer)

        self.assertIn(
            f"Iris owes ${game.board[39].mortgage // 10} mortgage transfer interest.",
            lines,
        )

    def test_save_payload_is_versioned_and_unknown_versions_are_rejected(self) -> None:
        """Saves carry a version number and future versions refuse to load."""
        game = make_game()
        payload = game.to_dict()
        invalid = copy.deepcopy(payload)
        invalid["save_version"] = payload["save_version"] + 99

        self.assertGreaterEqual(payload["save_version"], 2)
        with self.assertRaises(ValueError):
            MonopolyGame.from_dict(invalid)


class AiGrowthTests(unittest.TestCase):
    """AI profiles and the seeded simulation harness."""

    def test_named_ai_profiles_feed_property_valuation(self) -> None:
        """Profile value scales change how much the AI thinks a title is worth."""
        game = make_game()
        standard = ai.property_value(game, game.players[1], 1, ai.AI_PROFILES["standard"])
        cautious = ai.property_value(game, game.players[1], 1, ai.AI_PROFILES["cautious"])

        self.assertIn("standard", ai.AI_PROFILES)
        self.assertGreater(standard, cautious)

    def test_seeded_ai_simulation_reports_strategy_metrics(self) -> None:
        """A headless all-AI game finishes and reports tuning metrics."""
        from simulation import run_ai_game

        metrics = run_ai_game(seed=11, max_actions=1000, profile_key="standard")

        self.assertEqual(metrics["seed"], 11)
        self.assertEqual(metrics["profile"], "standard")
        self.assertGreater(metrics["turns"], 0)
        self.assertIn("winner", metrics)
        self.assertIn("auction_count", metrics)
        self.assertIn("trade_count", metrics)


if __name__ == "__main__":
    unittest.main()
