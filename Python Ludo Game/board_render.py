"""Procedural drawing of the themed Ludo boards and tokens."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

import visual_theme as theme
from models import Move
from settings import GOLD, INK, PLAYER_COLORS, WHITE


Point = tuple[float, float]
SQUARE_CELL = 42
SQUARE_LEFT = 135
SQUARE_TOP = 105
SQUARE_SIZE = SQUARE_CELL * 15
RADIAL_CENTER = (450.0, 410.0)
RADIAL_RADIUS = 245.0
RADIAL_INNER_DISTANCE = 78.0
RADIAL_CELL_STEP = 28.0
RADIAL_CELL_SIZE = 30.0
RADIAL_LANE_OFFSET = 34.0
RADIAL_YARD_GAP = 70.0


@dataclass(frozen=True)
class DisplayCell:
    """One visible board cell with a center point and rotated corners."""

    center: Point
    corners: tuple[Point, Point, Point, Point]


@dataclass(frozen=True)
class DisplayLayout:
    """Screen coordinates used by the renderer for one board shape.

    The rules engine keeps its compact step indexes. This display layout lets
    the four-player game look like a traditional square board while the five-
    and six-player games keep the generalized radial coordinates.
    """

    total_players: int
    polygon_sides: int
    track_positions: tuple[Point, ...]
    home_lanes: tuple[tuple[Point, ...], ...]
    yard_positions: tuple[tuple[Point, ...], ...]
    center: Point
    radius: float
    track_cells: tuple[DisplayCell, ...] = ()
    home_lane_cells: tuple[tuple[DisplayCell, ...], ...] = ()
    arm_backplates: tuple[tuple[Point, ...], ...] = ()


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
        self._draw_center_home(surface)
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

        for backplate in self.display.arm_backplates:
            theme.draw_shadowed_polygon(
                surface,
                [_ipoint(point) for point in backplate],
                theme.CREAM,
                border=theme.BOARD_EDGE,
                border_width=3,
            )
        pygame.draw.circle(surface, theme.CREAM, _ipoint(self.display.center), 108)
        pygame.draw.circle(surface, theme.BOARD_EDGE, _ipoint(self.display.center), 108, 3)

    def _draw_square_homes(self, surface: pygame.Surface, game, fonts: dict[str, pygame.font.Font]) -> None:
        """Draw four large square home yards like a classic Ludo board."""

        for player_index, yard in enumerate(_square_home_rects()):
            positions = self.display.yard_positions[player_index]
            color = PLAYER_COLORS[player_index]
            theme.draw_shadowed_rect(surface, yard, color, border=theme.BOARD_EDGE, radius=8)
            inner = yard.inflate(-92, -92)
            pygame.draw.rect(surface, WHITE, inner, border_radius=5)
            pygame.draw.rect(surface, theme.BOARD_EDGE, inner, 2, border_radius=5)
            self._draw_yard_slots(surface, positions, color)
            self._draw_player_tab(surface, game, fonts, player_index, yard)

    def _draw_radial_homes(self, surface: pygame.Surface, game, fonts: dict[str, pygame.font.Font]) -> None:
        """Draw triangular homes for the five- and six-player boards."""

        cx, cy = self.display.center
        for player_index, positions in enumerate(self.display.yard_positions):
            color = PLAYER_COLORS[player_index]
            yard_center = _average_point(positions)
            outward = _normal((yard_center[0] - cx, yard_center[1] - cy))
            tangent = (-outward[1], outward[0])
            base = (yard_center[0] + outward[0] * 48, yard_center[1] + outward[1] * 48)
            tip = (yard_center[0] - outward[0] * 98, yard_center[1] - outward[1] * 98)
            points = [
                _ipoint((base[0] + tangent[0] * 92, base[1] + tangent[1] * 92)),
                _ipoint(tip),
                _ipoint((base[0] - tangent[0] * 92, base[1] - tangent[1] * 92)),
            ]
            theme.draw_shadowed_polygon(surface, points, color, border=theme.BOARD_EDGE, border_width=4)
            inner = [
                _ipoint((yard_center[0] + tangent[0] * 54, yard_center[1] + tangent[1] * 54)),
                _ipoint((yard_center[0] - outward[0] * 54, yard_center[1] - outward[1] * 54)),
                _ipoint((yard_center[0] - tangent[0] * 54, yard_center[1] - tangent[1] * 54)),
            ]
            pygame.draw.polygon(surface, WHITE, inner)
            pygame.draw.polygon(surface, theme.BOARD_EDGE, inner, 2)
            self._draw_yard_slots(surface, positions, color)
            self._draw_player_tab(surface, game, fonts, player_index, pygame.Rect(0, 0, 1, 1), yard_center, outward)

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
        point: tuple[float, float] | None = None,
        outward: tuple[float, float] | None = None,
    ) -> None:
        """Draw the player's name tag near their home area."""

        color = PLAYER_COLORS[player_index]
        name = game.players[player_index].name[:16]
        if point is None:
            label_y = yard.bottom + 10 if yard.centery < self.display.center[1] else yard.y - 34
            rect = pygame.Rect(0, 0, 150, 28)
            rect.center = (yard.centerx, label_y)
        else:
            outward = outward or (0.0, 1.0)
            rect = pygame.Rect(0, 0, 150, 28)
            # Radial homes can sit close to the screen edge, especially the
            # top seat. Clamp the banner so the player's name remains readable.
            label_x = int(point[0] + outward[0] * 88)
            label_y = int(point[1] + outward[1] * 88)
            rect.center = (max(78, min(832, label_x)), max(36, min(764, label_y)))
        theme.draw_player_banner(surface, rect, color, name, fonts)

    def _draw_track(self, surface: pygame.Surface) -> None:
        """Draw the shared white track and colored start squares."""

        for index, point in enumerate(self.display.track_positions):
            owner = _owner_for_start(index, self.layout.start_indices)
            fill = WHITE
            border = theme.BOARD_EDGE
            if owner is not None:
                fill = theme.brighten(PLAYER_COLORS[owner], 8)
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
        theme.draw_arrow(surface, point, angle, PLAYER_COLORS[player_index], length=22)

    def _draw_home_lanes(self, surface: pygame.Surface) -> None:
        """Draw each player's private colored path into the center."""

        for player_index, lane in enumerate(self.display.home_lanes):
            color = PLAYER_COLORS[player_index]
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

    def _draw_center_home(self, surface: pygame.Surface) -> None:
        """Draw the multicolor home medallion in the board center."""

        if self.layout.total_players == 4:
            self._draw_square_center_home(surface)
            return

        cx, cy = self.display.center
        radius = 74
        for player_index in range(self.layout.total_players):
            start = -math.pi / 2 + math.tau * player_index / self.layout.total_players
            end = -math.pi / 2 + math.tau * (player_index + 1) / self.layout.total_players
            points = [_ipoint((cx, cy))]
            for step in range(8):
                angle = start + (end - start) * step / 7
                points.append(_ipoint((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius)))
            pygame.draw.polygon(surface, PLAYER_COLORS[player_index], points)
        pygame.draw.circle(surface, theme.HUD_DARK, _ipoint(self.display.center), 38)
        pygame.draw.circle(surface, theme.WALLPAPER_BLUE, _ipoint(self.display.center), 28)
        pygame.draw.circle(surface, WHITE, _ipoint(self.display.center), 7)
        pygame.draw.circle(surface, theme.BOARD_EDGE, _ipoint(self.display.center), radius, 3)

    def _draw_square_center_home(self, surface: pygame.Surface) -> None:
        """Draw the four colored triangles in the classic square board center."""

        center_rect = _square_center_rect()
        cx, cy = center_rect.center
        corners = [
            center_rect.topleft,
            center_rect.topright,
            center_rect.bottomright,
            center_rect.bottomleft,
        ]
        wedges = [
            [corners[0], corners[1], (cx, cy)],
            [corners[1], corners[2], (cx, cy)],
            [corners[2], corners[3], (cx, cy)],
            [corners[3], corners[0], (cx, cy)],
        ]
        for player_index, points in enumerate(wedges):
            pygame.draw.polygon(surface, PLAYER_COLORS[player_index], points)
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


def _square_display_layout(layout) -> DisplayLayout:
    """Build classic 15-by-15 Ludo coordinates for the four-player board."""

    # These grid cells trace the standard outer cross path. Rotating by one
    # segment places player 1 at the top, then the other players clockwise.
    base_track = [
        (6, 1), (6, 2), (6, 3), (6, 4), (6, 5), (5, 6), (4, 6), (3, 6), (2, 6), (1, 6), (0, 6), (0, 7), (0, 8),
        (1, 8), (2, 8), (3, 8), (4, 8), (5, 8), (6, 9), (6, 10), (6, 11), (6, 12), (6, 13), (6, 14), (7, 14), (8, 14),
        (8, 13), (8, 12), (8, 11), (8, 10), (8, 9), (9, 8), (10, 8), (11, 8), (12, 8), (13, 8), (14, 8), (14, 7), (14, 6),
        (13, 6), (12, 6), (11, 6), (10, 6), (9, 6), (8, 5), (8, 4), (8, 3), (8, 2), (8, 1), (8, 0), (7, 0), (6, 0),
    ]
    rotated = base_track[13:] + base_track[:13]
    home_lanes = (
        tuple(_grid_center(7, row) for row in range(1, 7)),
        tuple(_grid_center(col, 7) for col in range(13, 7, -1)),
        tuple(_grid_center(7, row) for row in range(13, 7, -1)),
        tuple(_grid_center(col, 7) for col in range(1, 7)),
    )
    yard_grids = (
        ((2, 2), (4, 2), (2, 4), (4, 4)),
        ((10, 2), (12, 2), (10, 4), (12, 4)),
        ((10, 10), (12, 10), (10, 12), (12, 12)),
        ((2, 10), (4, 10), (2, 12), (4, 12)),
    )
    return DisplayLayout(
        total_players=layout.total_players,
        polygon_sides=layout.polygon_sides,
        track_positions=tuple(_grid_center(col, row) for col, row in rotated),
        home_lanes=home_lanes,
        yard_positions=tuple(tuple(_grid_center(col, row) for col, row in group) for group in yard_grids),
        center=_grid_center(7, 7),
        radius=SQUARE_SIZE / 2,
    )


def _radial_display_layout(layout) -> DisplayLayout:
    """Build fitted pentagon/hexagon arm grids for the desktop play area."""

    center = RADIAL_CENTER
    radius = RADIAL_RADIUS
    segment_length = len(layout.track_positions) // layout.total_players
    home_length = len(layout.home_lanes[0])

    track_cells: list[DisplayCell] = []
    track_positions: list[Point] = []
    home_lane_cells: list[tuple[DisplayCell, ...]] = []
    home_lanes: list[tuple[Point, ...]] = []
    yard_positions: list[tuple[Point, ...]] = []
    arm_backplates: list[tuple[Point, ...]] = []

    for player_index in range(layout.total_players):
        outward = _player_outward(player_index, layout.total_players)
        tangent = (-outward[1], outward[0])
        arm_backplates.append(_radial_arm_backplate(center, outward, tangent))

        # A radial Ludo arm has two white race lanes flanking one coloured home
        # lane. The main track walks down the left lane, crosses near the hub,
        # then walks back up the right lane.
        segment_cells = _radial_track_cells(center, outward, tangent)
        if len(segment_cells) != segment_length:
            raise ValueError("radial visual track must match the rules segment length")
        track_cells.extend(segment_cells)
        track_positions.extend(cell.center for cell in segment_cells)

        home_cells = _radial_home_cells(center, outward, tangent, home_length)
        home_lane_cells.append(tuple(home_cells))
        home_lanes.append(tuple(cell.center for cell in home_cells))
        yard_positions.append(tuple(_radial_yard_cluster(center, outward, tangent)))

    return DisplayLayout(
        total_players=layout.total_players,
        polygon_sides=layout.polygon_sides,
        track_positions=tuple(track_positions),
        home_lanes=tuple(home_lanes),
        yard_positions=tuple(yard_positions),
        center=center,
        radius=radius,
        track_cells=tuple(track_cells),
        home_lane_cells=tuple(home_lane_cells),
        arm_backplates=tuple(arm_backplates),
    )


def _grid_center(col: int, row: int) -> Point:
    """Convert a 15-by-15 Ludo grid cell into a screen coordinate."""

    return (
        SQUARE_LEFT + col * SQUARE_CELL + SQUARE_CELL / 2,
        SQUARE_TOP + row * SQUARE_CELL + SQUARE_CELL / 2,
    )


def _square_home_rects() -> tuple[pygame.Rect, ...]:
    """Return the four large corner yards for the square board."""

    cell = SQUARE_CELL
    return (
        pygame.Rect(SQUARE_LEFT, SQUARE_TOP, cell * 6, cell * 6),
        pygame.Rect(SQUARE_LEFT + cell * 9, SQUARE_TOP, cell * 6, cell * 6),
        pygame.Rect(SQUARE_LEFT + cell * 9, SQUARE_TOP + cell * 9, cell * 6, cell * 6),
        pygame.Rect(SQUARE_LEFT, SQUARE_TOP + cell * 9, cell * 6, cell * 6),
    )


def _square_center_rect() -> pygame.Rect:
    """Return the middle 3-by-3 area where home lanes meet."""

    return pygame.Rect(SQUARE_LEFT + SQUARE_CELL * 6, SQUARE_TOP + SQUARE_CELL * 6, SQUARE_CELL * 3, SQUARE_CELL * 3)


def _player_outward(player_index: int, total_players: int) -> Point:
    """Return the direction from the hub toward one radial player base."""

    angle = -math.pi / 2 + math.tau * player_index / total_players
    return math.cos(angle), math.sin(angle)


def _radial_track_cells(center: Point, outward: Point, tangent: Point) -> list[DisplayCell]:
    """Return the 13 visible race cells for one 5P/6P arm.

    Seven cells move inward on one side of the arm, then six cells move back
    outward on the other side. That creates the same two-sided lane structure
    visible in the reference boards instead of a single polygon-edge line.
    """

    left_lane = [
        _radial_cell(center, outward, tangent, RADIAL_RADIUS - step * RADIAL_CELL_STEP, -RADIAL_LANE_OFFSET)
        for step in range(7)
    ]
    right_lane = [
        _radial_cell(
            center,
            outward,
            tangent,
            RADIAL_INNER_DISTANCE + step * RADIAL_CELL_STEP,
            RADIAL_LANE_OFFSET,
        )
        for step in range(6)
    ]
    return left_lane + right_lane


def _radial_home_cells(center: Point, outward: Point, tangent: Point, home_length: int) -> list[DisplayCell]:
    """Return the coloured center-lane cells that lead a player home."""

    return [
        _radial_cell(
            center,
            outward,
            tangent,
            RADIAL_RADIUS - (step + 1) * RADIAL_CELL_STEP,
            0.0,
        )
        for step in range(home_length)
    ]


def _radial_cell(center: Point, outward: Point, tangent: Point, distance: float, lane_offset: float) -> DisplayCell:
    """Build one rotated square cell from radial distance and lane offset."""

    cell_center = (
        center[0] + outward[0] * distance + tangent[0] * lane_offset,
        center[1] + outward[1] * distance + tangent[1] * lane_offset,
    )
    half = RADIAL_CELL_SIZE / 2
    corners = (
        _offset_point(cell_center, outward, tangent, -half, -half),
        _offset_point(cell_center, outward, tangent, half, -half),
        _offset_point(cell_center, outward, tangent, half, half),
        _offset_point(cell_center, outward, tangent, -half, half),
    )
    return DisplayCell(center=cell_center, corners=corners)


def _radial_arm_backplate(center: Point, outward: Point, tangent: Point) -> tuple[Point, ...]:
    """Return the cream board arm behind a 3-column radial lane."""

    half_width = RADIAL_LANE_OFFSET + RADIAL_CELL_SIZE / 2 + 9
    inner = RADIAL_INNER_DISTANCE - RADIAL_CELL_SIZE / 2 - 8
    outer = RADIAL_RADIUS + RADIAL_CELL_SIZE / 2 + 8
    return (
        _radial_point(center, outward, tangent, outer, -half_width),
        _radial_point(center, outward, tangent, outer, half_width),
        _radial_point(center, outward, tangent, inner, half_width),
        _radial_point(center, outward, tangent, inner, -half_width),
    )


def _radial_point(center: Point, outward: Point, tangent: Point, distance: float, offset: float) -> Point:
    """Convert radial arm coordinates into screen coordinates."""

    return (
        center[0] + outward[0] * distance + tangent[0] * offset,
        center[1] + outward[1] * distance + tangent[1] * offset,
    )


def _offset_point(base: Point, outward: Point, tangent: Point, along: float, across: float) -> Point:
    """Offset a point along the radial and tangent axes."""

    return (
        base[0] + outward[0] * along + tangent[0] * across,
        base[1] + outward[1] * along + tangent[1] * across,
    )


def _regular_polygon_points(sides: int, center: Point, radius: float) -> list[Point]:
    """Return vertices for a regular polygon that starts at the top."""

    cx, cy = center
    return [
        (
            cx + math.cos(-math.pi / 2 + math.tau * index / sides) * radius,
            cy + math.sin(-math.pi / 2 + math.tau * index / sides) * radius,
        )
        for index in range(sides)
    ]


def _radial_yard_cluster(center: Point, outward: Point, tangent: Point) -> list[Point]:
    """Return four token parking spots inside one triangular radial base."""

    base = _radial_point(center, outward, tangent, RADIAL_RADIUS + RADIAL_YARD_GAP, 0.0)
    offsets = [(-20, -20), (20, -20), (-20, 20), (20, 20)]
    return [
        (
            base[0] + tangent[0] * side + outward[0] * depth,
            base[1] + tangent[1] * side + outward[1] * depth,
        )
        for side, depth in offsets
    ]


def _lerp(start: Point, end: Point, amount: float) -> Point:
    """Linearly interpolate between two screen points."""

    return (
        start[0] + (end[0] - start[0]) * amount,
        start[1] + (end[1] - start[1]) * amount,
    )


def _outer_polygon(layout, padding: int) -> list[tuple[int, int]]:
    """Return the board outline, slightly larger than the playable track."""

    points = []
    cx, cy = layout.center
    for i in range(layout.polygon_sides):
        angle = -math.pi / 2 + math.tau * i / layout.polygon_sides
        points.append((int(cx + math.cos(angle) * (layout.radius + padding)), int(cy + math.sin(angle) * (layout.radius + padding))))
    return points


def _owner_for_start(index: int, start_indices: tuple[int, ...]) -> int | None:
    """Return which player owns a start square, or ``None``."""

    for owner, start in enumerate(start_indices):
        if index == start:
            return owner
    return None


def _cell_rect(point: tuple[float, float], radius: int) -> pygame.Rect:
    """Build a square pygame rect centered on a board coordinate."""

    return pygame.Rect(int(point[0] - radius), int(point[1] - radius), radius * 2, radius * 2)


def _bounds_for_points(points: tuple[tuple[float, float], ...]) -> pygame.Rect:
    """Return a rectangle that tightly contains a group of points."""

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return pygame.Rect(int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys)))


def _average_point(points: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    """Return the center point of a small cluster of coordinates."""

    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _normal(vector: tuple[float, float]) -> tuple[float, float]:
    """Return a length-one version of ``vector``."""

    x, y = vector
    length = math.hypot(x, y) or 1.0
    return x / length, y / length


def _ipoint(point: tuple[float, float]) -> tuple[int, int]:
    """Convert floating layout coordinates to integer pixels."""

    return int(point[0]), int(point[1])
