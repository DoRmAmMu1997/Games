"""The engine's sound-event queue: which kinds each rule queues, in order.

The window plays a sound for each event the engine reports. These tests
drive the engine directly (no window) and read its queue with
``drain_events``; humans and the AI call the same engine methods, so the
same events reach the window whoever acted.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from test_engine_regressions import make_game, rig_rolls
from test_foundation_improvements import give_group
from test_raise_funds import pay_each_debt, rent_debt, stack_card

import ai
from game import EVENT_KINDS, MonopolyGame
from settings import JAIL_FINE, JAIL_POSITION, MAX_JAIL_TURNS

CHANCE_ADVANCE_TO_GO = 0
CHANCE_GO_TO_JAIL = 8
CHANCE_COLLECT_50 = 10
CHEST_COLLECT_200 = 3


def rolled(game: MonopolyGame, *dice: int) -> list[str]:
    """Rig the next dice, roll once and return the events that roll queued."""
    game.drain_events()
    rig_rolls(game, *dice)
    game.roll_dice()
    return game.drain_events()


def post_roll(game: MonopolyGame) -> MonopolyGame:
    """Put the current player in their post-roll phase with an empty queue."""
    game.awaiting = "post_roll"
    game.drain_events()
    return game


class EventQueueTests(unittest.TestCase):
    """The queue itself: drained once, never saved, and filled for every seat."""

    def test_drain_returns_events_oldest_first_and_empties_the_queue(self) -> None:
        """A drain hands back everything queued so far; the next one is empty."""
        game = make_game()
        self.assertEqual(rolled(game, 1, 2), ["roll"])
        game.decline_property()
        self.assertEqual(game.drain_events(), ["auction_start"])
        self.assertEqual(game.drain_events(), [])

    def test_events_are_not_saved_or_loaded(self) -> None:
        """to_dict leaves the queue out and from_dict ignores a stray "events" key."""
        game = make_game()
        rig_rolls(game, 1, 2)
        game.roll_dice()
        game.buy_property()
        data = game.to_dict()
        self.assertNotIn("events", data)
        data["events"] = ["roll", "buy"]
        loaded = MonopolyGame.from_dict(data)
        self.assertEqual(loaded.events, [])

    def test_every_queued_kind_is_a_known_kind(self) -> None:
        """A long all-AI game only ever queues kinds listed in EVENT_KINDS."""
        game = MonopolyGame([(f"AI {seat}", False) for seat in range(4)], seed=7)
        seen: set[str] = set()
        for _ in range(3000):
            if game.phase == "game_over":
                break
            ai.take_action(game)
            seen.update(game.drain_events())
        self.assertLessEqual(seen, set(EVENT_KINDS))
        self.assertLessEqual({"roll", "buy", "rent", "pass_go", "card_chance", "card_chest"}, seen)

    def test_ai_actions_queue_the_same_events(self) -> None:
        """An AI roll goes through roll_dice, so it queues a roll like a human's."""
        game = MonopolyGame([("Iris", False), ("Knox", False)], seed=2)
        ai.take_action(game)
        self.assertEqual(game.drain_events()[0], "roll")


class DiceEventTests(unittest.TestCase):
    """Rolls, doubles, three doubles and passing GO."""

    def test_every_roll_queues_a_roll_even_a_repeat(self) -> None:
        """Two identical rolls on different turns each queue their own roll."""
        game = make_game()
        self.assertEqual(rolled(game, 1, 2), ["roll"])
        game.decline_property()
        while game.awaiting == "auction":
            game.auction_pass()
        game.end_turn()
        self.assertEqual(rolled(game, 1, 2)[0], "roll")

    def test_doubles_follow_their_roll(self) -> None:
        """A double queues doubles right after its roll."""
        self.assertEqual(rolled(make_game(), 3, 3), ["roll", "doubles"])

    def test_third_double_sends_the_player_to_jail(self) -> None:
        """A third double queues the speeding event, then the trip to Jail."""
        game = make_game()
        game.doubles_count = 2
        self.assertEqual(rolled(game, 3, 3), ["roll", "doubles", "three_doubles_jail", "go_to_jail"])

    def test_passing_go_on_a_roll(self) -> None:
        """A roll that wraps past GO queues pass_go."""
        game = make_game()
        game.players[0].position = 38
        self.assertEqual(rolled(game, 1, 2), ["roll", "pass_go"])


class LandingEventTests(unittest.TestCase):
    """What a landing queues: buy, rent, tax, cards and Go To Jail."""

    def test_buying_the_landed_title(self) -> None:
        """Buy queues buy; a buyer who cannot afford it opens an auction instead."""
        game = make_game()
        rolled(game, 1, 2)
        game.buy_property()
        self.assertEqual(game.drain_events(), ["buy"])
        poor = make_game()
        poor.players[0].cash = 10
        rolled(poor, 1, 2)
        poor.buy_property()
        self.assertEqual(poor.drain_events(), ["auction_start"])

    def test_rent_paid_to_another_player(self) -> None:
        """Landing on another player's title queues rent; a mortgaged one queues nothing more."""
        game = make_game()
        give_group(game, 1, (3,))
        self.assertEqual(rolled(game, 1, 2), ["roll", "rent"])
        mortgaged = make_game()
        give_group(mortgaged, 1, (3,))
        mortgaged.mortgaged.add(3)
        self.assertEqual(rolled(mortgaged, 1, 2), ["roll"])

    def test_tax(self) -> None:
        """Income Tax queues tax."""
        self.assertEqual(rolled(make_game(), 1, 3), ["roll", "tax"])

    def test_each_deck_has_its_own_card_event(self) -> None:
        """A Chance space queues card_chance, a Community Chest space card_chest."""
        chance = make_game()
        chance.players[0].position = 4
        stack_card(chance, "chance", CHANCE_COLLECT_50)
        self.assertEqual(rolled(chance, 1, 2), ["roll", "card_chance"])
        chest = make_game()
        chest.players[0].position = 14
        stack_card(chest, "chest", CHEST_COLLECT_200)
        self.assertEqual(rolled(chest, 1, 2), ["roll", "card_chest"])

    def test_card_moves_queue_their_own_events(self) -> None:
        """Advance to GO pays the salary; Go to Jail sends the player there."""
        to_go = make_game()
        to_go.players[0].position = 4
        stack_card(to_go, "chance", CHANCE_ADVANCE_TO_GO)
        self.assertEqual(rolled(to_go, 1, 2), ["roll", "card_chance", "pass_go"])
        to_jail = make_game()
        to_jail.players[0].position = 4
        stack_card(to_jail, "chance", CHANCE_GO_TO_JAIL)
        self.assertEqual(rolled(to_jail, 1, 2), ["roll", "card_chance", "go_to_jail"])

    def test_go_to_jail_space(self) -> None:
        """The Go To Jail corner queues go_to_jail."""
        game = make_game()
        game.players[0].position = 27
        self.assertEqual(rolled(game, 1, 2), ["roll", "go_to_jail"])


class JailEventTests(unittest.TestCase):
    """Every way out of Jail queues leave_jail; staying in queues only the roll."""

    def jailed(self, turns: int = 0) -> MonopolyGame:
        """Return a game whose human sits in Jail after `turns` failed rolls."""
        game = make_game()
        human = game.players[0]
        human.position = JAIL_POSITION
        human.in_jail = True
        human.jail_turns = turns
        return game

    def test_doubles_free_the_player(self) -> None:
        """Rolling doubles in Jail queues the roll, the doubles and leave_jail."""
        self.assertEqual(rolled(self.jailed(), 2, 2)[:3], ["roll", "doubles", "leave_jail"])

    def test_a_failed_roll_stays_in(self) -> None:
        """A non-double roll in Jail queues only the roll."""
        self.assertEqual(rolled(self.jailed(), 1, 2), ["roll"])

    def test_the_forced_fine_frees_the_player(self) -> None:
        """The last failed roll charges the fine and queues leave_jail before the move."""
        self.assertEqual(rolled(self.jailed(MAX_JAIL_TURNS - 1), 1, 2)[:2], ["roll", "leave_jail"])

    def test_paying_or_using_a_card(self) -> None:
        """Paying the fine early, or spending a card, queues leave_jail."""
        paid = self.jailed()
        paid.pay_jail_fine()
        self.assertEqual(paid.drain_events(), ["leave_jail"])
        self.assertEqual(paid.players[0].cash, 1500 - JAIL_FINE)
        carded = self.jailed()
        carded.grant_jail_card(carded.players[0], "chance")
        carded.use_jail_card()
        self.assertEqual(carded.drain_events(), ["leave_jail"])


class PropertyEventTests(unittest.TestCase):
    """Building, selling, mortgaging and lifting mortgages."""

    def test_build_a_house_then_a_hotel(self) -> None:
        """A first building queues build_house; the fifth queues build_hotel."""
        game = post_roll(make_game())
        give_group(game, 0, (1, 3))
        game.build_house(1)
        self.assertEqual(game.drain_events(), ["build_house"])
        game.houses.update({1: 4, 3: 4})
        game.build_house(3)
        self.assertEqual(game.drain_events(), ["build_hotel"])

    def test_refused_actions_queue_nothing(self) -> None:
        """Building without the group, or lifting an unmortgaged title, is silent."""
        game = post_roll(make_game())
        give_group(game, 0, (1,))
        game.build_house(1)
        game.unmortgage(1)
        game.sell_house(1)
        self.assertEqual(game.drain_events(), [])

    def test_selling_a_building(self) -> None:
        """Selling a house queues sell_building, also an automatic sale breaking hotels in a shortage."""
        game = post_roll(make_game())
        give_group(game, 0, (1, 3))
        game.houses.update({1: 2, 3: 2})
        game.sell_house(1)
        self.assertEqual(game.drain_events(), ["sell_building"])
        game.houses.update({1: 5, 3: 5})
        game.bank_houses = 0
        game.sell_house(1, forced=True)
        self.assertEqual(game.drain_events(), ["sell_building"])

    def test_mortgage_and_lift(self) -> None:
        """Mortgaging queues mortgage and lifting it queues unmortgage."""
        game = post_roll(make_game())
        give_group(game, 0, (1,))
        game.mortgage(1)
        game.unmortgage(1)
        self.assertEqual(game.drain_events(), ["mortgage", "unmortgage"])


class AuctionAndTradeEventTests(unittest.TestCase):
    """Auctions open, take bids and end at the gavel; trades are offered and answered."""

    def test_an_auction_from_start_to_gavel(self) -> None:
        """Declining opens it, each legal bid queues a bid, and a winner queues auction_won."""
        game = make_game()
        rolled(game, 1, 2)
        game.decline_property()
        game.auction_bid(10)
        game.auction_bid(5)                      # not above the high bid: ignored
        while game.awaiting == "auction":
            game.auction_pass()
        self.assertEqual(game.drain_events(), ["auction_start", "auction_bid", "auction_won"])

    def test_an_auction_without_bids_ends_quietly(self) -> None:
        """Nobody bidding leaves no auction_won."""
        game = make_game()
        rolled(game, 1, 2)
        game.decline_property()
        while game.awaiting == "auction":
            game.auction_pass()
        self.assertEqual(game.drain_events(), ["auction_start"])

    def offer(self, game: MonopolyGame) -> None:
        """Have the human offer $50 to the second seat for its brown title."""
        give_group(game, 1, (1,))
        game.propose_trade({"from": 0, "to": 1, "give": {"props": [], "cash": 50, "jail": 0},
                            "get": {"props": [1], "cash": 0, "jail": 0}})

    def test_a_trade_offered_and_accepted_or_rejected(self) -> None:
        """Proposing queues trade_proposed; the answer queues accepted or rejected."""
        for accept, answer in ((True, "trade_accepted"), (False, "trade_rejected")):
            with self.subTest(accept=accept):
                game = post_roll(make_game())
                self.offer(game)
                game.respond_trade(accept)
                self.assertEqual(game.drain_events(), ["trade_proposed", answer])

    def test_an_illegal_offer_is_silent(self) -> None:
        """A refused proposal queues nothing."""
        game = post_roll(make_game())
        game.propose_trade({"from": 0, "to": 1, "give": {"props": [], "cash": 99999, "jail": 0},
                            "get": {"props": [], "cash": 0, "jail": 0}})
        self.assertEqual(game.drain_events(), [])


class DebtAndEndingEventTests(unittest.TestCase):
    """Raising funds, bankruptcy and the end of the game."""

    def test_raise_funds_is_announced_once_on_the_way_in(self) -> None:
        """A short human's rent queues rent, then raise_funds; extra debts add no repeat."""
        self.assertEqual(rent_debt().drain_events(), ["roll", "rent", "raise_funds"])
        events = pay_each_debt().drain_events()
        self.assertEqual(events.count("raise_funds"), 1)

    def test_conceding_queues_bankrupt(self) -> None:
        """Declaring bankruptcy while raising funds queues bankrupt."""
        game = rent_debt()
        game.drain_events()
        game.declare_bankruptcy()
        self.assertEqual(game.drain_events()[0], "bankrupt")

    def test_an_ai_that_cannot_pay_goes_bankrupt_and_the_game_ends(self) -> None:
        """The last opponent going broke queues rent, bankrupt and game_over once."""
        game = MonopolyGame([("P1", True), ("Iris", False)], seed=3)
        give_group(game, 0, (3,))
        game.current = 1
        game.players[1].cash = 0
        self.assertEqual(rolled(game, 1, 2), ["roll", "rent", "bankrupt", "game_over"])
        self.assertEqual(game.winner, 0)

    def test_the_turn_cap_ends_the_game(self) -> None:
        """A game forced to finish at the turn cap queues game_over."""
        game = make_game()
        game._force_finish()
        self.assertEqual(game.drain_events(), ["game_over"])


if __name__ == "__main__":
    unittest.main()
