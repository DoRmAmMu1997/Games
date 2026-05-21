"""Focused rules-engine coverage for the Monopoly foundation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from game import MonopolyGame
from settings import GO_SALARY


def make_game() -> MonopolyGame:
    return MonopolyGame(
        [("P1", True), ("P2", False), ("P3", False), ("P4", False)],
        seed=3,
    )


def rig_rolls(game: MonopolyGame, *rolls: int) -> None:
    pending = list(rolls)
    game.rng.randint = lambda _start, _end: pending.pop(0)


class EngineRegressionTests(unittest.TestCase):
    def test_turn_flow_pauses_to_buy_then_advances_after_end_turn(self) -> None:
        game = make_game()
        rig_rolls(game, 1, 2)

        game.roll_dice()
        self.assertEqual(game.pending_purchase, 3)
        self.assertEqual(game.awaiting, "buy_or_auction")

        game.buy_property()
        game.end_turn()
        self.assertEqual(game.owners[3], 0)
        self.assertEqual(game.current, 1)
        self.assertEqual(game.awaiting, "pre_roll")

    def test_rent_transfers_cash_on_owned_unmortgaged_property(self) -> None:
        game = make_game()
        game.current_player.position = 39
        game.owners[1] = 1
        rig_rolls(game, 1, 1)
        payer_before = game.players[0].cash
        owner_before = game.players[1].cash

        game.roll_dice()

        self.assertEqual(
            game.players[0].cash,
            payer_before + GO_SALARY - game.board[1].rent[0],
        )
        self.assertEqual(game.players[1].cash, owner_before + game.board[1].rent[0])

    def test_mortgage_and_unmortgage_round_trip_uses_interest(self) -> None:
        game = make_game()
        game.owners[5] = 0
        player = game.current_player
        cash_before = player.cash

        self.assertTrue(game.mortgage(5))
        self.assertIn(5, game.mortgaged)
        self.assertEqual(player.cash, cash_before + game.board[5].mortgage)

        self.assertTrue(game.unmortgage(5))
        self.assertNotIn(5, game.mortgaged)
        self.assertEqual(
            player.cash,
            cash_before + game.board[5].mortgage
            - int(round(game.board[5].mortgage * 1.1)),
        )

    def test_save_load_round_trip_keeps_property_state_and_ai_profile(self) -> None:
        game = MonopolyGame(
            [("P1", True), ("P2", False), ("P3", False), ("P4", False)],
            ai_profile="sharp",
        )
        game.owners[1] = 0
        game.houses[1] = 2
        game.owners[5] = 1
        game.mortgaged.add(5)

        restored = MonopolyGame.from_dict(game.to_dict())

        self.assertEqual(restored.ai_profile, "sharp")
        self.assertEqual(restored.owners, game.owners)
        self.assertEqual(restored.houses, game.houses)
        self.assertEqual(restored.mortgaged, game.mortgaged)

    def test_bankruptcy_win_check_names_last_solvent_player(self) -> None:
        game = make_game()
        for player in game.players[1:]:
            player.bankrupt = True

        game._check_for_winner()

        self.assertEqual(game.phase, "game_over")
        self.assertEqual(game.winner, 0)


if __name__ == "__main__":
    unittest.main()
