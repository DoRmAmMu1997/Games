"""UI wiring checks that keep new Monopoly controls reachable."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import pygame

import ui
from game import MonopolyGame
from main import MonopolyApp


class UiWiringTests(unittest.TestCase):
    """Buttons and app plumbing stay reachable as the UI evolves."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once for the headless UI checks."""
        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the UI checks finish."""
        pygame.quit()

    def test_setup_buttons_include_ai_profile_stepper(self) -> None:
        """The setup screen exposes the AI-difficulty stepper."""
        keys = {button.key for button in ui.setup_buttons(has_save=False)}

        self.assertIn("ai_profile_prev", keys)
        self.assertIn("ai_profile_next", keys)

    def test_human_with_buildings_gets_sell_button_in_action_bar(self) -> None:
        """Owning a developed street unlocks the Sell Buildings button."""
        app = MonopolyApp()
        game = MonopolyGame(
            [("Human", True), ("Iris", False), ("Knox", False), ("Mira", False)],
            seed=9,
        )
        game.owners[1] = 0
        game.owners[3] = 0
        game.houses[1] = 1
        app.start_game(game)

        keys = {button.key for button in app._playing_buttons()}

        self.assertIn("sell", keys)

    def test_asset_manager_opens_and_dispatches_engine_actions(self) -> None:
        """The Assets dialog opens, builds via the engine, and closes cleanly."""
        app = MonopolyApp()
        game = MonopolyGame(
            [("Human", True), ("Iris", False), ("Knox", False), ("Mira", False)],
            seed=10,
        )
        game.owners[1] = 0
        game.owners[3] = 0
        app.start_game(game)

        self.assertIn("assets", {button.key for button in app._playing_buttons()})

        app._on_button("assets")
        buttons = {button.key: button for button in app._playing_buttons()}

        self.assertEqual(app.mode, "assets")
        self.assertEqual(app.asset_position, 1)
        self.assertTrue(buttons["asset_build"].enabled)
        app._on_button("asset_build")
        self.assertEqual(game.houses[1], 1)

        app._on_button("asset_close")
        self.assertEqual(app.mode, "normal")


if __name__ == "__main__":
    unittest.main()
