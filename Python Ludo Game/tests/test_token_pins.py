"""Token pin placement and click hit-testing on the rendered boards.

``BoardRenderer.token_pins`` is the single place that decides where each pawn
is drawn. These tests check that pawns sharing a cell fan out instead of
hiding each other, and that clicks pick the pawn whose DRAWN pin is nearest.
"""

from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from board_render import BoardRenderer
from game import LudoGame, LudoRules
from settings import TOKEN_HIT_RADIUS


def make_game(total_players: int) -> LudoGame:
    """Create a deterministic game with seat 0 human and the rest AI."""

    players = [(f"P{i + 1}", i == 0) for i in range(total_players)]
    return LudoGame(players, LudoRules(total_players=total_players), seed=3)


def pixel(point: tuple[float, float]) -> tuple[int, int]:
    """Round a pin centre to the whole pixel a click would land on."""

    return round(point[0]), round(point[1])


def arrange_safe_square(game: LudoGame) -> None:
    """Put two tokens each of three different players on one safe star square."""

    layout = game.layout
    safe = layout.safe_indices[1]
    for seat in (0, 2, 3):
        for token in game.players[seat].tokens[:2]:
            token.steps = layout.steps_to_reach(seat, safe)


def arrange_start_square(game: LudoGame) -> None:
    """Stack three of seat 1's tokens and one visitor on seat 1's start square."""

    layout = game.layout
    for token in game.players[1].tokens[:3]:
        token.steps = 0
    game.players[0].tokens[0].steps = layout.steps_to_reach(0, layout.start_indices[1])


def arrange_lane_cells(game: LudoGame) -> None:
    """Stack every seat's tokens two and two on its first two home-lane cells."""

    for player in game.players:
        for index, token in enumerate(player.tokens):
            token.steps = game.layout.lap_length + index // 2


def arrange_finish(game: LudoGame) -> None:
    """Send every token of every player home."""

    for player in game.players:
        for token in player.tokens:
            token.steps = game.layout.finish_steps


class TokenPinPlacementTests(unittest.TestCase):
    """Pins sharing one on-screen cell fan out; lone pins sit on the cell centre."""

    def assert_pins_distinct(self, game: LudoGame) -> None:
        """Fail if any two of the game's pins resolve to the same pixel."""

        pins = BoardRenderer(game.layout).token_pins(game)
        pixels = [pixel(centre) for centre, _radius in pins.values()]
        self.assertEqual(len(pins), len(game.players) * 4)
        self.assertEqual(len(set(pixels)), len(pixels), "two pins share a pixel")

    def test_lone_token_sits_exactly_on_its_cell_centre(self) -> None:
        """A token alone on its cell is drawn at that cell's centre, unshifted."""

        for count in (4, 5, 6):
            with self.subTest(total_players=count):
                game = make_game(count)
                game.players[0].tokens[0].steps = 5
                renderer = BoardRenderer(game.layout)
                centre, _radius = renderer.token_pins(game)[(0, 0)]
                self.assertEqual(centre, renderer.position_for(0, 5, 0))

    def test_tokens_sharing_a_cell_never_share_a_pixel(self) -> None:
        """Safe squares, start squares, lane cells, and the finish all fan out."""

        for count in (4, 5, 6):
            for name, arrange in (
                ("safe square", arrange_safe_square),
                ("start square", arrange_start_square),
                ("lane cells", arrange_lane_cells),
                ("finish", arrange_finish),
            ):
                with self.subTest(total_players=count, case=name):
                    game = make_game(count)
                    arrange(game)
                    self.assert_pins_distinct(game)

    def test_finished_tokens_resolve_to_one_cell_centre(self) -> None:
        """All of one player's finished tokens share a cell, so they need fanning out."""

        for count in (4, 5, 6):
            with self.subTest(total_players=count):
                game = make_game(count)
                renderer = BoardRenderer(game.layout)
                finish = game.layout.finish_steps
                points = {renderer.position_for(0, finish, index) for index in range(4)}
                self.assertEqual(len(points), 1)


class TokenHitTests(unittest.TestCase):
    """Clicks pick the nearest drawn pin within TOKEN_HIT_RADIUS."""

    def test_click_on_adjacent_six_player_tokens_picks_the_nearest(self) -> None:
        """On the tight 6P board, clicking a token never selects its neighbour.

        Two seat-0 tokens sit on neighbouring cells only 33 px apart, so the
        click on the second token is also inside the first token's radius.
        """

        game = make_game(6)
        game.players[0].tokens[0].steps = 1
        game.players[0].tokens[1].steps = 2
        game.record_roll(1)
        moves = game.legal_moves(1)
        self.assertEqual(sorted(move.token_index for move in moves), [0, 1])
        renderer = BoardRenderer(game.layout)
        pins = renderer.token_pins(game)
        second_click = pixel(pins[(0, 1)][0])
        self.assertLessEqual(
            math.dist(second_click, pins[(0, 0)][0]), TOKEN_HIT_RADIUS, "test needs overlapping hit radii"
        )

        for token_index in (0, 1):
            with self.subTest(token=token_index + 1):
                move = renderer.move_at_pos(pixel(pins[(0, token_index)][0]), moves, game)
                assert move is not None
                self.assertEqual(move.token_index, token_index)

    def test_clicks_on_a_crowded_safe_square_pick_the_drawn_pin(self) -> None:
        """Each of seat 0's drawn pins selects that token, even inside a five-pawn stack.

        Seat 0's token 1 shares a 6P safe square with four of seat 1's
        tokens, and seat 0's token 2 waits one cell ahead. With a roll of 1
        both seat-0 tokens may move, and clicking either drawn pin must pick
        exactly that token.
        """

        game = make_game(6)
        layout = game.layout
        safe = layout.safe_indices[2]
        game.players[0].tokens[0].steps = layout.steps_to_reach(0, safe)
        for token in game.players[1].tokens:
            token.steps = layout.steps_to_reach(1, safe)
        game.players[0].tokens[1].steps = layout.steps_to_reach(0, safe) + 1
        game.record_roll(1)
        moves = game.legal_moves(1)
        self.assertEqual(sorted(move.token_index for move in moves), [0, 1])
        renderer = BoardRenderer(layout)
        pins = renderer.token_pins(game)

        for token_index in (0, 1):
            with self.subTest(token=token_index + 1):
                move = renderer.move_at_pos(pixel(pins[(0, token_index)][0]), moves, game)
                assert move is not None
                self.assertEqual(move.token_index, token_index)

    def test_click_far_from_every_pin_selects_nothing(self) -> None:
        """A click outside every pin's hit radius returns no move."""

        game = make_game(4)
        game.record_roll(6)
        renderer = BoardRenderer(game.layout)
        self.assertIsNone(renderer.move_at_pos((5, 5), game.legal_moves(6), game))


if __name__ == "__main__":
    unittest.main()
