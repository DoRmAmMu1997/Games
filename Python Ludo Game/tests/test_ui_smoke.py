"""Headless pygame wiring checks for the Ludo app."""

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

from main import LudoApp


class UiSmokeTests(unittest.TestCase):
    """Small pygame checks that catch broken imports and screen wiring."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once for this test class."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame resources after the smoke tests."""

        pygame.quit()

    def test_setup_buttons_expose_player_and_rule_controls(self) -> None:
        """The setup screen should expose the expected controls."""

        app = LudoApp()
        try:
            keys = {button.key for button in app.setup_buttons()}
            self.assertIn("total_players_next", keys)
            self.assertIn("human_count_next", keys)
            self.assertIn("ai_profile_next", keys)
            self.assertIn("toggle_blockades", keys)
            self.assertIn("start", keys)
        finally:
            app.running = False

    def test_autotest_frames_can_render_without_crashing(self) -> None:
        """The app should draw a few headless frames successfully."""

        app = LudoApp()
        try:
            app.run(max_frames=3)
        finally:
            app.running = False


if __name__ == "__main__":
    unittest.main()
