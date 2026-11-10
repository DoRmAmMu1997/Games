"""Window icon loading: the bundled PNG first, the drawn icon as a fallback."""

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
from settings import ICON_FILE, ICON_SIZE


class WindowIconTests(unittest.TestCase):
    """The real icon ships next to main.py and loads; the fallback stays usable."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once so images can be decoded."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the icon checks."""

        pygame.quit()

    def test_icon_file_resolves_next_to_main_and_loads(self) -> None:
        """_resource_path finds ludo_icon.png beside main.py, and pygame can decode it."""

        path = main._resource_path(ICON_FILE)
        self.assertEqual(Path(path).parent, GAME_DIR)
        self.assertTrue(os.path.exists(path))
        self.assertIsInstance(pygame.image.load(path), pygame.Surface)

    def test_load_icon_returns_the_bundled_image(self) -> None:
        """_load_icon returns the full-size bundled PNG, not the drawn fallback."""

        self.assertEqual(main._load_icon().get_size(), (256, 256))

    def test_load_icon_falls_back_to_the_drawn_icon(self) -> None:
        """A missing icon file falls back to the procedural icon instead of crashing."""

        with mock.patch.object(main, "_resource_path", return_value=str(GAME_DIR / "missing_icon.png")):
            self.assertEqual(main._load_icon().get_size(), (ICON_SIZE, ICON_SIZE))

    def test_make_icon_is_64_pixels_square(self) -> None:
        """The procedural fallback icon is a 64x64 surface."""

        self.assertEqual(main._make_icon().get_size(), (64, 64))


if __name__ == "__main__":
    unittest.main()
