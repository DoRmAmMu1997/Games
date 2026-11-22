"""Headless rendering tests for the HUD, panels and overlays in ``ui.py``.

These tests draw onto off-screen surfaces under SDL's dummy driver. They
check layout with real font measurements and generous margins (never a
one-pixel fit), and they compare chosen colours directly instead of sampling
antialiased edges, so they hold with other fonts and on other platforms.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import pygame

import ui


class UiTestCase(unittest.TestCase):
    """Shared setup: pygame started and a display mode set for ``convert``."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start pygame once for every test in the class."""

        pygame.init()
        pygame.display.set_mode((1, 1))


class PanelTests(UiTestCase):
    """Panels and buttons keep their gloss inside the rounded shape."""

    def test_panel_corner_has_no_gloss_patch(self) -> None:
        """The panel art is transparent outside its rounded corners."""

        panel = ui.panel_surface((232, 190), (11, 20, 44, 205), (88, 132, 206), 28)
        for corner in ((1, 1), (230, 1), (1, 188), (230, 188)):
            with self.subTest(corner=corner):
                self.assertEqual(panel.get_at(corner).a, 0)
        self.assertGreater(panel.get_at((116, 95)).a, 150)

    def test_button_shine_is_translucent(self) -> None:
        """The shine bar blends at alpha 42 instead of drawing solid white."""

        class Assets:
            """Minimal stand-in exposing the one font a button needs."""

            ui_font = pygame.font.Font(None, 34)

        target = pygame.Surface((300, 120))
        target.fill((0, 0, 0))
        button = ui.Button(pygame.Rect(40, 30, 220, 60), "Go")
        button.draw(target, Assets(), (-1, -1))
        shine = target.get_at((button.rect.centerx - 60, button.rect.y + 10))
        self.assertLess(max(shine.r, shine.g, shine.b), 160)


if __name__ == "__main__":
    unittest.main()
