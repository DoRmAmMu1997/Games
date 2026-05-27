"""Procedural drawing of polygon Ludo boards and tokens."""

from __future__ import annotations

import math

import pygame

from models import Move
from settings import (
    BOARD_BG,
    BOARD_LINE,
    GOLD,
    HOME_FILL,
    INK,
    PLAYER_COLORS,
    TRACK_FILL,
    WHITE,
)


class BoardRenderer:
    """Draw a generated Ludo layout with active highlights."""

    def __init__(self, layout) -> None:
        self.layout = layout
        self.cell_radius = 17

    def draw(
        self,
        surface: pygame.Surface,
        game,
        fonts: dict[str, pygame.font.Font],
        legal_moves: list[Move] | None = None,
        animated_positions: dict[tuple[int, int], tuple[float, float]] | None = None,
    ) -> None:
        legal_moves = legal_moves or []
        animated_positions = animated_positions or {}
        self._draw_board_background(surface, fonts)
        self._draw_track(surface)
        self._draw_home_lanes(surface)
        self._draw_yards(surface, game, fonts)
        self._draw_move_highlights(surface, legal_moves)
        self._draw_tokens(surface, game, fonts, animated_positions)

    def move_at_pos(self, pos: tuple[int, int], moves: list[Move]) -> Move | None:
        """Return the move whose token was clicked, if any."""

        px, py = pos
        for move in moves:
            center = self.layout.position_for(move.player_index, move.from_steps, move.token_index)
            if math.hypot(px - center[0], py - center[1]) <= self.cell_radius + 12:
                return move
        return None

    def _draw_board_background(self, surface: pygame.Surface, fonts: dict[str, pygame.font.Font]) -> None:
        polygon = _outer_polygon(self.layout)
        pygame.draw.polygon(surface, BOARD_BG, polygon)
        pygame.draw.polygon(surface, BOARD_LINE, polygon, 4)
        pygame.draw.circle(surface, (246, 241, 220), _point(self.layout.center), 72)
        pygame.draw.circle(surface, BOARD_LINE, _point(self.layout.center), 72, 3)
        title = fonts["title"].render("LUDO", True, BOARD_LINE)
        surface.blit(title, title.get_rect(center=_point(self.layout.center)))

    def _draw_track(self, surface: pygame.Surface) -> None:
        for index, point in enumerate(self.layout.track_positions):
            rect = _cell_rect(point, self.cell_radius)
            fill = TRACK_FILL
            owner = _owner_for_start(index, self.layout.start_indices)
            if owner is not None:
                fill = PLAYER_COLORS[owner]
            elif index in self.layout.safe_indices:
                fill = GOLD
            pygame.draw.rect(surface, fill, rect, border_radius=7)
            pygame.draw.rect(surface, BOARD_LINE, rect, 2, border_radius=7)
            if index in self.layout.safe_indices:
                _draw_star(surface, point, 8, BOARD_LINE)

    def _draw_home_lanes(self, surface: pygame.Surface) -> None:
        for player_index, lane in enumerate(self.layout.home_lanes):
            color = PLAYER_COLORS[player_index]
            for point in lane:
                rect = _cell_rect(point, self.cell_radius)
                pygame.draw.rect(surface, HOME_FILL, rect, border_radius=7)
                pygame.draw.rect(surface, color, rect, 3, border_radius=7)

    def _draw_yards(self, surface: pygame.Surface, game, fonts: dict[str, pygame.font.Font]) -> None:
        for player_index, positions in enumerate(self.layout.yard_positions):
            color = PLAYER_COLORS[player_index]
            xs = [point[0] for point in positions]
            ys = [point[1] for point in positions]
            yard = pygame.Rect(min(xs) - 34, min(ys) - 34, max(xs) - min(xs) + 68, max(ys) - min(ys) + 68)
            pygame.draw.rect(surface, (238, 232, 209), yard, border_radius=18)
            pygame.draw.rect(surface, color, yard, 4, border_radius=18)
            label_y = yard.y - 24 if yard.y > 40 else yard.bottom + 4
            name = game.players[player_index].name
            image = fonts["small"].render(name[:16], True, WHITE)
            plate = image.get_rect(center=(yard.centerx, label_y + 10))
            pygame.draw.rect(surface, color, plate.inflate(12, 6), border_radius=8)
            surface.blit(image, plate)

    def _draw_move_highlights(self, surface: pygame.Surface, moves: list[Move]) -> None:
        for move in moves:
            start = self.layout.position_for(move.player_index, move.from_steps, move.token_index)
            pygame.draw.circle(surface, WHITE, _point(start), self.cell_radius + 10, 3)
            landing = self.layout.position_for(move.player_index, move.to_steps, move.token_index)
            pygame.draw.circle(surface, GOLD, _point(landing), self.cell_radius + 13, 3)

    def _draw_tokens(
        self,
        surface: pygame.Surface,
        game,
        fonts: dict[str, pygame.font.Font],
        animated_positions: dict[tuple[int, int], tuple[float, float]],
    ) -> None:
        stack_offsets: dict[tuple[int, int], int] = {}
        for player_index, player in enumerate(game.players):
            for token_index, token in enumerate(player.tokens):
                base = animated_positions.get(
                    (player_index, token_index),
                    self.layout.position_for(player_index, token.steps, token_index),
                )
                track_index = self.layout.track_index(player_index, token.steps)
                offset = (0, 0)
                if track_index is not None:
                    count = stack_offsets.get((player_index, track_index), 0)
                    stack_offsets[(player_index, track_index)] = count + 1
                    offset = ((count % 2) * 10 - 5, (count // 2) * 10 - 5)
                center = (int(base[0] + offset[0]), int(base[1] + offset[1]))
                color = player.color
                pygame.draw.circle(surface, WHITE, center, self.cell_radius)
                pygame.draw.circle(surface, color, center, self.cell_radius - 3)
                pygame.draw.circle(surface, INK, center, self.cell_radius, 2)
                number = fonts["tiny"].render(str(token_index + 1), True, WHITE)
                surface.blit(number, number.get_rect(center=center))


def _outer_polygon(layout) -> list[tuple[int, int]]:
    points = []
    cx, cy = layout.center
    for i in range(layout.polygon_sides):
        angle = -math.pi / 2 + math.tau * i / layout.polygon_sides
        points.append((int(cx + math.cos(angle) * (layout.radius + 105)), int(cy + math.sin(angle) * (layout.radius + 105))))
    return points


def _owner_for_start(index: int, start_indices: tuple[int, ...]) -> int | None:
    for owner, start in enumerate(start_indices):
        if index == start:
            return owner
    return None


def _cell_rect(point: tuple[float, float], radius: int) -> pygame.Rect:
    return pygame.Rect(int(point[0] - radius), int(point[1] - radius), radius * 2, radius * 2)


def _point(point: tuple[float, float]) -> tuple[int, int]:
    return int(point[0]), int(point[1])


def _draw_star(surface: pygame.Surface, center: tuple[float, float], radius: int, color: tuple[int, int, int]) -> None:
    points = []
    cx, cy = center
    for index in range(10):
        r = radius if index % 2 == 0 else radius * 0.45
        angle = -math.pi / 2 + index * math.pi / 5
        points.append((int(cx + math.cos(angle) * r), int(cy + math.sin(angle) * r)))
    pygame.draw.polygon(surface, color, points)
