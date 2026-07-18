"""Engine tests for the merge-detection rules in ``merge_logic.py``.

These tests build bodies directly and never open a window, so they run
headless in CI. They lock in the core "same tier + valid state = evolve"
rules that make the puzzle work.
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

import pygame

from entities import CelestialBody
from merge_logic import find_merge_events
from settings import MERGE_VELOCITY_DAMP, TIERS

NOW = 100.0


def make_body(
    body_id: int,
    tier: int,
    x: float,
    y: float,
    vx: float = 0.0,
    vy: float = 0.0,
    age: float = 10.0,
) -> CelestialBody:
    """Create one body that is old enough to merge unless ``age`` says otherwise."""

    return CelestialBody(
        body_id=body_id,
        tier=tier,
        position=pygame.Vector2(x, y),
        velocity=pygame.Vector2(vx, vy),
        created_at=NOW - age,
    )


class MergeDetectionTests(unittest.TestCase):
    """Which pairs of bodies are allowed to merge."""

    def test_touching_same_tier_bodies_merge_upward(self) -> None:
        """Two overlapping tier-0 bodies produce one tier-1 merge event."""

        radius = TIERS[0].radius
        bodies = [make_body(1, 0, 0.0, 0.0), make_body(2, 0, radius * 1.5, 0.0)]

        events = find_merge_events(bodies, NOW)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source_tier, 0)
        self.assertEqual(events[0].target_tier, 1)
        self.assertEqual(events[0].score_gain, TIERS[1].score)
        self.assertEqual({events[0].first_id, events[0].second_id}, {1, 2})

    def test_different_tiers_do_not_merge(self) -> None:
        """A tier-0 and a tier-1 body touching is not a merge."""

        bodies = [make_body(1, 0, 0.0, 0.0), make_body(2, 1, 5.0, 0.0)]

        self.assertEqual(find_merge_events(bodies, NOW), [])

    def test_bodies_out_of_contact_range_do_not_merge(self) -> None:
        """Same-tier bodies far apart stay separate."""

        far = TIERS[0].radius * 4
        bodies = [make_body(1, 0, 0.0, 0.0), make_body(2, 0, far, 0.0)]

        self.assertEqual(find_merge_events(bodies, NOW), [])

    def test_fresh_bodies_wait_before_merging(self) -> None:
        """A just-created body is not merge-eligible yet."""

        bodies = [make_body(1, 0, 0.0, 0.0), make_body(2, 0, 5.0, 0.0, age=0.0)]

        self.assertEqual(find_merge_events(bodies, NOW), [])

    def test_highest_tier_bodies_never_merge(self) -> None:
        """The final evolution cannot evolve further."""

        top = len(TIERS) - 1
        bodies = [make_body(1, top, 0.0, 0.0), make_body(2, top, 5.0, 0.0)]

        self.assertEqual(find_merge_events(bodies, NOW), [])

    def test_each_body_participates_in_one_merge_per_frame(self) -> None:
        """Three overlapping bodies yield one merge; the third is left alone."""

        bodies = [
            make_body(1, 0, 0.0, 0.0),
            make_body(2, 0, 5.0, 0.0),
            make_body(3, 0, 10.0, 0.0),
        ]

        events = find_merge_events(bodies, NOW)

        self.assertEqual(len(events), 1)


class MergeResultTests(unittest.TestCase):
    """What the resulting merged body looks like."""

    def test_merge_spawns_at_mass_weighted_center(self) -> None:
        """Equal-tier parents have equal mass, so the child spawns midway."""

        radius = TIERS[0].radius
        bodies = [make_body(1, 0, 0.0, 0.0), make_body(2, 0, radius, 0.0)]

        event = find_merge_events(bodies, NOW)[0]

        self.assertAlmostEqual(event.position.x, radius / 2, places=5)
        self.assertAlmostEqual(event.position.y, 0.0, places=5)

    def test_merged_velocity_is_damped(self) -> None:
        """The child keeps a damped fraction of the combined parent velocity."""

        bodies = [
            make_body(1, 0, 0.0, 0.0, vx=100.0),
            make_body(2, 0, 5.0, 0.0, vx=50.0),
        ]

        event = find_merge_events(bodies, NOW)[0]

        self.assertAlmostEqual(event.velocity.x, 150.0 * MERGE_VELOCITY_DAMP, places=5)
        self.assertAlmostEqual(event.velocity.y, 0.0, places=5)


if __name__ == "__main__":
    unittest.main()
