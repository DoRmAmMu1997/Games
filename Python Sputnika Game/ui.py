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

# Sidebar panels: score on top, the drop queue, then controls and progress.
SCORE_PANEL = pygame.Rect(SIDEBAR_X, 42, SIDEBAR_WIDTH, 190)
QUEUE_PANEL = pygame.Rect(SIDEBAR_X, 252, SIDEBAR_WIDTH, 316)
INFO_PANEL = pygame.Rect(SIDEBAR_X, 588, SIDEBAR_WIDTH, 356)

# The "Danger line" label: white text on a translucent dark pill.
DANGER_LABEL_TEXT = WHITE
DANGER_LABEL_BACKING = (8, 12, 26, 200)
# The pill is this much wider/taller than its text.
DANGER_LABEL_PAD = (18, 8)
# Vertical gap below the danger line (and between fallback rows), how far the
# label stays in from the bubble wall, how much room it keeps around the
# launcher orb and aim line, and how many rows down it may move to find room.
DANGER_LABEL_GAP = 10
DANGER_LABEL_WALL_INSET = 26
DANGER_LABEL_CLEARANCE = 8
DANGER_LABEL_ROWS = 4

# The main menu dims the scene behind it a little less than pause does.
MENU_VEIL = (4, 8, 16, 120)

# Overlay modals. Every button and text line is placed relative to these.
# The main menu has no sidebar beside it, so it is centred on the screen. The
# pause and game-over modals appear mid-run, so they are centred over the
# bubble and stay clear of the sidebar HUD.
MENU_MODAL = pygame.Rect(188, 236, 648, 584)
PAUSE_MODAL = pygame.Rect(0, 316, 520, 430)
PAUSE_MODAL.centerx = PLAYFIELD_CENTER[0]
GAME_OVER_MODAL = pygame.Rect(0, 300, 594, 460)
GAME_OVER_MODAL.centerx = PLAYFIELD_CENTER[0]

# Largest visible radius (glow included) of the current and next queue previews.
CURRENT_SLOT_RADIUS = 46
NEXT_SLOT_RADIUS = 24

# Spare pixels around a preview backplate so its outermost halo ring is never clipped.
BACKPLATE_PADDING = 8

# The controls reference: (keys, action) per row.
CONTROL_ROWS = (
    ("Mouse / A, D", "Move"),
    ("Right drag / W, S", "Angle"),
    ("Wheel / Up, Dn", "Fine aim"),
    ("Click / Space", "Launch"),
    ("Esc / P", "Pause"),
    ("R / M", "Restart / Menu"),
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
    target.blit(panel_surface(rect.size, fill, border, radius), rect.topleft)


def panel_surface(
    size: tuple[int, int],
    fill: tuple[int, int, int, int],
    border: tuple[int, int, int],
    radius: int,
) -> pygame.Surface:
    """Build the rounded, glossy glass body of one panel on an alpha surface.

    Beginner note:
    - The gloss and shadow ellipses are wider than the panel, so on their own
      they would also tint the empty corners outside the rounded shape and
      leave square-looking patches there.
    - They are therefore drawn on a separate layer that is multiplied by a
      rounded-rectangle mask, which wipes out everything outside the corners.
    """
    # Draw onto a temporary alpha surface so the caller can get soft transparency.
    # This makes the panel feel like tinted glass instead of a flat opaque box.
    width, height = size
    panel = pygame.Surface(size, pygame.SRCALPHA)
    panel_rect = panel.get_rect()
    pygame.draw.rect(panel, fill, panel_rect, border_radius=radius)

    # A glossy ellipse across the top acts like reflected light on curved glass.
    gloss = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.ellipse(
        gloss,
        (255, 255, 255, 26),
        pygame.Rect(
            -int(width * 0.14),
            -int(height * 0.44),
            int(width * 1.28),
            int(height * 0.88),
        ),
    )

    # A darker ellipse near the bottom adds depth so the panel does not feel flat.
    lower_shadow = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.ellipse(
        lower_shadow,
        (0, 0, 0, 34),
        pygame.Rect(
            int(width * 0.06),
            int(height * 0.68),
            int(width * 0.88),
            int(height * 0.34),
        ),
    )
    gloss.blit(lower_shadow, (0, 0))

    # Keep the gloss and shadow inside the rounded shape: multiplying by a
    # white rounded rectangle leaves pixels inside untouched and zeroes the
    # alpha of everything outside the corners.
    mask = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), panel_rect, border_radius=radius)
    gloss.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    panel.blit(gloss, (0, 0))

    # The outer border and inner highlight give the panel a layered rim.
    pygame.draw.rect(panel, (*border, 220), panel_rect, width=2, border_radius=radius)
    pygame.draw.rect(
        panel,
        (255, 255, 255, 38),
        panel_rect.inflate(-14, -14),
        width=1,
        border_radius=max(8, radius - 10),
    )
    return panel


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
    # The widest halo ring is drawn out to `radius + 6`, so the surface gets
    # `BACKPLATE_PADDING` spare pixels beyond `radius` on every side; a surface
    # only `radius` wide would clip the halo into a square.
    half = radius + BACKPLATE_PADDING
    halo = pygame.Surface((half * 2, half * 2), pygame.SRCALPHA)
    halo_center = pygame.Vector2(half, half)
    for ring, alpha in ((0, 36), (8, 20), (16, 10)):
        pygame.draw.circle(halo, (*color, alpha), halo_center, radius - 10 + ring, width=10 if ring else 0)
    pygame.draw.circle(halo, (255, 255, 255, 26), halo_center, radius - 18, width=2)
    target.blit(halo, halo.get_rect(center=center))


def preview_scale(orb: pygame.Surface, slot_radius: float, max_scale: float) -> float:
    """Return how much to scale a preview orb so its visible art fits its slot.

    `orb` is the tier's full orb art (glow included). Small tiers keep the
    friendly `max_scale`; larger tiers shrink so their glow never spills over
    the labels around the slot.
    """
    visible = orb.get_bounding_rect()
    half_extent = max(visible.w, visible.h) / 2.0
    return min(max_scale, slot_radius / half_extent) if half_extent > 0 else max_scale


@dataclass(slots=True)
class PreviewSlot:
    """Where and how big one drop-queue preview orb is drawn.

    Attributes:
        tier: Which tier's sprite to show.
        center: Canvas position of the orb and its backplate.
        scale: Sprite scale from `preview_scale()`.
        alpha: Sprite opacity (the "next" orb is slightly faded).
        backplate_radius, backplate_color: Size and tint of the halo behind it.
    """

    tier: int
    center: tuple[int, int]
    scale: float
    alpha: int
    backplate_radius: int
    backplate_color: tuple[int, int, int]


def queue_layout(
    assets, game, queue_rect: pygame.Rect
) -> tuple[list[tuple[pygame.Surface, pygame.Rect]], list[PreviewSlot]]:
    """Lay out the Drop Queue panel: its text items and its two preview slots.

    Returning the layout (instead of drawing straight away) lets the tests
    check that previews never cover the labels, using the real fonts.
    """
    left, top, middle = queue_rect.x, queue_rect.y, queue_rect.centerx
    texts: list[tuple[pygame.Surface, pygame.Rect]] = []

    def add_text(surface: pygame.Surface, **anchor: tuple[int, int]) -> None:
        """Record one rendered label at its anchored position."""
        texts.append((surface, surface.get_rect(**anchor)))

    add_text(assets.small_font.render("Drop Queue", True, SOFT_WHITE), topleft=(left + 20, top + 16))
    add_text(assets.body_font.render(game.current_body_name, True, WHITE), center=(middle, top + 172))
    add_text(assets.tiny_font.render("Current", True, GLOW), center=(middle, top + 198))
    # The next body's caption and name share one line, centred as a pair.
    next_hint = assets.tiny_font.render("Next", True, GLOW)
    next_name = assets.small_font.render(game.next_body_name, True, SOFT_WHITE)
    pair_left = middle - (next_hint.get_width() + 8 + next_name.get_width()) // 2
    add_text(next_hint, midleft=(pair_left, top + 288))
    add_text(next_name, midleft=(pair_left + next_hint.get_width() + 8, top + 288))

    current_scale = preview_scale(assets.get_body_surface(game.current_tier), CURRENT_SLOT_RADIUS, 1.12)
    next_scale = preview_scale(assets.get_body_surface(game.next_tier), NEXT_SLOT_RADIUS, 0.82)
    slots = [
        PreviewSlot(game.current_tier, (middle, top + 104), current_scale, 255, CURRENT_SLOT_RADIUS + 6, GLOW),
        PreviewSlot(game.next_tier, (middle, top + 244), next_scale, 215, NEXT_SLOT_RADIUS + 6, shade(GLOW, 0.88)),
    ]
    return texts, slots


def control_rows(assets, info_rect: pygame.Rect) -> list[tuple[pygame.Surface, pygame.Rect]]:
    """Lay out the controls reference as two columns: keys left, action right."""
    items: list[tuple[pygame.Surface, pygame.Rect]] = []
    for index, (keys, action) in enumerate(CONTROL_ROWS):
        color = WHITE if index < 2 else SOFT_WHITE
        y = info_rect.y + 56 + index * 28
        keys_text = assets.tiny_font.render(keys, True, color)
        action_text = assets.tiny_font.render(action, True, GLOW)
        items.append((keys_text, keys_text.get_rect(topleft=(info_rect.x + 20, y))))
        items.append((action_text, action_text.get_rect(topright=(info_rect.right - 20, y))))
    return items


@dataclass(slots=True)
class Button:
    """Simple clickable UI button with hover styling.

    A `Button` only knows its rectangle, label and accent colour. It never acts
    on a click itself: `game.py` asks `contains()` whether a click landed on it
    and decides what to do. The overlay `place_*_buttons` helpers move and
    resize the rectangle so it sits inside its modal.

    Attributes:
        rect: Position and size in canvas coordinates (also the click area).
        label: Text drawn in the middle of the button.
        accent: Border colour; it brightens a little while hovered.
    """

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
        # The shine bar is a faint (alpha 42) reflection. Drawing an alpha
        # colour straight onto the opaque canvas would ignore the alpha and
        # paint solid white, so it goes on its own small alpha strip first.
        shine = pygame.Surface((self.rect.w - 48, 2), pygame.SRCALPHA)
        shine.fill((255, 255, 255, 42))
        target.blit(shine, (self.rect.x + 24, self.rect.y + 10))
        shadow = assets.ui_font.render(self.label, True, (8, 12, 24))
        target.blit(shadow, shadow.get_rect(center=(self.rect.centerx, self.rect.centery + 2)))
        label = assets.ui_font.render(self.label, True, WHITE if hovered else SOFT_WHITE)
        target.blit(label, label.get_rect(center=self.rect.center))


def draw_playfield(surface: pygame.Surface, danger_ratio: float) -> None:
    """Draw the bubble container and its danger line.

    The "Danger line" label is drawn separately by `draw_danger_label`, on top
    of the bodies and the launcher, at a spot `danger_label_rect` keeps clear.
    """
    center = pygame.Vector2(PLAYFIELD_CENTER)
    # The outer glow rings reach 30 px past the rim, so the glow surface needs
    # that much room (plus a little spare) on every side; a smaller surface
    # would cut the round glow off in flat edges.
    glow_reach = 30 + 4
    bubble_rect = pygame.Rect(0, 0, (CONTAINER_RADIUS + glow_reach) * 2, (CONTAINER_RADIUS + glow_reach) * 2)
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
    # from the circle equation instead of guessing a fixed width: at vertical
    # offset `dy` from the centre, the circle is `sqrt(R^2 - dy^2)` wide on
    # each side. The line stops 18 px short of the wall at both ends.
    # The danger line colour walks a calm -> yellow -> orange -> red gradient so
    # rising risk is obvious well before the line actually turns red.
    line_color = danger_gradient(danger_ratio)
    chord_y = FAIL_LINE_Y
    dy = chord_y - center.y
    half_span = math.sqrt(max(0.0, CONTAINER_RADIUS * CONTAINER_RADIUS - dy * dy)) - 18.0
    left = int(center.x - half_span)
    right = int(center.x + half_span)
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


def danger_label_rect(
    text_size: tuple[int, int],
    launcher: pygame.Vector2,
    launcher_radius: float,
    aim_back: pygame.Vector2,
    aim_front: pygame.Vector2,
) -> pygame.Rect:
    """Choose where the "Danger line" label goes so it never hides the launcher.

    The label sits just below the danger line, tucked toward the left or right
    end of it. The side away from the launcher is tried first; a side is used
    only if the label keeps clear of the launcher orb and the aim line
    (`aim_back` to `aim_front`). If neither side is clear on the first row, the
    next row down is tried. Every spot stays well inside the bubble wall.
    """
    pill = pygame.Rect(0, 0, text_size[0] + DANGER_LABEL_PAD[0], text_size[1] + DANGER_LABEL_PAD[1])
    center_x, center_y = PLAYFIELD_CENTER
    orb = pygame.Rect(0, 0, round(launcher_radius * 2), round(launcher_radius * 2))
    orb.center = (round(launcher.x), round(launcher.y))
    sides = ("left", "right") if launcher.x >= center_x else ("right", "left")
    candidate = pill
    for row in range(DANGER_LABEL_ROWS):
        top = FAIL_LINE_Y + DANGER_LABEL_GAP + row * (pill.h + DANGER_LABEL_GAP)
        # Half-width of the bubble at the row's top edge (the narrower edge).
        half_width = math.sqrt(max(0.0, CONTAINER_RADIUS**2 - (top - center_y) ** 2))
        for side in sides:
            candidate = pill.copy()
            candidate.top = top
            if side == "left":
                candidate.left = int(center_x - half_width + DANGER_LABEL_WALL_INSET)
            else:
                candidate.right = int(center_x + half_width - DANGER_LABEL_WALL_INSET)
            clearance = candidate.inflate(DANGER_LABEL_CLEARANCE * 2, DANGER_LABEL_CLEARANCE * 2)
            if not clearance.colliderect(orb) and not clearance.clipline(aim_back, aim_front):
                return candidate
    return candidate


def draw_danger_label(surface: pygame.Surface, font: pygame.font.Font, center: tuple[int, int]) -> pygame.Rect:
    """Draw the "Danger line" label on a dark pill and return the pill's rect.

    The label usually floats over a crowded, colourful stack, so plain white
    text was hard to read; the translucent dark backing keeps it legible.
    """
    text = font.render("Danger line", True, DANGER_LABEL_TEXT)
    pill_rect = text.get_rect().inflate(*DANGER_LABEL_PAD)
    pill_rect.center = center
    pill = pygame.Surface(pill_rect.size, pygame.SRCALPHA)
    pygame.draw.rect(pill, DANGER_LABEL_BACKING, pill.get_rect(), border_radius=pill_rect.h // 2)
    surface.blit(pill, pill_rect)
    surface.blit(text, text.get_rect(center=center))
    return pill_rect


def draw_hud(surface: pygame.Surface, game, assets) -> None:
    """Draw the sidebar HUD with score, queue, controls, and warning meter.

    The sidebar is three panels, top to bottom:

    - Score: the live score, the high score and the number of bodies.
    - Drop Queue: the current and next bodies, laid out by `queue_layout`.
    - Controls and progress: the key reference, the best body reached this
      run (green once the top tier is reached), and the "Container stress"
      bar filled from `game.container_stress`.

    Args:
        surface: The canvas to draw on.
        game: The running `OrbitalOrchardGame`; only read, never changed.
        assets: The `AssetLibrary` with fonts and orb sprites.
    """
    # These panels divide the sidebar into clear chunks of information.
    score_rect = SCORE_PANEL
    queue_rect = QUEUE_PANEL
    info_rect = INFO_PANEL

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
    # The current preview is larger so the player's next action is obvious.
    # Each preview is scaled to fit its slot (see `queue_layout`), so big
    # tiers never cover the panel title or the labels around them.
    texts, slots = queue_layout(assets, game, queue_rect)
    draw_section_rule(surface, queue_rect.x + 20, queue_rect.y + 40, queue_rect.w - 40, GLOW)
    for slot in slots:
        draw_preview_backplate(surface, slot.center, slot.backplate_radius, slot.backplate_color)
        assets.draw_preview_orb(surface, slot.tier, slot.center, game.now, scale=slot.scale, alpha=slot.alpha)
    for text, rect in texts:
        surface.blit(text, rect)

    # Compact controls reference for the player: keys on the left, the action
    # they perform right-aligned, so long key lists can never run off the panel.
    controls_title = assets.small_font.render("Controls", True, SOFT_WHITE)
    surface.blit(controls_title, (info_rect.x + 20, info_rect.y + 16))
    draw_section_rule(surface, info_rect.x + 20, info_rect.y + 40, info_rect.w - 40, GLOW)
    for text, rect in control_rows(assets, info_rect):
        surface.blit(text, rect)

    # Progress summary: best body reached this run.
    best_tier = assets.small_font.render("Best body", True, SOFT_WHITE)
    surface.blit(best_tier, (info_rect.x + 20, info_rect.y + 232))
    unlocked = assets.ui_font.render(game.best_tier_name, True, SUCCESS if game.goal_reached else WHITE)
    surface.blit(unlocked, (info_rect.x + 20, info_rect.y + 258))

    # The stress meter updates continuously based on stack height, then fills the
    # final segment from the actual fail countdown while the player is in danger.
    danger = min(1.0, game.container_stress)
    bar_rect = pygame.Rect(info_rect.x + 20, info_rect.y + 318, info_rect.w - 40, 18)
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


def place_menu_buttons(buttons: list[Button]) -> None:
    """Centre the menu buttons along the bottom of the menu modal."""
    for index, button in enumerate(reversed(buttons)):
        button.rect.size = (260, 64)
        button.rect.centerx = MENU_MODAL.centerx
        button.rect.bottom = MENU_MODAL.bottom - 24 - index * 78


def menu_texts(
    assets, high_score: int, games_played: int, best_tier_name: str
) -> list[tuple[pygame.Surface, pygame.Rect]]:
    """Render and place every text line of the main menu modal."""
    modal = MENU_MODAL
    lines = [
        (assets.title_font, "Orbital", WHITE, 84),
        (assets.title_font, "Orchard", WHITE, 168),
        (assets.small_font, "Drop, bounce, and merge celestial cuties into a Quasar Crown.", SOFT_WHITE, 228),
        (assets.ui_font, "Stack bodies inside the bubble.", WHITE, 286),
        (assets.ui_font, "Touch two matching tiers to evolve them.", WHITE, 332),
        (assets.ui_font, "Keep old bodies under the red danger line.", WHITE, 378),
        (assets.small_font, f"Local high score: {high_score:,}", GLOW, 424),
        (assets.tiny_font, f"Games played: {games_played:,}    Best body: {best_tier_name}", SOFT_WHITE, 458),
    ]
    texts = []
    for font, text, color, offset in lines:
        surface = font.render(text, True, color)
        texts.append((surface, surface.get_rect(center=(modal.centerx, modal.y + offset))))
    return texts


def draw_menu_overlay(
    surface: pygame.Surface,
    assets,
    buttons: list[Button],
    high_score: int,
    games_played: int,
    best_tier_name: str,
    mouse_pos: tuple[int, int],
) -> None:
    """Draw the main menu overlay.

    A translucent veil dims the scene behind, then the menu modal is drawn
    with the title, a short how-to-play, the lifetime stats, and the buttons.

    Args:
        surface: The canvas to draw on.
        assets: The `AssetLibrary` with fonts.
        buttons: Menu buttons owned by the game (placed inside the modal here).
        high_score, games_played, best_tier_name: Lifetime stats to show.
        mouse_pos: Canvas mouse position, for hover highlighting.
    """
    # Dim whatever is behind the menu (the bubble, a stack left over from a
    # previous run, the danger line) so none of it reads as part of the menu.
    veil = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    veil.fill(MENU_VEIL)
    surface.blit(veil, (0, 0))

    # Menus are just overlays drawn on top of the existing background.
    # The main loop decides *when* to draw them, this function decides *how*.
    draw_panel(surface, MENU_MODAL, (10, 18, 42, 230), (108, 148, 238), radius=34)
    for text, rect in menu_texts(assets, high_score, games_played, best_tier_name):
        surface.blit(text, rect)

    # Buttons are passed in from the game object so click handling stays there;
    # they are placed inside the modal here so the layout lives in one place.
    place_menu_buttons(buttons)
    for button in buttons:
        button.draw(surface, assets, mouse_pos)


def place_pause_buttons(buttons: list[Button]) -> None:
    """Stack the pause buttons inside the pause modal."""
    for index, button in enumerate(buttons):
        button.rect.size = (310, 60)
        button.rect.centerx = PAUSE_MODAL.centerx
        button.rect.y = PAUSE_MODAL.y + 184 + index * 74


def pause_texts(assets) -> list[tuple[pygame.Surface, pygame.Rect]]:
    """Render and place the pause modal's title and hint."""
    modal = PAUSE_MODAL
    title = assets.header_font.render("Paused", True, WHITE)
    hint = assets.small_font.render("Take a breath. Your orchard is waiting.", True, SOFT_WHITE)
    return [
        (title, title.get_rect(center=(modal.centerx, modal.y + 74))),
        (hint, hint.get_rect(center=(modal.centerx, modal.y + 134))),
    ]


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
    draw_panel(surface, PAUSE_MODAL, (10, 18, 42, 236), (108, 148, 238), radius=34)
    for text, rect in pause_texts(assets):
        surface.blit(text, rect)

    # Reposition buttons every frame relative to the modal so the layout stays
    # consistent even if button objects are reused elsewhere.
    place_pause_buttons(buttons)
    for button in buttons:
        button.draw(surface, assets, mouse_pos)


def place_game_over_buttons(buttons: list[Button]) -> None:
    """Stack the game-over buttons inside the bottom of the game-over modal."""
    for index, button in enumerate(buttons):
        button.rect.size = (320, 60)
        button.rect.centerx = GAME_OVER_MODAL.centerx
        button.rect.y = GAME_OVER_MODAL.y + 296 + index * 74


def game_over_texts(
    assets,
    score: int,
    high_score: int,
    new_record: bool,
    games_played: int,
    best_tier_name: str,
) -> list[tuple[pygame.Surface, pygame.Rect]]:
    """Render and place every text line of the game-over modal."""
    modal = GAME_OVER_MODAL
    status = "New high score!" if new_record else f"Best: {high_score:,}"
    lines = [
        (assets.header_font, "Orbit Lost", WHITE, 70),
        (assets.score_font, f"{score:,}", WHITE, 148),
        (assets.small_font, "Final score", SOFT_WHITE, 192),
        (assets.small_font, status, SUCCESS if new_record else GLOW, 228),
        (assets.tiny_font, f"Games played: {games_played:,}    Best ever: {best_tier_name}", SOFT_WHITE, 262),
    ]
    texts = []
    for font, text, color, offset in lines:
        surface = font.render(text, True, color)
        texts.append((surface, surface.get_rect(center=(modal.centerx, modal.y + offset))))
    return texts


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
    draw_panel(surface, GAME_OVER_MODAL, (10, 18, 42, 240), (255, 140, 140), radius=34)
    for text, rect in game_over_texts(assets, score, high_score, new_record, games_played, best_tier_name):
        surface.blit(text, rect)

    # Place the retry buttons relative to the modal, matching the pause overlay.
    place_game_over_buttons(buttons)
    for button in buttons:
        button.draw(surface, assets, mouse_pos)
