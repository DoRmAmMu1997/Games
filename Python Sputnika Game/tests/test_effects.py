"""Headless tests for the floating popups in ``effects.py``."""

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

import effects
from effects import EffectsManager, PopupText, popup_alpha
from settings import WHITE


def _luminance(color: tuple[int, ...]) -> float:
    """Return the WCAG relative luminance of an RGB colour."""

    channels = []
    for value in color[:3]:
        c = value / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(first: tuple[int, ...], second: tuple[int, ...]) -> float:
    """Return the WCAG contrast ratio between two colours."""

    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class PopupReadabilityTests(unittest.TestCase):
    """Score and combo popups start fully opaque and stand out from the stack."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start pygame once for the class."""

        pygame.init()

    def test_fresh_popups_are_fully_opaque(self) -> None:
        """Every kind of popup is drawn at full alpha the moment it appears."""

        manager = EffectsManager()
        manager.merge(pygame.Vector2(300, 600), (200, 120, 90), 24, 3)
        manager.combo(2, pygame.Vector2(300, 600))
        manager.announce("Quasar Crown reached!", pygame.Vector2(300, 600))
        for popup in manager.popups:
            with self.subTest(text=popup.text):
                self.assertEqual(popup_alpha(popup), 255)

    def test_popups_fade_out_over_their_own_lifetime(self) -> None:
        """Opacity stays full for the first half, then falls to zero at the end."""

        popup = PopupText("+3", pygame.Vector2(), pygame.Vector2(), WHITE, life=0.9)
        popup.life = 0.5
        self.assertEqual(popup_alpha(popup), 255)
        popup.life = 0.225
        self.assertAlmostEqual(popup_alpha(popup), 127, delta=1)
        popup.life = 0.0
        self.assertEqual(popup_alpha(popup), 0)

    def test_popup_colours_contrast_with_their_outline(self) -> None:
        """Every popup colour contrasts at least 7:1 with the dark outline."""

        manager = EffectsManager()
        manager.merge(pygame.Vector2(), (0, 0, 0), 1, 0)
        manager.combo(2, pygame.Vector2())
        manager.announce("Goal", pygame.Vector2())
        for popup in manager.popups:
            with self.subTest(text=popup.text):
                self.assertGreaterEqual(_contrast(popup.color, effects.POPUP_OUTLINE), 7.0)


if __name__ == "__main__":
    unittest.main()
