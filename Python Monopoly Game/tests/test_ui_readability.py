"""Pure-data checks for Monopoly UI readability helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import ui
from game import MonopolyGame


def make_game() -> MonopolyGame:
    """Create a deterministic four-player game with one human."""
    return MonopolyGame(
        [("Human", True), ("Iris", False), ("Knox", False), ("Mira", False)],
        seed=5,
    )


class ReadabilityHelperTests(unittest.TestCase):
    """Text helpers the panels rely on to explain game state."""

    def test_property_detail_lines_describe_owner_rent_and_mortgage_state(self) -> None:
        """Hovering a title lists its owner, rent, and mortgage status."""
        game = make_game()
        game.owners[1] = 1
        game.mortgaged.add(1)

        lines = ui.property_detail_lines(game, 1)

        self.assertIn("Owner: Iris", lines)
        self.assertIn("Mortgaged", lines)
        self.assertTrue(any(line.startswith("Rent:") for line in lines))

    def test_trade_error_explains_why_developed_group_cannot_move(self) -> None:
        """Illegal trades come back with a human-readable blocker reason."""
        game = make_game()
        game.owners[1] = 0
        game.owners[3] = 0
        game.houses[1] = 1
        offer = {
            "from": 0,
            "to": 1,
            "give": {"props": [3], "cash": 0, "jail": 0},
            "get": {"props": [], "cash": 0, "jail": 0},
        }

        self.assertEqual(
            game.trade_error(offer),
            "Sell buildings in that color group before trading it.",
        )


if __name__ == "__main__":
    unittest.main()
