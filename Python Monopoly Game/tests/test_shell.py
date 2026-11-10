"""Headless shell tests: the action bar, dialogs and buttons the human clicks.

These drive `MonopolyApp` under the SDL dummy driver. Clicks go through the
real path -- draw a frame, then click a button's centre -- so a button that
is drawn but not wired (or wired but not drawn) fails here.
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
from test_raise_funds import collect_each_debt, rent_debt

import main
from game import MonopolyGame
from main import MonopolyApp


def click(app: MonopolyApp, key: str) -> None:
    """Draw a frame, then click the centre of the button with `key`."""
    app._draw()
    button = next(b for b in app.buttons if b.key == key)
    app._handle_click(button.rect.center)


def button_states(app: MonopolyApp) -> dict[str, bool]:
    """Draw a frame and return {button key: enabled} for what is on screen."""
    app._draw()
    return {button.key: button.enabled for button in app.buttons}


class ShellTestCase(unittest.TestCase):
    """Initialise pygame once per test class for the headless app."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start pygame under the dummy video driver."""
        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Shut pygame down after the class's tests."""
        pygame.quit()

    def make_app(self, game: MonopolyGame) -> MonopolyApp:
        """Return an app already playing `game`."""
        app = MonopolyApp()
        app.start_game(game)
        return app


class AppLifecycleTests(ShellTestCase):
    """Buttons that exist with no game in progress still work."""

    def test_quit_on_setup_screen_stops_the_app(self) -> None:
        """Quit on the setup screen closes the app instead of asserting on no game."""
        app = MonopolyApp()
        self.assertEqual(app.screen, "setup")

        click(app, "quit")

        self.assertFalse(app.running)


class SeededSaveDirTestCase(ShellTestCase):
    """Point the app's save files at a temp folder pre-seeded with real data."""

    def setUp(self) -> None:
        """Create a temp save folder holding stats and a saved game."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        (self.folder / "stats.json").write_text(json.dumps({"games": 3, "human_wins": 1}))
        (self.folder / "savegame.json").write_text(json.dumps(MonopolyGame([("A", True), ("B", False)]).to_dict()))
        for name, path in (("SAVE_DIR", self.folder), ("STATS_PATH", self.folder / "stats.json"),
                           ("SAVEGAME_PATH", self.folder / "savegame.json")):
            patcher = mock.patch.object(main, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def snapshot(self) -> dict[str, bytes]:
        """Return every file in the save folder with its exact bytes."""
        return {path.name: path.read_bytes() for path in self.folder.iterdir()}


class AutotestPersistenceTests(SeededSaveDirTestCase):
    """The headless self-test never touches the player's save or stats."""

    def test_autotest_leaves_seeded_save_folder_byte_identical(self) -> None:
        """MONOPOLY_AUTOTEST builds a non-persisting app: autosave, game over and stats write nothing."""
        before = self.snapshot()
        seen: list[MonopolyApp] = []

        def fast_run(app: MonopolyApp, max_frames: int | None = None) -> None:
            """Stand in for the 4000-frame run: autosave once, then finish the game."""
            seen.append(app)
            game = app._require_game()
            game.current = 1
            app._update(True)                    # a turn change would autosave
            for player in game.players[1:]:
                player.bankrupt = True
            game._check_for_winner()
            app._update(True)                    # game over would record stats, clear the save

        with mock.patch.dict(os.environ, {"MONOPOLY_AUTOTEST": "1"}), \
                mock.patch.object(MonopolyApp, "run", fast_run):
            main.main()
        pygame.init()                            # main() quits pygame on exit

        self.assertFalse(seen[0].persist)
        self.assertEqual(seen[0].screen, "over")
        self.assertEqual(self.snapshot(), before)

    def test_save_and_quit_writes_nothing_without_persistence(self) -> None:
        """A non-persisting app's Save & Quit leaves the save folder alone."""
        before = self.snapshot()
        app = MonopolyApp(persist=False)
        app.start_game(MonopolyGame([("Human", True), ("Iris", False)], seed=1))

        click(app, "save_quit")

        self.assertEqual(app.screen, "setup")
        self.assertEqual(self.snapshot(), before)


class CorruptFileTests(SeededSaveDirTestCase):
    """Damaged save files are logged and survived, never crash the app."""

    def test_malformed_stats_load_as_zeros_and_are_logged(self) -> None:
        """A stats file that is not a usable JSON object reads as no stats yet."""
        for text in ("[]", '"text"', '{"games": Infinity}'):
            with self.subTest(text=text):
                (self.folder / "stats.json").write_text(text)

                self.assertEqual(main.load_stats(), {"games": 0, "human_wins": 0})
                self.assertTrue((self.folder / "error.log").exists())

    def test_non_dict_save_is_set_aside_and_resume_disappears(self) -> None:
        """Resume on a save that is not a JSON object renames it to savegame.bad.json."""
        (self.folder / "savegame.json").write_text("[1, 2, 3]")
        app = MonopolyApp(persist=False)
        self.assertIn("resume", button_states(app))

        click(app, "resume")

        self.assertEqual(app.screen, "setup")
        self.assertNotIn("resume", button_states(app))
        self.assertEqual((self.folder / "savegame.bad.json").read_text(), "[1, 2, 3]")
        self.assertFalse((self.folder / "savegame.json").exists())
        self.assertTrue((self.folder / "error.log").exists())


class RaiseFundsBarTests(ShellTestCase):
    """The debtor gets Pay, Assets and Declare Bankruptcy while raising funds."""

    def test_raise_funds_bar_shows_amount_owed_and_disables_pay_until_covered(self) -> None:
        """Pay names the debt and stays disabled until the debtor's cash covers it."""
        app = self.make_app(rent_debt())

        states = button_states(app)

        self.assertEqual(set(states), {"pay_debts", "assets", "declare_bankruptcy"})
        self.assertFalse(states["pay_debts"])
        pay = next(b for b in app.buttons if b.key == "pay_debts")
        self.assertIn("$100", pay.label)
        self.assertIn("$60", app._prompt())

    def test_debtor_mortgages_in_assets_then_pays(self) -> None:
        """Clicking through the asset manager raises the cash; Pay then settles."""
        game = rent_debt()
        app = self.make_app(game)

        click(app, "assets")
        self.assertEqual(app.mode, "assets")
        click(app, "asset_mortgage")
        click(app, "asset_title_3")
        click(app, "asset_mortgage")
        click(app, "asset_close")
        self.assertTrue(button_states(app)["pay_debts"])
        click(app, "pay_debts")

        self.assertEqual(game.awaiting, "post_roll")
        self.assertEqual(game.players[0].cash, 0)
        self.assertIn("end_turn", button_states(app))

    def test_declare_bankruptcy_button_concedes_to_the_creditor(self) -> None:
        """Declare Bankruptcy hands the estate to the player owed."""
        game = rent_debt()
        app = self.make_app(game)

        click(app, "declare_bankruptcy")

        self.assertTrue(game.players[0].bankrupt)
        self.assertEqual(game.owners[1], 1)

    def test_non_current_debtor_gets_the_bar_and_their_own_titles(self) -> None:
        """A birthday debtor who is not the current player manages their own assets."""
        game = collect_each_debt()
        app = self.make_app(game)

        self.assertIn("pay_debts", button_states(app))
        click(app, "assets")
        self.assertEqual(app.asset_position, 1)
        click(app, "asset_mortgage")
        click(app, "asset_close")
        click(app, "pay_debts")

        self.assertEqual(game.awaiting, "post_roll")
        self.assertEqual(game.current, 2)
        self.assertEqual(game.players[0].cash, 25)


if __name__ == "__main__":
    unittest.main()
