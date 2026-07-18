"""Drawing helpers for HUD panels, buttons, and overlay screens."""

# Beginner note:
# This file focuses on presentation only.
# It does not decide game rules, scores, or physics outcomes.
# Instead, it takes already-known game state and turns that state into readable UI.

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

from settings import (
    CONTAINER_RADIUS,
    FAIL_LINE_Y,
    GLOW,
    PLAYFIELD_CENTER,
    SIDEBAR_WIDTH,
    SIDEBAR_X,
    SOFT_WHITE,
    SUCCESS,
    WHITE,
    danger_gradient,
    shade,
)


def draw_panel(
    target: pygame.Surface,
    rect: pygame.Rect,
    fill: tuple[int, int, int, int] = (11, 20, 44, 205),
    border: tuple[int, int, int] = (88, 132, 206),
    radius: int = 28,
) -> None:
    """Draw a rounded translucent panel with a subtle border."""
    # First draw a soft glow slightly larger than the panel itself.
    # This gives the UI a luminous sci-fi edge without requiring separate art files.
    glow = pygame.Surface((rect.w + 28, rect.h + 28), pygame.SRCALPHA)
    glow_rect = glow.get_rect()
    for inset, alpha in ((0, 18), (8, 12), (16, 8)):
        pygame.draw.rect(
            glow,
            (*border, alpha),
            glow_rect.inflate(-inset * 2, -inset * 2),
            border_radius=radius + 14,
        )
    target.blit(glow, (rect.x - 14, rect.y - 14))

    # Draw onto a temporary alpha surface so the caller can get soft transparency.
    # This makes the panel feel like tinted glass instead of a flat opaque box.
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    panel_rect = panel.get_rect()
    pygame.draw.rect(panel, fill, panel_rect, border_radius=radius)

    # A glossy ellipse across the top acts like reflected light on curved glass.
    gloss = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.ellipse(
        gloss,
        (255, 255, 255, 26),
        pygame.Rect(
            -int(rect.w * 0.14),
            -int(rect.h * 0.44),
            int(rect.w * 1.28),
            int(rect.h * 0.88),
        ),
    )
    panel.blit(gloss, (0, 0))

    # A darker ellipse near the bottom adds depth so the panel does not feel flat.
    lower_shadow = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.ellipse(
        lower_shadow,
        (0, 0, 0, 34),
        pygame.Rect(
            int(rect.w * 0.06),
            int(rect.h * 0.68),
            int(rect.w * 0.88),
            int(rect.h * 0.34),
        ),
    )
    panel.blit(lower_shadow, (0, 0))

    # The outer border and inner highlight give the panel a layered rim.
    pygame.draw.rect(panel, (*border, 220), panel_rect, width=2, border_radius=radius)
    pygame.draw.rect(
        panel,
        (255, 255, 255, 38),
        panel_rect.inflate(-14, -14),
        width=1,
        border_radius=max(8, radius - 10),
    )
    target.blit(panel, rect.topleft)


def draw_section_rule(
    target: pygame.Surface,
    left: int,
    y: int,
    width: int,
    color: tuple[int, int, int],
) -> None:
    """Draw a small glowing divider line beneath a panel heading."""
    rule = pygame.Surface((width, 10), pygame.SRCALPHA)
    center_y = rule.get_height() // 2
    pygame.draw.line(rule, (*color, 135), (6, center_y), (width - 6, center_y), 2)
    pygame.draw.circle(rule, (*color, 190), (6, center_y), 4)
    target.blit(rule, (left, y))


def draw_preview_backplate(
    target: pygame.Surface,
    center: tuple[int, int],
    radius: int,
    color: tuple[int, int, int],
) -> None:
    """Draw a decorative halo behind current/next preview bodies.

    The previews are important gameplay information, so this helper gives them a
    visual stage of their own. That makes the queue easier to scan at a glance.
    """
    halo = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    halo_center = pygame.Vector2(halo.get_width() / 2, halo.get_height() / 2)
    for ring, alpha in ((0, 36), (8, 20), (16, 10)):
        pygame.draw.circle(halo, (*color, alpha), halo_center, radius - 10 + ring, width=10 if ring else 0)
    pygame.draw.circle(halo, (255, 255, 255, 26), halo_center, radius - 18, width=2)
    target.blit(halo, halo.get_rect(center=center))


@dataclass(slots=True)
class Button:
    """Simple clickable UI button with hover styling."""

    # `rect` stores both the button's size and screen position.
    rect: pygame.Rect
    label: str
    accent: tuple[int, int, int] = GLOW

    def contains(self, point: tuple[int, int]) -> bool:
        """Return True if the given point is inside the button rectangle."""
        return self.rect.collidepoint(point)

    def draw(self, target: pygame.Surface, assets, mouse_pos: tuple[int, int]) -> None:
        """Render the button and switch colors when hovered."""
        # Hover detection is visual only here. Actual click handling happens in `game.py`.
        hovered = self.contains(mouse_pos)
        fill = (20, 34, 68, 235) if hovered else (12, 24, 50, 220)
        outline = shade(self.accent, 1.18 if hovered else 1.0)
        draw_panel(target, self.rect, fill, outline, radius=22)
        shine_y = self.rect.y + 10
        pygame.draw.line(target, (255, 255, 255, 42), (self.rect.x + 24, shine_y), (self.rect.right - 24, shine_y), 2)
        shadow = assets.ui_font.render(self.label, True, (8, 12, 24))
        target.blit(shadow, shadow.get_rect(center=(self.rect.centerx, self.rect.centery + 2)))
        label = assets.ui_font.render(self.label, True, WHITE if hovered else SOFT_WHITE)
        target.blit(label, label.get_rect(center=self.rect.center))


def draw_playfield(surface: pygame.Surface, now: float, danger_ratio: float, warning_active: bool) -> None:
    """Draw the bubble container and its danger line."""
    center = pygame.Vector2(PLAYFIELD_CENTER)
    bubble_rect = pygame.Rect(0, 0, CONTAINER_RADIUS * 2 + 28, CONTAINER_RADIUS * 2 + 28)
    bubble_rect.center = (int(center.x), int(center.y))

    # The outer glow gives the glass bubble a soft luminous edge.
    glow = pygame.Surface(bubble_rect.size, pygame.SRCALPHA)
    bubble_center = pygame.Vector2(glow.get_width() / 2, glow.get_height() / 2)
    for ring in range(3, 0, -1):
        pygame.draw.circle(glow, (96, 154, 255, 22 * ring), bubble_center, CONTAINER_RADIUS + ring * 10)
    pygame.draw.circle(glow, (11, 18, 38, 120), bubble_center, CONTAINER_RADIUS + 2)
    surface.blit(glow, bubble_rect.topleft)

    bubble = pygame.Surface((CONTAINER_RADIUS * 2 + 8, CONTAINER_RADIUS * 2 + 8), pygame.SRCALPHA)
    local_center = pygame.Vector2(bubble.get_width() / 2, bubble.get_height() / 2)

    # Fill the inside of the bubble with a faint atmospheric tint so the play
    # area feels like a distinct chamber rather than just empty screen space.
    interior = pygame.Surface(bubble.get_size(), pygame.SRCALPHA)
    pygame.draw.circle(interior, (8, 16, 36, 88), local_center, CONTAINER_RADIUS - 3)
    glow_center = local_center - pygame.Vector2(CONTAINER_RADIUS * 0.22, CONTAINER_RADIUS * 0.28)
    pygame.draw.circle(interior, (255, 255, 255, 18), glow_center, int(CONTAINER_RADIUS * 0.48))
    pygame.draw.ellipse(
        interior,
        (22, 48, 92, 42),
        pygame.Rect(
            int(local_center.x - CONTAINER_RADIUS * 0.86),
            int(local_center.y + CONTAINER_RADIUS * 0.3),
            int(CONTAINER_RADIUS * 1.72),
            int(CONTAINER_RADIUS * 0.54),
        ),
    )
    bubble.blit(interior, (0, 0))

    # The container uses layered circles/arcs so it reads as a translucent
    # bubble instead of a plain white ring.
    pygame.draw.circle(bubble, (10, 16, 34, 110), local_center, CONTAINER_RADIUS)
    pygame.draw.circle(bubble, (126, 170, 255, 34), local_center, CONTAINER_RADIUS + 6, width=12)
    pygame.draw.circle(bubble, (186, 220, 255, 185), local_center, CONTAINER_RADIUS, 5)
    pygame.draw.circle(bubble, (255, 255, 255, 36), local_center, CONTAINER_RADIUS - 11, 2)
    pygame.draw.arc(
        bubble,
        (255, 255, 255, 55),
        bubble.get_rect().inflate(-70, -70).move(-18, -22),
        math.pi * 0.95,
        math.pi * 1.48,
        5,
    )
    pygame.draw.arc(
        bubble,
        (120, 180, 255, 30),
        bubble.get_rect().inflate(-34, -34).move(24, 22),
        math.pi * 0.18,
        math.pi * 0.82,
        4,
    )
    surface.blit(bubble, bubble.get_rect(center=(int(center.x), int(center.y))))

    # The fail line is actually a chord across the circle, so we compute its span
    # from the circle equation instead of guessing a fixed width.
    # The danger line colour walks a calm -> yellow -> orange -> red gradient so
    # rising risk is obvious well before the line actually turns red.
    line_color = danger_gradient(danger_ratio)
    chord_y = FAIL_LINE_Y
    dy = chord_y - center.y
    half_span = math.sqrt(max(0.0, CONTAINER_RADIUS * CONTAINER_RADIUS - dy * dy)) - 18.0
    left = int(center.x - half_span)
    right = int(center.x + half_span)
    pulse = 1.0 + math.sin(now * 9.0) * 0.2 * danger_ratio
    width = 3 + int(3 * danger_ratio)
    if danger_ratio > 0.0:
        warning_glow = pygame.Surface((right - left + 40, 40), pygame.SRCALPHA)
        pygame.draw.line(
            warning_glow,
            (*line_color, int(26 + danger_ratio * 54)),
            (20, warning_glow.get_height() // 2),
            (warning_glow.get_width() - 20, warning_glow.get_height() // 2),
            10,
        )
        surface.blit(warning_glow, (left - 20, chord_y - warning_glow.get_height() // 2))
    pygame.draw.line(surface, line_color, (left, chord_y), (right, chord_y), width)
    if warning_active:
        # Show a floating label only when the player is actually in danger.
        hint = pygame.font.Font(None, 28).render("Danger line", True, WHITE)
        hint_rect = hint.get_rect(midbottom=(int(center.x), int(chord_y - 10 - pulse * 4)))
        surface.blit(hint, hint_rect)


def draw_hud(surface: pygame.Surface, game, assets) -> None:
    """Draw the sidebar HUD with score, queue, controls, and warning meter."""
    # These panels divide the sidebar into clear chunks of information.
    score_rect = pygame.Rect(SIDEBAR_X, 42, SIDEBAR_WIDTH, 190)
    queue_rect = pygame.Rect(SIDEBAR_X, 252, SIDEBAR_WIDTH, 292)
    info_rect = pygame.Rect(SIDEBAR_X, 564, SIDEBAR_WIDTH, 380)

    draw_panel(surface, score_rect)
    draw_panel(surface, queue_rect)
    draw_panel(surface, info_rect)

    # Score panel.
    # The game object already knows the live score/high score, so the UI simply
    # reads those values and converts them into rendered text surfaces.
    title = assets.small_font.render("Score", True, SOFT_WHITE)
    surface.blit(title, (score_rect.x + 20, score_rect.y + 18))
    draw_section_rule(surface, score_rect.x + 20, score_rect.y + 42, score_rect.w - 40, GLOW)
    value = assets.score_font.render(f"{game.score:,}", True, WHITE)
    surface.blit(value, (score_rect.x + 20, score_rect.y + 46))
    best = assets.small_font.render(f"High score  {game.high_score:,}", True, GLOW)
    surface.blit(best, (score_rect.x + 20, score_rect.y + 126))

    body_count = assets.tiny_font.render(f"Bodies: {len(game.bodies)}", True, SOFT_WHITE)
    surface.blit(body_count, (score_rect.x + 20, score_rect.y + 156))

    # Current and next drop previews.
    # The current preview is slightly larger so the player's next action is obvious.
    queue_title = assets.small_font.render("Drop Queue", True, SOFT_WHITE)
    surface.blit(queue_title, (queue_rect.x + 20, queue_rect.y + 16))
    draw_section_rule(surface, queue_rect.x + 20, queue_rect.y + 40, queue_rect.w - 40, GLOW)

    draw_preview_backplate(surface, (queue_rect.centerx, queue_rect.y + 96), 72, GLOW)
    assets.draw_preview_orb(surface, game.current_tier, (queue_rect.centerx, queue_rect.y + 96), game.now, scale=1.12)
    current_name = assets.body_font.render(game.current_body_name, True, WHITE)
    surface.blit(current_name, current_name.get_rect(center=(queue_rect.centerx, queue_rect.y + 168)))
    current_hint = assets.tiny_font.render("Current", True, GLOW)
    surface.blit(current_hint, current_hint.get_rect(center=(queue_rect.centerx, queue_rect.y + 196)))

    next_orb_center = (queue_rect.centerx, queue_rect.y + 228)
    draw_preview_backplate(surface, next_orb_center, 54, shade(GLOW, 0.88))
    assets.draw_preview_orb(surface, game.next_tier, next_orb_center, game.now, scale=0.82, alpha=215)
    next_name = assets.small_font.render(game.next_body_name, True, SOFT_WHITE)
    surface.blit(next_name, next_name.get_rect(center=(queue_rect.centerx, queue_rect.y + 264)))
    next_hint = assets.tiny_font.render("Next", True, GLOW)
    surface.blit(next_hint, next_hint.get_rect(center=(queue_rect.centerx, queue_rect.y + 286)))

    # Compact controls reference for the player.
    # Keeping these strings here makes the HUD easy to tweak without changing
    # the input logic itself.
    controls_title = assets.small_font.render("Controls", True, SOFT_WHITE)
    surface.blit(controls_title, (info_rect.x + 20, info_rect.y + 16))
    draw_section_rule(surface, info_rect.x + 20, info_rect.y + 40, info_rect.w - 40, GLOW)
    controls = [
        "Mouse near top / A,D   Move",
        "Right drag / W,S       Angle",
        "Wheel / Up,Down        Fine aim",
        "Left click / Space     Launch",
        "Esc/P pause  R restart",
        "M menu",
    ]
    for index, line in enumerate(controls):
        text = assets.tiny_font.render(line, True, WHITE if index < 2 else SOFT_WHITE)
        surface.blit(text, (info_rect.x + 20, info_rect.y + 58 + index * 32))

    # Progress summary: best body reached this run.
    best_tier = assets.small_font.render("Best body", True, SOFT_WHITE)
    surface.blit(best_tier, (info_rect.x + 20, info_rect.y + 252))
    unlocked = assets.ui_font.render(game.best_tier_name, True, SUCCESS if game.goal_reached else WHITE)
    surface.blit(unlocked, (info_rect.x + 20, info_rect.y + 286))

    # The stress meter updates continuously based on stack height, then fills the
    # final segment from the actual fail countdown while the player is in danger.
    danger = min(1.0, game.container_stress)
    bar_rect = pygame.Rect(info_rect.x + 20, info_rect.y + 344, info_rect.w - 40, 18)
    pygame.draw.rect(surface, (18, 28, 52), bar_rect, border_radius=10)
    fill_width = max(8, int(bar_rect.w * danger)) if danger > 0.0 else 0
    if fill_width > 0:
        fill_rect = pygame.Rect(bar_rect.x, bar_rect.y, fill_width, bar_rect.h)
        # The bar colour shifts with the danger level (calm blue -> red).
        fill_color = danger_gradient(danger)
        pygame.draw.rect(surface, fill_color, fill_rect, border_radius=10)
    # The border is drawn last so it stays crisp on top of the fill.
    pygame.draw.rect(surface, (100, 136, 208), bar_rect, width=2, border_radius=10)
    warning_text = assets.tiny_font.render("Container stress", True, SOFT_WHITE)
    surface.blit(warning_text, (bar_rect.x, bar_rect.y - 24))


def draw_menu_overlay(
    surface: pygame.Surface,
    assets,
    buttons: list[Button],
    high_score: int,
    games_played: int,
    best_tier_name: str,
    mouse_pos: tuple[int, int],
) -> None:
    """Draw the main menu overlay."""
    modal = pygame.Rect(188, 244, 648, 520)

    # Menus are just overlays drawn on top of the existing background.
    # The main loop decides *when* to draw them, this function decides *how*.
    draw_panel(surface, modal, (10, 18, 42, 230), (108, 148, 238), radius=34)

    title = assets.title_font.render("Orbital", True, WHITE)
    title2 = assets.title_font.render("Orchard", True, WHITE)
    surface.blit(title, title.get_rect(center=(modal.centerx, modal.y + 88)))
    surface.blit(title2, title2.get_rect(center=(modal.centerx, modal.y + 164)))

    subtitle_text = "Drop, bounce, and merge celestial cuties into a Quasar Crown."
    subtitle = assets.small_font.render(subtitle_text, True, SOFT_WHITE)
    surface.blit(subtitle, subtitle.get_rect(center=(modal.centerx, modal.y + 228)))

    tips = [
        "Stack bodies inside the bubble.",
        "Touch two matching tiers to evolve them.",
        "Keep old bodies under the red danger line.",
    ]
    for index, line in enumerate(tips):
        text = assets.ui_font.render(line, True, WHITE)
        surface.blit(text, text.get_rect(center=(modal.centerx, modal.y + 286 + index * 46)))

    best = assets.small_font.render(f"Local high score: {high_score:,}", True, GLOW)
    surface.blit(best, best.get_rect(center=(modal.centerx, modal.y + 420)))
    stats_line = f"Games played: {games_played:,}    Best body: {best_tier_name}"
    stats = assets.tiny_font.render(stats_line, True, SOFT_WHITE)
    surface.blit(stats, stats.get_rect(center=(modal.centerx, modal.y + 456)))

    # Buttons are passed in from the game object so click handling stays there.
    for button in buttons:
        button.draw(surface, assets, mouse_pos)


def draw_pause_overlay(
    surface: pygame.Surface,
    assets,
    buttons: list[Button],
    mouse_pos: tuple[int, int],
) -> None:
    """Draw the pause overlay and place its buttons neatly inside the modal."""
    veil = pygame.Surface(surface.get_size(), pygame.SRCALPHA)

    # The dark veil dims gameplay behind the modal so the pause state is readable.
    veil.fill((4, 8, 16, 150))
    surface.blit(veil, (0, 0))
    modal = pygame.Rect(252, 316, 520, 430)
    draw_panel(surface, modal, (10, 18, 42, 236), (108, 148, 238), radius=34)
    title = assets.header_font.render("Paused", True, WHITE)
    surface.blit(title, title.get_rect(center=(modal.centerx, modal.y + 74)))
    hint = assets.small_font.render("Take a breath. Your orchard is waiting.", True, SOFT_WHITE)
    surface.blit(hint, hint.get_rect(center=(modal.centerx, modal.y + 134)))

    # Reposition buttons every frame relative to the modal so the layout stays
    # consistent even if button objects are reused elsewhere.
    # Doing this here also means the pause menu can be resized/reframed later
    # without manually updating three separate button rectangles in `game.py`.
    for index, button in enumerate(buttons):
        button.rect.size = (310, 60)
        button.rect.centerx = modal.centerx
        button.rect.y = modal.y + 184 + index * 74

    for button in buttons:
        button.draw(surface, assets, mouse_pos)


def draw_game_over_overlay(
    surface: pygame.Surface,
    assets,
    buttons: list[Button],
    score: int,
    high_score: int,
    new_record: bool,
    games_played: int,
    best_tier_name: str,
    mouse_pos: tuple[int, int],
) -> None:
    """Draw the game-over overlay with final score and retry actions."""
    veil = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    veil.fill((6, 10, 18, 165))
    surface.blit(veil, (0, 0))
    modal = pygame.Rect(220, 300, 594, 436)
    draw_panel(surface, modal, (10, 18, 42, 240), (255, 140, 140), radius=34)

    title = assets.header_font.render("Orbit Lost", True, WHITE)
    surface.blit(title, title.get_rect(center=(modal.centerx, modal.y + 70)))
    score_text = assets.score_font.render(f"{score:,}", True, WHITE)
    surface.blit(score_text, score_text.get_rect(center=(modal.centerx, modal.y + 148)))
    label = assets.small_font.render("Final score", True, SOFT_WHITE)
    surface.blit(label, label.get_rect(center=(modal.centerx, modal.y + 190)))

    status = "New high score!" if new_record else f"Best: {high_score:,}"
    status_color = SUCCESS if new_record else GLOW
    status_text = assets.small_font.render(status, True, status_color)
    surface.blit(status_text, status_text.get_rect(center=(modal.centerx, modal.y + 228)))

    stats_line = f"Games played: {games_played:,}    Best ever: {best_tier_name}"
    stats_text = assets.tiny_font.render(stats_line, True, SOFT_WHITE)
    surface.blit(stats_text, stats_text.get_rect(center=(modal.centerx, modal.y + 264)))

    # Place the retry buttons relative to the modal, matching the pause overlay.
    for index, button in enumerate(buttons):
        button.rect.size = (320, 60)
        button.rect.centerx = modal.centerx
        button.rect.y = modal.y + 300 + index * 74

    for button in buttons:
        button.draw(surface, assets, mouse_pos)
