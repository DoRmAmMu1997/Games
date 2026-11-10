"""Raise funds: a short human sells and mortgages before paying a debt.

A human who owes more cash than they hold, but could cover it by selling
buildings and mortgaging titles, is not stripped automatically. The debt
is queued and the game waits in `awaiting == "raise_funds"` until the
debtor pays (`pay_debts`) or concedes (`declare_bankruptcy`). These tests
drive every kind of debt -- rent, tax, a card, both card loops and the
forced jail fine -- through both endings.
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

import ai
from game import MonopolyGame
from settings import JAIL_POSITION, MAX_JAIL_TURNS, STARTING_CASH

HOSPITAL_FEES = 12      # Community Chest: pay $100
BIRTHDAY = 11           # Community Chest: collect $10 from each player
CHAIRMAN = 13           # Chance: pay each player $50


def stack_card(game: MonopolyGame, deck_name: str, index: int) -> None:
    """Put card `index` of a deck on top of its pile so the next draw takes it."""
    deck = game._deck(deck_name)
    deck.order.remove(index)
    deck.order.insert(0, index)


def rent_debt() -> MonopolyGame:
    """The human lands on Iris's undeveloped dark-blue monopoly: $100 rent.

    They hold $40 plus two brown titles that mortgage for $30 each, so
    selling up covers the debt exactly.
    """
    game = make_game()
    give_group(game, 1, (37, 39))
    give_group(game, 0, (1, 3))
    game.players[0].cash = 40
    game.players[0].position = 36
    rig_rolls(game, 1, 2)
    game.roll_dice()
    return game


def tax_debt() -> MonopolyGame:
    """The human lands on Income Tax ($200) holding $100 and two pink titles."""
    game = make_game()
    give_group(game, 0, (11, 13))
    game.players[0].cash = 100
    rig_rolls(game, 1, 3)
    game.roll_dice()
    return game


def card_debt() -> MonopolyGame:
    """The human draws Hospital Fees ($100) holding $50 and two brown titles."""
    game = make_game()
    give_group(game, 0, (1, 3))
    game.players[0].cash = 50
    game.players[0].position = 14
    stack_card(game, "chest", HOSPITAL_FEES)
    rig_rolls(game, 1, 2)
    game.roll_dice()
    return game


def pay_each_debt() -> MonopolyGame:
    """The human must pay each player $50 holding $60 and two pink titles.

    The first $50 is paid in cash; the other two payments are queued.
    """
    game = make_game()
    give_group(game, 0, (11, 13))
    game.players[0].cash = 60
    game.players[0].position = 4
    stack_card(game, "chance", CHAIRMAN)
    rig_rolls(game, 1, 2)
    game.roll_dice()
    return game


def collect_each_debt() -> MonopolyGame:
    """Knox (AI) has a birthday; the human, NOT the current player, owes $10.

    The human holds $5 and a brown title, so they must mortgage it during
    Knox's turn before Knox's turn can continue.
    """
    game = make_game()
    give_group(game, 0, (1,))
    game.players[0].cash = 5
    game.current = 2
    game.players[2].position = 14
    stack_card(game, "chest", BIRTHDAY)
    rig_rolls(game, 1, 2)
    game.roll_dice()
    return game


def jail_fine_debt() -> MonopolyGame:
    """The human fails a third jail roll with $20 and a brown title for the $50 fine."""
    game = make_game()
    human = game.players[0]
    give_group(game, 0, (1,))
    human.cash = 20
    human.position = JAIL_POSITION
    human.in_jail = True
    human.jail_turns = MAX_JAIL_TURNS - 1
    rig_rolls(game, 1, 2)
    game.roll_dice()
    return game


class RaiseFundsDebtTests(unittest.TestCase):
    """Every human debt can be raised for and paid, or conceded."""

    def assert_raising(self, game: MonopolyGame, debtor: int, owed: list[tuple[int | None, int]]) -> None:
        """Check the game waits for `debtor` to raise funds for exactly `owed`."""
        self.assertEqual(game.awaiting, "raise_funds")
        self.assertEqual(game.actor(), debtor)
        self.assertEqual([(d["payee"], d["amount"]) for d in game.debts], owed)
        self.assertTrue(all(d["payer"] == debtor for d in game.debts))

    def test_rent_debt_is_raised_then_paid_or_declared(self) -> None:
        """Rent: mortgage both titles and pay, or concede everything to the owner."""
        with self.subTest("paid"):
            game = rent_debt()
            self.assert_raising(game, 0, [(1, 100)])
            self.assertTrue(game.mortgage(1))
            self.assertTrue(game.mortgage(3))
            self.assertTrue(game.pay_debts())
            self.assertEqual(game.players[0].cash, 0)
            self.assertEqual(game.players[1].cash, STARTING_CASH + 100)
            self.assertEqual(game.awaiting, "post_roll")
            self.assertEqual(game.debts, [])
        with self.subTest("declared"):
            game = rent_debt()
            game.declare_bankruptcy()
            self.assertTrue(game.players[0].bankrupt)
            self.assertEqual(game.players[1].cash, STARTING_CASH + 40)
            self.assertEqual((game.owners[1], game.owners[3]), (1, 1))
            self.assertNotIn(1, game.mortgaged)
            self.assertEqual(game.awaiting, "post_roll")
            self.assertEqual(game.debts, [])

    def test_tax_debt_is_raised_then_paid_or_declared(self) -> None:
        """Tax: pay the Bank after mortgaging, or concede and the Bank auctions the titles."""
        with self.subTest("paid"):
            game = tax_debt()
            self.assert_raising(game, 0, [(None, 200)])
            game.mortgage(11)
            game.mortgage(13)
            self.assertTrue(game.pay_debts())
            self.assertEqual(game.players[0].cash, 40)
            self.assertEqual(game.awaiting, "post_roll")
        with self.subTest("declared"):
            game = tax_debt()
            game.declare_bankruptcy()
            self.assertTrue(game.players[0].bankrupt)
            self.assertEqual(game.awaiting, "auction")
            assert game.auction is not None
            self.assertEqual(game.auction["position"], 11)
            self.assertEqual(game.bankruptcy_auction_queue, [13])

    def test_card_debt_is_raised_then_paid_or_declared(self) -> None:
        """A "pay $100" card: raise and pay, or concede to the Bank."""
        with self.subTest("paid"):
            game = card_debt()
            self.assert_raising(game, 0, [(None, 100)])
            game.mortgage(1)
            game.mortgage(3)
            self.assertTrue(game.pay_debts())
            self.assertEqual(game.players[0].cash, 10)
            self.assertEqual(game.awaiting, "post_roll")
        with self.subTest("declared"):
            game = card_debt()
            game.declare_bankruptcy()
            self.assertTrue(game.players[0].bankrupt)
            self.assertEqual(game.awaiting, "auction")

    def test_pay_each_debts_are_queued_then_paid_or_declared(self) -> None:
        """Pay-each: unpaid transfers queue in order; conceding pays the head payee."""
        with self.subTest("paid"):
            game = pay_each_debt()
            self.assert_raising(game, 0, [(2, 50), (3, 50)])
            self.assertEqual(game.players[1].cash, STARTING_CASH + 50)
            game.mortgage(11)
            game.mortgage(13)
            self.assertTrue(game.pay_debts())
            self.assertEqual(game.players[0].cash, 50)
            self.assertEqual(game.players[2].cash, STARTING_CASH + 50)
            self.assertEqual(game.players[3].cash, STARTING_CASH + 50)
            self.assertEqual(game.awaiting, "post_roll")
        with self.subTest("declared"):
            game = pay_each_debt()
            game.declare_bankruptcy()
            self.assertTrue(game.players[0].bankrupt)
            self.assertEqual(game.players[2].cash, STARTING_CASH + 10)
            self.assertEqual((game.owners[11], game.owners[13]), (2, 2))
            self.assertEqual(game.players[3].cash, STARTING_CASH)
            self.assertEqual(game.debts, [])
            self.assertEqual(game.awaiting, "post_roll")

    def test_collect_each_debt_from_a_non_current_human(self) -> None:
        """A birthday debt makes the non-current human the actor until it is settled."""
        with self.subTest("paid"):
            game = collect_each_debt()
            self.assert_raising(game, 0, [(2, 10)])
            self.assertEqual(game.current, 2)
            self.assertTrue(game.mortgage(1))
            self.assertTrue(game.pay_debts())
            self.assertEqual(game.players[0].cash, 25)
            self.assertEqual(game.players[2].cash, STARTING_CASH + 30)
            self.assertEqual(game.awaiting, "post_roll")
            self.assertEqual(game.actor(), 2)
        with self.subTest("declared"):
            game = collect_each_debt()
            game.declare_bankruptcy()
            self.assertTrue(game.players[0].bankrupt)
            self.assertEqual(game.owners[1], 2)
            self.assertEqual(game.players[2].cash, STARTING_CASH + 20 + 5)
            self.assertEqual(game.awaiting, "post_roll")
            self.assertEqual(game.actor(), 2)

    def test_jail_fine_debt_moves_only_after_it_is_paid(self) -> None:
        """The freed player steps forward once the fine is paid, never after conceding."""
        with self.subTest("paid"):
            game = jail_fine_debt()
            self.assert_raising(game, 0, [(None, 50)])
            human = game.players[0]
            self.assertEqual(human.position, JAIL_POSITION)
            self.assertFalse(human.in_jail)
            game.mortgage(1)
            self.assertTrue(game.pay_debts())
            self.assertEqual(human.position, JAIL_POSITION + 3)
            self.assertEqual(game.awaiting, "buy_or_auction")
        with self.subTest("declared"):
            game = jail_fine_debt()
            game.declare_bankruptcy()
            self.assertTrue(game.players[0].bankrupt)
            self.assertEqual(game.players[0].position, JAIL_POSITION)
            self.assertEqual(game.awaiting, "auction")
            for _ in range(3):
                game.auction_pass()
            self.assertEqual(game.awaiting, "post_roll")
            self.assertEqual(game.players[0].position, JAIL_POSITION)


class RaiseFundsRuleTests(unittest.TestCase):
    """Who enters raise funds, what they may do there, and what is never saved."""

    def test_hopeless_human_is_bankrupted_automatically(self) -> None:
        """A human who could not cover the debt even by selling up is not asked."""
        game = make_game()
        give_group(game, 1, (37, 39))
        game.players[0].cash = 0
        game.players[0].position = 36
        rig_rolls(game, 1, 2)

        game.roll_dice()

        self.assertTrue(game.players[0].bankrupt)
        self.assertEqual(game.debts, [])
        self.assertEqual(game.awaiting, "post_roll")

    def test_debt_is_never_saved(self) -> None:
        """A save taken while raising funds holds no debt and a resumable state."""
        game = rent_debt()
        payload = game.to_dict()

        self.assertNotIn("debts", payload)
        self.assertIn(payload["awaiting"], ("pre_roll", "post_roll"))
        self.assertEqual(MonopolyGame.from_dict(payload).debts, [])

    def test_debtor_may_sell_and_mortgage_but_not_build_while_raising_funds(self) -> None:
        """Only selling and mortgaging are open, and a hotel may break in a shortage."""
        game = rent_debt()
        human = game.players[0]
        give_group(game, 0, (16, 18, 19))
        game.houses.update({16: 5, 18: 5, 19: 5})
        game.bank_houses = 0
        actions = game.asset_actions_for(human, 16)

        self.assertTrue(actions["sell"]["allowed"])
        self.assertFalse(actions["build"]["allowed"])
        self.assertTrue(game.asset_actions_for(human, 1)["mortgage"]["allowed"])
        self.assertTrue(game.sell_house(16))
        self.assertEqual(game.houses[16], 0)
        self.assertEqual(human.cash, 40 + 5 * 50)
        self.assertFalse(game.unmortgage(1))

    def test_debt_queued_during_an_auction_waits_for_it_to_finish(self) -> None:
        """A running auction completes first, then play resumes into raise funds."""
        game = make_game()
        give_group(game, 0, (1, 3))
        game.players[0].cash = 50
        game._start_auction(5)

        game.charge(game.players[0], 100)
        self.assertEqual(game.awaiting, "auction")
        self.assertEqual(len(game.debts), 1)
        for _ in range(4):
            game.auction_pass()

        self.assertEqual(game.awaiting, "raise_funds")
        self.assertEqual(game.actor(), 0)

    def test_pay_debts_settles_a_creditors_debt_in_the_same_call(self) -> None:
        """Paying the head debt can fund the next payer's debt, all in one call."""
        game = MonopolyGame([("Ann", True), ("Bob", True), ("Iris", False)], seed=2)
        ann, bob = game.players[0], game.players[1]
        ann.cash, bob.cash = 100, 0
        game.debts = [{"payer": 0, "payee": 1, "amount": 100},
                      {"payer": 1, "payee": None, "amount": 20}]
        game.awaiting = "raise_funds"

        self.assertTrue(game.pay_debts())

        self.assertEqual((ann.cash, bob.cash), (0, 80))
        self.assertEqual(game.debts, [])

    def test_nobody_owes_a_bankrupt_player(self) -> None:
        """A transfer to a player who has already gone bankrupt is simply dropped."""
        game = make_game()
        game.players[1].bankrupt = True
        game.players[1].cash = 0
        game.players[0].cash = 10

        game.transfer(game.players[0], game.players[1], 100)

        self.assertEqual(game.players[0].cash, 10)
        self.assertEqual(game.players[1].cash, 0)
        self.assertEqual(game.debts, [])

    def test_ai_never_stalls_in_raise_funds(self) -> None:
        """If an AI ever is the debtor, it raises what it can, then pays or concedes."""
        for cash, bankrupt in ((50, False), (0, True)):
            with self.subTest(cash=cash):
                game = make_game()
                iris = game.players[1]
                if cash:
                    give_group(game, 1, (1, 3))
                iris.cash = cash
                game.debts = [{"payer": 1, "payee": None, "amount": 100}]
                game.awaiting = "raise_funds"

                ai.take_action(game)

                self.assertNotEqual(game.awaiting, "raise_funds")
                self.assertEqual(iris.bankrupt, bankrupt)


if __name__ == "__main__":
    unittest.main()
