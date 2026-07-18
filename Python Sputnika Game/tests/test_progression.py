"""Sanity checks for the tier ladder and spawn tuning in ``settings.py``.

These tests keep the data tables honest: the evolution chain must grow, the
spawn odds must reference real low tiers, and the HUD stress phases must
cover the whole meter.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from settings import (
    SPAWN_WEIGHTS,
    STRESS_PREVIEW_SHARE,
    STRESS_TIMER_SHARE,
    TIERS,
)


class TierLadderTests(unittest.TestCase):
    """The evolution chain that drives the whole game."""

    def test_tiers_grow_in_size_and_reward(self) -> None:
        """Each evolution is bigger and scores more than the previous one."""

        radii = [tier.radius for tier in TIERS]
        scores = [tier.score for tier in TIERS]
        self.assertEqual(radii, sorted(radii))
        self.assertEqual(scores, sorted(scores))
        self.assertLess(radii[0], radii[-1])
        self.assertLess(scores[0], scores[-1])

    def test_tier_names_are_unique(self) -> None:
        """Milestone popups and the HUD rely on distinct tier names."""

        names = [tier.name for tier in TIERS]
        self.assertEqual(len(names), len(set(names)))


class SpawnTuningTests(unittest.TestCase):
    """The queue only offers low tiers, with sensible odds."""

    def test_spawn_weights_reference_low_tiers_only(self) -> None:
        """There must be a weight per spawnable tier, all positive."""

        self.assertLessEqual(len(SPAWN_WEIGHTS), len(TIERS) - 1)
        self.assertTrue(all(weight > 0 for weight in SPAWN_WEIGHTS))


class StressMeterTests(unittest.TestCase):
    """The two HUD stress phases must exactly fill the meter."""

    def test_stress_shares_sum_to_one(self) -> None:
        """Preview share plus timer share covers the full 0..1 bar."""

        self.assertAlmostEqual(STRESS_PREVIEW_SHARE + STRESS_TIMER_SHARE, 1.0, places=9)


if __name__ == "__main__":
    unittest.main()
