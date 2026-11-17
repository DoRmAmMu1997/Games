"""Headless tests for the pygame shell in ``game.py``.

These tests build a real ``OrbitalOrchardGame`` under SDL's dummy video and
audio drivers, so no window ever appears. Saved progress is redirected into a
temporary folder for every test, so the player's real save is never touched.

Beginner note:
- ``game.py`` imports ``SAVE_DATA_DIR`` and ``SAVE_DATA_PATH`` by name, so the
  tests patch those names *inside the game module*; patching ``settings``
  would be too late, because the game already holds its own references.
"""

from __future__ import annotations

import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import pygame

import game as game_module
from game import OrbitalOrchardGame
from physics import PhysicsWorld
from settings import SPAWN_Y, TIERS


class GameTestCase(unittest.TestCase):
    """Shared setup: pygame started, saves redirected, randomness seeded."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start pygame once for every test in the class."""

        pygame.init()

    def setUp(self) -> None:
        """Point saves at a fresh temporary folder and build a seeded game."""

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        save_dir = Path(self._tmp.name) / "Orbital Orchard"
        for name, value in (("SAVE_DATA_DIR", save_dir), ("SAVE_DATA_PATH", save_dir / "save_data.json")):
            patcher = mock.patch.object(game_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.save_path = save_dir / "save_data.json"
        self.game = self.make_game()

    def make_game(self, seed: int = 7) -> OrbitalOrchardGame:
        """Build a game whose queue and merges come from a seeded generator."""

        game = OrbitalOrchardGame()
        game.random = random.Random(seed)
        return game


class SpawnInsideCircleTests(GameTestCase):
    """Launched bodies start inside the same legal circle the solver enforces."""

    def _first_step_snap(self, tier: int, where: str) -> float:
        """Drop a ``tier`` body at the left/centre/right of the span; return the wall snap."""

        game = self.game
        game.start_round()
        game.current_tier = tier
        low, high = game.world.allowed_spawn_x(TIERS[tier].radius)
        game.spawn_x = {"left": low, "centre": (low + high) / 2, "right": high}[where]
        game.drop_current_body()
        body = game.bodies[-1]

        snaps: list[float] = []
        original = PhysicsWorld._solve_boundaries

        def recording_solve(world, bodies, emit_events):
            """Run the real wall solver and record how far it moved the body."""

            before = pygame.Vector2(body.position)
            result = original(world, bodies, emit_events)
            snaps.append((body.position - before).length())
            return result

        with mock.patch.object(PhysicsWorld, "_solve_boundaries", recording_solve):
            game.world.step([body], 1 / 60)
        return max(snaps)

    def test_first_step_never_snaps_a_fresh_body(self) -> None:
        """Tiers 0-4 move less than 0.1 px on their first wall solve, anywhere on the span."""

        for tier in range(5):
            for where in ("left", "centre", "right"):
                with self.subTest(tier=tier, where=where):
                    self.assertLess(self._first_step_snap(tier, where), 0.1)

    def test_spawn_point_lies_inside_the_legal_circle(self) -> None:
        """``spawn_point`` never returns a point outside ``R - r - 3``."""

        world = PhysicsWorld()
        for tier in range(5):
            radius = TIERS[tier].radius
            low, high = world.allowed_spawn_x(radius)
            for x in (low, (low + high) / 2, high):
                point = world.spawn_point(x, radius)
                self.assertLessEqual((point - world.center).length(), world.radius - radius - 3.0 + 1e-6)

    def test_spawn_point_keeps_points_that_already_fit(self) -> None:
        """A small body near the centre keeps its exact spawn coordinates."""

        world = PhysicsWorld()
        self.assertEqual(world.spawn_point(world.center.x, 1.0), pygame.Vector2(world.center.x, SPAWN_Y))

    def test_preview_keeps_many_points_for_large_tiers(self) -> None:
        """Tier 3-4 previews at non-zero angles show a real dotted path, not one dot."""

        game = self.game
        game.start_round()
        captured: list[list[pygame.Vector2]] = []
        original = game.world.preview_trajectory

        def capture(*args, **kwargs):
            """Call the real preview and keep a copy of its points."""

            points = original(*args, **kwargs)
            captured.append(points)
            return points

        with mock.patch.object(game.world, "preview_trajectory", capture):
            for tier in (3, 4):
                for angle in (-40.0, -15.0, 15.0, 40.0):
                    with self.subTest(tier=tier, angle=angle):
                        game.current_tier = tier
                        game.launch_angle = angle
                        game._draw_spawn_indicator(pygame.Vector2())
                        self.assertGreater(len(captured[-1]), 5)


if __name__ == "__main__":
    unittest.main()
