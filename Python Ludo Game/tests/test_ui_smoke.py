"""Headless pygame wiring checks for the Ludo app."""

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

import main as ludo_main
from game import LudoGame, LudoRules
from main import LudoApp, _name_rect


class UiSmokeTests(unittest.TestCase):
    """Small pygame checks that catch broken imports and screen wiring."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once for this test class."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame resources after the smoke tests."""

        pygame.quit()

    def test_setup_buttons_expose_player_and_rule_controls(self) -> None:
        """The setup screen should expose the expected controls."""

        app = LudoApp()
        try:
            keys = {button.key for button in app.setup_buttons()}
            self.assertIn("total_players_next", keys)
            self.assertIn("human_count_next", keys)
            self.assertIn("ai_profile_next", keys)
            self.assertIn("toggle_blockades", keys)
            self.assertIn("start", keys)
        finally:
            app.running = False

    def test_setup_option_rows_keep_labels_values_and_buttons_aligned(self) -> None:
        """Setup option labels, values, and buttons should share row geometry."""

        row_helper = getattr(ludo_main, "_setup_option_row", None)
        self.assertIsNotNone(row_helper)

        app = LudoApp()
        try:
            buttons = {button.key: button for button in app.setup_buttons()}
            rows = [
                (0, "total_players_prev", "total_players_next"),
                (1, "human_count_prev", "human_count_next"),
                (2, "ai_profile_prev", "ai_profile_next"),
            ]
            for offset, (row_index, left_key, right_key) in enumerate(rows):
                with self.subTest(row=row_index):
                    row = row_helper(row_index)
                    left_button = buttons[left_key].rect
                    right_button = buttons[right_key].rect

                    self.assertEqual(left_button, row.left_button)
                    self.assertEqual(right_button, row.right_button)
                    self.assertLessEqual(row.label_y + app.fonts["body"].get_height(), row.control_y)
                    self.assertEqual(row.value_center[1], left_button.centery)
                    self.assertEqual(row.value_center[1], right_button.centery)

                    if offset + 1 < len(rows):
                        next_row = row_helper(row_index + 1)
                        self.assertLessEqual(left_button.bottom, next_row.label_y)
                        self.assertLessEqual(right_button.bottom, next_row.label_y)
        finally:
            app.running = False

    def test_setup_name_fields_do_not_overlap_buttons_for_large_human_counts(self) -> None:
        """Name fields must stay clear of buttons even with every seat human."""

        app = LudoApp()
        try:
            for human_count in (4, 5, 6):
                with self.subTest(human_count=human_count):
                    app.total_players = human_count
                    app.human_count = human_count
                    buttons = app.setup_buttons()
                    for index in range(human_count):
                        name_rect = _name_rect(index)
                        for button in buttons:
                            self.assertFalse(
                                name_rect.colliderect(button.rect),
                                f"Player {index + 1} name field {name_rect} overlaps "
                                f"{button.key} button {button.rect}.",
                            )
        finally:
            app.running = False

    def test_scaled_window_size_fits_short_work_area(self) -> None:
        """The real window should shrink when the desktop is shorter than the logical layout."""

        fit_window = getattr(ludo_main, "_fit_window_size", None)
        self.assertIsNotNone(fit_window)

        window_size = fit_window((1536, 816), (0, 0))

        self.assertLessEqual(window_size[0], 1536)
        self.assertLessEqual(window_size[1], 816)
        self.assertAlmostEqual(window_size[0] / window_size[1], 1280 / 900, delta=0.02)

    def test_scaled_mouse_coordinates_can_reach_bottom_buttons(self) -> None:
        """Scaled display clicks should map back to logical bottom-button rectangles."""

        fit_window = getattr(ludo_main, "_fit_window_size", None)
        logical_to_window = getattr(ludo_main, "_logical_to_window_point", None)
        window_to_logical = getattr(ludo_main, "_window_to_logical_point", None)
        self.assertIsNotNone(fit_window)
        self.assertIsNotNone(logical_to_window)
        self.assertIsNotNone(window_to_logical)

        display_size = fit_window((1536, 816), (0, 0))
        app = LudoApp()
        try:
            setup_buttons = {button.key: button for button in app.setup_buttons()}
            for key in ("resume", "start"):
                with self.subTest(screen="setup", button=key):
                    window_point = logical_to_window(setup_buttons[key].rect.center, display_size)
                    logical_point = window_to_logical(window_point, display_size)
                    self.assertTrue(setup_buttons[key].rect.collidepoint(logical_point))

            app.screen = "playing"
            players = [(f"P{i + 1}", i == 0) for i in range(4)]
            app.game = LudoGame(players, LudoRules(total_players=4), seed=7)
            play_buttons = {button.key: button for button in app._buttons_for_screen()}
            for key in ("save_quit", "new_game"):
                with self.subTest(screen="playing", button=key):
                    window_point = logical_to_window(play_buttons[key].rect.center, display_size)
                    logical_point = window_to_logical(window_point, display_size)
                    self.assertTrue(play_buttons[key].rect.collidepoint(logical_point))
        finally:
            app.running = False

    def test_autotest_frames_can_render_without_crashing(self) -> None:
        """The app should draw a few headless frames successfully."""

        app = LudoApp()
        try:
            app.run(max_frames=3)
        finally:
            app.running = False


if __name__ == "__main__":
    unittest.main()
