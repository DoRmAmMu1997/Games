"""Transient visual effects such as particles, popups, and screen shake."""

# Beginner note:
# This file handles the "juicy" feedback that makes the game feel responsive.
# None of these effects change the score or physics rules directly.
# They only make events easier and more satisfying to notice.

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pygame

from settings import SCREEN_HEIGHT, SCREEN_WIDTH, SOFT_WHITE, WHITE


@dataclass(slots=True)
class Particle:
    """A tiny moving dot used for impact and merge bursts."""

    # Each particle keeps only the minimum data needed to animate itself.
    position: pygame.Vector2
    velocity: pygame.Vector2
    color: tuple[int, int, int]
    radius: float
    life: float
    gravity: float = 0.0

    def update(self, dt: float) -> None:
        """Move the particle forward and age it out."""
        self.life -= dt
        self.velocity.y += self.gravity * dt
        self.velocity *= 0.985
        self.position += self.velocity * dt


@dataclass(slots=True)
class RingPulse:
    """An expanding outline ring used mainly for merges."""

    # A ring pulse starts small, grows outward, and fades as `life` approaches zero.
    position: pygame.Vector2
    color: tuple[int, int, int]
    radius: float
    growth: float
    life: float

    def update(self, dt: float) -> None:
        """Increase the ring radius while reducing its remaining lifetime."""
        self.life -= dt
        self.radius += self.growth * dt


@dataclass(slots=True)
class PopupText:
    """Floating score text such as `+24` or milestone announcements."""

    # `scale` lets special messages look larger without needing a second font.
    text: str
    position: pygame.Vector2
    velocity: pygame.Vector2
    color: tuple[int, int, int]
    life: float
    scale: float = 1.0

    def update(self, dt: float) -> None:
        """Move upward gently while fading over time."""
        self.life -= dt
        self.position += self.velocity * dt
        self.velocity *= 0.92


class EffectsManager:
    """Central place for creating, updating, and drawing temporary effects."""

    def __init__(self) -> None:
        # Separate lists keep each effect type easy to manage and debug.
        self.particles: list[Particle] = []
        self.rings: list[RingPulse] = []
        self.popups: list[PopupText] = []

        # Reusing one transparent overlay surface is cheaper than creating a new
        # full-screen surface every frame.
        self.overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)

        # `trauma` is a common game-dev term for shake intensity.
        # Higher trauma means stronger camera shake.
        self.trauma = 0.0

    def add_shake(self, amount: float) -> None:
        """Increase the camera-shake amount, clamped to a safe maximum."""
        self.trauma = min(1.0, self.trauma + amount)

    def impact(self, position: pygame.Vector2, color: tuple[int, int, int], strength: float) -> None:
        """Create a small impact burst when a collision is strong enough."""
        if strength < 180.0:
            # Quiet collisions are ignored so the screen is not noisy all the time.
            return
        count = 5 + int(strength / 120.0)
        for _ in range(count):
            # Pick a random mostly-upward direction so impact debris sprays nicely.
            direction = pygame.Vector2(random.uniform(-1.0, 1.0), random.uniform(-1.0, 0.2))
            if direction.length_squared() == 0.0:
                direction = pygame.Vector2(1.0, 0.0)
            direction = direction.normalize()
            speed = random.uniform(80.0, 220.0) + strength * 0.15
            self.particles.append(
                Particle(
                    position=pygame.Vector2(position),
                    velocity=direction * speed,
                    color=color,
                    radius=random.uniform(2.0, 5.0),
                    life=random.uniform(0.18, 0.34),
                    gravity=180.0,
                )
            )
        self.add_shake(min(0.12, strength / 2600.0))

    def merge(self, position: pygame.Vector2, color: tuple[int, int, int], score_gain: int, target_tier: int) -> None:
        """Create the bigger celebration effect used for successful merges."""
        # Bigger tiers produce bigger bursts.
        burst_count = 16 + target_tier * 2
        for _ in range(burst_count):
            angle = random.uniform(0.0, math.tau)
            speed = random.uniform(90.0, 260.0) + target_tier * 12.0
            velocity = pygame.Vector2(math.cos(angle), math.sin(angle)) * speed
            self.particles.append(
                Particle(
                    position=pygame.Vector2(position),
                    velocity=velocity,
                    color=color,
                    radius=random.uniform(2.0, 6.0),
                    life=random.uniform(0.24, 0.42),
                    gravity=40.0,
                )
            )

        # The expanding ring helps merges read instantly even in a busy stack.
        self.rings.append(
            RingPulse(
                position=pygame.Vector2(position),
                color=color,
                radius=18.0,
                growth=180.0 + target_tier * 12.0,
                life=0.34,
            )
        )

        # Floating score text rewards the player immediately.
        self.popups.append(
            PopupText(
                text=f"+{score_gain}",
                position=pygame.Vector2(position.x, position.y - 10.0),
                velocity=pygame.Vector2(0.0, -88.0),
                color=WHITE,
                life=0.9,
                scale=1.0 + min(0.4, target_tier * 0.03),
            )
        )
        self.add_shake(0.12 + target_tier * 0.018)

    def announce(self, text: str, position: pygame.Vector2) -> None:
        """Spawn a larger text popup for milestones such as reaching the top tier."""
        self.popups.append(
            PopupText(
                text=text,
                position=pygame.Vector2(position),
                velocity=pygame.Vector2(0.0, -50.0),
                color=SOFT_WHITE,
                life=1.4,
                scale=1.5,
            )
        )
        self.add_shake(0.28)

    def combo(self, count: int, position: pygame.Vector2) -> None:
        """Spawn a small popup celebrating a chain of quick back-to-back merges."""
        self.popups.append(
            PopupText(
                text=f"Combo x{count}",
                position=pygame.Vector2(position.x, position.y - 34.0),
                velocity=pygame.Vector2(0.0, -70.0),
                color=(255, 214, 90),
                life=1.0,
                scale=1.2,
            )
        )

    def reward_burst(self, position: pygame.Vector2, color: tuple[int, int, int]) -> None:
        """Create an extra-celebratory burst for reaching a new best tier.

        This is deliberately bigger than a normal merge burst: more particles,
        two expanding rings, and a strong screen shake make a personal record
        feel like a genuine milestone.
        """
        for _ in range(40):
            angle = random.uniform(0.0, math.tau)
            speed = random.uniform(160.0, 430.0)
            velocity = pygame.Vector2(math.cos(angle), math.sin(angle)) * speed
            self.particles.append(
                Particle(
                    position=pygame.Vector2(position),
                    velocity=velocity,
                    color=color,
                    radius=random.uniform(3.0, 7.0),
                    life=random.uniform(0.4, 0.78),
                    gravity=30.0,
                )
            )
        # Two rings of different starting size add depth to the celebration.
        for start_radius in (16.0, 30.0):
            self.rings.append(
                RingPulse(
                    position=pygame.Vector2(position),
                    color=color,
                    radius=start_radius,
                    growth=270.0,
                    life=0.5,
                )
            )
        self.add_shake(0.4)

    def update(self, dt: float) -> None:
        """Advance and prune every active effect object."""
        self.trauma = max(0.0, self.trauma - dt * 1.3)

        # Rebuild each list with only still-alive effects, then update survivors.
        # This is a simple pattern beginners will see often in games:
        # "throw away expired objects, then advance the active ones."
        self.particles = [particle for particle in self.particles if particle.life > 0.0]
        for particle in self.particles:
            particle.update(dt)

        self.rings = [ring for ring in self.rings if ring.life > 0.0]
        for ring in self.rings:
            ring.update(dt)

        self.popups = [popup for popup in self.popups if popup.life > 0.0]
        for popup in self.popups:
            popup.update(dt)

    def camera_offset(self) -> pygame.Vector2:
        """Convert current shake intensity into a random camera offset."""
        if self.trauma <= 0.0:
            return pygame.Vector2()

        # Squaring trauma makes small values subtle while big values still feel punchy.
        amount = self.trauma * self.trauma * 16.0
        return pygame.Vector2(random.uniform(-amount, amount), random.uniform(-amount, amount))

    def draw(self, target: pygame.Surface, assets, camera_offset: pygame.Vector2) -> None:
        """Render all effects on top of the playfield."""
        # Clear the reusable transparent overlay surface first.
        self.overlay.fill((0, 0, 0, 0))

        for ring in self.rings:
            # As `life` shrinks, alpha also shrinks so the ring fades out.
            alpha = int(max(0.0, min(1.0, ring.life / 0.34)) * 170)
            pygame.draw.circle(
                self.overlay,
                (*ring.color, alpha),
                (int(ring.position.x + camera_offset.x), int(ring.position.y + camera_offset.y)),
                int(ring.radius),
                4,
            )

        for particle in self.particles:
            # Particles fade with their remaining life as well.
            alpha = int(max(0.0, min(1.0, particle.life / 0.42)) * 255)
            pygame.draw.circle(
                self.overlay,
                (*particle.color, alpha),
                (int(particle.position.x + camera_offset.x), int(particle.position.y + camera_offset.y)),
                max(1, int(particle.radius)),
            )

        target.blit(self.overlay, (0, 0))

        for popup in self.popups:
            # Text popups are rendered after the overlay so they stay crisp.
            # If we drew them onto the big transparent overlay first, they would
            # look blurrier and would be harder to read.
            alpha = int(max(0.0, min(1.0, popup.life / 1.4)) * 255)
            base = assets.body_font.render(popup.text, True, popup.color)
            if abs(popup.scale - 1.0) > 0.01:
                width = max(1, int(base.get_width() * popup.scale))
                height = max(1, int(base.get_height() * popup.scale))
                base = pygame.transform.smoothscale(base, (width, height))
            base.set_alpha(alpha)
            center = (int(popup.position.x + camera_offset.x), int(popup.position.y + camera_offset.y))
            target.blit(base, base.get_rect(center=center))
