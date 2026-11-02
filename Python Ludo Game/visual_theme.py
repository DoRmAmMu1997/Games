"""Procedural art helpers for the Ludo desktop game.

The game intentionally avoids shipping a large pile of bitmap assets. Instead,
this module draws reusable pieces such as the blue board-game wallpaper, player
tabs, glossy token pins, and dice tray directly with pygame primitives.
"""

from __future__ import annotations

import math

import pygame

from settings import LABEL_DARK, LABEL_LIGHT, WHITE

WALLPAPER_BLUE = (30, 123, 197)
WALLPAPER_DEEP = (12, 52, 93)
WALLPAPER_TEAL = (18, 126, 142)
CREAM = (250, 247, 232)
BOARD_EDGE = (15, 21, 28)
SHADOW = (0, 0, 0, 95)       # translucent black for card, board, and banner shadows
PAWN_SHADOW = (0, 0, 0, 85)  # slightly lighter oval under each pawn
# Shadow layers are cached by shape; this cap keeps the cache small even if
# many differently sized shapes (such as winner plaques) appear in a session.
SHADOW_CACHE_LIMIT = 256
HUD_DARK = (14, 22, 31)
HUD_EDGE = (255, 214, 56)
PILL_SHADE = 20  # a pill button's fill is its colour darkened by this much
# The soft light pool behind the board: full strength in the middle, then it
# fades to nothing over its outer GLOW_FADE share, drawn as rings GLOW_STEP px
# apart (small steps keep the fade smooth, with no visible rim).
GLOW_COLOR = (64, 172, 245)
GLOW_MAX_ALPHA = 55
GLOW_FADE = 0.45
GLOW_STEP = 2

_WALLPAPER_CACHE: dict[tuple[int, int], pygame.Surface] = {}
_SHADOW_CACHE: dict[tuple, pygame.Surface] = {}


def brighten(color: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    """Return ``color`` with every channel pushed toward white.

    Beginners often see RGB tuples as mysterious numbers. Each channel is just
    red, green, and blue brightness from 0 to 255, so this helper makes small
    highlight colors easier to read at call sites.
    """

    red, green, blue = color
    return (min(255, red + amount), min(255, green + amount), min(255, blue + amount))


def darken(color: tuple[int, int, int], amount: int) -> tuple[int, int, int]:
    """Return ``color`` with every channel pulled toward black."""

    red, green, blue = color
    return (max(0, red - amount), max(0, green - amount), max(0, blue - amount))


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """Return the WCAG contrast ratio between two colours, from 1 (same) to 21.

    Beginner note: our eyes judge brightness unevenly (green looks much
    brighter than blue at the same RGB value), so the ratio compares each
    colour's *relative luminance* rather than raw RGB numbers.
    """

    light, dark = sorted((_relative_luminance(a), _relative_luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def readable_on(fill: tuple[int, int, int]) -> tuple[int, int, int]:
    """Return the label colour for text or markings drawn on ``fill``.

    Whichever of ``LABEL_LIGHT`` (white) or ``LABEL_DARK`` (black) contrasts
    more with ``fill`` wins, so dark seats such as blue get white labels and
    light seats such as yellow, orange and green get black ones. Comparing
    the two, instead of keeping white until it barely passes a bar, leaves
    every seat colour comfortably above ``LABEL_CONTRAST_TARGET``.
    """

    light = contrast_ratio(LABEL_LIGHT, fill)
    dark = contrast_ratio(LABEL_DARK, fill)
    return LABEL_LIGHT if light >= dark else LABEL_DARK


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

    draw_shadow_rect(surface, rect.move(*shadow_offset), radius)
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
    draw_shadow_polygon(surface, shadow_points)
    pygame.draw.polygon(surface, fill, points)
    pygame.draw.polygon(surface, border, points, border_width)


def draw_shadow_rect(
    surface: pygame.Surface,
    rect: pygame.Rect,
    radius: int,
    color: tuple[int, int, int, int] = SHADOW,
) -> None:
    """Blend a translucent rounded-rectangle shadow onto ``surface``.

    Beginner note: ``pygame.draw`` ignores the alpha part of a colour when it
    draws straight onto an opaque surface such as the game window, so a
    "95/255 black" shadow would come out solid black. Drawing the shape on a
    small transparent layer first and blitting that layer blends it instead.
    """

    draw_translucent_rect(surface, rect, radius, color)


def draw_translucent_rect(
    surface: pygame.Surface,
    rect: pygame.Rect,
    radius: int,
    color: tuple[int, int, int, int],
) -> None:
    """Blend a rounded rectangle of an RGBA ``color`` onto ``surface``.

    Used for shadows and for see-through plates behind text on the wallpaper;
    see ``draw_shadow_rect`` for why the shape goes through a layer.
    """

    key = ("rect", rect.size, radius, color)
    fresh = key not in _SHADOW_CACHE
    layer = _shadow_layer(key, rect.size)
    if fresh:
        pygame.draw.rect(layer, color, layer.get_rect(), border_radius=radius)
    surface.blit(layer, rect.topleft)


def draw_shadow_polygon(
    surface: pygame.Surface,
    points: list[tuple[int, int]],
    color: tuple[int, int, int, int] = SHADOW,
) -> None:
    """Blend a translucent polygon shadow onto ``surface`` (see ``draw_shadow_rect``)."""

    left = min(x for x, _ in points)
    top = min(y for _, y in points)
    local = tuple((x - left, y - top) for x, y in points)
    size = (max(x for x, _ in local) + 1, max(y for _, y in local) + 1)
    key = ("polygon", local, color)
    fresh = key not in _SHADOW_CACHE
    layer = _shadow_layer(key, size)
    if fresh:
        pygame.draw.polygon(layer, color, local)
    surface.blit(layer, (left, top))


def draw_shadow_ellipse(
    surface: pygame.Surface,
    rect: pygame.Rect,
    color: tuple[int, int, int, int] = PAWN_SHADOW,
) -> None:
    """Blend a translucent oval shadow (under a pawn) onto ``surface``."""

    key = ("ellipse", rect.size, color)
    fresh = key not in _SHADOW_CACHE
    layer = _shadow_layer(key, rect.size)
    if fresh:
        pygame.draw.ellipse(layer, color, layer.get_rect())
    surface.blit(layer, rect.topleft)


def _shadow_layer(key: tuple, size: tuple[int, int]) -> pygame.Surface:
    """Return the cached transparent layer for ``key``, creating a blank one if needed."""

    layer = _SHADOW_CACHE.get(key)
    if layer is None:
        if len(_SHADOW_CACHE) >= SHADOW_CACHE_LIMIT:
            _SHADOW_CACHE.clear()
        layer = pygame.Surface((max(1, size[0]), max(1, size[1])), pygame.SRCALPHA)
        _SHADOW_CACHE[key] = layer
    return layer


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
    label = fonts["small"].render(text, True, readable_on(color))
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
    draw_shadow_ellipse(surface, pygame.Rect(cx - radius, cy + radius // 2, radius * 2, radius))
    pointer = [(cx, cy + radius + 13), (cx - radius + 5, cy + 6), (cx + radius - 5, cy + 6)]
    pygame.draw.polygon(surface, darken(color, 35), pointer)
    pygame.draw.circle(surface, WHITE, (cx, cy), radius + 4)
    pygame.draw.circle(surface, darken(color, 20), (cx, cy), radius)
    pygame.draw.circle(surface, color, (cx, cy - 2), radius - 4)
    pygame.draw.circle(surface, brighten(color, 95), (cx - radius // 3, cy - radius // 3), max(4, radius // 4))
    pygame.draw.circle(surface, BOARD_EDGE, (cx, cy), radius + 4, 2)
    if label and fonts is not None:
        text = fonts["tiny"].render(label, True, readable_on(color))
        surface.blit(text, text.get_rect(center=(cx, cy)))


def draw_die_face(
    surface: pygame.Surface,
    rect: pygame.Rect,
    value: int | None,
    fonts: dict[str, pygame.font.Font] | None = None,
) -> None:
    """Draw one rounded white die face showing ``value`` pips.

    ``None`` means no roll has happened yet: the face shows a dash when fonts
    are available and stays blank otherwise. This is the single die renderer
    shared by the HUD tray and the radial board hub.
    """

    pygame.draw.rect(surface, WHITE, rect, border_radius=10)
    pygame.draw.rect(surface, BOARD_EDGE, rect, 3, border_radius=10)
    if value is None:
        if fonts is not None:
            text = fonts["header"].render("-", True, BOARD_EDGE)
            surface.blit(text, text.get_rect(center=rect.center))
        return
    _draw_pips(surface, rect, value)


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
    draw_die_face(surface, die_rect, value, fonts)


def draw_round_icon_button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    color: tuple[int, int, int],
    text: str,
    fonts: dict[str, pygame.font.Font],
) -> None:
    """Draw a compact pill button for the Save and New table controls.

    The label takes ``readable_on`` of the actual fill, so a light pill (the
    gold Save button, or a yellow seat's New button) gets dark lettering.
    """

    fill = darken(color, PILL_SHADE)
    draw_shadowed_rect(surface, rect, fill, border=HUD_EDGE, radius=rect.height // 2)
    image = fonts["button"].render(text, True, readable_on(fill))
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
    wallpaper.blit(overlay, (0, 0))
    # The glow gets its own layer, blitted on top, so it tints the stamps
    # beneath it instead of replacing them (pygame.draw on an alpha surface
    # overwrites pixels rather than blending).
    wallpaper.blit(_build_glow(size), (0, 0))
    return wallpaper


def _build_glow(size: tuple[int, int]) -> pygame.Surface:
    """Return a transparent layer holding the soft round glow behind the board.

    Rings are painted from the outside in, each a touch more opaque, so the
    glow is strongest in the middle and fades smoothly to nothing at its edge.
    """

    width, height = size
    layer = pygame.Surface(size, pygame.SRCALPHA)
    radius = min(width, height) // 3
    fade = max(1.0, radius * GLOW_FADE)
    for ring in range(radius, 0, -GLOW_STEP):
        amount = min(1.0, (radius - ring) / fade)
        eased = amount * amount * (3 - 2 * amount)  # smoothstep: no kink at either end
        pygame.draw.circle(layer, (*GLOW_COLOR, round(GLOW_MAX_ALPHA * eased)), (width // 2, height // 2), ring)
    return layer


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

    return (
        int(a[0] + (b[0] - a[0]) * amount),
        int(a[1] + (b[1] - a[1]) * amount),
        int(a[2] + (b[2] - a[2]) * amount),
    )


def _relative_luminance(color: tuple[int, int, int]) -> float:
    """Return the WCAG relative luminance of an sRGB colour, from 0 to 1."""

    channels = []
    for value in color[:3]:
        level = value / 255
        # sRGB stores brightness on a curve; undo it before weighting.
        channels.append(level / 12.92 if level <= 0.04045 else ((level + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _ipoint(point: tuple[float, float]) -> tuple[int, int]:
    """Convert a floating-point coordinate to integer pixels."""

    return int(point[0]), int(point[1])
