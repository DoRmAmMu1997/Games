"""Headless shell tests: the action bar, dialogs and buttons the human clicks.

These drive `MonopolyApp` under the SDL dummy driver. Clicks go through the
real path -- draw a frame, then click a button's centre -- so a button that
is drawn but not wired (or wired but not drawn) fails here.
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
from test_raise_funds import collect_each_debt, rent_debt

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
