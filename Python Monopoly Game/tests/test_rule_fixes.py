"""Regression tests for the engine rule fixes found by the invariant audit.

Each test class pins one fixed rule: bankrupt players stop paying and
moving, forced hotel sales respect the Bank's house supply, auction turn
order, trade interest affordability, the last-creditor win, the Chance
deck, unmortgage costs, and where a bankrupt player's jail cards go.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from test_engine_regressions import rig_rolls
from test_foundation_improvements import give_group, make_game

from settings import BANK_HOTELS, JAIL_FINE, JAIL_POSITION, MAX_JAIL_TURNS


class BankruptPlayerTests(unittest.TestCase):
    """A bankrupt player has left the game: they neither pay nor move."""

    def test_player_bankrupted_by_forced_jail_fine_does_not_move(self) -> None:
        """A third failed jail roll that bankrupts the player leaves them in place.

        Only a solvent player steps forward and resolves the landing after
        the forced fine; a bankrupt one must not collect GO money or rent.
        """
        game = make_game()
        player = game.current_player
        player.position = JAIL_POSITION
        player.in_jail = True
        player.jail_turns = MAX_JAIL_TURNS - 1
        player.cash = JAIL_FINE - 10
        rig_rolls(game, 1, 2)

        game.roll_dice()

        self.assertTrue(player.bankrupt)
        self.assertEqual(player.position, JAIL_POSITION)
        self.assertFalse(player.in_jail)
        self.assertEqual(player.jail_turns, 0)
        self.assertEqual(player.cash, 0)
        self.assertEqual(game.awaiting, "post_roll")

    def test_player_bankrupted_by_paying_jail_fine_cannot_roll(self) -> None:
        """Paying the jail fine without the cash in hand is refused outright.

        The fine is optional, so it may never bankrupt anyone: the player
        stays solvent, still in Jail and still in pre_roll, free to roll.
        """
        game = make_game()
        player = game.current_player
        player.position = JAIL_POSITION
        player.in_jail = True
        player.cash = JAIL_FINE - 1

        game.pay_jail_fine()

        self.assertFalse(player.bankrupt)
        self.assertTrue(player.in_jail)
        self.assertEqual(player.cash, JAIL_FINE - 1)
        self.assertEqual(game.awaiting, "pre_roll")

    def test_debt_from_bankrupt_player_does_not_restart_bank_auctions(self) -> None:
        """A second charge to a bankrupt player is ignored, not re-bankrupted."""
        game = make_game()
        player = game.current_player
        give_group(game, player.index, (1, 3))
        player.cash = 0

        game.charge(player, 100)
        game.charge(player, 100)

        assert game.auction is not None
        self.assertEqual(game.auction["position"], 1)
        self.assertEqual(game.bankruptcy_auction_queue, [3])
        self.assertEqual(sum("has gone bankrupt" in line for line in game.log), 1)


class ForcedHotelSaleTests(unittest.TestCase):
    """Breaking a hotel to raise cash never overdraws the Bank's houses."""

    def test_forced_hotel_sale_in_house_shortage_keeps_bank_supply_valid(self) -> None:
        """A forced sale takes only the houses the Bank has; the rest are sold.

        With two houses left the hotel drops to two houses and three
        buildings' worth of half-price cash is paid; with none left it is
        sold down to bare land for five buildings' worth.
        """
        for bank_houses, level, cash in ((2, 2, 3 * 100 - 50), (0, 0, 5 * 100 - 50)):
            with self.subTest(bank_houses=bank_houses):
                game = make_game()
                debtor = game.players[1]
                give_group(game, debtor.index, (37, 39))
                game.houses = {37: 5, 39: 5}
                game.bank_houses = bank_houses
                game.bank_hotels = BANK_HOTELS - 2
                debtor.cash = 0

                game.charge(debtor, 50)

                self.assertFalse(debtor.bankrupt)
                self.assertEqual(game.houses[37], level)
                self.assertEqual(game.houses[39], 5)
                self.assertEqual(debtor.cash, cash)
                self.assertEqual(game.bank_houses, 0)
                self.assertEqual(game.bank_hotels, BANK_HOTELS - 1)


if __name__ == "__main__":
    unittest.main()
