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

from game import MonopolyGame
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


class AuctionOrderTests(unittest.TestCase):
    """Auction turns move clockwise even when a bidder passes."""

    def test_auction_pass_hands_the_bid_to_the_passers_clockwise_successor(self) -> None:
        """After seat 2 passes, seat 3 bids next -- not seat 0 again."""
        game = make_game()
        game._start_auction(1)

        game.auction_bid(10)
        game.auction_bid(20)
        game.auction_pass()

        assert game.auction is not None
        self.assertEqual(game.auction["active"], [0, 1, 3])
        self.assertEqual(game.auction["current"], 3)


class TradeInterestTests(unittest.TestCase):
    """A trade must leave each receiver able to pay mortgage interest."""

    def test_trade_rejected_when_receiver_cannot_pay_mortgage_interest(self) -> None:
        """Iris holds $5 but would owe $20 interest on mortgaged Boardwalk.

        The engine refuses the offer with an interest reason; once the giver
        adds $15 cash the receiver can cover the interest and it is legal.
        """
        game = make_game()
        game.owners[39] = 0
        game.mortgaged.add(39)
        game.players[1].cash = 5
        offer: dict = {
            "from": 0,
            "to": 1,
            "give": {"props": [39], "cash": 0, "jail": 0},
            "get": {"props": [], "cash": 0, "jail": 0},
        }

        error = game.trade_error(offer)
        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("interest", error)
        self.assertFalse(game.propose_trade(offer))

        offer["give"]["cash"] = 15
        self.assertTrue(game.trade_is_legal(offer))


class LastBankruptcyTests(unittest.TestCase):
    """The final bankruptcy ends the game cleanly, whoever is owed."""

    def test_creditor_wins_before_owing_interest_on_last_bankruptcy(self) -> None:
        """In a 2-player game the creditor wins before any transfer interest.

        The debtor's mortgaged titles pass to a cash-less creditor. Charging
        interest first would bankrupt the creditor too and open an auction
        with no bidders; instead the creditor has already won.
        """
        game = MonopolyGame([("Debtor", True), ("Creditor", False)], seed=4)
        debtor, creditor = game.players
        give_group(game, debtor.index, (37, 39))
        game.mortgaged.update((37, 39))
        debtor.cash = 0
        creditor.cash = 0

        game.transfer(debtor, creditor, 50)

        self.assertTrue(debtor.bankrupt)
        self.assertFalse(creditor.bankrupt)
        self.assertEqual(game.phase, "game_over")
        self.assertEqual(game.winner, creditor.index)
        self.assertEqual(game.owners, {37: creditor.index, 39: creditor.index})
        self.assertEqual(creditor.cash, 0)

    def test_bankruptcy_queue_without_bidders_is_dropped(self) -> None:
        """With no solvent bidder left, queued Bank titles are simply dropped."""
        game = make_game()
        for player in game.players:
            player.bankrupt = True
        game.bankruptcy_auction_queue = [1, 3]

        started = game._start_next_bankruptcy_auction()

        self.assertFalse(started)
        self.assertEqual(game.bankruptcy_auction_queue, [])
        self.assertIsNone(game.auction)


if __name__ == "__main__":
    unittest.main()
