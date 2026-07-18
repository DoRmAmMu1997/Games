"""Visual regression checks for the Ludo-inspired game overhaul."""

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

from board_render import BoardRenderer
from game import LudoGame, LudoRules
from settings import PANEL_X, SCREEN_HEIGHT, SCREEN_WIDTH, seat_colors


def make_game(total_players: int) -> LudoGame:
    """Create a deterministic game with every seat visible to the renderer."""

    players = [(f"Player {index + 1}", index == 0) for index in range(total_players)]
    return LudoGame(players, LudoRules(total_players=total_players), seed=total_players)


def count_near_color(surface: pygame.Surface, color: tuple[int, int, int], tolerance: int = 58) -> int:
    """Count sampled pixels close to ``color`` without scanning every pixel."""

    matches = 0
    for x in range(0, surface.get_width(), 8):
        for y in range(0, surface.get_height(), 8):
            pixel = surface.get_at((x, y))[:3]
            if sum(abs(pixel[channel] - color[channel]) for channel in range(3)) <= tolerance:
                matches += 1
    return matches


class VisualOverhaulTests(unittest.TestCase):
    """Checks that the game now renders as a themed Ludo board, not a plain diagram."""

    fonts: dict[str, pygame.font.Font]

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once for visual smoke tests."""

        pygame.init()
        cls.fonts = {
            "huge": pygame.font.SysFont("arial", 58, bold=True),
            "title": pygame.font.SysFont("arial", 44, bold=True),
            "header": pygame.font.SysFont("arial", 28, bold=True),
            "body": pygame.font.SysFont("arial", 22),
            "small": pygame.font.SysFont("arial", 18),
            "tiny": pygame.font.SysFont("arial", 15),
            "button": pygame.font.SysFont("arial", 19, bold=True),
        }

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the visual smoke tests finish."""

        pygame.quit()

    def test_theme_module_exposes_board_game_art_helpers(self) -> None:
        """A separate theme module should own reusable art helpers."""

        import visual_theme

        for helper_name in (
            "draw_ludo_wallpaper",
            "draw_player_banner",
            "draw_token_pin",
            "draw_dice_tray",
        ):
            self.assertTrue(hasattr(visual_theme, helper_name), helper_name)

    def test_boards_for_all_player_counts_show_wallpaper_and_player_colours(self) -> None:
        """Each supported board should render a vibrant themed arena."""

        import visual_theme

        for total_players in (4, 5, 6):
            with self.subTest(total_players=total_players):
                surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
                visual_theme.draw_ludo_wallpaper(surface)
                game = make_game(total_players)
                BoardRenderer(game.layout).draw(surface, game, self.fonts)

                self.assertGreater(count_near_color(surface, visual_theme.WALLPAPER_BLUE), 140)
                for color in seat_colors(total_players):
                    self.assertGreater(count_near_color(surface, color), 20)

    def test_play_screen_buttons_live_in_world_hud_not_right_sidebar(self) -> None:
        """Gameplay controls should sit in the board world instead of the old sidebar."""

        from main import LudoApp

        app = LudoApp()
        try:
            app.start_game(make_game(4))
            buttons = {button.key: button for button in app._buttons_for_screen()}

            self.assertLess(buttons["save_quit"].rect.centerx, PANEL_X)
            self.assertLess(buttons["new_game"].rect.centerx, PANEL_X)
        finally:
            app.running = False
