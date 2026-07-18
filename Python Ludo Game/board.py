"""Generated board geometry for 4-, 5-, and 6-player Ludo."""

from __future__ import annotations

import math
from dataclasses import dataclass

from settings import BOARD_CENTER, BOARD_RADIUS, HOME_LENGTH, SEGMENT_LENGTH

Point = tuple[float, float]


@dataclass(frozen=True)
class BoardLayout:
    """All track, home-lane, and yard coordinates for one player count.

    The rules engine uses indexes and step counts, while the renderer needs
    screen coordinates. This object is the translation table between those two
    worlds. It is immutable so tests, AI, and drawing code can all share it
    without worrying that one layer will move the board underneath another.
    """

    total_players: int
    polygon_sides: int
    track_positions: tuple[Point, ...]
    home_lanes: tuple[tuple[Point, ...], ...]
    yard_positions: tuple[tuple[Point, ...], ...]
    start_indices: tuple[int, ...]
    safe_indices: tuple[int, ...]
    center: Point
    radius: float

    @classmethod
    def for_player_count(cls, total_players: int) -> BoardLayout:
        """Build a square, pentagonal, or hexagonal board.

        A standard four-player Ludo board has four repeated arms. The five-
        and six-player versions keep that idea by giving every player a
        13-cell segment on the outer track and a 6-cell home lane.
        """

        if total_players not in (4, 5, 6):
            raise ValueError("Ludo supports 4, 5, or 6 total players")

        center = (float(BOARD_CENTER[0]), float(BOARD_CENTER[1]))
        radius = float(BOARD_RADIUS)
        vertices = _regular_polygon(total_players, center, radius)

        track: list[Point] = []
        for side in range(total_players):
            start = vertices[side]
            end = vertices[(side + 1) % total_players]
            # Every side contributes exactly SEGMENT_LENGTH main-track cells.
            # The endpoint itself belongs to the next side, which avoids
            # duplicate cells at the polygon corners.
            for step in range(SEGMENT_LENGTH):
                amount = step / SEGMENT_LENGTH
                track.append(_lerp(start, end, amount))

        home_lanes: list[tuple[Point, ...]] = []
        yard_positions: list[tuple[Point, ...]] = []
        for player_index in range(total_players):
            start_point = track[player_index * SEGMENT_LENGTH]
            lane = []
            # A home lane is a straight path from the player's start corner
            # into the center. The final home cell is near the center, not on
            # top of it, so several players can finish without overlapping.
            for lane_index in range(HOME_LENGTH):
                amount = (lane_index + 1) / (HOME_LENGTH + 1)
                lane.append(_lerp(start_point, center, amount))
            home_lanes.append(tuple(lane))
            yard_positions.append(tuple(_yard_cluster(vertices[player_index], center)))

        start_indices = tuple(player * SEGMENT_LENGTH for player in range(total_players))
        safe_indices = tuple(
            (player * SEGMENT_LENGTH + 8) % (total_players * SEGMENT_LENGTH)
            for player in range(total_players)
        )
        return cls(
            total_players=total_players,
            polygon_sides=total_players,
            track_positions=tuple(track),
            home_lanes=tuple(home_lanes),
            yard_positions=tuple(yard_positions),
            start_indices=start_indices,
            safe_indices=safe_indices,
            center=center,
            radius=radius,
        )

    @property
    def track_length(self) -> int:
        """Number of cells around the shared outer track."""

        return self.total_players * SEGMENT_LENGTH

    @property
    def finish_steps(self) -> int:
        """Relative step value that means a token is fully home."""

        return self.track_length + HOME_LENGTH - 1

    def track_index(self, player_index: int, steps: int) -> int | None:
        """Return the absolute main-track index for ``steps`` or ``None`` in home."""

        if steps < 0 or steps >= self.track_length:
            return None
        return (self.start_indices[player_index] + steps) % self.track_length

    def home_lane_index(self, steps: int) -> int | None:
        """Return the lane cell index for home-lane progress."""

        if steps < self.track_length:
            return None
        lane_index = steps - self.track_length
        return lane_index if 0 <= lane_index < HOME_LENGTH else None

    def position_for(self, player_index: int, steps: int, token_index: int = 0) -> Point:
        """Return a drawing coordinate for a token."""

        if steps < 0:
            return self.yard_positions[player_index][token_index % len(self.yard_positions[player_index])]
        track_index = self.track_index(player_index, steps)
        if track_index is not None:
            return self.track_positions[track_index]
        lane_index = self.home_lane_index(steps)
        if lane_index is None:
            return self.center
        return self.home_lanes[player_index][lane_index]

    def steps_to_reach(self, player_index: int, absolute_track_index: int) -> int:
        """Return the owning-player-relative progress for a track index."""

        return (absolute_track_index - self.start_indices[player_index]) % self.track_length

    def previous_index(self, absolute_track_index: int, distance: int) -> int:
        """Walk backward around the circular track by ``distance`` cells."""

        return (absolute_track_index - distance) % self.track_length

    def is_safe_index(self, absolute_track_index: int | None) -> bool:
        """Return True for start squares and star safe squares."""

        if absolute_track_index is None:
            return False
        return absolute_track_index in self.start_indices or absolute_track_index in self.safe_indices


def _regular_polygon(sides: int, center: Point, radius: float) -> list[Point]:
    """Return screen coordinates for a regular polygon's vertices."""

    cx, cy = center
    # Start at the top for a board that reads naturally on screen.
    start_angle = -math.pi / 2
    return [
        (
            cx + math.cos(start_angle + math.tau * i / sides) * radius,
            cy + math.sin(start_angle + math.tau * i / sides) * radius,
        )
        for i in range(sides)
    ]


def _lerp(start: Point, end: Point, amount: float) -> Point:
    """Linearly interpolate between two points.

    ``amount`` is 0 at ``start`` and 1 at ``end``. Values between them create
    the evenly spaced board cells along each polygon side.
    """

    return (
        start[0] + (end[0] - start[0]) * amount,
        start[1] + (end[1] - start[1]) * amount,
    )


def _yard_cluster(vertex: Point, center: Point) -> list[Point]:
    """Return four token parking spots outside one player's corner."""

    vx, vy = vertex
    cx, cy = center
    outward_x = vx - cx
    outward_y = vy - cy
    length = math.hypot(outward_x, outward_y) or 1.0
    outward_x /= length
    outward_y /= length
    tangent_x = -outward_y
    tangent_y = outward_x
    # ``outward`` pushes the yard away from the board, while ``tangent``
    # spreads the four token positions sideways around that corner.
    base_x = vx + outward_x * 72
    base_y = vy + outward_y * 72
    offsets = [(-20, -20), (20, -20), (-20, 20), (20, 20)]
    return [
        (
            base_x + tangent_x * side + outward_x * depth,
            base_y + tangent_y * side + outward_y * depth,
        )
        for side, depth in offsets
    ]
