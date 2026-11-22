"""Headless rendering tests for the HUD, panels and overlays in ``ui.py``.

These tests draw onto off-screen surfaces under SDL's dummy driver. They
check layout with real font measurements and generous margins (never a
one-pixel fit), and they compare chosen colours directly instead of sampling
antialiased edges, so they hold with other fonts and on other platforms.
"""

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

import ui
from assets import AssetLibrary
from physics import PhysicsWorld
from settings import CONTAINER_RADIUS, PLAYFIELD_CENTER, SCREEN_HEIGHT, SCREEN_WIDTH, SIDEBAR_X, SPAWN_WEIGHTS, TIERS


class UiTestCase(unittest.TestCase):
    """Shared setup: pygame started and a display mode set for ``convert``."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start pygame once for every test in the class."""

        pygame.init()
        pygame.display.set_mode((1, 1))


class PanelTests(UiTestCase):
    """Panels and buttons keep their gloss inside the rounded shape."""

    def test_panel_corner_has_no_gloss_patch(self) -> None:
        """The panel art is transparent outside its rounded corners."""

        panel = ui.panel_surface((232, 190), (11, 20, 44, 205), (88, 132, 206), 28)
        for corner in ((1, 1), (230, 1), (1, 188), (230, 188)):
            with self.subTest(corner=corner):
                self.assertEqual(panel.get_at(corner).a, 0)
        self.assertGreater(panel.get_at((116, 95)).a, 150)

    def test_button_shine_is_translucent(self) -> None:
        """The shine bar blends at alpha 42 instead of drawing solid white."""

        class Assets:
            """Minimal stand-in exposing the one font a button needs."""

            ui_font = pygame.font.Font(None, 34)

        target = pygame.Surface((300, 120))
        target.fill((0, 0, 0))
        button = ui.Button(pygame.Rect(40, 30, 220, 60), "Go")
        button.draw(target, Assets(), (-1, -1))
        shine = target.get_at((button.rect.centerx - 60, button.rect.y + 10))
        self.assertLess(max(shine.r, shine.g, shine.b), 160)


class BubbleGlowTests(UiTestCase):
    """The bubble's outer glow stays round instead of being cut off flat."""

    def test_glow_reaches_past_the_old_clip_on_every_side(self) -> None:
        """Glow pixels exist 18 px outside the rim to the left, right and below."""

        target = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        target.fill((0, 0, 0))
        ui.draw_playfield(target, 0.0)
        cx, cy = PLAYFIELD_CENTER
        reach = CONTAINER_RADIUS + 18
        for name, point in (("left", (cx - reach, cy)), ("right", (cx + reach, cy)), ("bottom", (cx, cy + reach))):
            with self.subTest(side=name):
                self.assertGreater(target.get_at(point).b, 20)


class FakeGame:
    """Just enough game state for the sidebar layout helpers."""

    def __init__(self, current_tier: int, next_tier: int) -> None:
        """Queue ``current_tier`` now and ``next_tier`` after it."""

        self.current_tier = current_tier
        self.next_tier = next_tier
        self.current_body_name = TIERS[current_tier].name
        self.next_body_name = TIERS[next_tier].name


class SidebarLayoutTests(UiTestCase):
    """The sidebar's text and previews fit their panels without overlapping."""

    # Real breathing room, never a one-pixel fit: content stays this far inside
    # each panel border, and previews stay this far from any label.
    PANEL_MARGIN = 10
    GAP = 3
    assets: AssetLibrary

    @classmethod
    def setUpClass(cls) -> None:
        """Build the real asset library (fonts and orb art) once."""

        super().setUpClass()
        cls.assets = AssetLibrary()

    def _orb_rect(self, slot) -> pygame.Rect:
        """Return the visible area of a preview orb, including its idle bob."""

        visible = self.assets.get_body_surface(slot.tier).get_bounding_rect()
        side = max(visible.w, visible.h) * slot.scale
        rect = pygame.Rect(0, 0, round(side), round(side) + 5)  # +5 covers the +-2.2 px bob
        rect.center = slot.center
        return rect

    def test_queue_previews_never_cover_labels(self) -> None:
        """For every spawnable current/next pair, orbs clear all text by a gap."""

        inner = ui.QUEUE_PANEL.inflate(-2 * self.PANEL_MARGIN, -2 * self.PANEL_MARGIN)
        for current in range(len(SPAWN_WEIGHTS)):
            for upcoming in range(len(SPAWN_WEIGHTS)):
                texts, slots = ui.queue_layout(self.assets, FakeGame(current, upcoming), ui.QUEUE_PANEL)
                with self.subTest(current=current, upcoming=upcoming):
                    orbs = [self._orb_rect(slot) for slot in slots]
                    for orb in orbs:
                        self.assertTrue(inner.contains(orb), orb)
                        for _, text in texts:
                            self.assertFalse(orb.inflate(2 * self.GAP, 2 * self.GAP).colliderect(text), (orb, text))
                    self.assertFalse(orbs[0].colliderect(orbs[1]))
                    for _, text in texts:
                        self.assertTrue(inner.contains(text), text)

    def test_queue_labels_fit_for_every_tier_name(self) -> None:
        """Even the longest tier name stays inside the queue panel."""

        inner = ui.QUEUE_PANEL.inflate(-2 * self.PANEL_MARGIN, -2 * self.PANEL_MARGIN)
        for tier in range(len(TIERS)):
            game = FakeGame(0, 0)
            game.current_body_name = game.next_body_name = TIERS[tier].name
            texts, _ = ui.queue_layout(self.assets, game, ui.QUEUE_PANEL)
            for _, text in texts:
                with self.subTest(tier=tier):
                    self.assertTrue(inner.contains(text), text)

    def test_control_rows_fit_the_panel(self) -> None:
        """Keys and actions stay inside the controls panel and never touch."""

        inner = ui.INFO_PANEL.inflate(-2 * self.PANEL_MARGIN, -2 * self.PANEL_MARGIN)
        items = ui.control_rows(self.assets, ui.INFO_PANEL)
        for keys, action in zip(items[0::2], items[1::2], strict=True):
            with self.subTest(row=keys[1].y):
                self.assertTrue(inner.contains(keys[1]), keys[1])
                self.assertTrue(inner.contains(action[1]), action[1])
                self.assertGreaterEqual(action[1].left - keys[1].right, 8)

    def test_backplate_halo_is_not_clipped(self) -> None:
        """The outer halo ring (out to ``radius + 6``) is drawn, not cut off."""

        target = pygame.Surface((200, 200), pygame.SRCALPHA)
        ui.draw_preview_backplate(target, (100, 100), 50, (110, 185, 255))
        self.assertGreater(target.get_at((100 + 50 + 4, 100)).a, 0)
        self.assertGreater(target.get_at((100, 100 - 50 - 4)).a, 0)


class ModalLayoutTests(UiTestCase):
    """Menu and game-over modals hold their text and buttons with room to spare."""

    TEXT_MARGIN = 24
    BUTTON_MARGIN = 16

    @classmethod
    def setUpClass(cls) -> None:
        """Build the real asset library (fonts) once."""

        super().setUpClass()
        cls.assets = AssetLibrary()

    assets: AssetLibrary

    def _check(self, modal: pygame.Rect, texts, buttons: list[ui.Button]) -> None:
        """Assert texts and buttons sit inside ``modal`` and never overlap each other."""

        text_area = modal.inflate(-2 * self.TEXT_MARGIN, -2 * self.TEXT_MARGIN)
        button_area = modal.inflate(-2 * self.BUTTON_MARGIN, -2 * self.BUTTON_MARGIN)
        rects = [rect for _, rect in texts]
        for rect in rects:
            self.assertTrue(text_area.contains(rect), (rect, text_area))
        for button in buttons:
            self.assertTrue(button_area.contains(button.rect), (button.rect, button_area))
            for rect in rects:
                self.assertFalse(button.rect.colliderect(rect), (button.rect, rect))
        everything = rects + [button.rect for button in buttons]
        for index, first in enumerate(everything):
            for second in everything[index + 1 :]:
                self.assertFalse(first.colliderect(second), (first, second))

    def test_menu_layout(self) -> None:
        """The title, tips, stats and Start button all fit inside the menu modal."""

        button = ui.Button(pygame.Rect(0, 0, 10, 10), "Start Run")
        ui.place_menu_buttons([button])
        texts = ui.menu_texts(self.assets, 123_456, 9_999, "Quasar Crown")
        self._check(ui.MENU_MODAL, texts, [button])

    def test_game_over_layout(self) -> None:
        """Score, status, stats and both buttons fit inside the game-over modal."""

        buttons = [ui.Button(pygame.Rect(0, 0, 10, 10), label) for label in ("Play Again", "Main Menu")]
        ui.place_game_over_buttons(buttons)
        for new_record in (False, True):
            with self.subTest(new_record=new_record):
                texts = ui.game_over_texts(self.assets, 987_654, 987_654, new_record, 9_999, "Quasar Crown")
                self._check(ui.GAME_OVER_MODAL, texts, buttons)

    def test_in_run_modals_clear_the_sidebar(self) -> None:
        """Each modal, with its 14 px glow, ends at least 8 px before the sidebar."""

        for name, modal in (("pause", ui.PAUSE_MODAL), ("game over", ui.GAME_OVER_MODAL)):
            with self.subTest(modal=name):
                self.assertLessEqual(modal.right + 14 + 8, SIDEBAR_X)
                self.assertGreaterEqual(modal.left - 14, 8)

    def test_pause_layout(self) -> None:
        """The pause title, hint and three buttons fit inside the pause modal."""

        buttons = [ui.Button(pygame.Rect(0, 0, 10, 10), label) for label in ("Resume", "Restart", "Main Menu")]
        ui.place_pause_buttons(buttons)
        self._check(ui.PAUSE_MODAL, ui.pause_texts(self.assets), buttons)


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


class DangerLabelTests(UiTestCase):
    """The danger-line label reads clearly over a busy stack."""

    def test_label_colours_have_strong_contrast(self) -> None:
        """The chosen text and backing colours contrast at least 7:1."""

        self.assertGreaterEqual(_contrast(ui.DANGER_LABEL_TEXT, ui.DANGER_LABEL_BACKING), 7.0)

    def test_label_sits_on_a_dark_backing(self) -> None:
        """Over a white backdrop, the label's backing pill is dark."""

        target = pygame.Surface((400, 200))
        target.fill((255, 255, 255))
        rect = ui.draw_danger_label(target, pygame.font.Font(None, 28), (200, 100))
        backing = target.get_at((rect.x + 4, rect.centery))
        self.assertLess(max(backing.r, backing.g, backing.b), 120)


class DangerLabelPlacementTests(UiTestCase):
    """The danger label never covers the launcher orb or its aim line."""

    def test_label_avoids_the_launcher_everywhere(self) -> None:
        """Across tiers, launcher positions and aim angles the label stays clear and inside the bubble."""

        world = PhysicsWorld()
        size = pygame.font.Font(None, 26).size("Danger line")
        center = pygame.Vector2(PLAYFIELD_CENTER)
        for tier in range(len(SPAWN_WEIGHTS)):
            radius = TIERS[tier].radius
            low, high = world.allowed_spawn_x(radius)
            for step in range(9):
                spawn = world.spawn_point(low + (high - low) * step / 8, radius)
                for angle in range(-60, 61, 10):
                    direction = pygame.Vector2(0, 1).rotate(-angle)
                    back, front = spawn - direction * 64.0, spawn + direction * 166.0
                    rect = ui.danger_label_rect(size, spawn, radius, back, front)
                    with self.subTest(tier=tier, step=step, angle=angle):
                        orb = pygame.Rect(0, 0, radius * 2, radius * 2)
                        orb.center = (round(spawn.x), round(spawn.y))
                        clear = rect.inflate(8, 8)
                        self.assertFalse(clear.colliderect(orb), (rect, orb))
                        self.assertFalse(clear.clipline(back, front), (rect, back, front))
                        for corner in (rect.topleft, rect.topright, rect.bottomleft, rect.bottomright):
                            self.assertLess((pygame.Vector2(corner) - center).length(), CONTAINER_RADIUS - 8)


class MenuBackdropTests(UiTestCase):
    """The main menu dims the playfield behind it."""

    def test_menu_veils_the_scene(self) -> None:
        """Pixels far outside the menu modal are darkened by a veil."""

        target = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        target.fill((255, 255, 255))
        assets = AssetLibrary()
        ui.draw_menu_overlay(target, assets, [], 0, 0, "Spark Dust", (-1, -1))
        corner = target.get_at((10, SCREEN_HEIGHT - 10))
        self.assertLess(corner.r, 200)


if __name__ == "__main__":
    unittest.main()
