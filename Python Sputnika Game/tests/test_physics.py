"""Engine tests for the circular-container physics in ``physics.py``.

The solver is intentionally game-feel physics, so these tests check the
stability guarantees the rest of the game relies on (bodies stay inside the
bubble, overlaps separate) rather than exact trajectories.
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
from physics import PhysicsWorld

NOW = 100.0


def make_body(body_id: int, tier: int, x: float, y: float, vx: float = 0.0, vy: float = 0.0) -> CelestialBody:
    """Create one body at an absolute playfield position."""

    return CelestialBody(
        body_id=body_id,
        tier=tier,
        position=pygame.Vector2(x, y),
        velocity=pygame.Vector2(vx, vy),
        created_at=NOW - 10.0,
    )


class ContainerTests(unittest.TestCase):
    """Bodies must always stay inside the circular bubble."""

    def test_keep_inside_clamps_a_body_placed_outside(self) -> None:
        """A body spawned beyond the wall is pulled back to the legal edge."""

        world = PhysicsWorld()
        body = make_body(1, 0, world.center.x + world.radius * 2, world.center.y)

        world.keep_inside(body)

        distance = (body.position - world.center).length()
        self.assertLessEqual(distance, world.radius - body.radius)

    def test_step_pushes_an_escaping_body_back_inside(self) -> None:
        """A body flying outward is reflected off the wall by one step."""

        world = PhysicsWorld()
        body = make_body(1, 0, world.center.x + world.radius - 5, world.center.y, vx=500.0)

        world.step([body], 1 / 60)

        distance = (body.position - world.center).length()
        self.assertLessEqual(distance, world.radius - body.radius)

    def test_spawn_span_is_symmetric_and_inside_the_bubble(self) -> None:
        """The legal spawn range is centered and narrower than the bubble."""

        world = PhysicsWorld()
        left, right = world.allowed_spawn_x(20.0)

        self.assertLess(left, right)
        self.assertAlmostEqual(world.center.x - left, right - world.center.x, places=5)
        self.assertGreater(left, world.center.x - world.radius)
        self.assertLess(right, world.center.x + world.radius)

    def test_preview_trajectory_never_leaves_the_bubble(self) -> None:
        """Every preview point stays within the container wall."""

        world = PhysicsWorld()
        radius = 18.0
        points = world.preview_trajectory(
            pygame.Vector2(world.center.x, world.center.y - world.radius * 0.7),
            pygame.Vector2(300.0, -200.0),
            radius,
            seed=0.5,
        )

        self.assertTrue(points)
        limit = world.radius - radius - 3.0 + 1e-6
        for point in points:
            self.assertLessEqual((point - world.center).length(), limit)


class PairSolverTests(unittest.TestCase):
    """Overlapping bodies must separate instead of sinking into each other."""

    def test_overlapping_bodies_separate(self) -> None:
        """Two heavily overlapped equal bodies end one step farther apart."""

        world = PhysicsWorld()
        offset = 10.0  # far less than two tier-0 radii
        first = make_body(1, 0, world.center.x - offset / 2, world.center.y)
        second = make_body(2, 0, world.center.x + offset / 2, world.center.y)
        before = (second.position - first.position).length()

        world.step([first, second], 1 / 60)

        after = (second.position - first.position).length()
        self.assertGreater(after, before)

    def test_equal_bodies_are_pushed_apart_symmetrically(self) -> None:
        """Equal masses share the separation correction evenly."""

        world = PhysicsWorld()
        offset = 10.0
        first = make_body(1, 0, world.center.x - offset / 2, world.center.y)
        second = make_body(2, 0, world.center.x + offset / 2, world.center.y)

        world.step([first, second], 1 / 60)

        left_push = world.center.x - first.position.x
        right_push = second.position.x - world.center.x
        self.assertAlmostEqual(left_push, right_push, delta=0.5)


if __name__ == "__main__":
    unittest.main()
