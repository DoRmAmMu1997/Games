"""Layout and legibility checks for the Monopoly graphics polish.

Every check here compares measured text sizes, rectangles or chosen colours
-- never sampled antialiased pixels -- and leaves real margin, so the suite
passes whatever typeface "arial" resolves to on the machine running it.
"""

from __future__ import annotations

import itertools
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import pygame
from test_raise_funds import rent_debt
from test_shell import ShellTestCase, big_incoming_offer, spectator_game

import board_data
import board_render
import cards
import ui
from game import MonopolyGame
from main import MonopolyApp
from settings import BOARD_FACE, INK, PANEL_CARD, WHITE

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


class BoardLabelTests(ShellTestCase):
    """Every tile's name and price fit inside the tile, on every theme."""

    def test_every_board_label_fits_inside_its_tile_on_every_theme(self) -> None:
        """Label lines fit the tile's width and depth by measurement, and lose no letters.

        The label must also stay clear of the 4 px ownership border, so the
        room it is measured against is inset from the tile's edges.
        """

        def letters(text: str) -> str:
            """Reduce text to its letters, ignoring wrap points and hyphens."""
            return text.replace(" ", "").replace("-", "")

        fonts = ui.make_fonts()
        self.assertGreaterEqual(board_render.TILE_LABEL_INSET, 6)
        for theme in board_data.THEME_ORDER:
            with self.subTest(theme=theme):
                problems: list[tuple] = []
                for space in board_data.build_board(theme):
                    font, lines = board_render.tile_label(fonts, space)
                    width, depth = board_render.label_room(space.position)
                    rect = board_render.space_rect(space.position)
                    if width > min(rect.size) - 2 * board_render.TILE_LABEL_INSET:
                        problems.append((space.name, "room wider than the inset tile"))
                    if any(font.size(line)[0] > width for line in lines):
                        problems.append((space.name, lines, "too wide"))
                    if len(lines) * board_render.label_pitch(font) > depth:
                        problems.append((space.name, lines, "too deep"))
                    name_lines = lines[:-1] if space.is_ownable else lines
                    if letters("".join(name_lines)) != letters(space.name):
                        problems.append((space.name, lines, "letters lost"))
                    if space.is_ownable and lines[-1] != f"${space.price}":
                        problems.append((space.name, lines, "price missing"))
                self.assertEqual(problems, [])

    def test_board_base_renders_for_every_theme(self) -> None:
        """The static board layer builds for every theme without error."""
        fonts = ui.make_fonts()
        for theme in board_data.THEME_ORDER:
            with self.subTest(theme=theme):
                board_render.BoardRenderer(board_data.build_board(theme)).build_base(fonts)


class ActionBarSpacingTests(ShellTestCase):
    """The eight action-bar slots are spaced evenly inside the bar."""

    def test_action_bar_buttons_are_evenly_spaced_inside_the_bar(self) -> None:
        """Side margins equal the column gap; top and bottom margins equal the row gap."""
        bar = ui.action_bar_layout()["bar"]
        slots = [ui.bar_slot_rect(slot) for slot in range(8)]

        across = [slots[0].left - bar.left, slots[1].left - slots[0].right, bar.right - slots[1].right]
        down = [slots[0].top - bar.top,
                *(slots[row * 2 + 2].top - slots[row * 2].bottom for row in range(3)),
                bar.bottom - slots[6].bottom]

        self.assertEqual(len(set(across)), 1, across)
        self.assertEqual(len(set(down)), 1, down)
        self.assertGreaterEqual(down[0], 4)
        self.assertTrue(all(left.size == slots[0].size for left in slots))


class GameLogTests(ShellTestCase):
    """Log lines are fitted to the log card by measurement, not by character count."""

    def test_log_lines_fit_the_card_by_measured_width(self) -> None:
        """Wide lines are shortened to fit; narrow ones are kept whole, however long."""
        fonts = ui.make_fonts()
        game = long_name_game()
        narrow = "i" * 60                       # many characters, few pixels
        wide = "W" * 46                         # few characters, many pixels
        for line in (narrow, wide, "Bartholomew pays $1100 rent to Iris (AI) on Kentucky Avenue."):
            game._note(line)

        card = ui.log_rect()
        placed = ui.log_lines(fonts, game)

        texts = [text for text, _pos in placed]
        self.assertIn(narrow, texts)
        self.assertNotIn(wide, texts)
        self.assertTrue(any(text.startswith("WWW") and text.endswith("...") for text in texts))
        for text, (x, y) in placed:
            with self.subTest(text=text):
                width, height = fonts["tiny"].size(text)
                self.assertGreaterEqual(x, card.left + ui.LOG_MARGIN)
                self.assertLessEqual(x + width, card.right - ui.LOG_MARGIN)
                self.assertLessEqual(y + height, card.bottom - 2)

    def test_log_shows_the_newest_lines_last(self) -> None:
        """The card shows as many of the latest events as fit, newest at the bottom."""
        fonts = ui.make_fonts()
        game = long_name_game()
        for turn in range(30):
            game._note(f"Event {turn}")

        texts = [text for text, _pos in ui.log_lines(fonts, game)]

        self.assertGreaterEqual(len(texts), 5)
        self.assertEqual(texts[-1], "Event 29")
        self.assertEqual(texts, [f"Event {30 - len(texts) + i}" for i in range(len(texts))])


class TokenSlotTests(unittest.TestCase):
    """Each player's token has its own spot on a tile, clear of the others."""

    def test_tokens_sharing_a_tile_never_overlap(self) -> None:
        """All four tokens fit on every tile: apart from each other, inside the tile."""
        radius = board_render.TOKEN_RADIUS
        for position in range(40):
            with self.subTest(position=position):
                tile = board_render.space_rect(position)
                centers = [board_render.token_center(position, slot) for slot in range(4)]
                for index, (x, y) in enumerate(centers):
                    disc = pygame.Rect(x - radius, y - radius, 2 * radius, 2 * radius)
                    # Inside the tile's own 2 px border, with a pixel to spare.
                    self.assertTrue(tile.inflate(-6, -6).contains(disc), (tile, disc))
                    for other_x, other_y in centers[index + 1:]:
                        apart = ((x - other_x) ** 2 + (y - other_y) ** 2) ** 0.5
                        self.assertGreaterEqual(apart, 2 * radius + 1)


def luminance(color: tuple[int, int, int]) -> float:
    """WCAG relative luminance of an sRGB colour."""
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in color[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(ink: tuple[int, int, int], fill: tuple[int, int, int]) -> float:
    """WCAG contrast ratio between two colours (1 to 21)."""
    light, dark = sorted((luminance(ink), luminance(fill)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class BoardMiddleTests(ShellTestCase):
    """The drawn card and the dice keep clear of the diagonal MONOPOLY title."""

    def clearance(self, rect: pygame.Rect) -> float:
        """Smallest distance from a rect's corners to the title's diagonal centre line."""
        cx = cy = board_render.BOARD_CENTER
        return min(abs((x - cx) + (y - cy)) / 2 ** 0.5
                   for x in (rect.left, rect.right) for y in (rect.top, rect.bottom))

    def test_card_and_dice_clear_the_title_inside_the_board_middle(self) -> None:
        """With the longest card text, card and dice stay inside the middle, off the title."""
        fonts = ui.make_fonts()
        half_title = fonts["title"].get_height() / 2
        middle = board_render.inner_rect()
        game = long_name_game()
        game.last_card = max(cards.CHANCE_CARDS + cards.CHEST_CARDS,
                             key=lambda card: len(cards.format_card_text(card, game.board)))

        card = ui.center_card_layout(fonts, game)
        dice = ui.dice_rect()

        for rect in (card["panel"], dice):
            self.assertTrue(middle.inflate(-8, -8).contains(rect), rect)
            self.assertGreaterEqual(self.clearance(rect), half_title + 8)
        self.assertFalse(card["panel"].colliderect(dice))
        self.assertGreaterEqual(card["body_top"], card["header"].bottom + 2)
        self.assertLessEqual(card["body_bottom"], card["panel"].bottom - 6)

    def test_card_header_and_text_are_readable_on_both_decks(self) -> None:
        """Header and body ink reach a 4.5:1 contrast on the Chance and Chest fills."""
        for deck in ("chance", "chest"):
            with self.subTest(deck=deck):
                fill, ink = ui.card_colors(deck)
                self.assertGreaterEqual(contrast(ink, fill), 4.5)


class DialogSpacingTests(ShellTestCase):
    """Dialog text is stacked with measured gaps and stays clear of controls."""

    def assert_stacked(self, plan: list, inside: pygame.Rect, limit: int) -> None:
        """Each line sits below the previous with a gap, inside `inside`, above `limit`."""
        rects = [rect for _key, _text, _color, rect in plan]
        self.assertTrue(rects)
        for upper, lower in itertools.pairwise(rects):
            self.assertGreaterEqual(lower.top, upper.bottom + ui.DIALOG_LINE_GAP, (upper, lower))
        for rect in rects:
            self.assertTrue(inside.contains(rect), (inside, rect))
            self.assertLessEqual(rect.bottom, limit)

    def test_auction_dialog_text_is_spaced_above_the_buttons(self) -> None:
        """A bank auction's title, deed, context and bid lines never touch."""
        fonts = ui.make_fonts()
        game = long_name_game()
        game._start_auction(5, context="bankruptcy")
        assert game.auction is not None
        game.auction.update(high_bid=260, high_bidder=1)
        layout = ui.auction_layout()

        plan = ui.auction_plan(fonts, game)

        self.assert_stacked(plan, layout["panel"].inflate(-20, -12), layout["bid"].top - 6)

    def test_asset_manager_text_is_spaced_in_header_and_detail(self) -> None:
        """Header lines clear the title rows; deed and status lines stay in the detail box."""
        fonts = ui.make_fonts()
        game = rent_debt()                     # raising funds: long blocker reasons
        player = game.players[0]
        layout = ui.asset_layout(game, player)
        first_row = min(row.top for row, _pos in layout["title_rows"])

        header = ui.assets_header_plan(fonts, game, player)
        self.assert_stacked(header, layout["panel"], first_row - 4)
        detail = ui.asset_detail_plan(fonts, game, player, 1)
        self.assert_stacked(detail, layout["detail"].inflate(-16, -8), layout["detail"].bottom - 6)

    def test_trade_dialog_header_is_spaced_above_the_lists(self) -> None:
        """Title, partner, cash and column headers all sit above the first title row."""
        fonts = ui.make_fonts()
        game = long_name_game(awaiting="post_roll")
        game.owners[1] = 0
        app = MonopolyApp(persist=False)
        app.start_game(game)
        app._on_button("trade")
        layout = ui.trade_layout(game, app.trade)
        first_row = min(row.top for row, _pos in layout["give_rows"])

        plan = ui.trade_header_plan(fonts, game, app.trade)

        centred = [item for item in plan if item[3].centerx == layout["panel"].centerx]
        self.assert_stacked(centred, layout["panel"], first_row - 4)
        for _key, _text, _color, rect in plan:
            self.assertLessEqual(rect.bottom, first_row - 4)


def rim_blend(surface: pygame.Surface, center: tuple[int, int], radius: int,
              pure: set[tuple[int, int, int]]) -> int:
    """Count pixels on a disc's rim that are a blend rather than a pure draw colour.

    An aliased circle paints every rim pixel in exactly one of its colours;
    an antialiased one leaves a ring of in-between pixels.
    """
    count = 0
    for x in range(center[0] - radius - 2, center[0] + radius + 3):
        for y in range(center[1] - radius - 2, center[1] + radius + 3):
            distance = ((x - center[0]) ** 2 + (y - center[1]) ** 2) ** 0.5
            if abs(distance - radius) <= 1.5 and tuple(surface.get_at((x, y))[:3]) not in pure:
                count += 1
    return count


class SmoothEdgeTests(ShellTestCase):
    """Round shapes are drawn antialiased, not with stair-stepped edges."""

    def test_tokens_dice_pips_and_player_discs_have_smooth_edges(self) -> None:
        """Each disc's rim holds blended pixels -- the sign of antialiasing."""
        fonts = ui.make_fonts()
        game = long_name_game()
        player = game.players[0]

        board = pygame.Surface((880, 880))
        board.fill(BOARD_FACE)
        board_render.BoardRenderer(game.board)._draw_tokens(
            board, game, fonts, pixel_overrides={0: (300, 300), 1: (500, 300), 2: (700, 300)})
        self.assertGreater(
            rim_blend(board, (300, 300), board_render.TOKEN_RADIUS,
                      {BOARD_FACE, INK, WHITE, player.token_color}), 0)

        die = pygame.Surface((60, 60))
        die.fill(WHITE)
        ui._draw_pips(die, die.get_rect(), 1)
        self.assertGreater(rim_blend(die, (30, 30), ui.PIP_RADIUS, {WHITE, INK}), 0)

        card = pygame.Surface((400, 130))
        card.fill(PANEL_CARD)
        rect = pygame.Rect(4, 4, 388, 118)
        ui._draw_player_card(card, fonts, game, player, rect, False)
        self.assertGreater(
            rim_blend(card, ui.player_disc_center(rect), ui.PLAYER_DISC_RADIUS,
                      {PANEL_CARD, INK, player.token_color}), 0)


if __name__ == "__main__":
    unittest.main()
