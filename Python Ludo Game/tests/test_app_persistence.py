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
from settings import AUTOTEST_FRAMES, AUTOTEST_SEED


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


class StatsRepairTests(TempSaveDirTestCase):
    """Damaged lifetime stats are repaired field by field instead of crashing."""

    def write_stats(self, payload: object) -> None:
        """Write ``payload`` as the on-disk stats JSON."""

        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.stats_path.write_text(json.dumps(payload), encoding="utf-8")

    def malformed_stats(self) -> dict:
        """Return stats with one bad value of each awkward kind, plus good ones to keep."""

        return {
            "games": None,
            "human_wins": "x",
            "ai_wins": float("inf"),
            "turn_total": [12],
            "by_player_count": {"4": None, "5": 3, "6": "y"},
        }

    def test_malformed_counters_and_buckets_fall_back_to_zero(self) -> None:
        """None, "x", inf, a list, and null buckets become 0; good values survive."""

        self.write_stats(self.malformed_stats())

        stats = main.load_stats()

        self.assertEqual(
            {key: stats[key] for key in ("games", "human_wins", "ai_wins", "turn_total")},
            {"games": 0, "human_wins": 0, "ai_wins": 0, "turn_total": 0},
        )
        self.assertEqual(stats["by_player_count"], {"4": 0, "5": 3, "6": 0})

    def test_repairs_are_logged_by_field_name(self) -> None:
        """Each repaired field is named in error.log so a bad file can be traced."""

        self.write_stats(self.malformed_stats())

        main.load_stats()

        log = (self.save_dir / "error.log").read_text(encoding="utf-8")
        for field in ("games", "human_wins", "ai_wins", "turn_total", "by_player_count[4]", "by_player_count[6]"):
            with self.subTest(field=field):
                self.assertIn(f"'{field}'", log)
        self.assertNotIn("by_player_count[5]", log)

    def test_valid_stats_load_without_logging(self) -> None:
        """A healthy stats file loads as-is and writes nothing to error.log."""

        good = {"games": 4, "human_wins": 1, "ai_wins": 3, "turn_total": 400,
                "by_player_count": {"4": 2, "5": 1, "6": 1}}
        self.write_stats(good)

        self.assertEqual(main.load_stats(), good)
        self.assertFalse((self.save_dir / "error.log").exists())

    def test_game_over_with_malformed_stats_does_not_crash(self) -> None:
        """Finishing a game records and shows stats even when the file was damaged."""

        self.write_stats(self.malformed_stats())
        app = main.LudoApp()
        game = make_game()
        tokens = game.players[0].tokens
        for token in tokens:
            token.steps = game.layout.finish_steps
        tokens[3].steps = game.layout.finish_steps - 1
        app.start_game(game)
        game.record_roll(1)

        app._apply_move(game.legal_moves(1)[0])
        app._update(False)
        app._draw()

        self.assertEqual(app.screen, "over")
        self.assertEqual(app.stats["games"], 1)
        self.assertEqual(app.stats["human_wins"], 1)
        self.assertEqual(app.stats["by_player_count"]["4"], 1)


class PersistFlagTests(TempSaveDirTestCase):
    """An app opened with persist=False never writes or deletes save files."""

    def seed_files(self) -> dict[str, bytes]:
        """Write a savegame and stats file, returning every file's bytes by name."""

        self.write_save(make_game().to_dict())
        self.stats_path.write_text(json.dumps(main.load_stats()), encoding="utf-8")
        return self.snapshot()

    def snapshot(self) -> dict[str, bytes]:
        """Return the bytes of every file currently in the temp save folder."""

        return {path.name: path.read_bytes() for path in sorted(self.save_dir.iterdir())}

    def test_default_app_does_write_its_save(self) -> None:
        """Control: a normal app overwrites the save when a new game starts."""

        before = self.seed_files()
        app = main.LudoApp()
        app._on_setup_button("start")
        self.assertNotEqual(self.snapshot()["savegame.json"], before["savegame.json"])

    def test_persist_false_leaves_save_and_stats_untouched(self) -> None:
        """Starting, autosaving, Save, Esc, and finishing a game write nothing to disk."""

        before = self.seed_files()
        app = main.LudoApp(persist=False)

        app._on_setup_button("start")
        app._roll_for_human()
        app._on_play_button("save_quit")
        app._on_setup_button("start")
        app._handle_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0))

        game = make_game()
        for token in game.players[0].tokens:
            token.steps = game.layout.finish_steps
        game.players[0].tokens[3].steps = game.layout.finish_steps - 1
        app.start_game(game)
        game.record_roll(1)
        app._apply_move(game.legal_moves(1)[0])
        app._update(False)

        self.assertEqual(app.screen, "over")
        self.assertEqual(app.stats["games"], 1, "stats should still be tracked in memory")
        self.assertEqual(self.snapshot(), before)


class AutotestTests(TempSaveDirTestCase):
    """LUDO_AUTOTEST plays a seeded all-AI game and leaves saves alone."""

    def test_autotest_plays_without_touching_seeded_saves(self) -> None:
        """The autotest plays real AI turns, yet the seeded files stay byte-identical."""

        self.write_save(make_game().to_dict())
        self.stats_path.write_text(json.dumps(main.load_stats()), encoding="utf-8")
        before = {path.name: path.read_bytes() for path in sorted(self.save_dir.iterdir())}
        apps: list[main.LudoApp] = []
        original_run = main.LudoApp.run

        def spy_run(app: main.LudoApp, max_frames: int | None = None) -> None:
            """Remember the autotest's app, then run it for real."""

            apps.append(app)
            original_run(app, max_frames=max_frames)

        self.addCleanup(pygame.init)  # main() quits pygame on the way out
        with (
            mock.patch.dict(os.environ, {"LUDO_AUTOTEST": "1"}),
            mock.patch.object(main.LudoApp, "run", autospec=True, side_effect=spy_run) as run,
        ):
            main.main()

        self.assertEqual(run.call_args.kwargs["max_frames"], AUTOTEST_FRAMES)
        app = apps[0]
        self.assertFalse(app.persist)
        assert app.game is not None
        self.assertEqual(app.game.seed, AUTOTEST_SEED)
        self.assertFalse(any(player.is_human for player in app.game.players))
        self.assertGreater(app.game.total_rolls, 0, "the autotest never rolled")
        after = {path.name: path.read_bytes() for path in sorted(self.save_dir.iterdir())}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
