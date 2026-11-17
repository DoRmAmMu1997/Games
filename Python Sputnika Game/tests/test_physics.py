"""Engine tests for the circular-container physics in ``physics.py``.

The solver is intentionally game-feel physics, so these tests check the
stability guarantees the rest of the game relies on (bodies stay inside the
bubble, overlaps separate) rather than exact trajectories.
"""

from __future__ import annotations

import os
import random
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
from settings import TIERS

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


class CachedBodyPropertiesTests(unittest.TestCase):
    """Radius and mass are stored once per body instead of looked up per pair check."""

    def test_radius_and_mass_are_plain_attributes(self) -> None:
        """``radius``, ``mass`` and ``inv_mass`` are data, not class-level properties."""

        for name in ("radius", "mass", "inv_mass"):
            with self.subTest(name=name):
                self.assertNotIsInstance(getattr(CelestialBody, name, None), property)

    def test_cached_values_match_the_tier_table(self) -> None:
        """Every tier caches its table radius and the area-based mass."""

        for tier, info in enumerate(TIERS):
            with self.subTest(tier=tier):
                body = make_body(1, tier, 0.0, 0.0)
                self.assertEqual(body.radius, info.radius)
                self.assertEqual(body.mass, max(4.0, info.radius * info.radius * 0.018))
                self.assertEqual(body.inv_mass, 1.0 / body.mass)


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


def _random_scene(rng: random.Random, count: int, world: PhysicsWorld) -> list[CelestialBody]:
    """Scatter ``count`` mixed-tier bodies inside the bubble, many overlapping."""

    bodies = []
    for body_id in range(count):
        offset = pygame.Vector2(rng.uniform(0.0, world.radius - 40.0), 0.0).rotate(rng.uniform(0.0, 360.0))
        bodies.append(
            CelestialBody(
                body_id=body_id,
                tier=rng.randrange(7),
                position=world.center + offset,
                velocity=pygame.Vector2(rng.uniform(-600, 600), rng.uniform(-600, 600)),
                created_at=NOW - 10.0,
                seed=rng.random(),
            )
        )
    return bodies


def _colliding_scene(rng: random.Random, count: int, world: PhysicsWorld) -> list[CelestialBody]:
    """Place up to ``count`` separate bodies legally inside the bubble, flying fast.

    Like the real game, bodies start apart and inside the wall; their random
    velocities then drive plenty of collisions over the following frames.
    """

    bodies: list[CelestialBody] = []
    for _ in range(count * 20):
        if len(bodies) == count:
            break
        tier = rng.randrange(7)
        radius = TIERS[tier].radius
        offset = pygame.Vector2(rng.uniform(0.0, world.radius - radius - 3.0), 0.0).rotate(rng.uniform(0.0, 360.0))
        position = world.center + offset
        if any((position - other.position).length() < radius + other.radius for other in bodies):
            continue
        bodies.append(
            CelestialBody(
                body_id=len(bodies),
                tier=tier,
                position=position,
                velocity=pygame.Vector2(rng.uniform(-900, 900), rng.uniform(-900, 900)),
                created_at=NOW - 10.0,
                seed=rng.random(),
            )
        )
    return bodies


def _event_keys(events) -> list[tuple[int, int | None, float, tuple[float, float]]]:
    """Reduce impact events to comparable tuples: body ids, speed, and contact point."""

    return [
        (event.body_a.body_id, event.body_b.body_id if event.body_b else None, event.impact_speed, tuple(event.point))
        for event in events
    ]


class AllPairsWorld(PhysicsWorld):
    """Reference world whose broad phase hands every pair to the solver."""

    def _broad_phase_pairs(self, bodies, margin):
        """Return every index pair ``(i, j)`` with ``i < j``, in all-pairs order."""

        return [(i, j) for i in range(len(bodies)) for j in range(i + 1, len(bodies))]


class BroadPhaseTests(unittest.TestCase):
    """The uniform grid must find exactly the pairs a brute-force scan finds."""

    def test_grid_matches_brute_force_within_the_margin(self) -> None:
        """On 40 random scenes the grid returns the brute-force set, in the same order."""

        rng = random.Random(2024)
        world = PhysicsWorld()
        for scene in range(40):
            bodies = _random_scene(rng, rng.randrange(2, 81), world)
            margin = rng.uniform(0.0, 60.0)
            expected = []
            for i in range(len(bodies)):
                for j in range(i + 1, len(bodies)):
                    reach = bodies[i].radius + bodies[j].radius + margin
                    if (bodies[j].position - bodies[i].position).length_squared() <= reach * reach:
                        expected.append((i, j))
            with self.subTest(scene=scene, bodies=len(bodies)):
                self.assertEqual(world._broad_phase_pairs(bodies, margin), expected)

    def test_solver_is_bit_identical_to_all_pairs(self) -> None:
        """Positions, velocities and events match an all-pairs world exactly."""

        rng = random.Random(77)
        for scene in range(8):
            count = rng.randrange(10, 81)
            seed = rng.random()
            grid_world, reference_world = PhysicsWorld(), AllPairsWorld()
            grid_bodies = _colliding_scene(random.Random(seed), count, grid_world)
            reference_bodies = _colliding_scene(random.Random(seed), count, reference_world)
            with self.subTest(scene=scene, bodies=len(grid_bodies)):
                for _ in range(45):
                    grid_events = grid_world.step(grid_bodies, 1 / 60)
                    reference_events = reference_world.step(reference_bodies, 1 / 60)
                    self.assertEqual(_event_keys(grid_events), _event_keys(reference_events))
                self.assertEqual(
                    [(tuple(b.position), tuple(b.velocity)) for b in grid_bodies],
                    [(tuple(b.position), tuple(b.velocity)) for b in reference_bodies],
                )


if __name__ == "__main__":
    unittest.main()
