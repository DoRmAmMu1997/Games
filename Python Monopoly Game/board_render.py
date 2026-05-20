"""Procedural drawing of the Monopoly board, tokens and buildings.

Nothing here decides rules -- it only turns the engine's state into pixels.
The static parts of the board (tile faces, colour bands, names, prices) are
drawn once into a cached surface; only the changing parts (ownership marks,
houses, tokens) are redrawn every frame.
"""

from __future__ import annotations

import pygame

import board_data
from settings import (
    BOARD_MARGIN, BOARD_SIZE, CORNER_SIZE, GROUP_COLORS, HIGHLIGHT, INK,
    RAIL_COLOR, TAX_COLOR, TILE_FACE, BOARD_FACE, UTILITY_COLOR, WHITE,
    TOKEN_COLORS, HOUSE_COLOR, HOTEL_COLOR, SOFT,
)

# Pre-computed board geometry (the board never moves or resizes).
_C = round(CORNER_SIZE)
_OX = BOARD_MARGIN
_OY = BOARD_MARGIN
_RIGHT = _OX + BOARD_SIZE
_BOTTOM = _OY + BOARD_SIZE
_BAND = 26                                  # colour-band thickness in pixels
_EDGE_SPAN = BOARD_SIZE - 2 * _C
_OFFSETS = [round(_EDGE_SPAN * k / 9) for k in range(10)]   # 9 edge tiles


def space_rect(position: int) -> pygame.Rect:
    """Return the screen rectangle of one of the 40 board spaces."""
    if position == 0:
        return pygame.Rect(_RIGHT - _C, _BOTTOM - _C, _C, _C)
    if position == 10:
        return pygame.Rect(_OX, _BOTTOM - _C, _C, _C)
    if position == 20:
        return pygame.Rect(_OX, _OY, _C, _C)
    if position == 30:
        return pygame.Rect(_RIGHT - _C, _OY, _C, _C)
    if 1 <= position <= 9:                       # bottom edge, right to left
        j = 9 - position
        x0, x1 = _OX + _C + _OFFSETS[j], _OX + _C + _OFFSETS[j + 1]
        return pygame.Rect(x0, _BOTTOM - _C, x1 - x0, _C)
    if 11 <= position <= 19:                     # left edge, bottom to top
        j = 19 - position
        y0, y1 = _OY + _C + _OFFSETS[j], _OY + _C + _OFFSETS[j + 1]
        return pygame.Rect(_OX, y0, _C, y1 - y0)
    if 21 <= position <= 29:                     # top edge, left to right
        j = position - 21
        x0, x1 = _OX + _C + _OFFSETS[j], _OX + _C + _OFFSETS[j + 1]
        return pygame.Rect(x0, _OY, x1 - x0, _C)
    j = position - 31                            # right edge, top to bottom
    y0, y1 = _OY + _C + _OFFSETS[j], _OY + _C + _OFFSETS[j + 1]
    return pygame.Rect(_RIGHT - _C, y0, _C, y1 - y0)


def _edge_of(position: int) -> str:
    """Which side of the board a space sits on: bottom/left/top/right."""
    if position == 0 or 1 <= position <= 9:
        return "bottom"
    if position == 10 or 11 <= position <= 19:
        return "left"
    if position == 20 or 21 <= position <= 29:
        return "top"
    return "right"


def token_center(position: int, slot: int) -> tuple[int, int]:
    """Return where to draw player token `slot` (0-3) on a space.

    Up to four tokens share a space; they are spread into a small 2x2 grid so
    they stay individually visible.
    """
    rect = space_rect(position)
    col, row = slot % 2, slot // 2
    gap_x = rect.width * 0.28
    gap_y = rect.height * 0.28
    cx = rect.centerx + (col - 0.5) * gap_x
    cy = rect.centery + (row - 0.5) * gap_y
    return int(cx), int(cy)


class BoardRenderer:
    """Draws the board. Builds the static layer once, then reuses it."""

    def __init__(self, board: list):
        self.board = board
        self._base: pygame.Surface | None = None

    # ------------------------------------------------------------------
    # Static layer
    # ------------------------------------------------------------------
    def build_base(self, fonts: dict) -> None:
        """Render the unchanging board image into a cached surface."""
        surface = pygame.Surface((BOARD_SIZE, BOARD_SIZE))
        surface.fill(BOARD_FACE)
        # The empty middle of the board.
        inner = pygame.Rect(_OX + _C - BOARD_MARGIN, _OY + _C - BOARD_MARGIN,
                            BOARD_SIZE - 2 * _C, BOARD_SIZE - 2 * _C)
        pygame.draw.rect(surface, BOARD_FACE, inner)

        for position, space in enumerate(self.board):
            self._draw_space(surface, position, space, fonts)

        # A diagonal title across the centre of the board.
        title = fonts["title"].render("MONOPOLY", True, INK)
        title = pygame.transform.rotate(title, 45)
        centre = (BOARD_SIZE // 2 - _OX, BOARD_SIZE // 2 - _OY)
        surface.blit(title, title.get_rect(center=centre))
        self._base = surface

    def _draw_space(self, surface: pygame.Surface, position: int, space,
                    fonts: dict) -> None:
        """Draw one board space onto the static surface."""
        # The cached surface has its own origin, so shift the screen rect back.
        rect = space_rect(position).move(-_OX, -_OY)
        pygame.draw.rect(surface, TILE_FACE, rect)
        pygame.draw.rect(surface, INK, rect, 2)

        edge = _edge_of(position)
        if space.kind == "street":
            self._draw_band(surface, rect, edge, GROUP_COLORS[space.group])
        elif space.kind == "railroad":
            self._draw_band(surface, rect, edge, RAIL_COLOR)
        elif space.kind == "utility":
            self._draw_band(surface, rect, edge, UTILITY_COLOR)
        elif space.kind in ("tax", "chance", "chest"):
            self._draw_band(surface, rect, edge, TAX_COLOR)

        # The space label (and price), rotated to suit the board side.
        lines = _wrap(space.name, 11)
        if space.is_ownable:
            lines.append(f"${space.price}")
        self._draw_label(surface, rect, edge, lines, fonts)

    def _draw_band(self, surface, rect, edge, color) -> None:
        """Draw the coloured strip along a tile's inner edge."""
        if edge == "bottom":
            band = pygame.Rect(rect.x, rect.y, rect.width, _BAND)
        elif edge == "top":
            band = pygame.Rect(rect.x, rect.bottom - _BAND, rect.width, _BAND)
        elif edge == "left":
            band = pygame.Rect(rect.right - _BAND, rect.y, _BAND, rect.height)
        else:  # right
            band = pygame.Rect(rect.x, rect.y, _BAND, rect.height)
        pygame.draw.rect(surface, color, band)
        pygame.draw.rect(surface, INK, band, 1)

    def _draw_label(self, surface, rect, edge, lines, fonts) -> None:
        """Draw a tile's text, rotated so it reads correctly for its side."""
        font = fonts["tile"]
        text = pygame.Surface((rect.width if edge in ("bottom", "top") else rect.height,
                               64), pygame.SRCALPHA)
        for i, line in enumerate(lines):
            glyph = font.render(line, True, INK)
            text.blit(glyph, glyph.get_rect(center=(text.get_width() // 2, 12 + i * 16)))
        if edge == "left":
            text = pygame.transform.rotate(text, -90)
        elif edge == "right":
            text = pygame.transform.rotate(text, 90)
        # Place the text away from the coloured band.
        if edge == "bottom":
            surface.blit(text, text.get_rect(midtop=(rect.centerx, rect.y + _BAND + 2)))
        elif edge == "top":
            surface.blit(text, text.get_rect(midbottom=(rect.centerx, rect.bottom - _BAND - 2)))
        elif edge == "left":
            surface.blit(text, text.get_rect(midright=(rect.right - _BAND - 2, rect.centery)))
        else:
            surface.blit(text, text.get_rect(midleft=(rect.x + _BAND + 2, rect.centery)))

    # ------------------------------------------------------------------
    # Dynamic layer -- drawn fresh every frame
    # ------------------------------------------------------------------
    def draw(self, target: pygame.Surface, game, fonts: dict,
             token_pixels: dict | None = None,
             highlight_positions=()) -> None:
        """Blit the cached board, then the live ownership, houses and tokens.

        `token_pixels` lets the caller animate token movement: if given, each
        player's token is drawn at that exact pixel instead of snapping to the
        centre of their space.  `highlight_positions` adds a bright ring over
        each listed space -- used while the human is choosing somewhere to
        build a house or to mortgage.
        """
        if self._base is None:
            self.build_base(fonts)
        target.blit(self._base, (_OX, _OY))

        # Ownership: a thin border in the owner's colour, plus mortgage shading.
        for position, owner_index in game.owners.items():
            rect = space_rect(position)
            pygame.draw.rect(target, TOKEN_COLORS[owner_index], rect, 4)
            if position in game.mortgaged:
                veil = pygame.Surface(rect.size, pygame.SRCALPHA)
                veil.fill((20, 20, 20, 120))
                target.blit(veil, rect.topleft)

        # Spaces the player can act on right now: a bright ring drawn on top.
        for position in highlight_positions:
            ring = space_rect(position).inflate(-2, -2)
            pygame.draw.rect(target, HIGHLIGHT, ring, 4, border_radius=4)

        self._draw_buildings(target, game)
        self._draw_tokens(target, game, fonts, pixel_overrides=token_pixels)

    def _draw_buildings(self, target, game) -> None:
        """Draw houses (green) and hotels (red) on developed streets."""
        for position, level in game.houses.items():
            if level <= 0:
                continue
            rect = space_rect(position)
            edge = _edge_of(position)
            if level == 5:
                # A single hotel.
                size = 16
                spot = self._building_slots(rect, edge, 1)[0]
                pygame.draw.rect(target, HOTEL_COLOR,
                                 (spot[0] - size // 2, spot[1] - 7, size, 14))
                pygame.draw.rect(target, INK,
                                 (spot[0] - size // 2, spot[1] - 7, size, 14), 1)
            else:
                for spot in self._building_slots(rect, edge, level):
                    pygame.draw.rect(target, HOUSE_COLOR,
                                     (spot[0] - 5, spot[1] - 5, 10, 10))
                    pygame.draw.rect(target, INK, (spot[0] - 5, spot[1] - 5, 10, 10), 1)

    def _building_slots(self, rect, edge, count) -> list:
        """Return evenly spaced points along a tile's coloured band."""
        slots = []
        for i in range(count):
            frac = (i + 1) / (count + 1)
            if edge == "bottom":
                slots.append((rect.x + int(rect.width * frac), rect.y + _BAND // 2))
            elif edge == "top":
                slots.append((rect.x + int(rect.width * frac), rect.bottom - _BAND // 2))
            elif edge == "left":
                slots.append((rect.right - _BAND // 2, rect.y + int(rect.height * frac)))
            else:
                slots.append((rect.x + _BAND // 2, rect.y + int(rect.height * frac)))
        return slots

    def _draw_tokens(self, target, game, fonts, pixel_overrides=None) -> None:
        """Draw each non-bankrupt player's token.

        Each player always uses their own slot in the 2x2 grid on a space, so
        two tokens never swap positions when they meet.  When `pixel_overrides`
        is provided, a token is drawn at that exact pixel instead -- which is
        how the caller smoothly animates movement across spaces.
        """
        for player in game.players:
            if player.bankrupt:
                continue
            if pixel_overrides is not None and player.index in pixel_overrides:
                cx, cy = pixel_overrides[player.index]
                cx, cy = int(cx), int(cy)
            else:
                cx, cy = token_center(player.position, player.index)
            pygame.draw.circle(target, WHITE, (cx, cy), 15)
            pygame.draw.circle(target, player.token_color, (cx, cy), 13)
            pygame.draw.circle(target, INK, (cx, cy), 15, 2)
            label = fonts["tile"].render(str(player.index + 1), True, WHITE)
            target.blit(label, label.get_rect(center=(cx, cy)))


def _wrap(text: str, width: int) -> list:
    """Greedily wrap `text` into lines no longer than `width` characters."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if len(trial) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:3]
