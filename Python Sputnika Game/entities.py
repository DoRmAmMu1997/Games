"""Definitions for the moving celestial bodies.

Each body stores:
- its gameplay state (tier, position, velocity),
- timing state for merging and impacts,
- small animation state for blinking, bobbing, and squashing.

Beginner note:
- A `CelestialBody` is both a physics object and a character.
- That is why this file mixes "simulation" values like `velocity` with
  "presentation" values like blinking and facial expressions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import random

import pygame

from settings import FAIL_LINE_Y, MERGE_ARM_TIME, POST_MERGE_LOCK, TIERS, WHITE, shade


def _random_phase() -> float:
    """Give each body a slightly different idle animation timing."""
    return random.uniform(0.0, math.tau)


@dataclass(slots=True)
class CelestialBody:
    """One round object inside the playfield."""

    # Core identity/state.
    # These values answer "what is this body and where is it right now?"
    body_id: int
    tier: int
    position: pygame.Vector2
    velocity: pygame.Vector2
    created_at: float

    # Small random values make each body feel slightly unique.
    # `seed` is also reused by some animation and gravity-flavor logic.
    seed: float = field(default_factory=random.random)
    hover_phase: float = field(default_factory=_random_phase)

    # Merge/impact timers prevent repeated triggers from happening too fast.
    merge_locked_until: float = 0.0
    impact_cooldown_until: float = 0.0

    # Short-lived animation values.
    pulse: float = 0.0
    flash: float = 0.0
    blink_cooldown: float = 0.0
    blink_time: float = 0.0
    # `birth_pop` drives the "arrival" scale-in of a freshly merged body:
    # it starts at 1.0 and decays to 0.0, growing the body from small to full.
    birth_pop: float = 0.0

    def __post_init__(self) -> None:
        # Fresh bodies are briefly prevented from merging instantly.
        # Dataclasses call `__post_init__` right after the generated `__init__`.
        if self.merge_locked_until == 0.0:
            self.merge_locked_until = self.created_at + POST_MERGE_LOCK

        # Each body also gets a different blink rhythm so they feel less robotic.
        if self.blink_cooldown == 0.0:
            self.blink_cooldown = 1.0 + random.random() * 2.6

    @property
    def info(self):
        """Shortcut to the tier data for this body."""
        return TIERS[self.tier]

    @property
    def radius(self) -> float:
        """Expose radius directly so the rest of the code reads cleanly."""
        return self.info.radius

    @property
    def mass(self) -> float:
        """Approximate mass from area, with a small minimum for stability."""
        return max(4.0, (self.radius * self.radius) * 0.018)

    @property
    def inv_mass(self) -> float:
        """Inverse mass is used often in collision math, so we precompute it on demand."""
        return 1.0 / self.mass

    @property
    def top(self) -> float:
        """Y coordinate of the body's top edge, useful for fail-line checks."""
        return self.position.y - self.radius

    def age(self, now: float) -> float:
        """How long this body has existed in seconds."""
        return now - self.created_at

    def can_merge(self, now: float) -> bool:
        """Return True only when the body is old enough and not merge-locked."""
        return now >= self.merge_locked_until and self.age(now) >= MERGE_ARM_TIME

    def lock_merge(self, now: float, delay: float = POST_MERGE_LOCK) -> None:
        """Push the merge lock into the future by `delay` seconds."""
        self.merge_locked_until = now + delay

    def register_impact(self, now: float, strength: float) -> bool:
        """Trigger squash/flash feedback for a noticeable impact.

        Returns `True` if a new impact was accepted and `False` if it was
        ignored because another impact was registered too recently.
        """
        if now < self.impact_cooldown_until:
            return False
        self.impact_cooldown_until = now + 0.055
        normalized = max(0.0, min(1.0, strength / 460.0))

        # Stronger collisions produce bigger squash/flash values.
        self.pulse = max(self.pulse, 0.35 + normalized * 0.95)
        self.flash = max(self.flash, 0.25 + normalized * 0.7)
        return True

    def update(self, dt: float) -> None:
        """Advance short-lived animation values by one frame."""
        # Pulse and flash decay back toward their neutral values over time.
        self.pulse = max(0.0, self.pulse - dt * 2.2)
        self.flash = max(0.0, self.flash - dt * 3.0)
        # The arrival pop fades out quickly (about a fifth of a second).
        self.birth_pop = max(0.0, self.birth_pop - dt * 5.0)

        if self.blink_time > 0.0:
            # While a blink is happening, count down until the eyes reopen.
            self.blink_time = max(0.0, self.blink_time - dt)
        else:
            # Otherwise count down to the next blink.
            self.blink_cooldown -= dt
            if self.blink_cooldown <= 0.0:
                self.blink_time = 0.12
                self.blink_cooldown = 1.4 + random.random() * 2.8

    def draw(
        self,
        target: pygame.Surface,
        assets,
        camera_offset: pygame.Vector2,
        now: float,
    ) -> None:
        """Draw the orb art plus its animated face."""
        # The body art itself comes from `assets.py`.
        # This function mainly decides *where* to draw it and *which extra face
        # animation state* should appear on top of it.
        bob = 0.0
        breathe = 0.0
        # Bodies that are almost resting gently float and "breathe" so a
        # settled stack still feels alive instead of completely frozen.
        if self.velocity.length_squared() < 2500.0:
            bob = math.sin(now * 1.4 + self.hover_phase) * 1.35
            breathe = math.sin(now * 1.1 + self.hover_phase) * 0.018

        # Three things affect the drawn size: `pulse` enlarges the sprite after
        # impacts/merges, `breathe` adds the tiny idle wobble, and `birth_pop`
        # makes a freshly merged body scale in from small to full size.
        scale = (1.0 + self.pulse * 0.14 + breathe) * (1.0 - self.birth_pop * 0.45)
        orb = assets.get_body_surface(self.tier)
        if abs(scale - 1.0) > 0.01:
            # `smoothscale` keeps resizing from looking jagged.
            width = max(8, int(orb.get_width() * scale))
            height = max(8, int(orb.get_height() * scale))
            orb = pygame.transform.smoothscale(orb, (width, height))

        draw_pos = pygame.Vector2(self.position.x, self.position.y + bob) + camera_offset

        # A soft shadow under each body helps the stack feel less flat.
        shadow_surface = pygame.Surface(
            (max(12, int(self.radius * scale * 2.0)), max(8, int(self.radius * scale * 0.72))),
            pygame.SRCALPHA,
        )
        shadow_rect = shadow_surface.get_rect(center=(round(draw_pos.x), round(draw_pos.y + self.radius * scale * 0.78)))
        pygame.draw.ellipse(
            shadow_surface,
            (4, 8, 18, 58 + int(self.radius * 0.45)),
            shadow_surface.get_rect(),
        )
        target.blit(shadow_surface, shadow_rect)

        # A brief flash halo sells heavier impacts and merge pops.
        if self.flash > 0.0:
            halo_size = max(12, int(self.radius * scale * 2.9))
            halo = pygame.Surface((halo_size, halo_size), pygame.SRCALPHA)
            halo_center = pygame.Vector2(halo_size / 2, halo_size / 2)
            halo_alpha = int(45 + self.flash * 90)
            pygame.draw.circle(
                halo,
                (*shade(self.info.color, 1.18), halo_alpha),
                halo_center,
                int(self.radius * scale * (1.08 + self.flash * 0.16)),
                width=max(2, int(self.radius * 0.08)),
            )
            target.blit(halo, halo.get_rect(center=(round(draw_pos.x), round(draw_pos.y))))

        rect = orb.get_rect(center=(round(draw_pos.x), round(draw_pos.y)))
        target.blit(orb, rect)

        # The face is drawn separately so it can react to current animation state.
        self._draw_face(target, rect.center, self.radius * scale, now)

    def _draw_face(
        self,
        target: pygame.Surface,
        center: tuple[int, int],
        radius: float,
        now: float,
    ) -> None:
        """Draw simple cartoon eyes, mouth, and cheeks on top of the orb."""
        info = self.info
        cx, cy = center

        # Read a richer face "state" first so several drawing decisions can
        # respond consistently to current motion, danger, or impact.
        expression = self._expression_state(now)

        # Eye placement is defined relative to the body radius so the same math
        # works for tiny and huge tiers.
        eye_y = cy - radius * 0.1
        eye_dx = radius * 0.28
        blink = self.blink_time > 0.0
        eye_color = shade(info.accent, 0.42)
        eye_radius = max(2, int(radius * 0.085))
        eye_white = shade(WHITE, 0.98)

        # Pupils look slightly in the movement direction. This tiny detail makes
        # the bodies feel much more alive and aware of the action around them.
        gaze = pygame.Vector2(self.velocity)
        if gaze.length_squared() > 1.0:
            gaze = gaze.normalize()
        else:
            gaze = pygame.Vector2(math.sin(now * 0.7 + self.seed * 4.0), math.cos(now * 0.9 + self.seed * 5.0)) * 0.15
        gaze *= radius * 0.035
        eyelid_drop = radius * (0.05 if expression["sleepy"] else 0.0)
        eye_height_scale = 0.78 if expression["sleepy"] else 1.0

        if blink:
            # Closed eyes are drawn as short lines.
            line_y = int(eye_y)
            line_half = max(3, int(radius * 0.09))
            pygame.draw.line(target, eye_color, (int(cx - eye_dx - line_half), line_y), (int(cx - eye_dx + line_half), line_y), 2)
            pygame.draw.line(target, eye_color, (int(cx + eye_dx - line_half), line_y), (int(cx + eye_dx + line_half), line_y), 2)
        else:
            # Open eyes use a white sclera, dark pupil, and highlight.
            # Slightly taller eyes help the expressions read more clearly.
            for eye_center_x in (cx - eye_dx, cx + eye_dx):
                eye_rect = pygame.Rect(0, 0, int(eye_radius * 2.7), int(eye_radius * 2.2 * eye_height_scale))
                eye_rect.center = (int(eye_center_x), int(eye_y + eyelid_drop))
                pygame.draw.ellipse(target, eye_white, eye_rect)
                pygame.draw.ellipse(target, (*shade(info.accent, 0.46), 255), eye_rect, width=1)

                pupil_radius = max(2, int(eye_radius * (0.68 if expression["startled"] else 0.82)))
                pupil_center = (
                    int(eye_center_x + gaze.x),
                    int(eye_y + eyelid_drop + gaze.y),
                )
                pygame.draw.circle(target, eye_color, pupil_center, pupil_radius)
                pygame.draw.circle(target, WHITE, (pupil_center[0] - 1, pupil_center[1] - 1), max(1, pupil_radius // 3))

        self._draw_brows(target, center, radius, expression)

        mouth_rect = pygame.Rect(0, 0, int(radius * 0.55), int(radius * 0.32))
        mouth_rect.center = (cx, int(cy + radius * 0.2))
        mouth_color = shade(info.accent, 0.55)

        mood = info.mood

        # Dynamic expressions override the default mood when the game state
        # makes the body look more surprised, worried, or delighted.
        if expression["startled"]:
            pygame.draw.circle(target, mouth_color, (cx, int(cy + radius * 0.22)), max(2, int(radius * 0.07)), 2)
        elif expression["worried"]:
            worried_rect = mouth_rect.copy()
            worried_rect.y += int(radius * 0.03)
            pygame.draw.arc(target, mouth_color, worried_rect, math.pi + 0.18, math.tau - 0.18, 3)
        elif expression["delighted"]:
            happy_rect = mouth_rect.inflate(int(radius * 0.08), int(radius * 0.06))
            pygame.draw.arc(target, mouth_color, happy_rect, 0.0, math.pi, 3)
            pygame.draw.circle(target, (*WHITE, 90), (int(cx - radius * 0.08), int(cy + radius * 0.2)), max(1, int(radius * 0.035)))
        # Different tiers use different mouth shapes so they feel like distinct characters.
        elif mood in {"cheery", "smile", "spark", "bright"}:
            pygame.draw.arc(target, mouth_color, mouth_rect, 0.1, math.pi - 0.1, 3)
        elif mood == "curious":
            pygame.draw.circle(target, mouth_color, (cx, int(cy + radius * 0.2)), max(2, int(radius * 0.05)), 2)
        elif mood == "calm":
            pygame.draw.arc(target, mouth_color, mouth_rect, 0.35, math.pi - 0.35, 2)
        elif mood == "wry":
            start = (int(cx - radius * 0.16), int(cy + radius * 0.2))
            end = (int(cx + radius * 0.16), int(cy + radius * 0.14))
            pygame.draw.line(target, mouth_color, start, end, 3)
        elif mood == "sleepy":
            pygame.draw.line(
                target,
                mouth_color,
                (int(cx - radius * 0.16), int(cy + radius * 0.21)),
                (int(cx + radius * 0.16), int(cy + radius * 0.21)),
                2,
            )
        elif mood == "proud":
            pygame.draw.arc(target, mouth_color, mouth_rect, 0.0, math.pi, 2)
            pygame.draw.line(target, mouth_color, (cx, int(cy + radius * 0.08)), (cx, int(cy + radius * 0.18)), 2)
        else:
            # The fallback "cosmic" mouth gently wiggles over time.
            wobble = math.sin(now * 2.2 + self.seed * 9.0) * radius * 0.04
            pygame.draw.arc(
                target,
                mouth_color,
                mouth_rect.move(0, wobble),
                0.1,
                math.pi - 0.1,
                3,
            )

        # Soft cheeks make the faces feel warmer and more expressive.
        cheek_alpha = 136 if expression["delighted"] else 110
        cheek_color = (*shade(info.color, 1.08), cheek_alpha)
        cheek_surface = pygame.Surface((int(radius * 0.42), int(radius * 0.22)), pygame.SRCALPHA)
        pygame.draw.ellipse(cheek_surface, cheek_color, cheek_surface.get_rect())
        target.blit(cheek_surface, cheek_surface.get_rect(center=(int(cx - radius * 0.35), int(cy + radius * 0.08))))
        target.blit(cheek_surface, cheek_surface.get_rect(center=(int(cx + radius * 0.35), int(cy + radius * 0.08))))

        # A tiny sweat drop is a cute shorthand for "I'm stressed!" when the
        # body rises too near the danger line.
        if expression["worried"]:
            self._draw_sweat_drop(target, center, radius)

    def _expression_state(self, now: float) -> dict[str, bool]:
        """Summarize the body's current emotional read for face rendering.

        The game does not simulate true emotions. Instead, this helper maps
        physical/gameplay signals into readable animation states:
        - fast or flashing -> startled,
        - near the danger line -> worried,
        - strong pulse after a merge -> delighted,
        - very slow motion + sleepy tier mood -> sleepy.
        """
        speed = self.velocity.length()
        near_danger = self.top < FAIL_LINE_Y + self.radius * 0.7
        startled = self.flash > 0.16 or speed > 380.0
        delighted = self.pulse > 0.72 and self.flash > 0.1
        sleepy = self.info.mood == "sleepy" and speed < 75.0 and self.flash < 0.08
        worried = near_danger and self.age(now) > 0.35
        # Returning a dictionary keeps the call sites readable:
        # `expression["worried"]` is easier to scan than remembering index numbers.
        return {
            "startled": startled,
            "delighted": delighted,
            "sleepy": sleepy,
            "worried": worried,
            "focused": speed > 180.0 and not startled and not worried,
        }

    def _draw_brows(
        self,
        target: pygame.Surface,
        center: tuple[int, int],
        radius: float,
        expression: dict[str, bool],
    ) -> None:
        """Draw expressive brows above the eyes.

        Eyebrows are one of the cheapest ways to make simple faces feel alive.
        A tiny angle change can shift the whole emotion from happy to worried.
        """
        cx, cy = center
        brow_y = cy - radius * 0.27
        brow_dx = radius * 0.28
        brow_half = radius * 0.13
        brow_color = shade(self.info.accent, 0.42)

        if expression["sleepy"]:
            left = ((cx - brow_dx - brow_half), brow_y, (cx - brow_dx + brow_half), brow_y + radius * 0.02)
            right = ((cx + brow_dx - brow_half), brow_y + radius * 0.02, (cx + brow_dx + brow_half), brow_y)
        elif expression["startled"]:
            left = ((cx - brow_dx - brow_half), brow_y + radius * 0.02, (cx - brow_dx + brow_half), brow_y - radius * 0.06)
            right = ((cx + brow_dx - brow_half), brow_y - radius * 0.06, (cx + brow_dx + brow_half), brow_y + radius * 0.02)
        elif expression["worried"]:
            left = ((cx - brow_dx - brow_half), brow_y - radius * 0.02, (cx - brow_dx + brow_half), brow_y + radius * 0.07)
            right = ((cx + brow_dx - brow_half), brow_y + radius * 0.07, (cx + brow_dx + brow_half), brow_y - radius * 0.02)
        elif expression["focused"]:
            left = ((cx - brow_dx - brow_half), brow_y + radius * 0.03, (cx - brow_dx + brow_half), brow_y - radius * 0.05)
            right = ((cx + brow_dx - brow_half), brow_y - radius * 0.05, (cx + brow_dx + brow_half), brow_y + radius * 0.03)
        else:
            left = ((cx - brow_dx - brow_half), brow_y, (cx - brow_dx + brow_half), brow_y - radius * 0.03)
            right = ((cx + brow_dx - brow_half), brow_y - radius * 0.03, (cx + brow_dx + brow_half), brow_y)

        pygame.draw.line(target, brow_color, left[:2], left[2:], max(2, int(radius * 0.05)))
        pygame.draw.line(target, brow_color, right[:2], right[2:], max(2, int(radius * 0.05)))

    def _draw_sweat_drop(self, target: pygame.Surface, center: tuple[int, int], radius: float) -> None:
        """Draw a tiny anime-style sweat drop for worried faces."""
        cx, cy = center
        drop_surface = pygame.Surface((int(radius * 0.24), int(radius * 0.34)), pygame.SRCALPHA)
        points = [
            (drop_surface.get_width() / 2, 0),
            (drop_surface.get_width(), drop_surface.get_height() * 0.56),
            (drop_surface.get_width() / 2, drop_surface.get_height()),
            (0, drop_surface.get_height() * 0.56),
        ]
        pygame.draw.polygon(drop_surface, (210, 242, 255, 190), points)
        pygame.draw.polygon(drop_surface, (112, 172, 214, 190), points, 1)
        target.blit(drop_surface, drop_surface.get_rect(center=(int(cx + radius * 0.52), int(cy - radius * 0.14))))
