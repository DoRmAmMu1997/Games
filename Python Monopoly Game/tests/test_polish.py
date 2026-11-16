"""Layout and legibility checks for the Monopoly graphics polish.

Every check here compares measured text sizes, rectangles or chosen colours
-- never sampled antialiased pixels -- and leaves real margin, so the suite
passes whatever typeface "arial" resolves to on the machine running it.
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

from test_raise_funds import rent_debt
from test_shell import ShellTestCase, big_incoming_offer, spectator_game

import board_data
import ui
from game import MonopolyGame
from main import MonopolyApp

LONG_NAME = "Alexandra Q.xx"        # 14 characters: the longest name setup allows


def long_name_game(theme: str = "classic", **state) -> MonopolyGame:
    """A seeded game whose human has the longest allowed name, with state overrides."""
    game = MonopolyGame([(LONG_NAME, True), ("Quill (AI)", False), ("Knox (AI)", False)],
                        theme=theme, seed=8)
    for key, value in state.items():
        setattr(game, key, value)
    return game


def longest_title() -> tuple[str, int]:
    """Return the (theme, position) of the longest ownable title name on any board."""
    titles = [(key, space) for key in board_data.THEME_ORDER
              for space in board_data.build_board(key) if space.is_ownable]
    theme, space = max(titles, key=lambda item: len(item[1].name))
    return theme, space.position


class PromptStripTests(ShellTestCase):
    """The action-bar prompt is one line that stays inside its strip."""

    def standard_prompts(self) -> dict[str, str]:
        """Return the prompt the shell shows in each ordinary state."""
        jailed = long_name_game()
        jailed.players[0].in_jail = True
        auction = long_name_game()
        auction._start_auction(39)
        bank_auction = long_name_game()
        bank_auction._start_auction(39, context="bankruptcy")
        ai_turn = long_name_game(current=1)
        long_theme, long_position = longest_title()
        states: dict[str, tuple[MonopolyGame, str]] = {
            "pre roll": (long_name_game(), "normal"),
            "jail": (jailed, "normal"),
            "post roll": (long_name_game(awaiting="post_roll"), "normal"),
            "buy": (long_name_game(long_theme, awaiting="buy_or_auction",
                                   pending_purchase=long_position), "normal"),
            "build": (long_name_game(awaiting="post_roll"), "build"),
            "mortgage": (long_name_game(awaiting="post_roll"), "mortgage"),
            "sell": (long_name_game(awaiting="post_roll"), "sell"),
            "assets": (long_name_game(awaiting="post_roll"), "assets"),
            "auction": (auction, "normal"),
            "bank auction": (bank_auction, "normal"),
            "trade offer": (big_incoming_offer(), "normal"),
            "ai turn": (ai_turn, "normal"),
            "raise funds": (rent_debt(), "normal"),
            "spectator": (spectator_game(), "normal"),
        }
        prompts = {}
        for name, (game, mode) in states.items():
            app = MonopolyApp(persist=False)
            app.start_game(game)
            app.mode = mode
            prompts[name] = app._prompt()
        return prompts

    def test_every_prompt_is_one_line_inside_its_strip(self) -> None:
        """Standard prompts and long engine messages all fit the strip with margin."""
        fonts = ui.make_fonts()
        strip = ui.action_bar_layout()["prompt"]
        prompts = self.standard_prompts()
        prompts["long reason"] = f"{LONG_NAME} needs $20 cash for mortgage transfer interest."
        prompts["longer still"] = "This reason is far too long to fit on one line of the prompt strip, " * 2

        for name, prompt in prompts.items():
            with self.subTest(state=name):
                text, font = ui.prompt_line(fonts, prompt)
                self.assertLessEqual(font.size(text)[0], strip.width - 2 * ui.PROMPT_MARGIN)
                self.assertLessEqual(font.get_height(), strip.height - 4)

    def test_standard_prompts_are_shown_in_full(self) -> None:
        """No ordinary prompt has to be shortened, even with the longest names."""
        fonts = ui.make_fonts()
        for name, prompt in self.standard_prompts().items():
            with self.subTest(state=name):
                self.assertTrue(prompt)
                self.assertEqual(ui.prompt_line(fonts, prompt)[0], prompt)


if __name__ == "__main__":
    unittest.main()
