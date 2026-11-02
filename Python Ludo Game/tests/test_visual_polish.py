"""Checkable parts of the Ludo graphics polish: text fits, nothing overlaps.

These tests rasterize shapes into pygame masks where rectangles alone cannot
describe them (the triangular radial yards), so "does not overlap" means no
shared pixel at all.
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

import main
from board_render import BoardRenderer, _square_home_rects
from game import LudoGame, LudoRules
from settings import SCREEN_HEIGHT, SCREEN_WIDTH

# Yard parking slots are drawn as rings of this radius (see _draw_yard_slots).
YARD_SLOT_RADIUS = 24
# Name banners cast a drop shadow this far below themselves.
BANNER_SHADOW_DROP = 4


def make_game(total_players: int) -> LudoGame:
    """Create a deterministic game with seat 0 human and the rest AI."""

    players = [(f"P{i + 1}", i == 0) for i in range(total_players)]
    return LudoGame(players, LudoRules(total_players=total_players), seed=12)


def yard_mask(renderer: BoardRenderer) -> pygame.mask.Mask:
    """Return a full-canvas mask of every yard frame and parking-slot ring."""

    surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    solid = (255, 255, 255, 255)
    if renderer.display.yard_frames:
        for frame in renderer.display.yard_frames:
            pygame.draw.polygon(surface, solid, [(round(x), round(y)) for x, y in frame])
    else:
        for yard in _square_home_rects():
            pygame.draw.rect(surface, solid, yard)
    for slots in renderer.display.yard_positions:
        for x, y in slots:
            pygame.draw.circle(surface, solid, (round(x), round(y)), YARD_SLOT_RADIUS)
    return pygame.mask.from_surface(surface)


class BannerPlacementTests(unittest.TestCase):
    """Player name banners sit fully outside their yards and on the canvas."""

    def test_banners_clear_every_yard(self) -> None:
        """No banner shares a pixel with any yard frame or parking slot."""

        for count in (4, 5, 6):
            renderer = BoardRenderer(make_game(count).layout)
            yards = yard_mask(renderer)
            for seat, rect in enumerate(renderer.banner_rects()):
                with self.subTest(total_players=count, seat=seat):
                    banner = pygame.mask.Mask(rect.size, fill=True)
                    self.assertEqual(yards.overlap_area(banner, rect.topleft), 0, f"banner {rect} covers a yard")

    def test_banners_stay_on_the_canvas(self) -> None:
        """Every banner, including its drop shadow, is fully inside the window."""

        screen = pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
        for count in (4, 5, 6):
            for seat, rect in enumerate(BoardRenderer(make_game(count).layout).banner_rects()):
                with self.subTest(total_players=count, seat=seat):
                    self.assertTrue(screen.contains(rect.inflate(0, 2 * BANNER_SHADOW_DROP)), rect)

    def test_bottom_banner_and_shadow_clear_the_dice_tray(self) -> None:
        """Seat 0's banner, shadow included, stops above the HUD dice tray."""

        for count in (4, 5, 6):
            with self.subTest(total_players=count):
                rect = BoardRenderer(make_game(count).layout).banner_rects()[0]
                shadowed = rect.union(rect.move(0, BANNER_SHADOW_DROP))
                self.assertFalse(shadowed.colliderect(main.PLAY_DICE_TRAY_RECT), f"{shadowed} touches the tray")


if __name__ == "__main__":
    unittest.main()
