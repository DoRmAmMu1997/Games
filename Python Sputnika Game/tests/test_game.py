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
from entities import CelestialBody
from game import OrbitalOrchardGame
from merge_logic import find_merge_events
from physics import PhysicsWorld
from settings import FAIL_AGE_GATE, SPAWN_Y, TIERS


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

    def use_fake_clock(self, frame_ms: int = 20) -> None:
        """Make every ``clock.tick`` report ``frame_ms`` without sleeping."""

        self.game.clock = mock.Mock(tick=mock.Mock(return_value=frame_ms))


class PauseClockTests(GameTestCase):
    """Game time stands still while the pause menu is open."""

    def test_pause_does_not_age_bodies(self) -> None:
        """A body launched just before a pause is still fresh when play resumes."""

        game = self.game
        self.use_fake_clock(25)
        game.start_round()
        game.drop_current_body()
        body = game.bodies[-1]
        game.scene = "paused"

        game.run(max_frames=40)  # one second of real time behind the pause menu

        game.scene = "playing"
        self.assertLess(body.age(game.now), FAIL_AGE_GATE)

    def test_playing_still_advances_the_clock(self) -> None:
        """Outside the pause menu the game clock follows frame time."""

        game = self.game
        self.use_fake_clock()
        game.start_round()
        before = game.now

        game.run(max_frames=10)

        self.assertAlmostEqual(game.now - before, 0.2, places=6)


def _reference_trail(canvas: pygame.Surface, points, camera: pygame.Vector2, color) -> None:
    """Draw the preview dots the original way, on one full-screen overlay."""

    trail = pygame.Surface(canvas.get_size(), pygame.SRCALPHA)
    total = max(1, len(points) - 1)
    for index, point in enumerate(points):
        progress = index / total
        center = point + camera
        dot_radius = max(2, int(8 - progress * 4.5))
        dot_alpha = int(125 - progress * 72)
        glow_alpha = int(42 - progress * 22)
        spot = (int(center.x), int(center.y))
        pygame.draw.circle(trail, (*color, max(0, glow_alpha)), spot, dot_radius + 4)
        pygame.draw.circle(trail, (*color, max(0, dot_alpha)), spot, dot_radius)
    canvas.blit(trail, (0, 0))


def _reference_guides(canvas: pygame.Surface, start: pygame.Vector2, direction: pygame.Vector2, color) -> None:
    """Draw the faded aim-guide segments the original way, one full-screen overlay each."""

    for guide_length, alpha in ((72.0, 95), (118.0, 70), (162.0, 45)):
        ghost = pygame.Surface(canvas.get_size(), pygame.SRCALPHA)
        pygame.draw.line(ghost, (*color, alpha), start, start + direction * guide_length, 2)
        canvas.blit(ghost, (0, 0))


class SpawnOverlayTests(GameTestCase):
    """Content-sized overlays must look exactly like the old full-screen ones."""

    def _backdrop(self) -> pygame.Surface:
        """Return a canvas-sized surface with a busy gradient to blend onto."""

        surface = pygame.Surface(self.game.canvas.get_size()).convert()
        for y in range(0, surface.get_height(), 8):
            surface.fill(((y * 3) % 256, (y * 7) % 256, (y * 11) % 256), (0, y, surface.get_width(), 8))
        return surface

    def test_trail_and_guides_match_full_screen_overlays(self) -> None:
        """Across many aims, positions, shakes and colours the pixels are identical."""

        game = self.game
        rng = random.Random(11)
        backdrop = self._backdrop()
        for case in range(60):
            tier = rng.randrange(5)
            low, high = game.world.allowed_spawn_x(TIERS[tier].radius)
            spawn = game.world.spawn_point(rng.uniform(low, high), TIERS[tier].radius)
            angle = rng.uniform(-60.0, 60.0)
            game.launch_angle = angle
            direction = game._launch_direction()
            camera = pygame.Vector2(rng.uniform(-9, 9), rng.uniform(-9, 9))
            color = rng.choice([(175, 216, 255), (255, 112, 112)])
            points = game.world.preview_trajectory(spawn, direction * 520.0, TIERS[tier].radius, rng.random())
            with self.subTest(case=case, tier=tier, angle=round(angle, 1)):
                expected = backdrop.copy()
                _reference_trail(expected, points, camera, color)
                _reference_guides(expected, spawn + camera, direction, color)
                game.canvas = backdrop.copy()
                game._draw_preview_trail(points, camera, color)
                game._draw_aim_guides(spawn + camera, direction, color)
                self.assertEqual(
                    pygame.image.tobytes(game.canvas, "RGB"),
                    pygame.image.tobytes(expected, "RGB"),
                )


class DrawOrderTests(GameTestCase):
    """The launcher stays visible even when a tall stack rises behind it."""

    def test_launcher_is_drawn_after_the_bodies(self) -> None:
        """The spawn indicator (launcher orb, aim line) is drawn on top of every body."""

        game = self.game
        game.start_round()
        center = game.world.center
        game.bodies = [
            CelestialBody(1, 4, pygame.Vector2(center.x, SPAWN_Y + 10), pygame.Vector2(), game.now - 5.0),
            CelestialBody(2, 2, pygame.Vector2(center.x + 60, SPAWN_Y + 40), pygame.Vector2(), game.now - 5.0),
        ]
        calls: list[str] = []
        original_body_draw = CelestialBody.draw
        original_indicator = game._draw_spawn_indicator

        def record_body(body, *args, **kwargs):
            """Note a body draw, then draw it for real."""

            calls.append("body")
            return original_body_draw(body, *args, **kwargs)

        def record_indicator(*args, **kwargs):
            """Note the launcher draw, then draw it for real."""

            calls.append("launcher")
            return original_indicator(*args, **kwargs)

        with (
            mock.patch.object(CelestialBody, "draw", record_body),
            mock.patch.object(game, "_draw_spawn_indicator", record_indicator),
        ):
            game._draw()

        self.assertEqual(calls, ["body", "body", "launcher"])


class MenuDangerTests(GameTestCase):
    """Leaving a run in danger leaves no danger label behind the main menu."""

    def test_menu_shows_a_calm_danger_line(self) -> None:
        """In the menu the playfield gets no warning and no danger level."""

        game = self.game
        game.start_round()
        game.warning_active = True
        game.fail_timer = 1.5
        game.scene = "menu"

        with mock.patch.object(game_module, "draw_playfield") as playfield:
            game._draw()

        _, _, danger_ratio, warning_active = playfield.call_args.args
        self.assertEqual(danger_ratio, 0.0)
        self.assertFalse(warning_active)

    def test_paused_run_still_shows_the_danger(self) -> None:
        """Behind the pause menu the run's danger is still shown."""

        game = self.game
        game.start_round()
        game.warning_active = True
        game.fail_timer = 1.2
        game.scene = "paused"

        with mock.patch.object(game_module, "draw_playfield") as playfield:
            game._draw()

        _, _, danger_ratio, warning_active = playfield.call_args.args
        self.assertAlmostEqual(danger_ratio, 0.5)
        self.assertTrue(warning_active)


class MergeDeterminismTests(GameTestCase):
    """Gameplay randomness flows through the game's own seeded generator."""

    def _merge_once(self, game: OrbitalOrchardGame) -> CelestialBody:
        """Merge two touching tier-0 bodies in ``game`` and return the result."""

        game.start_round()
        radius = TIERS[0].radius
        center = game.world.center
        game.bodies = [
            CelestialBody(1, 0, pygame.Vector2(center.x, center.y), pygame.Vector2(), game.now - 5.0),
            CelestialBody(2, 0, pygame.Vector2(center.x + radius, center.y), pygame.Vector2(), game.now - 5.0),
        ]
        game._next_body_id = 3
        game._apply_merges(find_merge_events(game.bodies, game.now))
        return game.bodies[-1]

    def test_identical_game_seeds_give_identical_merged_seeds(self) -> None:
        """Two games seeded the same way produce merged bodies with the same seed."""

        random.seed(1)  # the global generator must not matter
        first = self._merge_once(self.make_game(seed=99))
        random.seed(2)
        second = self._merge_once(self.make_game(seed=99))

        self.assertEqual(first.tier, 1)
        self.assertEqual(first.seed, second.seed)


class MergeSaveTests(GameTestCase):
    """Merges only write the save file when a record actually moves."""

    def _merge(self, tier: int) -> None:
        """Merge two touching ``tier`` bodies in a running round."""

        game = self.game
        radius = TIERS[tier].radius
        center = game.world.center
        game.bodies = [
            CelestialBody(1, tier, pygame.Vector2(center.x, center.y), pygame.Vector2(), game.now - 5.0),
            CelestialBody(2, tier, pygame.Vector2(center.x + radius, center.y), pygame.Vector2(), game.now - 5.0),
        ]
        game._next_body_id = 3
        game._apply_merges(find_merge_events(game.bodies, game.now))

    def setUp(self) -> None:
        """Start a round whose records sit well above an ordinary merge."""

        super().setUp()
        self.game.start_round()
        self.game.high_score = 10_000
        self.game.lifetime_best_tier = 6

    def test_ordinary_merge_does_not_write(self) -> None:
        """A merge that beats neither the high score nor the best tier saves nothing."""

        with mock.patch.object(self.game, "_save_progress") as save:
            self._merge(0)
        self.assertEqual(save.call_count, 0)

    def test_new_best_tier_writes_once(self) -> None:
        """A merge that reaches a new best tier saves exactly once."""

        with mock.patch.object(self.game, "_save_progress") as save:
            self._merge(6)
        self.assertEqual(save.call_count, 1)

    def test_new_high_score_writes_once(self) -> None:
        """A merge that lifts the score past the high score saves exactly once."""

        self.game.score = 9_999
        with mock.patch.object(self.game, "_save_progress") as save:
            self._merge(0)
        self.assertEqual(save.call_count, 1)


class ErrorLogTests(GameTestCase):
    """Save failures are written to ``error.log`` instead of crashing the game."""

    def test_failed_save_is_logged_to_error_log(self) -> None:
        """An OSError while saving appends one stamped line to ``error.log``."""

        with mock.patch.object(game_module.os, "replace", side_effect=OSError("disk full")):
            self.game._save_progress()

        log = self.save_path.parent / "error.log"
        self.assertRegex(log.read_text(encoding="utf-8"), r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] disk full\n$")
        self.assertFalse((self.save_path.parent / "save_error.log").exists())


class NoPersistTests(GameTestCase):
    """``persist=False`` reads saved progress but never writes it."""

    def test_non_persisting_game_leaves_the_save_untouched(self) -> None:
        """Playing, recording and losing a round does not change a pre-seeded save."""

        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        original = '{"high_score": 5, "games_played": 3, "best_tier": 2}'
        self.save_path.write_text(original, encoding="utf-8")

        game = OrbitalOrchardGame(persist=False)
        self.assertEqual((game.high_score, game.games_played, game.lifetime_best_tier), (5, 3, 2))
        game.start_round()
        game.score = 999
        game._trigger_game_over()

        self.assertEqual(game.high_score, 999)
        self.assertEqual(self.save_path.read_text(encoding="utf-8"), original)
        self.assertEqual(sorted(path.name for path in self.save_path.parent.iterdir()), ["save_data.json"])

    def test_default_game_still_saves(self) -> None:
        """Normal games keep saving progress."""

        self.game.start_round()
        self.assertTrue(self.save_path.exists())


class CorruptSaveTests(GameTestCase):
    """A damaged save file loads as fresh progress instead of crashing startup."""

    DEFAULTS = {"high_score": 0, "games_played": 0, "best_tier": 0}

    def _load_text(self, text: str) -> dict:
        """Write ``text`` as the save file and return what the game loads from it."""

        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        self.save_path.write_text(text, encoding="utf-8")
        return self.game._load_progress()

    def test_huge_number_loads_as_defaults(self) -> None:
        """``1e999`` parses as infinity, which cannot become an int."""

        self.assertEqual(self._load_text('{"high_score": 1e999}'), self.DEFAULTS)

    def test_infinity_literal_loads_as_defaults(self) -> None:
        """Python's JSON reader accepts ``Infinity``; it must not crash either."""

        self.assertEqual(self._load_text('{"games_played": Infinity}'), self.DEFAULTS)

    def test_deeply_nested_save_loads_as_defaults(self) -> None:
        """A save nested 100000 levels deep exhausts recursion; it must not crash."""

        self.assertEqual(self._load_text("[" * 100000 + "]" * 100000), self.DEFAULTS)

    def test_a_game_starts_with_a_corrupt_save(self) -> None:
        """Building the whole game on top of a corrupt save still works."""

        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        self.save_path.write_text('{"high_score": 1e999}', encoding="utf-8")
        self.assertEqual(self.make_game().high_score, 0)


class StressMeterTests(GameTestCase):
    """The HUD stress meter reacts to the settled stack, not to fresh launches."""

    def test_drop_into_empty_bubble_does_not_spike_the_meter(self) -> None:
        """A body still falling from the launcher leaves the meter at zero."""

        game = self.game
        game.start_round()
        game.drop_current_body()

        game._update_fail_state(1 / 60)

        self.assertEqual(game.container_stress, 0.0)

    def test_settled_high_body_still_raises_the_meter(self) -> None:
        """Once a body is older than the age gate, its height counts."""

        game = self.game
        game.start_round()
        game.drop_current_body()
        game.now += FAIL_AGE_GATE + 0.1

        game._update_fail_state(1 / 60)

        self.assertGreater(game.container_stress, 0.5)


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
