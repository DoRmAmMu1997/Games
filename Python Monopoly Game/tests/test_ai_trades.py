"""Regression coverage for AI trade-proposal sanity.

Guards against the AI proposing a useless 1-for-1 swap *within* the colour
group it is trying to monopolise (observed on the dark-blue group, whose only
two members are positions 37 and 39).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import ai
from game import MonopolyGame

# The dark-blue colour group -- exactly two members.
DARK_BLUE_LOW, DARK_BLUE_HIGH = 37, 39


def make_game() -> MonopolyGame:
    return MonopolyGame(
        [("Human", True), ("Knox", False), ("P3", False), ("P4", False)],
        seed=3,
    )


class AITradeProposalTests(unittest.TestCase):
    def test_ai_does_not_propose_a_same_group_swap(self) -> None:
        """The AI must never give away a dark-blue tile to get the other one.

        Such a swap leaves both players still owning one dark-blue tile each --
        nobody completes the monopoly, so the trade is pointless.
        """
        game = make_game()
        ai_player = game.players[1]
        human = game.players[0]
        # The AI owns one dark-blue tile; the human owns the other.
        game.owners[DARK_BLUE_LOW] = ai_player.index
        game.owners[DARK_BLUE_HIGH] = human.index
        ai_player.cash = 5000          # plenty to fund a genuine cash offer

        offer = ai.propose_trade(game, ai_player)

        if offer is not None:
            give_groups = {game.board[p].group for p in offer["give"]["props"]}
            get_groups = {game.board[p].group for p in offer["get"]["props"]}
            self.assertTrue(
                give_groups.isdisjoint(get_groups),
                f"AI offered a same-group swap: give={offer['give']['props']} "
                f"get={offer['get']['props']}",
            )

    def test_trade_swing_ignores_a_monopoly_being_traded_away(self) -> None:
        """`_trade_swing` must not credit a monopoly the AI is breaking up.

        For the dark-blue swap (give 37, get 39) the AI ends up owning only
        one dark-blue tile, so there is no monopoly bonus to award. Before the
        fix the score carried a phantom `+price * 2` bonus.
        """
        game = make_game()
        ai_player = game.players[1]
        human = game.players[0]
        game.owners[DARK_BLUE_LOW] = ai_player.index
        game.owners[DARK_BLUE_HIGH] = human.index

        swap = {
            "from": ai_player.index, "to": human.index,
            "give": {"props": [DARK_BLUE_LOW], "cash": 0, "jail": 0},
            "get": {"props": [DARK_BLUE_HIGH], "cash": 0, "jail": 0},
        }
        swing = ai._trade_swing(game, ai_player, swap)

        self.assertLess(
            swing, game.board[DARK_BLUE_HIGH].price,
            f"swing {swing} looks inflated by a phantom monopoly bonus",
        )


if __name__ == "__main__":
    unittest.main()
