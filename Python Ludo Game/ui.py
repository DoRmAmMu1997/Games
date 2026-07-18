"""Pygame UI helpers for buttons, text labels, and log colors."""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from settings import (
    DANGER,
    DISABLED,
    GOLD,
    INK,
    PANEL_CARD,
    PANEL_EDGE,
    SOFT,
    SUCCESS,
    WHITE,
)


@dataclass
class Button:
    """Simple rectangular button used by setup and play screens.

    The ``key`` is the value the app receives when the button is clicked. That
    lets drawing code stay generic while ``main.py`` decides what each button
    actually does.
    """

    rect: pygame.Rect
    text: str
    key: str
    enabled: bool = True
    accent: tuple[int, int, int] = GOLD

    def contains(self, pos: tuple[int, int]) -> bool:
        """Return True when ``pos`` clicks this enabled button."""

        return self.enabled and self.rect.collidepoint(pos)

    def draw(self, surface: pygame.Surface, fonts: dict[str, pygame.font.Font], mouse: tuple[int, int]) -> None:
        """Render the button, including disabled and hover states."""

        hovered = self.contains(mouse)
        fill = self.accent if hovered else PANEL_CARD
        if not self.enabled:
            fill = DISABLED
        pygame.draw.rect(surface, fill, self.rect, border_radius=8)
        pygame.draw.rect(surface, PANEL_EDGE if self.enabled else INK, self.rect, 2, border_radius=8)
        color = INK if hovered and self.enabled else WHITE
        draw_text(surface, fonts["button"], self.text, self.rect.center, color, center=True)


def make_fonts() -> dict[str, pygame.font.Font]:
    """Create the small set of fonts used by the whole app."""

    return {
        "huge": pygame.font.SysFont("arial", 58, bold=True),
        "title": pygame.font.SysFont("arial", 44, bold=True),
        "header": pygame.font.SysFont("arial", 28, bold=True),
        "body": pygame.font.SysFont("arial", 22),
        "small": pygame.font.SysFont("arial", 18),
        "tiny": pygame.font.SysFont("arial", 15),
        "button": pygame.font.SysFont("arial", 19, bold=True),
    }


def draw_text(
    surface: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    pos: tuple[int, int] | tuple[float, float],
    color: tuple[int, int, int] = WHITE,
    *,
    center: bool = False,
) -> None:
    """Draw a single line of text.

    Pygame surfaces draw text by rendering it into a tiny image first, then
    blitting that image onto the main window. ``center=True`` changes how the
    destination rectangle is positioned.
    """

    image = font.render(text, True, color)
    rect = image.get_rect(center=pos) if center else image.get_rect(topleft=pos)
    surface.blit(image, rect)


def draw_wrapped(
    surface: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    rect: pygame.Rect,
    color: tuple[int, int, int] = WHITE,
    line_gap: int = 4,
) -> None:
    """Draw text inside ``rect`` using simple word wrapping.

    This helper is intentionally small and predictable. It is good enough for
    short UI prompts and avoids pulling in a larger text layout dependency.
    """

    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if font.size(candidate)[0] <= rect.width:
            current = candidate
        else:
            # Once adding the next word would overflow, commit the line we
            # already know fits and start a fresh line with the new word.
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    y = rect.y
    for line in lines:
        if y + font.get_height() > rect.bottom:
            break
        draw_text(surface, font, line, (rect.x, y), color)
        y += font.get_height() + line_gap


def status_color(text: str) -> tuple[int, int, int]:
    """Choose an event-log text color from a short message."""

    lowered = text.lower()
    if "wins" in lowered or "home" in lowered:
        return SUCCESS
    if "captur" in lowered or "loses" in lowered:
        return DANGER
    return SOFT
