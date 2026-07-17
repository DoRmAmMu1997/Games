"""Regression tests for the on-screen board geometry.

The rules engine only tracks abstract step indexes, so the visual layout in
``board_render.DisplayLayout`` fully decides where cells appear and which way
tokens travel. These tests lock in the authentic-Ludo properties:

- the shared track is one connected loop (no teleporting cells),
- tokens travel CLOCKWISE around the board,
- every seat's start square sits beside its own yard,
- every seat's final loop cell hands over cleanly to its home column,
- home columns run inward and finish at the board center,
- Player 1 (seat 0) sits at the bottom and seats continue clockwise.
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

from board import BoardLayout
from board_render import BoardRenderer
from settings import SEAT_COLORS

# Player counts whose display layout follows the authentic clockwise rules.
SUPPORTED_COUNTS = (4,)

# A step between two consecutive track cells is at most one grid cell plus the
# occasional corner turn, which measures sqrt(2) cells. 1.6 gives headroom for
# rounding without letting real gaps slip through.
ADJACENT_CELLS = 1.6


def make_display(total_players: int):
    """Return the display layout the renderer would use for one player count."""

    return BoardRenderer(BoardLayout.for_player_count(total_players)).display


def centroid(points) -> tuple[float, float]:
    """Return the average point of a small coordinate cluster."""

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Return the straight-line distance between two points."""

    return math.hypot(a[0] - b[0], a[1] - b[1])


class TrackContinuityTests(unittest.TestCase):
    """The shared loop must be connected and must run clockwise."""

    def test_consecutive_track_cells_are_adjacent(self) -> None:
        """Every step around the loop, including the wrap, is one cell long."""

        for count in SUPPORTED_COUNTS:
            display = make_display(count)
            limit = ADJACENT_CELLS * display.cell_size
            with self.subTest(total_players=count):
                track = display.track_positions
                for index, point in enumerate(track):
                    following = track[(index + 1) % len(track)]
                    self.assertLessEqual(
                        distance(point, following),
                        limit,
                        f"track cells {index} and {(index + 1) % len(track)} are not adjacent",
                    )

    def test_track_runs_clockwise_on_screen(self) -> None:
        """The shoelace sum is positive, which means clockwise in y-down coordinates."""

        for count in SUPPORTED_COUNTS:
            display = make_display(count)
            with self.subTest(total_players=count):
                track = display.track_positions
                area = 0.0
                for index, (x1, y1) in enumerate(track):
                    x2, y2 = track[(index + 1) % len(track)]
                    area += x1 * y2 - x2 * y1
                self.assertGreater(area, 0.0, "track winds anti-clockwise")


class SeatAlignmentTests(unittest.TestCase):
    """Each seat's start, yard, home column, and colors must stay in lockstep."""

    def test_start_cells_sit_beside_their_own_yards(self) -> None:
        """The closest yard to every start square belongs to the same seat."""

        for count in SUPPORTED_COUNTS:
            display = make_display(count)
            layout = BoardLayout.for_player_count(count)
            yard_centroids = [centroid(slots) for slots in display.yard_positions]
            for seat, start_index in enumerate(layout.start_indices):
                with self.subTest(total_players=count, seat=seat):
                    start = display.track_positions[start_index]
                    nearest = min(
                        range(count), key=lambda other: distance(start, yard_centroids[other])
                    )
                    self.assertEqual(nearest, seat)
                    self.assertLessEqual(distance(start, yard_centroids[seat]), 5 * display.cell_size)

    def test_final_loop_cell_reaches_the_home_column(self) -> None:
        """The last shared cell is adjacent to that seat's first home cell."""

        for count in SUPPORTED_COUNTS:
            display = make_display(count)
            layout = BoardLayout.for_player_count(count)
            limit = ADJACENT_CELLS * display.cell_size
            for seat, start_index in enumerate(layout.start_indices):
                with self.subTest(total_players=count, seat=seat):
                    final_index = (start_index - 1) % layout.track_length
                    final_cell = display.track_positions[final_index]
                    home_entry = display.home_lanes[seat][0]
                    self.assertLessEqual(distance(final_cell, home_entry), limit)

    def test_home_lanes_march_inward_to_the_center(self) -> None:
        """Home cells get strictly closer to the center and end beside it."""

        for count in SUPPORTED_COUNTS:
            display = make_display(count)
            for seat, lane in enumerate(display.home_lanes):
                with self.subTest(total_players=count, seat=seat):
                    distances = [distance(cell, display.center) for cell in lane]
                    self.assertEqual(distances, sorted(distances, reverse=True))
                    self.assertLessEqual(distances[-1], 2.2 * display.cell_size)

    def test_seat_zero_sits_at_the_bottom_and_seats_continue_clockwise(self) -> None:
        """Player 1 is the bottom seat; the rest follow in clockwise order."""

        for count in SUPPORTED_COUNTS:
            display = make_display(count)
            with self.subTest(total_players=count):
                yard_centroids = [centroid(slots) for slots in display.yard_positions]
                self.assertGreater(
                    yard_centroids[0][1], display.center[1], "seat 0 is not in the bottom half"
                )
                angles = [
                    math.atan2(y - display.center[1], x - display.center[0])
                    for x, y in yard_centroids
                ]
                for seat in range(count):
                    step = (angles[(seat + 1) % count] - angles[seat]) % math.tau
                    self.assertLess(step, math.pi, f"seat {seat + 1} is not clockwise of seat {seat}")

    def test_display_uses_the_seat_color_table(self) -> None:
        """The renderer paints with the same palette the engine assigns."""

        for count in SUPPORTED_COUNTS:
            with self.subTest(total_players=count):
                self.assertEqual(make_display(count).seat_colors, SEAT_COLORS[count])


if __name__ == "__main__":
    unittest.main()
