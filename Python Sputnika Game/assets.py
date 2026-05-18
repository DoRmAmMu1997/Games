"""Procedural art, fonts, background generation, and placeholder sounds.

The goal of this file is to keep the project self-contained:
- no external images are required,
- no external sound files are required,
- the rest of the game can request ready-to-use surfaces by tier.

Beginner note:
- "Procedural" means the game draws or generates assets in code at runtime.
- That is why you will see lots of circles, arcs, gradients, and math here
  instead of loading `.png` and `.wav` files from disk.
"""

from __future__ import annotations

from array import array
import math
import random

import pygame

from settings import (
    BACKGROUND_STAR_COUNT,
    BG_BOTTOM,
    BG_TOP,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SOFT_WHITE,
    TIERS,
    WHITE,
    lerp_color,
    shade,
)


class SoundBank:
    """Creates and stores short procedural sounds used by the game."""

    def __init__(self) -> None:
        # If the mixer failed to initialize, the game still runs silently.
        self.enabled = pygame.mixer.get_init() is not None
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        if not self.enabled:
            return

        try:
            # Build a small sound palette from pure generated tones.
            # Different frequency combinations make each event type sound distinct.
            self.sounds["drop"] = self._make_tone([280, 420], 0.08, 0.35)
            self.sounds["merge"] = self._make_tone([420, 560, 760], 0.14, 0.32)
            self.sounds["big_merge"] = self._make_tone([320, 480, 720, 980], 0.22, 0.34)
            self.sounds["button"] = self._make_tone([540, 780], 0.06, 0.28)
            self.sounds["game_over"] = self._make_tone([300, 220, 160], 0.36, 0.34)
            self.sounds["record"] = self._make_tone([520, 660, 880, 1200], 0.22, 0.34)
            # A tense low double-tone used for the escalating danger warning beep.
            self.sounds["warning"] = self._make_tone([196, 262], 0.11, 0.3)
        except pygame.error:
            # Any mixer/build error disables sound cleanly instead of crashing.
            self.enabled = False
            self.sounds.clear()

    def play(self, name: str, volume: float = 1.0) -> None:
        """Play one named sound if audio is available."""
        if not self.enabled:
            return
        sound = self.sounds.get(name)
        if sound is None:
            return
        sound.set_volume(max(0.0, min(1.0, volume)))
        sound.play()

    def _make_tone(self, frequencies: list[float], duration: float, volume: float) -> pygame.mixer.Sound:
        """Synthesize a short waveform directly into a pygame Sound object."""
        mixer_state = pygame.mixer.get_init()
        if mixer_state is None:
            raise pygame.error("Mixer unavailable")

        sample_rate, _, channels = mixer_state
        sample_count = int(sample_rate * duration)
        samples = array("h")
        for index in range(sample_count):
            # Convert the current sample index into seconds.
            t = index / sample_rate

            # Quick attack + exponential decay keeps the tone snappy and game-like.
            envelope = min(1.0, index / max(1, int(sample_count * 0.06)))
            envelope *= math.exp(-3.4 * index / sample_count)
            value = 0.0
            for harmonic, frequency in enumerate(frequencies, start=1):
                # Blend several sine waves; later harmonics are quieter.
                # This is a tiny version of building a richer musical timbre.
                value += math.sin(math.tau * frequency * t) / harmonic
            value *= volume * envelope

            # Convert from a floating-point wave in roughly [-1, 1] to a signed
            # 16-bit integer sample pygame's mixer can store.
            sample = int(max(-1.0, min(1.0, value)) * 32767)
            if channels == 2:
                # Stereo would need two samples per moment; we copy the same
                # value into both left and right channels.
                samples.extend((sample, sample))
            else:
                samples.append(sample)
        return pygame.mixer.Sound(buffer=samples.tobytes())


class AssetLibrary:
    """Caches procedural surfaces and exposes shared fonts and sounds."""

    def __init__(self) -> None:
        # `body_cache` avoids redrawing every tier from scratch each frame.
        # Caching is important here because these body surfaces contain several
        # layered drawing operations and would be wasteful to rebuild constantly.
        self.body_cache: dict[int, pygame.Surface] = {}

        # Build heavyweight assets once up front.
        self.background = self._build_background()
        self.stars = self._build_stars()
        self.sparkles = self._build_sparkles()
        self.vignette = self._build_vignette()
        self.sounds = SoundBank()

        # pygame's default built-in font is enough for this prototype.
        # Different sizes are stored here so callers can reuse them easily.
        self.title_font = pygame.font.Font(None, 104)
        self.header_font = pygame.font.Font(None, 60)
        self.score_font = pygame.font.Font(None, 72)
        self.body_font = pygame.font.Font(None, 38)
        self.ui_font = pygame.font.Font(None, 34)
        self.small_font = pygame.font.Font(None, 26)
        self.tiny_font = pygame.font.Font(None, 22)

    def get_body_surface(self, tier: int) -> pygame.Surface:
        """Return the prebuilt orb art for one tier, generating it on first use."""
        if tier not in self.body_cache:
            self.body_cache[tier] = self._build_body_surface(tier)
        return self.body_cache[tier]

    def draw_background(self, target: pygame.Surface, now: float, drift: pygame.Vector2 | None = None) -> None:
        """Draw the static background plus twinkling moving stars."""
        target.blit(self.background, (0, 0))
        drift = drift or pygame.Vector2()
        for x, y, size, speed, phase, depth in self.stars:
            # The sine wave changes brightness over time for a twinkle effect.
            twinkle = 0.55 + 0.45 * math.sin(now * speed + phase)
            brightness = int(170 + 85 * twinkle)

            # `depth` makes some stars move slightly more than others, giving
            # a cheap parallax effect when the background drifts.
            px = (x + drift.x * depth * 0.15) % SCREEN_WIDTH
            py = (y + drift.y * depth * 0.06) % SCREEN_HEIGHT
            pygame.draw.circle(target, (brightness, brightness, 255), (int(px), int(py)), size)

        # Sparkles are larger and rarer than stars. They slowly shimmer to make
        # the background feel more alive without distracting from the playfield.
        for x, y, radius, speed, phase, hue_shift in self.sparkles:
            glow = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(now * speed + phase))
            alpha = int(38 + 72 * glow)
            sparkle = pygame.Surface((radius * 6, radius * 6), pygame.SRCALPHA)
            sparkle_center = pygame.Vector2(sparkle.get_width() / 2, sparkle.get_height() / 2)
            sparkle_color = (
                min(255, 210 + hue_shift),
                min(255, 220 + hue_shift // 2),
                255,
                alpha,
            )
            pygame.draw.circle(sparkle, sparkle_color, sparkle_center, radius)
            pygame.draw.line(
                sparkle,
                (*sparkle_color[:3], alpha - 12),
                (sparkle_center.x - radius * 2, sparkle_center.y),
                (sparkle_center.x + radius * 2, sparkle_center.y),
                max(1, radius // 2),
            )
            pygame.draw.line(
                sparkle,
                (*sparkle_color[:3], alpha - 12),
                (sparkle_center.x, sparkle_center.y - radius * 2),
                (sparkle_center.x, sparkle_center.y + radius * 2),
                max(1, radius // 2),
            )
            px = int((x + drift.x * 0.08) % SCREEN_WIDTH)
            py = int((y + drift.y * 0.04) % SCREEN_HEIGHT)
            target.blit(sparkle, sparkle.get_rect(center=(px, py)))

        # The vignette darkens the outer edges slightly so the eye is drawn
        # toward the center play area and the sidebar.
        target.blit(self.vignette, (0, 0))

    def draw_preview_orb(
        self,
        target: pygame.Surface,
        tier: int,
        center: tuple[int, int] | pygame.Vector2,
        now: float,
        scale: float = 1.0,
        alpha: int = 255,
    ) -> None:
        """Draw a floating preview version of a tier icon."""
        orb = self.get_body_surface(tier)
        if alpha != 255:
            orb = orb.copy()
            orb.set_alpha(alpha)
        if abs(scale - 1.0) > 0.01:
            # Previews can be drawn larger or smaller than their normal size.
            width = max(8, int(orb.get_width() * scale))
            height = max(8, int(orb.get_height() * scale))
            orb = pygame.transform.smoothscale(orb, (width, height))

        # A tiny vertical bob prevents preview objects from feeling static.
        draw_center = pygame.Vector2(center)
        draw_center.y += math.sin(now * 1.8 + tier * 0.7) * 2.2
        rect = orb.get_rect(center=(round(draw_center.x), round(draw_center.y)))
        target.blit(orb, rect)

    def _build_background(self) -> pygame.Surface:
        """Create the large static nebula background once."""
        surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        for y in range(SCREEN_HEIGHT):
            # Draw a vertical gradient one scan line at a time.
            # This is slower than a single fill, but it only happens once at startup.
            amount = y / max(1, SCREEN_HEIGHT - 1)
            color = lerp_color(BG_TOP, BG_BOTTOM, amount)
            pygame.draw.line(surface, color, (0, y), (SCREEN_WIDTH, y))

        cloud = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        nebulae = [
            ((150, 170), 210, (72, 120, 255, 18)),
            ((320, 1040), 260, (255, 108, 195, 16)),
            ((860, 320), 220, (102, 225, 255, 18)),
            ((760, 980), 320, (255, 190, 120, 12)),
        ]
        for center, radius, color in nebulae:
            # Several translucent circles layered together make a soft nebula blob.
            for ring in range(5, 0, -1):
                alpha = max(0, color[3] - ring * 2)
                draw_radius = radius - ring * 18
                pygame.draw.circle(cloud, (*color[:3], alpha), center, draw_radius)

        # Add a few distant decorative planets so the world feels bigger than
        # the single puzzle container on screen.
        decorative_worlds = [
            ((160, 54), 138, (36, 52, 92, 90), (74, 96, 156, 58)),
            ((988, 165), 168, (20, 42, 76, 82), (52, 94, 140, 46)),
            ((118, 1168), 210, (24, 30, 66, 70), (90, 68, 128, 34)),
            ((904, 1090), 128, (18, 28, 60, 66), (66, 90, 168, 30)),
        ]
        for center, radius, fill, rim in decorative_worlds:
            pygame.draw.circle(cloud, fill, center, radius)
            pygame.draw.circle(cloud, rim, center, radius, width=5)
            highlight_center = (center[0] - radius * 0.26, center[1] - radius * 0.34)
            pygame.draw.circle(cloud, (255, 255, 255, 18), highlight_center, int(radius * 0.44))
        surface.blit(cloud, (0, 0))
        return surface

    def _build_stars(self) -> list[tuple[float, float, int, float, float, float]]:
        """Create random-but-repeatable star positions and animation seeds."""
        # A fixed random seed means the background looks consistent between runs.
        rng = random.Random(37)
        stars: list[tuple[float, float, int, float, float, float]] = []
        for _ in range(BACKGROUND_STAR_COUNT):
            stars.append(
                (
                    rng.uniform(0, SCREEN_WIDTH),
                    rng.uniform(0, SCREEN_HEIGHT),
                    rng.choice((1, 1, 1, 2, 2, 3)),
                    rng.uniform(0.8, 2.2),
                    rng.uniform(0.0, math.tau),
                    rng.uniform(0.3, 1.0),
                )
            )
        return stars

    def _build_sparkles(self) -> list[tuple[float, float, int, float, float, int]]:
        """Create a small set of larger shimmer points for extra atmosphere."""
        rng = random.Random(113)
        sparkles: list[tuple[float, float, int, float, float, int]] = []
        for _ in range(22):
            sparkles.append(
                (
                    rng.uniform(40, SCREEN_WIDTH - 40),
                    rng.uniform(30, SCREEN_HEIGHT - 30),
                    rng.choice((2, 3, 4)),
                    rng.uniform(0.7, 1.4),
                    rng.uniform(0.0, math.tau),
                    rng.randint(0, 28),
                )
            )
        return sparkles

    def _build_vignette(self) -> pygame.Surface:
        """Create a subtle dark edge overlay that helps focus the composition."""
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        center = pygame.Vector2(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)
        max_distance = center.length()
        for y in range(SCREEN_HEIGHT):
            for x in range(0, SCREEN_WIDTH, 4):
                # We step by 4 pixels horizontally instead of every single pixel.
                # That keeps startup cost reasonable while still looking smooth.
                distance = (pygame.Vector2(x, y) - center).length()
                amount = max(0.0, min(1.0, distance / max_distance))
                alpha = int((amount ** 2.4) * 74)
                if alpha <= 0:
                    continue
                pygame.draw.rect(overlay, (0, 0, 0, alpha), (x, y, 4, 1))
        return overlay

    def _build_body_surface(self, tier: int) -> pygame.Surface:
        """Draw the full orb artwork for one tier onto a transparent surface."""
        info = TIERS[tier]
        radius = info.radius

        # Add padding so glow/rays can extend beyond the main circle without clipping.
        size = radius * 2 + 58
        center = pygame.Vector2(size / 2, size / 2)
        surface = pygame.Surface((size, size), pygame.SRCALPHA)

        # Outer glow makes higher-tier bodies feel more magical and valuable.
        glow_alpha = 28 if tier >= 7 else 18
        for ring in range(5, 0, -1):
            pygame.draw.circle(
                surface,
                (*shade(info.color, 1.06), glow_alpha * ring),
                center,
                radius + ring * 5,
            )

        if info.icon in {"flare", "sun", "nova", "crown"}:
            # Star-like tiers get extra rays around the orb.
            ray_color = (*shade(info.color, 1.15), 85)
            ray_count = 8 + tier
            for index in range(ray_count):
                angle = (math.tau / ray_count) * index
                inner = center + pygame.Vector2(math.cos(angle), math.sin(angle)) * (radius * 0.92)
                outer = center + pygame.Vector2(math.cos(angle), math.sin(angle)) * (radius + 10 + tier * 1.2)
                pygame.draw.line(surface, ray_color, inner, outer, max(2, tier // 2))

        # Draw the main sphere using a base fill, highlight, and outline.
        # Even though the art is simple, these layered circles help it read like
        # a shaded object instead of a flat disk.
        shadow_center = center + pygame.Vector2(radius * 0.08, radius * 0.12)
        pygame.draw.circle(surface, shade(info.accent, 0.62), shadow_center, radius + 1)
        pygame.draw.circle(surface, info.color, center, radius)

        # Extra shaded bands create stronger depth so the bodies feel more glossy.
        for band in range(4):
            band_radius = int(radius * (1.0 - band * 0.11))
            band_center = center - pygame.Vector2(radius * (0.08 + band * 0.05), radius * (0.10 + band * 0.05))
            band_color = (*shade(info.color, 1.04 + band * 0.035), max(18, 72 - band * 13))
            pygame.draw.circle(surface, band_color, band_center, band_radius)

        # A lower shadow band helps the orb read as round rather than flat.
        lower_shadow = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.ellipse(
            lower_shadow,
            (*shade(info.accent, 0.62), 84),
            pygame.Rect(center.x - radius * 0.88, center.y + radius * 0.15, radius * 1.76, radius * 0.9),
        )
        surface.blit(lower_shadow, (0, 0))

        # Large top highlight plus a smaller specular dot give the "toy-like"
        # shine typical of charming merge-game art.
        pygame.draw.circle(surface, shade(info.color, 1.11), center - pygame.Vector2(radius * 0.25, radius * 0.30), int(radius * 0.68))
        pygame.draw.circle(surface, (*SOFT_WHITE, 76), center - pygame.Vector2(radius * 0.40, radius * 0.44), int(radius * 0.35))
        pygame.draw.circle(surface, (*WHITE, 118), center - pygame.Vector2(radius * 0.24, radius * 0.33), max(3, int(radius * 0.09)))
        pygame.draw.circle(surface, shade(info.accent, 0.82), center, radius, width=3)

        # A thin rim light around the upper-left edge helps separate the body
        # from dark backgrounds and neighboring planets.
        rim_rect = pygame.Rect(0, 0, radius * 2 + 2, radius * 2 + 2)
        rim_rect.center = (center.x, center.y)
        pygame.draw.arc(surface, (*WHITE, 160), rim_rect, math.pi * 0.95, math.pi * 1.62, 3)

        self._decorate_body(surface, center, radius, tier)
        return surface

    def _decorate_body(
        self,
        surface: pygame.Surface,
        center: pygame.Vector2,
        radius: int,
        tier: int,
    ) -> None:
        """Add tier-specific visual details on top of the basic sphere."""
        info = TIERS[tier]
        accent = shade(info.accent, 1.0)
        dark = shade(info.accent, 0.78)

        if info.icon == "dust":
            # Tiny specks communicate that the body is still just space dust.
            rng = random.Random(200 + tier)
            for _ in range(7):
                angle = rng.uniform(0.0, math.tau)
                distance = rng.uniform(radius * 0.25, radius * 0.8)
                point = center + pygame.Vector2(math.cos(angle), math.sin(angle)) * distance
                pygame.draw.circle(surface, (*shade(info.color, 0.9), 170), point, rng.randint(2, 4))
        elif info.icon in {"crater", "moon"}:
            # Rocky tiers get simple crater shapes.
            offsets = [(-0.2, -0.12), (0.24, 0.16), (-0.3, 0.24)]
            for ox, oy in offsets:
                crater_center = center + pygame.Vector2(radius * ox, radius * oy)
                pygame.draw.circle(surface, dark, crater_center, max(4, int(radius * 0.16)))
                pygame.draw.circle(surface, shade(info.color, 0.92), crater_center + pygame.Vector2(-2, -2), max(2, int(radius * 0.08)))
        elif info.icon == "ocean":
            # Ocean worlds use repeating arc bands as stylized waves.
            for row in range(3):
                wave_rect = pygame.Rect(0, 0, int(radius * 1.1), int(radius * 0.5))
                wave_rect.center = (center.x, center.y + radius * (-0.18 + row * 0.22))
                pygame.draw.arc(surface, accent, wave_rect, 0.35, math.pi - 0.35, 3)
            pygame.draw.circle(surface, (*WHITE, 36), center - pygame.Vector2(radius * 0.08, radius * 0.02), int(radius * 0.78), width=2)
        elif info.icon == "continent":
            # Earth-like worlds get simple landmass blobs.
            blobs = [(-0.24, -0.05, 0.24), (0.18, 0.16, 0.2), (-0.02, 0.28, 0.15)]
            for ox, oy, scale in blobs:
                pygame.draw.circle(surface, accent, center + pygame.Vector2(radius * ox, radius * oy), int(radius * scale))
            pygame.draw.arc(surface, (*WHITE, 32), pygame.Rect(center.x - radius * 0.76, center.y - radius * 0.54, radius * 1.2, radius * 0.7), 0.2, 2.6, 2)
        elif info.icon == "ring":
            # Gas giants use ellipses to fake a ring system.
            ring_rect = pygame.Rect(0, 0, int(radius * 2.2), int(radius * 0.72))
            ring_rect.center = center
            pygame.draw.ellipse(surface, (*accent, 155), ring_rect, 4)
            inner_rect = ring_rect.inflate(-16, -10)
            pygame.draw.ellipse(surface, (*shade(info.color, 0.65), 145), inner_rect, 3)
            pygame.draw.ellipse(surface, (*WHITE, 28), ring_rect.inflate(14, 4), 2)
        elif info.icon == "storm":
            # Storm planets use several spiral-like arcs.
            for arc_index in range(3):
                rect = pygame.Rect(0, 0, int(radius * (1.15 - arc_index * 0.16)), int(radius * (0.8 - arc_index * 0.1)))
                rect.center = (center.x, center.y + arc_index * 6)
                pygame.draw.arc(surface, accent, rect, 0.1, math.pi + 0.45, 3)
            eye_storm = center + pygame.Vector2(radius * 0.12, radius * 0.16)
            pygame.draw.circle(surface, (*WHITE, 42), eye_storm, max(4, int(radius * 0.09)))
        elif info.icon == "flare":
            # Dwarf stars get glowing flare spots around the edge.
            for flare in range(6):
                angle = math.tau * flare / 6.0
                outer = center + pygame.Vector2(math.cos(angle), math.sin(angle)) * (radius + 7)
                pygame.draw.circle(surface, (*accent, 110), outer, max(3, radius // 9))
        elif info.icon == "sun":
            # Suns use concentric glowing rings.
            for band in range(3):
                pygame.draw.circle(surface, (*accent, 70 - band * 14), center, radius + 5 + band * 8, width=4)
            pygame.draw.circle(surface, (*WHITE, 40), center, int(radius * 0.82), width=2)
        elif info.icon == "nova":
            # Nova tiers get a diamond burst shape.
            diamond = [
                center + pygame.Vector2(0, -radius - 10),
                center + pygame.Vector2(radius + 10, 0),
                center + pygame.Vector2(0, radius + 10),
                center + pygame.Vector2(-radius - 10, 0),
            ]
            pygame.draw.polygon(surface, (*accent, 72), diamond, width=3)
        elif info.icon == "crown":
            # The top-tier crown uses alternating long/short points.
            points = []
            for index in range(10):
                angle = -math.pi / 2 + index * (math.tau / 10.0)
                dist = radius + 12 if index % 2 == 0 else radius + 2
                points.append(center + pygame.Vector2(math.cos(angle), math.sin(angle)) * dist)
            pygame.draw.polygon(surface, (*accent, 76), points, width=3)
            pygame.draw.circle(surface, (*WHITE, 34), center, int(radius * 0.88), width=2)
