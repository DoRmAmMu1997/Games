"""Save, load, and stats persistence checks for the Ludo app shell.

Every test here points the app's save paths at a throwaway temp folder, so the
suite never reads or writes the real ``%APPDATA%\\Ludo`` folder.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import pygame

import main
from game import LudoGame, LudoRules


def make_game(total_players: int = 4) -> LudoGame:
    """Create a deterministic game whose save data the tests can damage."""

    players = [(f"P{i + 1}", i == 0) for i in range(total_players)]
    return LudoGame(players, LudoRules(total_players=total_players), seed=5)


class TempSaveDirTestCase(unittest.TestCase):
    """Base class that redirects every save path into a fresh temp folder."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once so the app can open its dummy window."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after this class's tests finish."""

        pygame.quit()

    def setUp(self) -> None:
        """Patch main's save folder, savegame, and stats paths into a temp dir."""

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.save_dir = Path(temp.name) / "Ludo"
        self.savegame_path = self.save_dir / "savegame.json"
        self.stats_path = self.save_dir / "stats.json"
        for name, value in (
            ("SAVE_DIR", self.save_dir),
            ("SAVEGAME_PATH", self.savegame_path),
            ("STATS_PATH", self.stats_path),
        ):
            patcher = mock.patch.object(main, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_save(self, payload: object) -> None:
        """Write ``payload`` as the on-disk savegame JSON."""

        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.savegame_path.write_text(json.dumps(payload), encoding="utf-8")


class CorruptSaveResumeTests(TempSaveDirTestCase):
    """Resuming a damaged save keeps the player on setup instead of crashing."""

    def test_resume_with_corrupt_save_stays_on_setup(self) -> None:
        """Each damaged savegame loads as None and the Resume button does nothing."""

        def last_roll_infinite() -> dict:
            """Return a valid save whose last roll is an infinite number."""

            data = make_game().to_dict()
            data["last_roll"] = float("inf")
            return data

        def token_entry_is_list() -> dict:
            """Return a valid save where one token entry is a list, not an object."""

            data = make_game().to_dict()
            data["players"][0]["tokens"][0] = [3]
            return data

        cases = {
            "top-level list": [make_game().to_dict()],
            "top-level null": None,
            "infinite last_roll": last_roll_infinite(),
            "token entry is a list": token_entry_is_list(),
        }
        for name, payload in cases.items():
            with self.subTest(case=name):
                self.write_save(payload)
                self.assertIsNone(main.load_saved_game())
                app = main.LudoApp()
                app._on_setup_button("resume")
                self.assertEqual(app.screen, "setup")
                self.assertIsNone(app.game)


if __name__ == "__main__":
    unittest.main()
