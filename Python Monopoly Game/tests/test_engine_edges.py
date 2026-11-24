"""Edge-case tests for Monopoly engine branches the rule suites do not reach.

These pin small but real behaviours: how net worth values mortgaged land and
buildings, the turn-limit finish, actions refused in the wrong state, paying
the jail fine, every reason a trade offer can be illegal, refused building
sales and mortgages, and jail cards travelling in both directions of a trade.
They also keep the coverage floor in CI from sitting right at the edge.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import game as game_module
from game import MonopolyGame, TradeOffer, TradeSide
from settings import JAIL_FINE

MEDITERRANEAN, BALTIC, ORIENTAL = 1, 3, 6


def make_game() -> MonopolyGame:
    """Create a deterministic two-player game: a human and one AI."""
    return MonopolyGame([("Ada", True), ("Bo", False)], seed=11)


def side(props: list[int] | None = None, cash: int = 0, jail: int = 0) -> TradeSide:
    """Build one side of a trade offer."""
    return {"props": props or [], "cash": cash, "jail": jail}


def offer(give: TradeSide, get: TradeSide, frm: int = 0, to: int = 1) -> TradeOffer:
    """Build a trade offer from player `frm` to player `to`."""
    return {"from": frm, "to": to, "give": give, "get": get}


class ValuationTests(unittest.TestCase):
    """Net worth and building counts value land the way the docstrings say."""

    def test_net_worth_counts_cash_land_mortgages_and_half_price_buildings(self) -> None:
        """Mortgaged land counts at its mortgage value, buildings at half cost."""
        game = make_game()
        player = game.players[0]
        for pos in (MEDITERRANEAN, BALTIC, ORIENTAL):
            game.owners[pos] = player.index
        game.houses[MEDITERRANEAN] = 2
        game.mortgaged.add(ORIENTAL)
        board = game.board
        expected = (
            player.cash
            + board[MEDITERRANEAN].price + 2 * board[MEDITERRANEAN].house_cost // 2
            + board[BALTIC].price
            + board[ORIENTAL].mortgage
        )
        self.assertEqual(game.net_worth(player), expected)

    def test_count_buildings_separates_hotels_from_houses(self) -> None:
        """Level 5 is a hotel; lower levels add up as houses."""
        game = make_game()
        player = game.players[0]
        game.owners[MEDITERRANEAN] = game.owners[BALTIC] = player.index
        game.houses[MEDITERRANEAN] = 5
        game.houses[BALTIC] = 3
        self.assertEqual(game.count_buildings(player), (3, 1))

    def test_count_in_group_counts_only_the_players_titles(self) -> None:
        """Owning one of the two browns counts as one."""
        game = make_game()
        game.owners[MEDITERRANEAN] = 0
        game.owners[BALTIC] = 1
        self.assertEqual(game.count_in_group(game.players[0], "brown"), 1)

    def test_bank_payment_of_nothing_changes_nothing(self) -> None:
        """A zero or negative bank payment is ignored."""
        game = make_game()
        player = game.players[0]
        before = player.cash
        game.gain(player, 0)
        game.gain(player, -50)
        self.assertEqual(player.cash, before)


class TurnFlowTests(unittest.TestCase):
    """The turn limit and actions taken in the wrong state."""

    def test_turn_limit_ends_the_game_with_the_richest_survivor(self) -> None:
        """Passing TURN_SAFETY_CAP ranks survivors on net worth."""
        game = make_game()
        game.players[1].cash += 5000
        game.turn_count = game_module.TURN_SAFETY_CAP
        game._start_turn()
        self.assertEqual(game.phase, "game_over")
        self.assertEqual(game.awaiting, "game_over")
        self.assertEqual(game.winner, 1)

    def test_end_turn_and_roll_are_refused_in_the_wrong_state(self) -> None:
        """end_turn needs post_roll; roll_dice needs pre_roll."""
        game = make_game()
        current = game.current
        game.end_turn()
        self.assertEqual(game.current, current)
        game.awaiting = "post_roll"
        dice = game.dice
        self.assertEqual(game.roll_dice(), dice)
        self.assertEqual(game.awaiting, "post_roll")

    def test_paying_the_jail_fine_frees_the_player(self) -> None:
        """A jailed player with the cash pays the fine before rolling."""
        game = make_game()
        player = game.current_player
        player.in_jail = True
        player.jail_turns = 1
        before = player.cash
        game.pay_jail_fine()
        self.assertFalse(player.in_jail)
        self.assertEqual(player.jail_turns, 0)
        self.assertEqual(player.cash, before - JAIL_FINE)


class TradeErrorTests(unittest.TestCase):
    """Every reason trade_error gives for an illegal offer."""

    def setUp(self) -> None:
        """Give each player one brown title and a jail card."""
        self.game = make_game()
        self.game.owners[MEDITERRANEAN] = 0
        self.game.owners[BALTIC] = 1

    def test_incomplete_offers_are_reported_not_raised(self) -> None:
        """A malformed offer gets a message and no consequence lines."""
        broken: TradeOffer = {"from": 0, "to": 9, "give": side(), "get": side()}
        self.assertEqual(self.game.trade_error(broken), "That trade offer is incomplete.")
        self.assertEqual(self.game.trade_consequence_lines(broken), [])

    def test_trading_with_yourself_or_a_bankrupt_player_is_refused(self) -> None:
        """The partner must be another solvent player."""
        self.assertEqual(self.game.trade_error(offer(side(), side(), 0, 0)),
                         "Choose a solvent trade partner.")
        self.game.players[1].bankrupt = True
        self.assertEqual(self.game.trade_error(offer(side(), side())),
                         "Choose a solvent trade partner.")

    def test_cash_jail_cards_and_titles_must_be_held(self) -> None:
        """Each side may only hand over what it actually has."""
        ada, bo = self.game.players
        message = self.game.trade_error(offer(side(cash=ada.cash + 1), side()))
        self.assertEqual(message, f"{ada.name} does not have that cash available.")
        message = self.game.trade_error(offer(side(), side(jail=1)))
        self.assertEqual(message, f"{bo.name} does not hold that many jail cards.")
        message = self.game.trade_error(offer(side(props=[BALTIC]), side()))
        self.assertEqual(message, f"{ada.name} does not own every selected title.")


class TradeExecutionTests(unittest.TestCase):
    """Jail cards travel in both directions of an accepted trade."""

    def test_jail_cards_move_from_the_receiver_back_to_the_proposer(self) -> None:
        """Cards the receiver gives keep their deck of origin."""
        game = make_game()
        ada, bo = game.players
        bo.jail_cards = 1
        bo.jail_card_decks = ["chest"]
        game._execute_trade(offer(side(cash=10), side(jail=1)))
        self.assertEqual((ada.jail_cards, bo.jail_cards), (1, 0))
        self.assertEqual(ada.jail_card_decks, ["chest"])

    def test_a_card_with_no_recorded_deck_defaults_to_chance(self) -> None:
        """An older save may hold a card count with no deck list."""
        game = make_game()
        ada, bo = game.players
        bo.jail_cards = 1
        bo.jail_card_decks = []
        game._execute_trade(offer(side(), side(jail=1)))
        self.assertEqual(ada.jail_card_decks, ["chance"])


class RefusedAssetActionTests(unittest.TestCase):
    """Selling houses and mortgaging refuse titles they cannot act on."""

    def test_sell_house_refuses_unowned_empty_and_unevenly_built_titles(self) -> None:
        """No owner, no building, or breaking even-building all refuse."""
        game = make_game()
        self.assertFalse(game.sell_house(MEDITERRANEAN))
        game.owners[MEDITERRANEAN] = game.owners[BALTIC] = 0
        self.assertFalse(game.sell_house(MEDITERRANEAN))
        game.houses[MEDITERRANEAN] = 1
        game.houses[BALTIC] = 2
        self.assertFalse(game.sell_house(MEDITERRANEAN))
        self.assertEqual(game.houses[MEDITERRANEAN], 1)

    def test_mortgage_refuses_unowned_built_and_already_mortgaged_titles(self) -> None:
        """Normal and forced mortgages both check the title first."""
        game = make_game()
        self.assertFalse(game.mortgage(MEDITERRANEAN))
        game.owners[MEDITERRANEAN] = game.owners[BALTIC] = 0
        game.houses[BALTIC] = 1
        self.assertFalse(game.mortgage(MEDITERRANEAN))
        self.assertFalse(game.mortgage(BALTIC, forced=True))
        game.mortgaged.add(MEDITERRANEAN)
        self.assertFalse(game.mortgage(MEDITERRANEAN, forced=True))


if __name__ == "__main__":
    unittest.main()
