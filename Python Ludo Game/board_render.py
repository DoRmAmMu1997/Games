"""Procedural drawing of the themed Ludo boards and tokens."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

import visual_theme as theme
from models import Move
from settings import GOLD, INK, WHITE, seat_colors


Point = tuple[float, float]
Color = tuple[int, int, int]
GRID_CELLS = 15
SQUARE_CELL = 42
SQUARE_LEFT = 135
SQUARE_TOP = 105
SQUARE_SIZE = SQUARE_CELL * GRID_CELLS
RADIAL_CENTER = (450.0, 410.0)


@dataclass(frozen=True)
class RadialSpec:
    """Tuning knobs for one compact radial board (five or six players).

    Every distance is measured in pixels from the board center. The values
    are chosen so neighbouring arms just meet at the hub ring, the tip
    diagonal stays within one comfortable token step, and the whole board
    plus name banners fits the fixed logical canvas.
    """

    inner_radius: float      # distance to the innermost track cells (hub ring)
    cell_step: float         # radial distance between neighbouring lane cells
    cell_size: float         # side length of one rotated square cell
    lane_offset: float       # sideways distance from the arm axis to each lane
    yard_apex_radius: float  # inward point of the yard triangle
    yard_base_radius: float  # outer edge of the yard triangle
    yard_half_angle: float   # angular half-width of the yard triangle base
    token_radius: float      # distance to the middle of the 2x2 token cluster
    token_spread: float      # half-spacing between yard token slots
    banner_radius: float     # distance to the player name banner


RADIAL_SPECS: dict[int, RadialSpec] = {
    5: RadialSpec(
        inner_radius=92.0,
        cell_step=36.0,
        cell_size=33.0,
        lane_offset=37.0,
        yard_apex_radius=136.0,
        yard_base_radius=330.0,
        yard_half_angle=math.radians(22.0),
        token_radius=258.0,
        token_spread=24.0,
        banner_radius=362.0,
    ),
    6: RadialSpec(
        inner_radius=98.0,
        cell_step=33.0,
        cell_size=30.0,
        lane_offset=34.0,
        yard_apex_radius=138.0,
        yard_base_radius=318.0,
        yard_half_angle=math.radians(17.0),
        token_radius=250.0,
        token_spread=22.0,
        banner_radius=350.0,
    ),
}


@dataclass(frozen=True)
class DisplayCell:
    """One visible board cell with a center point and rotated corners."""

    center: Point
    corners: tuple[Point, Point, Point, Point]


@dataclass(frozen=True)
class DisplayLayout:
    """Screen coordinates used by the renderer for one board shape.

    The rules engine keeps its compact step indexes. This display layout maps
    every index onto the screen: a traditional square cross for four players
    and compact radial boards for five and six players. ``track_positions``
    is index-aligned with the engine's track, so its ordering alone decides
    the on-screen movement direction (clockwise).
    """

    total_players: int
    seat_colors: tuple[Color, ...]
    track_positions: tuple[Point, ...]
    home_lanes: tuple[tuple[Point, ...], ...]
    yard_positions: tuple[tuple[Point, ...], ...]
    center: Point
    radius: float
    cell_size: float
    track_cells: tuple[DisplayCell, ...] = ()
    home_lane_cells: tuple[tuple[DisplayCell, ...], ...] = ()
    yard_frames: tuple[tuple[Point, ...], ...] = ()
    silhouette: tuple[Point, ...] = ()
    hub_polygon: tuple[Point, ...] = ()
    banner_anchors: tuple[Point, ...] = ()


class BoardRenderer:
    """Draw the Ludo arena without changing the rules engine.

    ``BoardLayout`` still owns the true token coordinates and click targets.
    This renderer dresses those coordinates in a brighter board-game style:
    square homes for four players, triangular homes for five and six players,
    player tabs, safe stars, arrows, and glossy pawn pins.
    """

    def __init__(self, layout) -> None:
        """Store the immutable layout and choose one shared cell size."""

        self.layout = layout
        self.display = _display_layout_for(layout)
        self.cell_radius = 15

    def draw(
        self,
        surface: pygame.Surface,
        game,
        fonts: dict[str, pygame.font.Font],
        legal_moves: list[Move] | None = None,
        animated_positions: dict[tuple[int, int], tuple[float, float]] | None = None,
    ) -> None:
        """Draw the complete board for the current animation frame."""

        legal_moves = legal_moves or []
        animated_positions = animated_positions or {}
        self._draw_table(surface)
        if self.layout.total_players == 4:
            self._draw_square_homes(surface, game, fonts)
        else:
            self._draw_radial_homes(surface, game, fonts)
        self._draw_track(surface)
        self._draw_home_lanes(surface)
        self._draw_center_home(surface, game)
        self._draw_move_highlights(surface, legal_moves)
        self._draw_tokens(surface, game, fonts, animated_positions)

    def move_at_pos(self, pos: tuple[int, int], moves: list[Move]) -> Move | None:
        """Return the legal move whose token was clicked, if any."""

        px, py = pos
        for move in moves:
            center = self.position_for(move.player_index, move.from_steps, move.token_index)
            if math.hypot(px - center[0], py - center[1]) <= self.cell_radius + 18:
                return move
        return None

    def position_for(self, player_index: int, steps: int, token_index: int = 0) -> Point:
        """Return the rendered coordinate for a token.

        This mirrors ``BoardLayout.position_for`` but reads from ``self.display``
        so square-mode tokens, highlights, and clicks all share the same visual
        coordinate system.
        """

        if steps < 0:
            return self.display.yard_positions[player_index][token_index % len(self.display.yard_positions[player_index])]
        track_index = self.layout.track_index(player_index, steps)
        if track_index is not None:
            return self.display.track_positions[track_index]
        lane_index = self.layout.home_lane_index(steps)
        if lane_index is None:
            return self.display.center
        return self.display.home_lanes[player_index][lane_index]

    def _draw_table(self, surface: pygame.Surface) -> None:
        """Draw the raised board base that sits on the wallpaper."""

        if self.layout.total_players == 4:
            board = pygame.Rect(SQUARE_LEFT - 6, SQUARE_TOP - 6, SQUARE_SIZE + 12, SQUARE_SIZE + 12)
            theme.draw_shadowed_rect(surface, board, theme.CREAM, border=theme.BOARD_EDGE, radius=8)
            return

        # One convex cream slab behind the whole radial board, so the arms and
        # yard wedges read as a single physical game board.
        theme.draw_shadowed_polygon(
            surface,
            [_ipoint(point) for point in self.display.silhouette],
            theme.CREAM,
            border=theme.BOARD_EDGE,
            border_width=4,
        )

    def _draw_square_homes(self, surface: pygame.Surface, game, fonts: dict[str, pygame.font.Font]) -> None:
        """Draw four large square home yards like a classic Ludo board."""

        for player_index, yard in enumerate(_square_home_rects()):
            positions = self.display.yard_positions[player_index]
            color = self.display.seat_colors[player_index]
            theme.draw_shadowed_rect(surface, yard, color, border=theme.BOARD_EDGE, radius=8)
            inner = yard.inflate(-92, -92)
            pygame.draw.rect(surface, WHITE, inner, border_radius=5)
            pygame.draw.rect(surface, theme.BOARD_EDGE, inner, 2, border_radius=5)
            self._draw_yard_slots(surface, positions, color)
            self._draw_player_tab(surface, game, fonts, player_index, yard)

    def _draw_radial_homes(self, surface: pygame.Surface, game, fonts: dict[str, pygame.font.Font]) -> None:
        """Draw the triangular yard wedges between the radial board arms."""

        for player_index, positions in enumerate(self.display.yard_positions):
            color = self.display.seat_colors[player_index]
            frame = self.display.yard_frames[player_index]
            theme.draw_shadowed_polygon(
                surface,
                [_ipoint(point) for point in frame],
                color,
                border=theme.BOARD_EDGE,
                border_width=4,
            )
            # A smaller white triangle inside the coloured wedge holds the
            # 2x2 token parking cluster, like the reference boards.
            centroid = _average_point(frame)
            inner = [
                _ipoint(
                    (
                        centroid[0] + (point[0] - centroid[0]) * 0.62,
                        centroid[1] + (point[1] - centroid[1]) * 0.62,
                    )
                )
                for point in frame
            ]
            pygame.draw.polygon(surface, WHITE, inner)
            pygame.draw.polygon(surface, theme.BOARD_EDGE, inner, 2)
            self._draw_yard_slots(surface, positions, color)
            banner = pygame.Rect(0, 0, 150, 28)
            banner.center = _ipoint(self.display.banner_anchors[player_index])
            theme.draw_player_banner(
                surface, banner, color, game.players[player_index].name[:16], fonts
            )

    def _draw_yard_slots(
        self,
        surface: pygame.Surface,
        positions: tuple[tuple[float, float], ...],
        color: tuple[int, int, int],
    ) -> None:
        """Paint the empty circular parking spots inside a player's home."""

        for point in positions:
            pygame.draw.circle(surface, theme.darken(color, 38), _ipoint(point), 24)
            pygame.draw.circle(surface, WHITE, _ipoint(point), 18)
            pygame.draw.circle(surface, theme.BOARD_EDGE, _ipoint(point), 18, 2)

    def _draw_player_tab(
        self,
        surface: pygame.Surface,
        game,
        fonts: dict[str, pygame.font.Font],
        player_index: int,
        yard: pygame.Rect,
    ) -> None:
        """Draw the player's name tag on the outer edge of a square yard.

        Banners live outside the board: above the two top yards and below the
        two bottom yards, never over track cells.
        """

        color = self.display.seat_colors[player_index]
        name = game.players[player_index].name[:16]
        if yard.centery < self.display.center[1]:
            label_y = yard.y - 24
        else:
            label_y = yard.bottom + 24
        rect = pygame.Rect(0, 0, 150, 28)
        rect.center = (yard.centerx, label_y)
        theme.draw_player_banner(surface, rect, color, name, fonts)

    def _draw_track(self, surface: pygame.Surface) -> None:
        """Draw the shared white track and colored start squares."""

        for index, point in enumerate(self.display.track_positions):
            owner = _owner_for_start(index, self.layout.start_indices)
            fill = WHITE
            border = theme.BOARD_EDGE
            if owner is not None:
                fill = theme.brighten(self.display.seat_colors[owner], 8)
            if self.display.track_cells:
                self._draw_display_cell(surface, self.display.track_cells[index], fill, border)
            else:
                rect = _cell_rect(point, self.cell_radius)
                pygame.draw.rect(surface, fill, rect, border_radius=2)
                pygame.draw.rect(surface, border, rect, 2, border_radius=2)
            if index in self.layout.safe_indices:
                theme.draw_star(surface, point, 13, theme.BOARD_EDGE, fill=WHITE)
            if owner is not None:
                self._draw_start_arrow(surface, owner, point)

    def _draw_start_arrow(self, surface: pygame.Surface, player_index: int, point: tuple[float, float]) -> None:
        """Draw a colored arrow showing the first movement direction."""

        next_index = (self.layout.start_indices[player_index] + 1) % self.layout.track_length
        next_point = self.display.track_positions[next_index]
        angle = math.atan2(next_point[1] - point[1], next_point[0] - point[0])
        theme.draw_arrow(surface, point, angle, self.display.seat_colors[player_index], length=22)

    def _draw_home_lanes(self, surface: pygame.Surface) -> None:
        """Draw each player's private colored path into the center."""

        for player_index, lane in enumerate(self.display.home_lanes):
            color = self.display.seat_colors[player_index]
            for lane_index, point in enumerate(lane):
                if self.display.home_lane_cells:
                    self._draw_display_cell(
                        surface,
                        self.display.home_lane_cells[player_index][lane_index],
                        theme.brighten(color, 22),
                        theme.BOARD_EDGE,
                    )
                else:
                    rect = _cell_rect(point, self.cell_radius)
                    pygame.draw.rect(surface, theme.brighten(color, 22), rect, border_radius=2)
                    pygame.draw.rect(surface, theme.BOARD_EDGE, rect, 2, border_radius=2)

    def _draw_display_cell(
        self,
        surface: pygame.Surface,
        cell: DisplayCell,
        fill: tuple[int, int, int],
        border: tuple[int, int, int],
    ) -> None:
        """Draw one rotated radial board cell."""

        points = [_ipoint(point) for point in cell.corners]
        pygame.draw.polygon(surface, fill, points)
        pygame.draw.polygon(surface, border, points, 2)

    def _draw_center_home(self, surface: pygame.Surface, game) -> None:
        """Draw the multicolor finish area in the board center."""

        if self.layout.total_players == 4:
            self._draw_square_center_home(surface)
            return

        # Radial hub: one coloured wedge per seat, each facing the arm whose
        # home column ends on that hub edge, with the live die on top.
        hub = self.display.hub_polygon
        center = _ipoint(self.display.center)
        shadow = [(x + 0, y + 6) for x, y in (_ipoint(point) for point in hub)]
        pygame.draw.polygon(surface, theme.SHADOW, shadow)
        for seat in range(self.layout.total_players):
            wedge = [
                center,
                _ipoint(hub[seat - 1]),
                _ipoint(hub[seat]),
            ]
            pygame.draw.polygon(surface, self.display.seat_colors[seat], wedge)
        pygame.draw.polygon(surface, theme.BOARD_EDGE, [_ipoint(point) for point in hub], 3)
        die_size = 44
        die_rect = pygame.Rect(0, 0, die_size, die_size)
        die_rect.center = center
        theme.draw_die_face(surface, die_rect, game.last_roll)

    def _draw_square_center_home(self, surface: pygame.Surface) -> None:
        """Draw the four colored triangles in the classic square board center."""

        center_rect = _square_center_rect()
        cx, cy = center_rect.center
        # Each finish wedge points at the seat that owns it: seat 0 arrives
        # from the bottom edge, then clockwise seats 1..3 arrive from the
        # left, top, and right edges.
        wedges = [
            [center_rect.bottomleft, center_rect.bottomright, (cx, cy)],
            [center_rect.topleft, center_rect.bottomleft, (cx, cy)],
            [center_rect.topleft, center_rect.topright, (cx, cy)],
            [center_rect.topright, center_rect.bottomright, (cx, cy)],
        ]
        for player_index, points in enumerate(wedges):
            pygame.draw.polygon(surface, self.display.seat_colors[player_index], points)
            pygame.draw.polygon(surface, theme.BOARD_EDGE, points, 2)
        pygame.draw.circle(surface, theme.HUD_DARK, (cx, cy), 24)
        pygame.draw.circle(surface, theme.WALLPAPER_BLUE, (cx, cy), 17)
        pygame.draw.circle(surface, WHITE, (cx, cy), 5)

    def _draw_move_highlights(self, surface: pygame.Surface, moves: list[Move]) -> None:
        """Ring clickable tokens and their destinations for a human turn."""

        for move in moves:
            start = self.position_for(move.player_index, move.from_steps, move.token_index)
            pygame.draw.circle(surface, WHITE, _ipoint(start), self.cell_radius + 18, 4)
            landing = self.position_for(move.player_index, move.to_steps, move.token_index)
            pygame.draw.circle(surface, GOLD, _ipoint(landing), self.cell_radius + 21, 4)

    def _draw_tokens(
        self,
        surface: pygame.Surface,
        game,
        fonts: dict[str, pygame.font.Font],
        animated_positions: dict[tuple[int, int], tuple[float, float]],
    ) -> None:
        """Draw all player pawns as glossy pin-shaped tokens."""

        stack_offsets: dict[tuple[int, int], int] = {}
        for player_index, player in enumerate(game.players):
            for token_index, token in enumerate(player.tokens):
                base = animated_positions.get(
                    (player_index, token_index),
                    self.position_for(player_index, token.steps, token_index),
                )
                track_index = self.layout.track_index(player_index, token.steps)
                offset = (0, 0)
                if track_index is not None:
                    count = stack_offsets.get((player_index, track_index), 0)
                    stack_offsets[(player_index, track_index)] = count + 1
                    offset = ((count % 2) * 12 - 6, (count // 2) * 12 - 6)
                center = (base[0] + offset[0], base[1] + offset[1])
                theme.draw_token_pin(surface, center, player.color, radius=15, label=str(token_index + 1), fonts=fonts)


def _display_layout_for(layout) -> DisplayLayout:
    """Return renderer coordinates while preserving the engine's indexes."""

    if layout.total_players == 4:
        return _square_display_layout(layout)
    return _radial_display_layout(layout)


# One quarter of the classic 15x15 cross, written for seat 0 (Player 1, blue,
# bottom-left yard). Cell 0 is the seat's colored start square, directly beside
# its yard, and the cells continue CLOCKWISE around the board: up the bottom
# arm's left column, west along the west arm's bottom row, then up the west
# tip. Rotating this template 90 degrees clockwise per seat builds the full
# 52-cell loop, which keeps every seat's start square, home column, and yard
# aligned by construction.
SQUARE_QUARTER_TRACK: tuple[tuple[int, int], ...] = (
    (6, 13), (6, 12), (6, 11), (6, 10), (6, 9),
    (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),
    (0, 7), (0, 6),
)

# Seat 0's private home column: entered from the bottom edge, climbing the
# middle column toward the center. The final cell sits inside the 3x3 center
# square, underneath that seat's colored finish wedge.
SQUARE_HOME_LANE: tuple[tuple[int, int], ...] = (
    (7, 13), (7, 12), (7, 11), (7, 10), (7, 9), (7, 8),
)


def _rotate_cell_cw(cell: tuple[int, int], quarter_turns: int) -> tuple[int, int]:
    """Rotate a 15x15 grid cell clockwise by 90-degree steps around the center."""

    col, row = cell
    for _ in range(quarter_turns % 4):
        col, row = GRID_CELLS - 1 - row, col
    return col, row


def _square_display_layout(layout) -> DisplayLayout:
    """Build classic 15-by-15 Ludo coordinates for the four-player board."""

    track_cells = [
        _rotate_cell_cw(cell, seat)
        for seat in range(layout.total_players)
        for cell in SQUARE_QUARTER_TRACK
    ]
    home_lanes = tuple(
        tuple(_grid_center(*_rotate_cell_cw(cell, seat)) for cell in SQUARE_HOME_LANE)
        for seat in range(layout.total_players)
    )
    yard_positions = tuple(_square_yard_slots(yard) for yard in _square_home_rects())
    return DisplayLayout(
        total_players=layout.total_players,
        seat_colors=seat_colors(layout.total_players),
        track_positions=tuple(_grid_center(col, row) for col, row in track_cells),
        home_lanes=home_lanes,
        yard_positions=yard_positions,
        center=_grid_center(7, 7),
        radius=SQUARE_SIZE / 2,
        cell_size=SQUARE_CELL,
    )


def _square_yard_slots(yard: pygame.Rect) -> tuple[Point, ...]:
    """Return four token parking spots centered inside one corner yard."""

    spread = 36
    return (
        (yard.centerx - spread, yard.centery - spread),
        (yard.centerx + spread, yard.centery - spread),
        (yard.centerx - spread, yard.centery + spread),
        (yard.centerx + spread, yard.centery + spread),
    )


def _radial_display_layout(layout) -> DisplayLayout:
    """Build a compact convex radial board for five or six players.

    Layout rules, mirroring the classic square board:

    - Seat 0's yard triangle points at the bottom of the screen and seats
      continue clockwise, one yard wedge between every pair of arms.
    - Each arm carries two white lanes plus a coloured home column. A token
      arrives near the hub, runs OUT along the lane away from its owner's
      yard, crosses the tip cell, and runs back IN along the lane beside the
      owner's yard, so the overall loop is clockwise.
    - The start cell is the inbound lane's outermost cell, right beside the
      seat's own yard, and the loop-end (the tip) hands over orthogonally to
      the home column, which marches inward and finishes at the hub.
    """

    total = layout.total_players
    spec = RADIAL_SPECS[total]
    center = RADIAL_CENTER
    home_length = len(layout.home_lanes[0])

    path_cells: list[DisplayCell] = []
    home_lane_cells: list[tuple[DisplayCell, ...]] = []
    yard_positions: list[tuple[Point, ...]] = []
    yard_frames: list[tuple[Point, ...]] = []
    banner_anchors: list[Point] = []

    for seat in range(total):
        arm_angle = _seat_arm_angle(seat, total)
        outward = _unit(arm_angle)
        tangent = (-outward[1], outward[0])

        # Outbound lane (away from the hub), tip, then inbound lane back to
        # the hub. The +tangent side faces this seat's own yard wedge.
        arm: list[DisplayCell] = []
        for step in range(home_length):
            arm.append(
                _radial_cell(center, outward, tangent, spec.inner_radius + step * spec.cell_step, -spec.lane_offset, spec.cell_size)
            )
        arm.append(
            _radial_cell(center, outward, tangent, spec.inner_radius + home_length * spec.cell_step, 0.0, spec.cell_size)
        )
        for step in range(home_length):
            arm.append(
                _radial_cell(
                    center,
                    outward,
                    tangent,
                    spec.inner_radius + (home_length - 1 - step) * spec.cell_step,
                    spec.lane_offset,
                    spec.cell_size,
                )
            )
        path_cells.extend(arm)

        home_lane_cells.append(
            tuple(
                _radial_cell(
                    center,
                    outward,
                    tangent,
                    spec.inner_radius + (home_length - 1 - step) * spec.cell_step,
                    0.0,
                    spec.cell_size,
                )
                for step in range(home_length)
            )
        )

        yard_angle = _seat_yard_angle(seat, total)
        yard_frames.append(_radial_yard_frame(center, yard_angle, spec))
        yard_positions.append(_radial_yard_slots(center, yard_angle, spec))
        banner_anchors.append(_radial_banner_anchor(center, yard_angle, spec))

    # Rotate the concatenated arm path so index 0 is seat 0's start cell (the
    # inbound lane's outermost cell). Engine start indices are 13 * seat, and
    # the same rotation aligns every other seat by symmetry.
    entry_offset = home_length + 1
    track_cells = path_cells[entry_offset:] + path_cells[:entry_offset]

    hub_polygon = tuple(
        _polar(center, _seat_yard_angle(seat, total), spec.inner_radius - 0.55 * spec.cell_step)
        for seat in range(total)
    )
    hull_points: list[Point] = []
    for cell in track_cells:
        hull_points.extend(cell.corners)
    for frame in yard_frames:
        hull_points.extend(frame)
    silhouette = tuple(_inflate_from(center, _convex_hull(hull_points), 14.0))

    return DisplayLayout(
        total_players=total,
        seat_colors=seat_colors(total),
        track_positions=tuple(cell.center for cell in track_cells),
        home_lanes=tuple(tuple(cell.center for cell in lane) for lane in home_lane_cells),
        yard_positions=tuple(yard_positions),
        center=center,
        radius=spec.yard_base_radius,
        cell_size=spec.cell_size,
        track_cells=tuple(track_cells),
        home_lane_cells=tuple(home_lane_cells),
        yard_frames=tuple(yard_frames),
        silhouette=silhouette,
        hub_polygon=hub_polygon,
        banner_anchors=tuple(banner_anchors),
    )


def _seat_arm_angle(seat: int, total_players: int) -> float:
    """Return the direction of one seat's arm, in radians.

    Seat 0's yard points straight down (pi/2 in y-down screen coordinates),
    and its arm sits one half-sector anti-clockwise of the yard. Increasing
    the angle moves clockwise on screen.
    """

    return math.pi / 2 - math.pi / total_players + math.tau * seat / total_players


def _seat_yard_angle(seat: int, total_players: int) -> float:
    """Return the direction of one seat's yard wedge, between two arms."""

    return math.pi / 2 + math.tau * seat / total_players


def _unit(angle: float) -> Point:
    """Return the unit vector for ``angle`` in y-down screen coordinates."""

    return math.cos(angle), math.sin(angle)


def _polar(center: Point, angle: float, radius: float) -> Point:
    """Return the point ``radius`` pixels from ``center`` along ``angle``."""

    return center[0] + math.cos(angle) * radius, center[1] + math.sin(angle) * radius


def _radial_yard_frame(center: Point, yard_angle: float, spec: RadialSpec) -> tuple[Point, ...]:
    """Return the colored yard triangle: apex toward the hub, base outward."""

    return (
        _polar(center, yard_angle, spec.yard_apex_radius),
        _polar(center, yard_angle - spec.yard_half_angle, spec.yard_base_radius),
        _polar(center, yard_angle + spec.yard_half_angle, spec.yard_base_radius),
    )


def _radial_yard_slots(center: Point, yard_angle: float, spec: RadialSpec) -> tuple[Point, ...]:
    """Return four token parking spots in a 2x2 grid inside one yard."""

    base = _polar(center, yard_angle, spec.token_radius)
    outward = _unit(yard_angle)
    tangent = (-outward[1], outward[0])
    spread = spec.token_spread
    offsets = ((-spread, -spread), (spread, -spread), (-spread, spread), (spread, spread))
    return tuple(
        (
            base[0] + tangent[0] * side + outward[0] * depth,
            base[1] + tangent[1] * side + outward[1] * depth,
        )
        for side, depth in offsets
    )


def _radial_banner_anchor(center: Point, yard_angle: float, spec: RadialSpec) -> Point:
    """Return the name-banner center on the outer edge of one yard."""

    x, y = _polar(center, yard_angle, spec.banner_radius)
    # Keep the whole 150x28 banner on the logical canvas with a small margin.
    return (max(92.0, min(1188.0, x)), max(28.0, min(872.0, y)))


def _convex_hull(points: list[Point]) -> list[Point]:
    """Return the convex hull of ``points`` using the monotone chain scan."""

    unique = sorted(set(points))
    if len(unique) <= 2:
        return unique

    def cross(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[Point] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _inflate_from(center: Point, points: list[Point], padding: float) -> list[Point]:
    """Push hull points radially away from ``center`` by ``padding`` pixels."""

    inflated: list[Point] = []
    for x, y in points:
        dx = x - center[0]
        dy = y - center[1]
        length = math.hypot(dx, dy) or 1.0
        scale = (length + padding) / length
        inflated.append((center[0] + dx * scale, center[1] + dy * scale))
    return inflated


def _grid_center(col: int, row: int) -> Point:
    """Convert a 15-by-15 Ludo grid cell into a screen coordinate."""

    return (
        SQUARE_LEFT + col * SQUARE_CELL + SQUARE_CELL / 2,
        SQUARE_TOP + row * SQUARE_CELL + SQUARE_CELL / 2,
    )


def _square_home_rects() -> tuple[pygame.Rect, ...]:
    """Return the four large corner yards, in clockwise seat order.

    Seat 0 (Player 1) owns the bottom-left corner, then seats continue
    clockwise: top-left, top-right, bottom-right.
    """

    cell = SQUARE_CELL
    return (
        pygame.Rect(SQUARE_LEFT, SQUARE_TOP + cell * 9, cell * 6, cell * 6),
        pygame.Rect(SQUARE_LEFT, SQUARE_TOP, cell * 6, cell * 6),
        pygame.Rect(SQUARE_LEFT + cell * 9, SQUARE_TOP, cell * 6, cell * 6),
        pygame.Rect(SQUARE_LEFT + cell * 9, SQUARE_TOP + cell * 9, cell * 6, cell * 6),
    )


def _square_center_rect() -> pygame.Rect:
    """Return the middle 3-by-3 area where home lanes meet."""

    return pygame.Rect(SQUARE_LEFT + SQUARE_CELL * 6, SQUARE_TOP + SQUARE_CELL * 6, SQUARE_CELL * 3, SQUARE_CELL * 3)


def _player_outward(player_index: int, total_players: int) -> Point:
    """Return the direction from the hub toward one radial player base."""

    angle = -math.pi / 2 + math.tau * player_index / total_players
    return math.cos(angle), math.sin(angle)


def _radial_cell(
    center: Point,
    outward: Point,
    tangent: Point,
    distance: float,
    lane_offset: float,
    size: float,
) -> DisplayCell:
    """Build one rotated square cell from radial distance and lane offset."""

    cell_center = (
        center[0] + outward[0] * distance + tangent[0] * lane_offset,
        center[1] + outward[1] * distance + tangent[1] * lane_offset,
    )
    half = size / 2
    corners = (
        _offset_point(cell_center, outward, tangent, -half, -half),
        _offset_point(cell_center, outward, tangent, half, -half),
        _offset_point(cell_center, outward, tangent, half, half),
        _offset_point(cell_center, outward, tangent, -half, half),
    )
    return DisplayCell(center=cell_center, corners=corners)


def _offset_point(base: Point, outward: Point, tangent: Point, along: float, across: float) -> Point:
    """Offset a point along the radial and tangent axes."""

    return (
        base[0] + outward[0] * along + tangent[0] * across,
        base[1] + outward[1] * along + tangent[1] * across,
    )


def _owner_for_start(index: int, start_indices: tuple[int, ...]) -> int | None:
    """Return which player owns a start square, or ``None``."""

    for owner, start in enumerate(start_indices):
        if index == start:
            return owner
    return None


def _cell_rect(point: tuple[float, float], radius: int) -> pygame.Rect:
    """Build a square pygame rect centered on a board coordinate."""

    return pygame.Rect(int(point[0] - radius), int(point[1] - radius), radius * 2, radius * 2)


def _average_point(points: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    """Return the center point of a small cluster of coordinates."""

    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _ipoint(point: tuple[float, float]) -> tuple[int, int]:
    """Convert floating layout coordinates to integer pixels."""

    return int(point[0]), int(point[1])
