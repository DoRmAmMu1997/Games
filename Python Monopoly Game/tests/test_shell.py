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
from test_engine_regressions import rig_rolls
from test_raise_funds import collect_each_debt, rent_debt

import board_render
import main
import ui
from game import MonopolyGame
from main import MonopolyApp
from settings import SCREEN_HEIGHT, SCREEN_WIDTH


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


class LayoutHelperTests(ShellTestCase):
    """Shared ui.py layout helpers keep drawn and clickable rects in step."""

    def test_every_action_bar_slot_sits_inside_the_bar(self) -> None:
        """All eight button slots fit inside the bar, and the bar inside the window."""
        bar = ui.action_bar_layout()["bar"]

        self.assertTrue(pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT).contains(bar))
        for slot in range(8):
            with self.subTest(slot=slot):
                self.assertTrue(bar.contains(ui.bar_slot_rect(slot)))

    def test_auction_buttons_use_the_shared_auction_layout(self) -> None:
        """Bid and Pass are built from ui.auction_layout and sit inside its panel."""
        game = MonopolyGame([("Human", True), ("Iris", False)], seed=1)
        game._start_auction(1)
        app = self.make_app(game)
        layout = ui.auction_layout()

        rects = {b.key: b.rect for b in app._playing_buttons()}

        self.assertEqual(rects, {"bid": layout["bid"], "pass": layout["pass"]})
        for rect in rects.values():
            self.assertTrue(layout["panel"].contains(rect))


def big_incoming_offer() -> MonopolyGame:
    """An AI offer to the human with eight titles a side, cash and mortgages."""
    game = MonopolyGame([("Human", True), ("Iris", False), ("Knox", False)], seed=3)
    theirs, mine = (5, 6, 8, 9, 11, 13, 14, 15), (21, 23, 24, 25, 26, 27, 29, 28)
    game.owners.update(dict.fromkeys(theirs, 1) | dict.fromkeys(mine, 0))
    game.mortgaged.update((5, 15, 21))
    game.current = 1
    game.pending_trade = {"from": 1, "to": 0,
                          "give": {"props": list(theirs), "cash": 120, "jail": 0},
                          "get": {"props": list(mine), "cash": 0, "jail": 0}}
    game._awaiting_before_trade = "post_roll"
    game.awaiting = "trade_response"
    return game


class TradeResponseDialogTests(ShellTestCase):
    """An incoming offer reads in two capped columns that never reach the buttons."""

    def test_offer_columns_cap_rows_and_stay_clear_of_the_buttons(self) -> None:
        """Long sides end in "+N more"; every line sits above panel.bottom - 64."""
        game = big_incoming_offer()
        layout = ui.trade_response_layout()
        assert game.pending_trade is not None
        plan = ui.trade_response_plan(game, game.pending_trade, ui.make_fonts())

        panel = layout["panel"]
        for _key, text, _color, rect in plan:
            with self.subTest(text=text):
                self.assertGreaterEqual(rect.left, panel.left + 20)
                self.assertLessEqual(rect.right, panel.right - 20)
                self.assertLessEqual(rect.bottom, panel.bottom - 64)
        texts = [text for _key, text, _color, _rect in plan]
        self.assertIn("+4 more", texts)      # 8 titles + cash: 5 shown, then "+4 more"
        self.assertIn("+3 more", texts)      # 8 titles: 5 shown, then "+3 more"
        self.assertTrue(any("interest" in text for text in texts))
        for column in ("receive", "give"):
            inside = [rect for _k, _t, _c, rect in plan if layout[column].collidepoint(rect.topleft)]
            self.assertLessEqual(len(inside), ui.TRADE_RESPONSE_ROWS + 1)   # + the header

    def test_accept_and_reject_come_from_the_shared_layout(self) -> None:
        """main.py's Accept/Reject buttons are the layout's rects, inside its panel."""
        app = self.make_app(big_incoming_offer())
        layout = ui.trade_response_layout()

        rects = {b.key: b.rect for b in app._playing_buttons()}

        self.assertEqual(rects, {"trade_accept": layout["accept"], "trade_reject": layout["reject"]})
        app._draw()                          # the dialog renders without error


def human_turn(**state) -> MonopolyGame:
    """A seeded four-seat game on the human's turn, with engine state overrides."""
    game = MonopolyGame([("Human", True), ("Iris", False), ("Knox", False), ("Mira", False)], seed=6)
    for key, value in state.items():
        setattr(game, key, value)
    return game


class BoardClickModeTests(ShellTestCase):
    """Board-click modes highlight real options and explain refusals."""

    def test_mortgage_mode_highlights_titles_that_can_be_mortgaged_or_lifted(self) -> None:
        """Developed groups and unaffordable lifts are not offered as clickable."""
        game = human_turn(awaiting="post_roll")
        human = game.players[0]
        for pos in (1, 3, 5, 12, 39):
            game.owners[pos] = 0
        game.houses[1] = 1                  # brown is developed: neither title can mortgage
        game.mortgaged.update((12, 39))     # $83 to lift 12, $220 to lift 39
        human.cash = 100
        app = self.make_app(game)
        app.mode = "mortgage"

        self.assertEqual(sorted(app._board_highlights()), [5, 12])

    def test_refused_board_click_shows_the_engine_reason_until_done(self) -> None:
        """Clicking a title that cannot take a house says why; Done clears it."""
        game = human_turn(awaiting="post_roll")
        game.owners[5] = 0
        app = self.make_app(game)
        click(app, "build")

        app._handle_click(board_render.space_rect(5).center)

        self.assertEqual(app._prompt(), "Only streets can take buildings.")
        click(app, "done")
        self.assertEqual(app.message, "")
        self.assertEqual(app.mode, "normal")

    def test_engine_actions_clear_a_stale_message(self) -> None:
        """Every engine-dispatching button starts from a clean prompt."""
        offer = {"from": 1, "to": 0, "give": {"props": [], "cash": 10, "jail": 0},
                 "get": {"props": [], "cash": 0, "jail": 0}}
        cases: dict[str, dict] = {
            "roll": {},
            "end_turn": {"awaiting": "post_roll"},
            "buy": {"awaiting": "buy_or_auction", "pending_purchase": 1},
            "auction_decline": {"awaiting": "buy_or_auction", "pending_purchase": 1},
            "trade_accept": {"awaiting": "trade_response", "pending_trade": dict(offer),
                             "_awaiting_before_trade": "post_roll"},
            "trade_reject": {"awaiting": "trade_response", "pending_trade": dict(offer),
                             "_awaiting_before_trade": "post_roll"},
        }
        for key, state in cases.items():
            with self.subTest(key=key):
                app = self.make_app(human_turn(**state))
                app.message = "stale"
                app._on_button(key)
                self.assertEqual(app.message, "")
        for key in ("bid", "pass"):
            with self.subTest(key=key):
                game = human_turn()
                game._start_auction(1)
                app = self.make_app(game)
                app.message = "stale"
                app._on_button(key)
                self.assertEqual(app.message, "")


class JailBarTests(ShellTestCase):
    """A jailed human may still manage assets and trade before rolling."""

    def test_jailed_human_pre_roll_bar_offers_mortgage_assets_and_trade(self) -> None:
        """The jail bar adds Mortgage, Assets and Trade beside Roll, Pay and Card."""
        game = human_turn()
        human = game.players[0]
        human.position, human.in_jail = 10, True
        game.owners[1] = 0
        app = self.make_app(game)

        states = button_states(app)

        for key in ("roll", "jail_pay", "jail_card", "mortgage", "assets", "trade"):
            self.assertIn(key, states)
        click(app, "trade")
        self.assertEqual(app.mode, "trade")


class SaveAfterDoubleTests(SeededSaveDirTestCase):
    """Save & Quit between doubles keeps the three-doubles count."""

    def test_save_and_quit_after_a_double_keeps_doubles_count(self) -> None:
        """A save taken after one double resumes on the extra roll, count intact."""
        game = human_turn()
        rig_rolls(game, 2, 2)                 # GO + 4: Income Tax, then roll again
        app = MonopolyApp()
        app.start_game(game)
        click(app, "roll")
        self.assertEqual((game.awaiting, game.doubles_count), ("pre_roll", 1))

        click(app, "save_quit")
        resumed = main.load_saved_game()

        assert resumed is not None
        self.assertEqual((resumed.awaiting, resumed.doubles_count), ("pre_roll", 1))


def spectator_game() -> MonopolyGame:
    """The only human has gone bankrupt; three AIs play on, Iris to move."""
    game = human_turn()
    game.players[0].bankrupt = True
    game.players[0].cash = 0
    game.current = 1
    return game


class SpectatorTests(SeededSaveDirTestCase):
    """With no solvent human left, the human may fast-forward or concede."""

    def test_spectator_bar_appears_once_no_solvent_human_remains(self) -> None:
        """Only Fast-forward and Concede / Main Menu are offered, and they are clickable."""
        app = self.make_app(spectator_game())

        self.assertEqual(set(button_states(app)), {"fast_forward", "concede"})

    def test_fast_forward_runs_the_ai_without_delay(self) -> None:
        """Before fast-forward the AI waits its delay; after it, it acts every frame."""
        game = spectator_game()
        app = self.make_app(game)
        app._update(False)                       # seeds token positions
        log_length = len(game.log)

        app._update(False)
        self.assertEqual(len(game.log), log_length)
        click(app, "fast_forward")
        app._update(False)

        self.assertTrue(app.fast_forward)
        self.assertGreater(len(game.log), log_length)

    def test_concede_records_a_loss_and_clears_the_save(self) -> None:
        """Concede counts a game (not a human win), deletes the save, returns to setup."""
        app = self.make_app(spectator_game())

        click(app, "concede")

        self.assertEqual(app.screen, "setup")
        self.assertIsNone(app.game)
        stats = json.loads((self.folder / "stats.json").read_text())
        self.assertEqual(stats, {"games": 4, "human_wins": 1})
        self.assertFalse((self.folder / "savegame.json").exists())

    def test_no_autosave_while_spectating(self) -> None:
        """A turn change while only AIs remain does not overwrite the save."""
        before = self.snapshot()
        game = spectator_game()
        app = self.make_app(game)

        game.current = 2
        app._update(False)

        self.assertEqual(self.snapshot(), before)


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
