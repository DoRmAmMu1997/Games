"""Layout checks for the in-game HUD around the Ludo boards.

The HUD (move buttons, table log, dice tray, and table buttons) must never
cover anything on the board: yard parking slots, track cells, home-lane cells,
or the players' name banners. Every check runs for the 4P, 5P, and 6P boards.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import pygame

import main
from board_render import BoardRenderer, DisplayCell
from game import LudoGame, LudoRules

# Yard parking slots are drawn as rings of this radius (see _draw_yard_slots).
YARD_SLOT_RADIUS = 24


def make_game(total_players: int) -> LudoGame:
    """Create a deterministic game with seat 0 human and the rest AI."""

    players = [(f"P{i + 1}", i == 0) for i in range(total_players)]
    return LudoGame(players, LudoRules(total_players=total_players), seed=9)


def cell_rect(center: tuple[float, float], size: float, cell: DisplayCell | None = None) -> pygame.Rect:
    """Return the screen rectangle covered by one board cell."""

    if cell is not None:
        xs = [point[0] for point in cell.corners]
        ys = [point[1] for point in cell.corners]
        return pygame.Rect(int(min(xs)), int(min(ys)), int(max(xs) - min(xs)) + 1, int(max(ys) - min(ys)) + 1)
    rect = pygame.Rect(0, 0, int(size), int(size))
    rect.center = (int(center[0]), int(center[1]))
    return rect


def board_rects(renderer: BoardRenderer) -> list[tuple[str, pygame.Rect]]:
    """Return labelled rectangles for every yard slot, cell, lane cell, and banner."""

    display = renderer.display
    rects: list[tuple[str, pygame.Rect]] = []
    for seat, slots in enumerate(display.yard_positions):
        for slot, point in enumerate(slots):
            rect = pygame.Rect(0, 0, 2 * YARD_SLOT_RADIUS, 2 * YARD_SLOT_RADIUS)
            rect.center = (int(point[0]), int(point[1]))
            rects.append((f"seat {seat} yard slot {slot}", rect))
    for index, point in enumerate(display.track_positions):
        cell = display.track_cells[index] if display.track_cells else None
        rects.append((f"track cell {index}", cell_rect(point, display.cell_size, cell)))
    for seat, lane in enumerate(display.home_lanes):
        for index, point in enumerate(lane):
            cell = display.home_lane_cells[seat][index] if display.home_lane_cells else None
            rects.append((f"seat {seat} lane cell {index}", cell_rect(point, display.cell_size, cell)))
    for seat, rect in enumerate(renderer.banner_rects()):
        rects.append((f"seat {seat} banner", rect))
    return rects


class HudLayoutTests(unittest.TestCase):
    """The play-screen HUD lives beside the board, never on top of it."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once for the HUD layout checks."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the HUD layout checks."""

        pygame.quit()

    def hud_rects(self) -> list[tuple[str, pygame.Rect]]:
        """Return every play-screen HUD rectangle, with all four move buttons shown."""

        rects = [(f"move button {index}", main._move_button_rect(index)) for index in range(4)]
        rects += [
            ("table log", main.PLAY_LOG_RECT),
            ("dice tray", main.PLAY_DICE_TRAY_RECT),
            ("roll button", main.PLAY_ROLL_RECT),
            ("save button", main.PLAY_SAVE_RECT),
            ("new button", main.PLAY_NEW_RECT),
        ]
        return rects

    def test_hud_never_covers_the_board(self) -> None:
        """No HUD rect intersects a yard slot, cell, lane cell, or banner."""

        for count in (4, 5, 6):
            renderer = BoardRenderer(make_game(count).layout)
            for board_name, board_rect in board_rects(renderer):
                for hud_name, hud_rect in self.hud_rects():
                    with self.subTest(total_players=count, hud=hud_name, board=board_name):
                        self.assertFalse(hud_rect.colliderect(board_rect), f"{hud_name} {hud_rect} covers {board_rect}")

    def test_move_buttons_and_log_sit_in_the_right_column_below_the_roster(self) -> None:
        """Move buttons and the log live in the free column under a full 6-player roster."""

        roster_bottom = main.PLAY_ROSTER_Y + 5 * main.PLAY_ROSTER_STEP + main.PLAY_ROSTER_CHIP_HEIGHT
        for name, rect in self.hud_rects()[:5]:
            with self.subTest(hud=name):
                self.assertGreaterEqual(rect.x, main.PLAY_ROSTER_X)
                self.assertGreater(rect.y, roster_bottom)
                self.assertLessEqual(rect.right, main.SCREEN_WIDTH)
                self.assertLessEqual(rect.bottom, main.SCREEN_HEIGHT)

    def test_click_inside_each_hud_button_runs_that_button(self) -> None:
        """Clicking the centre of a play-screen button triggers exactly that button."""

        with mock.patch.object(main, "save_game") as save_game:
            app = main.LudoApp()
            try:
                game = make_game(4)
                app.start_game(game)
                app._handle_click(main.PLAY_ROLL_RECT.center)
                self.assertEqual(game.total_rolls, 1, "roll button did not roll")

                game = make_game(4)
                app.start_game(game)
                game.record_roll(6)
                app._refresh_visible_moves()
                app._handle_click(main._move_button_rect(1).center)
                self.assertEqual(game.players[0].tokens[1].steps, 0, "move button 2 did not enter token 2")

                saves_before = save_game.call_count
                app._handle_click(main.PLAY_SAVE_RECT.center)
                self.assertEqual(app.screen, "setup")
                self.assertEqual(save_game.call_count, saves_before + 1, "save button did not save")

                app.start_game(make_game(4))
                app._handle_click(main.PLAY_NEW_RECT.center)
                self.assertEqual(app.screen, "setup")
            finally:
                app.running = False


if __name__ == "__main__":
    unittest.main()
