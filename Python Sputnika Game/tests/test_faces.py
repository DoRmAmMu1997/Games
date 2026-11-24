"""Headless tests for the shapes of the cartoon faces drawn on each body.

Beginner note: `pygame.draw.arc` measures its angles counter-clockwise as
seen on screen, starting from the right-hand side. An arc from 0 to pi is
therefore the upper half of its rectangle (an arch, like "n", which reads as
a frown), and an arc from pi to tau is the lower half (a cup, like "u",
which reads as a smile). These tests record the angles the face code asks
for, so they do not depend on how any pixel is antialiased.
"""

from __future__ import annotations

import math
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

import entities
from entities import CelestialBody
from settings import TIERS

SMILING_MOODS = {"cheery", "smile", "spark", "bright", "calm", "proud", "cosmic"}
CALM_FACE = {"startled": False, "delighted": False, "sleepy": False, "worried": False, "focused": False}


def is_cup(start: float, end: float) -> bool:
    """True when an arc covers only the lower half of its rectangle (a smile)."""

    return start >= math.pi - 1e-6 and end <= math.tau + 1e-6


def is_arch(start: float, end: float) -> bool:
    """True when an arc covers only the upper half of its rectangle (a frown)."""

    return start >= -1e-6 and end <= math.pi + 1e-6


class FaceShapeTests(unittest.TestCase):
    """Happy mouths curve up like a smile; worried mouths curve down."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start pygame once so surfaces can be created."""

        pygame.init()
        pygame.display.set_mode((1, 1))

    def mouth_arcs(self, tier: int, expression: dict[str, bool]) -> list[tuple[float, float]]:
        """Draw one face with a fixed expression and return each arc's (start, end) angles."""

        body = CelestialBody(body_id=1, tier=tier, position=pygame.Vector2(200, 600),
                             velocity=pygame.Vector2(0, 0), created_at=0.0, seed=0.3)
        target = pygame.Surface((400, 400), pygame.SRCALPHA)
        with mock.patch.object(CelestialBody, "_expression_state", return_value=expression), \
                mock.patch.object(entities.pygame.draw, "arc", wraps=pygame.draw.arc) as arc:
            body._draw_face(target, (200, 200), body.radius, now=1.0)
        return [(call.args[3], call.args[4]) for call in arc.call_args_list]

    def test_every_smiling_mood_draws_a_cup(self) -> None:
        """Cheery, smile, spark, bright, calm, proud and cosmic tiers all smile."""

        checked = 0
        for tier, info in enumerate(TIERS):
            if info.mood not in SMILING_MOODS:
                continue
            arcs = self.mouth_arcs(tier, CALM_FACE)
            with self.subTest(tier=tier, mood=info.mood):
                self.assertTrue(arcs)
                self.assertTrue(all(is_cup(start, end) for start, end in arcs), arcs)
            checked += 1
        self.assertGreaterEqual(checked, 5)

    def test_delighted_bodies_smile(self) -> None:
        """A body glowing after a merge shows a smile, whatever its tier."""

        for tier in range(len(TIERS)):
            arcs = self.mouth_arcs(tier, {**CALM_FACE, "delighted": True})
            with self.subTest(tier=tier):
                self.assertTrue(arcs)
                self.assertTrue(all(is_cup(start, end) for start, end in arcs), arcs)

    def test_worried_bodies_frown(self) -> None:
        """A body near the danger line shows a downturned mouth."""

        for tier in range(len(TIERS)):
            arcs = self.mouth_arcs(tier, {**CALM_FACE, "worried": True})
            with self.subTest(tier=tier):
                self.assertTrue(arcs)
                self.assertTrue(all(is_arch(start, end) for start, end in arcs), arcs)


if __name__ == "__main__":
    unittest.main()
