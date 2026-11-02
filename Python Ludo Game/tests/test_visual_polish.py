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
import ui
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


class SetupPanelTests(unittest.TestCase):
    """The setup column fits inside its dark panel even with six human names."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once for the setup-panel checks."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the setup-panel checks."""

        pygame.quit()

    def test_six_human_setup_fits_inside_the_panel(self) -> None:
        """Every setup button and name field sits at least 8 px inside the panel."""

        app = main.LudoApp(persist=False)
        self.addCleanup(setattr, app, "running", False)
        app.total_players = 6
        app.human_count = 6
        inner = main.SETUP_PANEL_RECT.inflate(-16, -16)
        rects = [(button.key, button.rect) for button in app.setup_buttons()]
        rects += [(f"name {index + 1}", main._name_rect(index)) for index in range(6)]
        for name, rect in rects:
            with self.subTest(control=name):
                self.assertTrue(inner.contains(rect), f"{name} {rect} leaves the panel {inner}")

    def test_section_headers_leave_a_gap_above_their_controls(self) -> None:
        """Each section header ends at least SETUP_HEADER_GAP px above its first control.

        Beginner note: the same font size renders at different line heights
        on different machines (28 px FreeSans here, about 32 px Arial on
        Windows, 33 px DejaVu Sans on some Linux CI runners). So the layout
        reserves SETUP_HEADER_LINE_ALLOWANCE for the header line, and this
        test checks both this machine's real font and that allowance, so a
        near miss fails everywhere, not only on the tallest-font platform.
        """

        app = main.LudoApp(persist=False)
        self.addCleanup(setattr, app, "running", False)
        header_height = app.fonts["header"].get_height()
        gap = main.SETUP_HEADER_GAP
        self.assertLessEqual(header_height, main.SETUP_HEADER_LINE_ALLOWANCE, "header font outgrew the layout")
        buttons = {button.key: button.rect for button in app.setup_buttons()}
        sections = (
            ("Advanced Rules", main.SETUP_RULES_HEADER_Y, buttons["toggle_blockades"].y),
            ("Human Names", main.SETUP_NAME_HEADER_Y, main._name_rect(0).y),
        )
        for name, header_y, control_y in sections:
            with self.subTest(header=name):
                self.assertLessEqual(header_y + header_height + gap, control_y, "measured header touches its control")
                self.assertLessEqual(
                    header_y + main.SETUP_HEADER_LINE_ALLOWANCE + gap, control_y, "no room for a taller header font"
                )
        self.assertLessEqual(main._setup_option_row(2).left_button.bottom + gap, main.SETUP_RULES_HEADER_Y)
        self.assertLessEqual(buttons["toggle_three_sixes"].bottom + gap, main.SETUP_NAME_HEADER_Y)


def luminance(color) -> float:
    """Return perceived brightness of an RGB colour, 0 (black) to 255 (white)."""

    return 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]


class ButtonStateTests(unittest.TestCase):
    """A disabled button reads as switched off: darker and dimmer than an idle one."""

    fonts: dict[str, pygame.font.Font]

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame and fonts once for the button checks."""

        pygame.init()
        cls.fonts = ui.make_fonts()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the button checks."""

        pygame.quit()

    def render(self, enabled: bool) -> tuple[pygame.Surface, pygame.Rect]:
        """Draw one button, not hovered, and return the surface and its rect."""

        surface = pygame.Surface((300, 80))
        rect = pygame.Rect(20, 20, 246, 34)
        ui.Button(rect, "Resume Saved Game", "resume", enabled=enabled).draw(surface, self.fonts, (0, 0))
        return surface, rect

    def test_disabled_fill_is_darker_than_an_enabled_fill(self) -> None:
        """The disabled background is never brighter than an idle enabled background."""

        enabled, rect = self.render(True)
        disabled, _rect = self.render(False)
        sample = (rect.x + 8, rect.centery)
        self.assertLess(luminance(disabled.get_at(sample)), luminance(enabled.get_at(sample)) + 1)

    def test_disabled_label_is_dimmed(self) -> None:
        """A disabled button draws no near-white label pixels."""

        surface, rect = self.render(False)
        brightest = max(
            luminance(surface.get_at((x, y))) for x in range(rect.x, rect.right) for y in range(rect.y, rect.bottom)
        )
        self.assertLess(brightest, 170)


if __name__ == "__main__":
    unittest.main()
