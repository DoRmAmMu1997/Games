"""Headless tests for the procedural assets in ``assets.py``."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import pygame

from assets import AssetLibrary, SoundBank
from settings import TIERS


class ToneChannelTests(unittest.TestCase):
    """Generated tones must hold one sample per channel for every moment."""

    def test_sample_count_matches_every_channel_layout(self) -> None:
        """Mono, stereo, 4, 6 and 8 channel mixers each get a full interleaved buffer."""

        rate, duration = 22050, 0.05
        frames = int(rate * duration)
        for channels in (1, 2, 4, 6, 8):
            with self.subTest(channels=channels):
                with (
                    mock.patch.object(pygame.mixer, "get_init", return_value=(rate, -16, channels)),
                    mock.patch.object(pygame.mixer, "Sound") as fake_sound,
                ):
                    SoundBank._make_tone(SoundBank.__new__(SoundBank), [440.0], duration, 0.3)

                # Each sample is a signed 16-bit integer, which is two bytes.
                buffer = fake_sound.call_args.kwargs["buffer"]
                self.assertEqual(len(buffer), frames * channels * 2)


class OrbArtTests(unittest.TestCase):
    """Translucent highlights blend onto an orb instead of punching holes in it."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start pygame and build the asset library once."""

        pygame.init()
        pygame.display.set_mode((1, 1))
        cls.assets = AssetLibrary()

    assets: AssetLibrary

    def test_every_orb_body_is_fully_opaque(self) -> None:
        """Every pixel inside each tier's body circle (3 px in from the rim) is opaque."""

        for tier, info in enumerate(TIERS):
            orb = self.assets.get_body_surface(tier)
            cx, cy = orb.get_width() / 2, orb.get_height() / 2
            limit = (info.radius - 3) ** 2
            holes = 0
            for y in range(orb.get_height()):
                for x in range(orb.get_width()):
                    if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= limit and orb.get_at((x, y)).a < 255:
                        holes += 1
            with self.subTest(tier=tier):
                self.assertEqual(holes, 0)

    def test_outer_glow_fades_away_from_the_orb(self) -> None:
        """The glow is strongest next to the orb and faintest at its outer edge.

        The glow is five stacked rings 5 px wide. Sampling straight below
        each orb, in the middle of each ring band (well away from any
        antialiased edge), the alpha must drop at every step outward. Some
        tiers' rings, rays or wide sprites cover the nearer bands, so only
        bands that show bare glow (alpha below 255) are compared.
        """

        for tier, info in enumerate(TIERS):
            orb = self.assets.get_body_surface(tier)
            cx, cy = orb.get_width() // 2, orb.get_height() // 2
            radius = int(info.radius)
            alphas = [orb.get_at((cx, cy + radius + offset)).a for offset in (7, 12, 17, 22)]
            glow = [alpha for alpha in alphas if alpha < 255]
            with self.subTest(tier=tier, alphas=alphas):
                self.assertGreaterEqual(len(glow), 2)
                self.assertEqual(glow, sorted(glow, reverse=True))
                self.assertEqual(len(set(glow)), len(glow))


if __name__ == "__main__":
    unittest.main()
