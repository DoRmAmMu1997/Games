"""Procedural art, fonts, background generation, and the sound bank.

The goal of this file is to keep the project self-contained:
- no external images are required,
- no external sound files are required,
- the rest of the game can request ready-to-use surfaces by tier.

The sounds themselves are synthesised by `audio.py` from the recipes in
`settings.py`; this file only builds the bank the game plays them from.

Beginner note:
- "Procedural" means the game draws or generates assets in code at runtime.
- That is why you will see lots of circles, arcs, gradients, and math here
  instead of loading `.png` and `.wav` files from disk.
"""

from __future__ import annotations

import math
import random

import pygame

from audio import SoundBank
from settings import (
    BACKGROUND_STAR_COUNT,
    BG_BOTTOM,
    BG_TOP,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SFX_COOLDOWNS,
    SFX_RECIPES,
    SOFT_WHITE,
    TIERS,
    WHITE,
    lerp_color,
    shade,
)


def _blend_onto(surface: pygame.Surface, draw) -> None:
    """Call `draw(layer)` on a fresh transparent layer, then blend it onto `surface`.

    Beginner note:
    - `pygame.draw` on an alpha surface *replaces* pixels, alpha included. A
      translucent highlight drawn straight onto an opaque orb therefore makes
      that patch of the orb see-through, like punching a hole in it.
    - Drawing on a separate layer and blitting it blends the highlight on top
      instead, leaving the orb underneath opaque.
    """
    layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    draw(layer)
    surface.blit(layer, (0, 0))


class AssetLibrary:
    """Caches procedural surfaces and exposes shared fonts and sounds.

    The game creates one `AssetLibrary` after pygame starts and passes it to
    everything that draws. Expensive images (the background gradient, the
    vignette, each tier's orb) are drawn once and reused every frame.

    Attributes:
        body_cache: Tier index to finished orb sprite, filled lazily by
            `get_body_surface()`.
        background: Full-screen gradient, nebulae and distant planets.
        stars, sparkles: Fixed-seed tuples describing the twinkling points
            that `draw_background()` animates each frame.
        vignette: Full-screen overlay that darkens the corners.
        sounds: The game's `audio.SoundBank`, built from `SFX_RECIPES`.
        title_font ... tiny_font: pygame's built-in font at several sizes.

    Beginner note:
    - A pygame `Surface` is an off-screen image you can draw on. Drawing a
      complex picture once onto a surface and then `blit`-ing (copying) it
      each frame is far cheaper than redrawing all its shapes every frame.
    - This class needs `pygame.init()` (for fonts and the mixer) to have run
      before it is constructed.
    """

    def __init__(self) -> None:
        """Pre-build the background layers, sounds and fonts; orbs are built on demand."""
        # `body_cache` avoids redrawing every tier from scratch each frame.
        # Caching is important here because these body surfaces contain several
        # layered drawing operations and would be wasteful to rebuild constantly.
        self.body_cache: dict[int, pygame.Surface] = {}

        # Build heavyweight assets once up front.
        self.background = self._build_background()
        self.stars = self._build_stars()
        self.sparkles = self._build_sparkles()
        self.vignette = self._build_vignette()
        self.sounds = SoundBank(SFX_RECIPES, SFX_COOLDOWNS)

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
        """Draw the static background plus twinkling moving stars.

        Layers, back to front: the pre-built `background`, the small stars,
        the larger sparkles, then the `vignette`. Stars and sparkles twinkle
        by a sine wave of `now`, each with its own speed and phase.

        Args:
            target: Surface to draw on (normally the whole screen).
            now: Animation clock in seconds.
            drift: Optional offset that follows the mouse (the game passes
                a small fraction of the cursor's distance from the playfield
                centre). Stars shift by it scaled by their `depth`, which gives
                a cheap parallax; positions wrap with `%` so stars that leave
                one edge come back on the other.
        """
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
        """Draw a floating preview version of a tier icon.

        Used for the launcher orb and the sidebar's current/next previews. The cached
        sprite is copied before changing its alpha so the shared cache entry is
        never modified.

        Args:
            target: Surface to draw on.
            tier: Which tier's sprite to show.
            center: Where the sprite's centre goes, before the idle bob.
            now: Animation clock; drives a small vertical bob.
            scale: Size multiplier (1.0 is the in-game size).
            alpha: Opacity from 0 (invisible) to 255 (solid).
        """
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
        """Create the large static nebula background once.

        The result is an opaque full-screen surface made of three layers:
        a top-to-bottom colour gradient (`BG_TOP` to `BG_BOTTOM`), a few
        soft nebula blobs, and four large dim "distant planets". The blobs
        and planets are drawn on a transparent `cloud` layer first and then
        blended onto the gradient in one blit.

        Beginner note:
        - `lerp_color(a, b, t)` mixes two colours: `t=0` gives `a`, `t=1`
          gives `b`, values between give a blend. Doing that per row makes
          a smooth gradient.
        """
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
        for nebula_center, nebula_radius, nebula_color in nebulae:
            # Several translucent circles layered together make a soft nebula blob.
            for ring in range(5, 0, -1):
                alpha = max(0, nebula_color[3] - ring * 2)
                draw_radius = nebula_radius - ring * 18
                pygame.draw.circle(cloud, (*nebula_color[:3], alpha), nebula_center, draw_radius)

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
        """Draw the full orb artwork for one tier onto a transparent surface.

        The sprite is `2 * radius + 58` pixels square so glows, rays and
        decorations can poke past the sphere without being clipped. Layers are
        drawn back to front:

        1. a soft outer glow of stacked circles;
        2. light rays for the star-like icons (flare, sun, nova, crown);
        3. a dark offset "shadow" disc and the main coloured disc;
        4. lighter shading bands toward the upper-left (the light source);
        5. a darker lower band so the orb reads as round;
        6. highlight, soft shine and a small specular dot, then the outline;
        7. a thin rim-light arc on the upper-left edge;
        8. the tier's own decoration from `_decorate_body()`.

        Translucent layers go through `_blend_onto()` so they blend on top
        instead of punching see-through holes in the opaque orb.

        Args:
            tier: Index into `TIERS`.

        Returns:
            A new per-pixel-alpha surface; `get_body_surface()` caches it.
        """
        info = TIERS[tier]
        radius = info.radius

        # Add padding so glow/rays can extend beyond the main circle without clipping.
        size = radius * 2 + 58
        center = pygame.Vector2(size / 2, size / 2)
        surface = pygame.Surface((size, size), pygame.SRCALPHA)

        # Outer glow makes higher-tier bodies feel more magical and valuable.
        # These circles are drawn straight onto the surface, largest first, so
        # each smaller circle *replaces* the pixels of the larger one under it
        # and every 5 px ring keeps its own alpha. The alpha therefore grows as
        # the rings shrink: the glow is strongest next to the orb and fades
        # out to a faint outer edge.
        glow_alpha = 28 if tier >= 7 else 18
        for ring in range(5, 0, -1):
            pygame.draw.circle(
                surface,
                (*shade(info.color, 1.06), glow_alpha * (6 - ring)),
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
            _blend_onto(
                surface,
                lambda layer, c=band_color, p=band_center, r=band_radius: pygame.draw.circle(layer, c, p, r),
            )

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
        highlight_center = center - pygame.Vector2(radius * 0.25, radius * 0.30)
        pygame.draw.circle(surface, shade(info.color, 1.11), highlight_center, int(radius * 0.68))
        soft_center = center - pygame.Vector2(radius * 0.40, radius * 0.44)
        _blend_onto(
            surface,
            lambda layer: pygame.draw.circle(layer, (*SOFT_WHITE, 76), soft_center, int(radius * 0.35)),
        )
        specular_center = center - pygame.Vector2(radius * 0.24, radius * 0.33)
        _blend_onto(
            surface,
            lambda layer: pygame.draw.circle(layer, (*WHITE, 118), specular_center, max(3, int(radius * 0.09))),
        )
        pygame.draw.circle(surface, shade(info.accent, 0.82), center, radius, width=3)

        # A thin rim light around the upper-left edge helps separate the body
        # from dark backgrounds and neighboring planets.
        rim_rect = pygame.Rect(0, 0, radius * 2 + 2, radius * 2 + 2)
        rim_rect.center = (center.x, center.y)
        _blend_onto(
            surface,
            lambda layer: pygame.draw.arc(layer, (*WHITE, 160), rim_rect, math.pi * 0.95, math.pi * 1.62, 3),
        )

        # Tier decorations include translucent details too, so they are drawn
        # on their own layer and blended on top as one piece.
        _blend_onto(surface, lambda layer: self._decorate_body(layer, center, radius, tier))
        return surface

    def _decorate_body(
        self,
        surface: pygame.Surface,
        center: pygame.Vector2,
        radius: int,
        tier: int,
    ) -> None:
        """Add tier-specific visual details on top of the basic sphere.

        `TIERS[tier].icon` picks one recipe: specks for dust, craters for
        rocky tiers, wave arcs for oceans, landmass blobs for continents, an
        elliptical ring for gas giants, spiral arcs for storms, flare spots,
        concentric sun rings, a nova diamond, or a crown star. Any icon not
        listed gets no decoration.

        Args:
            surface: Transparent layer to draw on (blended onto the orb later).
            center: Centre of the orb on that layer.
            radius: Orb radius in pixels; every detail is sized from it.
            tier: Index into `TIERS`. Random details use a fixed per-tier seed
                so a tier always looks the same.
        """
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
                inner_center = crater_center + pygame.Vector2(-2, -2)
                pygame.draw.circle(surface, shade(info.color, 0.92), inner_center, max(2, int(radius * 0.08)))
        elif info.icon == "ocean":
            # Ocean worlds use repeating arc bands as stylized waves.
            for row in range(3):
                wave_rect = pygame.Rect(0, 0, int(radius * 1.1), int(radius * 0.5))
                wave_rect.center = (center.x, center.y + radius * (-0.18 + row * 0.22))
                pygame.draw.arc(surface, accent, wave_rect, 0.35, math.pi - 0.35, 3)
            glow_center = center - pygame.Vector2(radius * 0.08, radius * 0.02)
            pygame.draw.circle(surface, (*WHITE, 36), glow_center, int(radius * 0.78), width=2)
        elif info.icon == "continent":
            # Earth-like worlds get simple landmass blobs.
            blobs = [(-0.24, -0.05, 0.24), (0.18, 0.16, 0.2), (-0.02, 0.28, 0.15)]
            for ox, oy, scale in blobs:
                blob_center = center + pygame.Vector2(radius * ox, radius * oy)
                pygame.draw.circle(surface, accent, blob_center, int(radius * scale))
            cloud_rect = pygame.Rect(
                center.x - radius * 0.76, center.y - radius * 0.54, radius * 1.2, radius * 0.7
            )
            pygame.draw.arc(surface, (*WHITE, 32), cloud_rect, 0.2, 2.6, 2)
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
