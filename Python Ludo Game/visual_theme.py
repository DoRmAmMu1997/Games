"""Procedural art helpers for the Ludo desktop game.

The game intentionally avoids shipping a large pile of bitmap assets. Instead,
this module draws reusable pieces such as the blue board-game wallpaper, player
tabs, glossy token pins, and dice tray directly with pygame primitives.
"""

from __future__ import annotations

import math

import pygame

from settings import INK, PLAYER_COLORS, WHITE


WALLPAPER_BLUE = (30, 123, 197)
WALLPAPER_DEEP = (12, 52, 93)
WALLPAPER_TEAL = (18, 126, 142)
CREAM = (250, 247, 232)
BOARD_EDGE = (15, 21, 28)
SHADOW = (0, 0, 0, 95)
HUD_DARK = (14, 22, 31)
HUD_EDGE = (255, 214, 56)

_WALLPAPER_CACHE: dict[tuple[int, int], pygame.Surface] = {}


def brighten(color: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    """Return ``color`` with every channel pushed toward white.

    Beginners often see RGB tuples as mysterious numbers. Each channel is just
    red, green, and blue brightness from 0 to 255, so this helper makes small
    highlight colors easier to read at call sites.
    """

    return tuple(min(255, channel + amount) for channel in color)


def darken(color: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    """Return ``color`` with every channel pulled toward black."""

    return tuple(max(0, channel - amount) for channel in color)


def draw_ludo_wallpaper(surface: pygame.Surface) -> None:
    """Fill ``surface`` with a blue patterned Ludo-game background."""

    size = surface.get_size()
    cached = _WALLPAPER_CACHE.get(size)
    if cached is None:
        cached = _build_wallpaper(size)
        _WALLPAPER_CACHE[size] = cached
    surface.blit(cached, (0, 0))


def draw_shadowed_rect(
    surface: pygame.Surface,
    rect: pygame.Rect,
    fill: tuple[int, int, int],
    *,
    border: tuple[int, int, int] | None = None,
    radius: int = 10,
    shadow_offset: tuple[int, int] = (0, 5),
) -> None:
    """Draw a rounded rectangle with a soft offset shadow."""

    shadow_rect = rect.move(*shadow_offset)
    pygame.draw.rect(surface, SHADOW, shadow_rect, border_radius=radius)
    pygame.draw.rect(surface, fill, rect, border_radius=radius)
    if border is not None:
        pygame.draw.rect(surface, border, rect, 2, border_radius=radius)


def draw_shadowed_polygon(
    surface: pygame.Surface,
    points: list[tuple[int, int]],
    fill: tuple[int, int, int],
    *,
    border: tuple[int, int, int] = BOARD_EDGE,
    shadow_offset: tuple[int, int] = (0, 6),
    border_width: int = 4,
) -> None:
    """Draw a polygon that looks lifted from the wallpaper."""

    shadow_points = [(x + shadow_offset[0], y + shadow_offset[1]) for x, y in points]
    pygame.draw.polygon(surface, SHADOW, shadow_points)
    pygame.draw.polygon(surface, fill, points)
    pygame.draw.polygon(surface, border, points, border_width)


def draw_star(
    surface: pygame.Surface,
    center: tuple[float, float],
    radius: int,
    color: tuple[int, int, int] = BOARD_EDGE,
    *,
    fill: tuple[int, int, int] = WHITE,
) -> None:
    """Draw a safe-square star with a white fill and dark outline."""

    points: list[tuple[int, int]] = []
    cx, cy = center
    for index in range(10):
        active_radius = radius if index % 2 == 0 else radius * 0.45
        angle = -math.pi / 2 + index * math.pi / 5
        points.append((int(cx + math.cos(angle) * active_radius), int(cy + math.sin(angle) * active_radius)))
    pygame.draw.polygon(surface, fill, points)
    pygame.draw.polygon(surface, color, points, 2)


def draw_arrow(
    surface: pygame.Surface,
    center: tuple[float, float],
    angle: float,
    color: tuple[int, int, int],
    *,
    length: int = 24,
) -> None:
    """Draw a small direction arrow on a start lane."""

    cx, cy = center
    tip = (cx + math.cos(angle) * length / 2, cy + math.sin(angle) * length / 2)
    tail = (cx - math.cos(angle) * length / 2, cy - math.sin(angle) * length / 2)
    left = (
        tip[0] - math.cos(angle) * 9 + math.cos(angle + math.pi / 2) * 7,
        tip[1] - math.sin(angle) * 9 + math.sin(angle + math.pi / 2) * 7,
    )
    right = (
        tip[0] - math.cos(angle) * 9 + math.cos(angle - math.pi / 2) * 7,
        tip[1] - math.sin(angle) * 9 + math.sin(angle - math.pi / 2) * 7,
    )
    pygame.draw.line(surface, color, _ipoint(tail), _ipoint(tip), 3)
    pygame.draw.polygon(surface, color, [_ipoint(tip), _ipoint(left), _ipoint(right)])


def draw_player_banner(
    surface: pygame.Surface,
    rect: pygame.Rect,
    color: tuple[int, int, int],
    text: str,
    fonts: dict[str, pygame.font.Font],
) -> None:
    """Draw the colored player tab used around the board and in the HUD."""

    draw_shadowed_rect(surface, rect, color, border=BOARD_EDGE, radius=8, shadow_offset=(0, 4))
    label = fonts["small"].render(text, True, INK if _is_light(color) else WHITE)
    surface.blit(label, label.get_rect(center=rect.center))


def draw_token_pin(
    surface: pygame.Surface,
    center: tuple[float, float],
    color: tuple[int, int, int],
    *,
    radius: int = 18,
    label: str | None = None,
    fonts: dict[str, pygame.font.Font] | None = None,
) -> None:
    """Draw one glossy pawn shaped like a map pin."""

    cx, cy = int(center[0]), int(center[1])
    pygame.draw.ellipse(surface, (0, 0, 0, 85), (cx - radius, cy + radius // 2, radius * 2, radius), 0)
    pointer = [(cx, cy + radius + 13), (cx - radius + 5, cy + 6), (cx + radius - 5, cy + 6)]
    pygame.draw.polygon(surface, darken(color, 35), pointer)
    pygame.draw.circle(surface, WHITE, (cx, cy), radius + 4)
    pygame.draw.circle(surface, darken(color, 20), (cx, cy), radius)
    pygame.draw.circle(surface, color, (cx, cy - 2), radius - 4)
    pygame.draw.circle(surface, brighten(color, 95), (cx - radius // 3, cy - radius // 3), max(4, radius // 4))
    pygame.draw.circle(surface, BOARD_EDGE, (cx, cy), radius + 4, 2)
    if label and fonts is not None:
        text = fonts["tiny"].render(label, True, WHITE)
        surface.blit(text, text.get_rect(center=(cx, cy)))


def draw_dice_tray(
    surface: pygame.Surface,
    rect: pygame.Rect,
    value: int | None,
    fonts: dict[str, pygame.font.Font],
    *,
    accent: tuple[int, int, int] = HUD_EDGE,
) -> None:
    """Draw the current die in a bright tray like a board-game control."""

    draw_shadowed_rect(surface, rect, HUD_DARK, border=accent, radius=14, shadow_offset=(0, 5))
    die_size = min(rect.height - 18, rect.width // 3)
    die_rect = pygame.Rect(rect.x + 14, rect.centery - die_size // 2, die_size, die_size)
    pygame.draw.rect(surface, WHITE, die_rect, border_radius=10)
    pygame.draw.rect(surface, BOARD_EDGE, die_rect, 3, border_radius=10)
    if value is None:
        text = fonts["header"].render("-", True, BOARD_EDGE)
        surface.blit(text, text.get_rect(center=die_rect.center))
    else:
        _draw_pips(surface, die_rect, value)


def draw_round_icon_button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    color: tuple[int, int, int],
    text: str,
    fonts: dict[str, pygame.font.Font],
) -> None:
    """Draw a compact action button for save, menu, and new-game controls."""

    draw_shadowed_rect(surface, rect, darken(color, 20), border=HUD_EDGE, radius=rect.height // 2)
    image = fonts["button"].render(text, True, WHITE)
    surface.blit(image, image.get_rect(center=rect.center))


def _build_wallpaper(size: tuple[int, int]) -> pygame.Surface:
    """Create a cached wallpaper surface for the requested window size."""

    width, height = size
    wallpaper = pygame.Surface(size)
    for y in range(height):
        amount = y / max(1, height - 1)
        color = _blend(WALLPAPER_BLUE, WALLPAPER_DEEP, amount * 0.88)
        pygame.draw.line(wallpaper, color, (0, y), (width, y))

    overlay = pygame.Surface(size, pygame.SRCALPHA)
    for x in range(-180, width + 220, 240):
        for y in range(-130, height + 180, 190):
            tint = WALLPAPER_TEAL if (x // 240 + y // 190) % 2 else (42, 85, 165)
            _draw_faint_board_stamp(overlay, (x, y), tint)
    pygame.draw.circle(overlay, (64, 172, 245, 55), (width // 2, height // 2), min(width, height) // 3)
    wallpaper.blit(overlay, (0, 0))
    return wallpaper


def _draw_faint_board_stamp(surface: pygame.Surface, pos: tuple[int, int], color: tuple[int, int, int]) -> None:
    """Draw a translucent mini Ludo board used as wallpaper texture."""

    x, y = pos
    board = pygame.Rect(x, y, 132, 132)
    pygame.draw.rect(surface, (*darken(color, 30), 56), board, border_radius=10)
    pygame.draw.rect(surface, (*brighten(color, 32), 34), board.inflate(-34, -34), border_radius=6)
    for dx, dy in ((28, 28), (74, 28), (28, 74), (74, 74)):
        pygame.draw.circle(surface, (*darken(color, 65), 58), (x + dx, y + dy), 14)
    pygame.draw.rect(surface, (255, 255, 255, 30), (x + 42, y + 108, 48, 10), border_radius=3)


def _draw_pips(surface: pygame.Surface, rect: pygame.Rect, value: int) -> None:
    """Draw standard die pips inside ``rect``."""

    offsets = {
        1: [(0, 0)],
        2: [(-1, -1), (1, 1)],
        3: [(-1, -1), (0, 0), (1, 1)],
        4: [(-1, -1), (1, -1), (-1, 1), (1, 1)],
        5: [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)],
        6: [(-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)],
    }
    pip_radius = max(3, rect.width // 11)
    for ox, oy in offsets[max(1, min(6, value))]:
        point = (rect.centerx + ox * rect.width // 4, rect.centery + oy * rect.height // 4)
        pygame.draw.circle(surface, BOARD_EDGE, point, pip_radius)


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    """Mix two colors by ``amount`` where 0 is all ``a`` and 1 is all ``b``."""

    return tuple(int(a[i] + (b[i] - a[i]) * amount) for i in range(3))


def _is_light(color: tuple[int, int, int]) -> bool:
    """Return True when black text is easier to read on ``color``."""

    red, green, blue = color
    return red * 0.299 + green * 0.587 + blue * 0.114 > 150


def _ipoint(point: tuple[float, float]) -> tuple[int, int]:
    """Convert a floating-point coordinate to integer pixels."""

    return int(point[0]), int(point[1])
