"""Shared constants and small helper utilities.

Keeping tuning values in one file makes the rest of the project easier to read:
- gameplay files can import a named value instead of hard-coding numbers,
- balancing changes are faster because most knobs live in one place,
- data such as planet tiers stays separate from simulation logic.

Beginner note:
- If you want to tweak the game's feel, this is usually the first file to open.
- Most numbers here are "design knobs" rather than mandatory math constants.
- Changing them lets you rebalance the game without rewriting the gameplay code.
"""

from __future__ import annotations

import colorsys
import os
from dataclasses import dataclass
from pathlib import Path

# Window and render-space size.
# The game internally renders to this portrait canvas even when the desktop
# window itself is resized smaller or larger.
#
# Why use a fixed internal size?
# - UI placement becomes much easier.
# - Art and HUD coordinates stay stable.
# - The real window can scale up or down without changing gameplay math.
WINDOW_TITLE = "Orbital Orchard"
SCREEN_WIDTH = 1024
SCREEN_HEIGHT = 1280
FPS = 60

# Fixed layout positions inside the internal 1024x1280 canvas.
# These numbers decide where the bubble and launcher appear in the scene.
PLAYFIELD_CENTER = (392, 780)
CONTAINER_RADIUS = 350
SPAWN_Y = 452
FAIL_LINE_Y = 492

# Sidebar layout values used by the HUD renderer.
# The sidebar sits to the right of the bubble and holds score/queue/control info.
SIDEBAR_X = 768
SIDEBAR_WIDTH = 232

# Physics tuning.
# These values control how heavy, floaty, bouncy, and stable the game feels.
GRAVITY = 1380.0
CENTER_PULL = 92.0
ORBITAL_PULL = 48.0
AIR_DRAG = 0.16
MAX_SPEED = 1700.0
PHYSICS_MAX_SUBSTEP = 1.0 / 120.0

# Collision response tuning.
# `RESTITUTION` controls bounce strength.
# `FRICTION` controls how much side-sliding is reduced after collisions.
# Wall settings are separate because hitting the bubble wall should feel a little
# different from hitting another body.
RESTITUTION = 0.12
FRICTION = 0.035
WALL_BOUNCE = 0.22
WALL_FRICTION = 0.28
SOLVER_ITERATIONS = 8
# How much of a detected overlap the solver corrects per iteration. Full
# correction (1.0) can feel too sharp with a simple solver; slightly under
# lets stacks settle softly instead of popping apart.
POSITION_CORRECTION_SOFTNESS = 0.92

# Player input and launcher tuning.
# These values shape how aiming feels.
# - Horizontal movement speed affects how quickly the launcher slides left/right.
# - Angle speed affects keyboard angle control.
# - Wheel step gives quick precise angle nudges.
# - Max angle prevents impossible backwards launches.
# - Launch speed sets the body's starting push before gravity takes over.
DROP_COOLDOWN = 0.45
KEYBOARD_AIM_SPEED = 460.0
ANGLE_AIM_SPEED = 115.0
MOUSE_WHEEL_ANGLE_STEP = 4.0
MAX_LAUNCH_ANGLE = 60.0
LAUNCH_SPEED = 520.0

# Merge rules.
# `MERGE_ARM_TIME` stops fresh bodies from instantly re-merging the same frame.
# `POST_MERGE_LOCK` gives newly created merged bodies a short cooldown too.
# `MERGE_CONTACT_SLOP` slightly widens the allowed merge distance so collisions
# feel more forgiving than strict perfect circle contact.
MERGE_ARM_TIME = 0.18
POST_MERGE_LOCK = 0.08
MERGE_CONTACT_SLOP = 4.0
# The merged body keeps this fraction of the two parents' combined velocity,
# so chain merges stay exciting but readable instead of ricocheting.
MERGE_VELOCITY_DAMP = 0.42

# Combo scoring: merges that happen within this many seconds of the previous
# merge build an escalating score multiplier (see `_apply_merges` in game.py).
COMBO_WINDOW = 1.1

# Loss-condition tuning.
# The player does not lose the instant something crosses the danger line.
# Instead:
# - a warning starts,
# - `FAIL_GRACE` counts upward while danger continues,
# - `FAIL_DECAY` drains that timer when the player recovers,
# - `FAIL_AGE_GATE` ignores very new bodies for fairness.
# `STRESS_PREVIEW_RANGE` controls how far below the fail line the HUD stress
# meter starts reacting to the stack height in real time.
FAIL_GRACE = 2.4
FAIL_DECAY = 1.6
FAIL_AGE_GATE = 0.75
STRESS_PREVIEW_RANGE = 280.0

# The HUD stress meter is split into two phases that add up to 1.0:
# stack height drives the first share, and once the fail line is actually
# crossed, the countdown timer drives the remaining share.
STRESS_PREVIEW_SHARE = 0.78
STRESS_TIMER_SHARE = 0.22

# Miscellaneous gameplay limits.
# `IMPACT_EVENT_SPEED` controls how hard a collision must be before it creates
# particles or other feedback.
# `MAX_BODIES` is a safety limit for performance/readability.
# `SPAWN_WEIGHTS` control how often the first few tiers appear in the queue.
IMPACT_EVENT_SPEED = 140.0
MAX_BODIES = 80
SPAWN_WEIGHTS = [38, 28, 18, 11, 5]

# Cosmetic background density.
BACKGROUND_STAR_COUNT = 150

# Save data must live in a stable per-user folder, never beside the source.
# A PyInstaller --onefile build unpacks into a temporary folder that Windows
# deletes when the .exe closes, so a save written there is lost every session.
# %APPDATA% persists across runs and resolves the same whether the game is
# launched from source or as a frozen .exe.
def _user_save_dir() -> Path:
    """Return the per-user folder that holds this game's save data."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "Orbital Orchard"


SAVE_DATA_DIR = _user_save_dir()
SAVE_DATA_PATH = SAVE_DATA_DIR / "save_data.json"

# Commonly reused colors.
# These are plain RGB tuples: (red, green, blue), each 0-255.
BG_TOP = (8, 10, 26)
BG_BOTTOM = (12, 26, 54)
WHITE = (244, 246, 255)
SOFT_WHITE = (215, 225, 255)
INK = (24, 27, 42)
GLOW = (110, 185, 255)
WARNING = (255, 112, 112)
SUCCESS = (145, 255, 205)


@dataclass(frozen=True, slots=True)
class TierInfo:
    """All display and scoring data for one merge tier."""

    # `frozen=True` above means once a TierInfo is created, its values should not
    # be changed accidentally later. That makes tier data safer to share.
    #
    # Field meanings:
    # - `name`: text shown in the HUD and milestone popups,
    # - `radius`: circle size used by both rendering and physics,
    # - `color`: main body color,
    # - `accent`: darker/secondary color for outlines and facial features,
    # - `score`: points awarded when this tier is created,
    # - `icon`: art-generator hint such as "ring" or "sun",
    # - `mood`: default face style used by the expression drawer.
    name: str
    radius: int
    color: tuple[int, int, int]
    accent: tuple[int, int, int]
    score: int
    icon: str
    mood: str


def clamp(value: float, low: float, high: float) -> float:
    """Keep `value` inside the inclusive range [`low`, `high`]."""
    # Example:
    # - clamp(5, 0, 10) -> 5
    # - clamp(-3, 0, 10) -> 0
    # - clamp(25, 0, 10) -> 10
    return max(low, min(high, value))


def hsv_rgb(hue: float, saturation: float, value: float) -> tuple[int, int, int]:
    """Convert a color from HSV percentages into 0-255 RGB integers."""
    # HSV is often easier than RGB when you want to pick colorful palettes by hand.
    red, green, blue = colorsys.hsv_to_rgb(hue / 360.0, saturation / 100.0, value / 100.0)
    return int(red * 255), int(green * 255), int(blue * 255)


def shade(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """Multiply a color by a brightness factor and clamp the result safely."""
    # Example:
    # - factor > 1.0 makes the color brighter,
    # - factor < 1.0 makes the color darker.
    return (
        int(clamp(color[0] * factor, 0, 255)),
        int(clamp(color[1] * factor, 0, 255)),
        int(clamp(color[2] * factor, 0, 255)),
    )


def lerp_color(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    """Blend smoothly between two RGB colors."""
    # `amount = 0.0` returns `start`,
    # `amount = 1.0` returns `end`,
    # values in between interpolate linearly.
    return (
        int(start[0] + (end[0] - start[0]) * amount),
        int(start[1] + (end[1] - start[1]) * amount),
        int(start[2] + (end[2] - start[2]) * amount),
    )


def danger_gradient(ratio: float) -> tuple[int, int, int]:
    """Map a 0..1 danger level to a calm-to-alarming colour.

    The colour walks through soft blue -> yellow -> orange -> red so the player
    can read how close they are to losing at a glance, instead of the colour
    jumping straight from neutral to red.
    """
    ratio = clamp(ratio, 0.0, 1.0)
    calm = (150, 200, 255)      # relaxed blue-white
    caution = (255, 214, 90)    # yellow
    alarm = (255, 150, 70)      # orange
    danger = (255, 86, 86)      # red
    if ratio < 0.5:
        # First half of the range: drift from the calm colour up to yellow.
        return lerp_color(calm, caution, ratio / 0.5)
    if ratio < 0.8:
        # Middle band: yellow blending into orange.
        return lerp_color(caution, alarm, (ratio - 0.5) / 0.3)
    # Final stretch: orange into full red as the player nears game over.
    return lerp_color(alarm, danger, (ratio - 0.8) / 0.2)


def build_tiers() -> list[TierInfo]:
    """Create the full ordered evolution chain used by the game.

    Each parallel list below lines up by index:
    - `names[0]`, `radii[0]`, `scores[0]`, `icons[0]`, and `moods[0]`
      all describe the first tier,
    - `names[1]`, `radii[1]`, and so on describe the next tier.
    """
    names = [
        "Spark Dust",
        "Comet Pebble",
        "Moonlet",
        "Tide Orb",
        "Verdant World",
        "Ring Giant",
        "Storm Titan",
        "Dwarf Star",
        "Sunforge",
        "Nova Bloom",
        "Quasar Crown",
    ]
    # Radius grows steadily so each successful merge is visually obvious.
    radii = [18, 24, 31, 39, 49, 60, 72, 86, 101, 118, 136]
    # Score jumps faster than size to make higher merges much more rewarding.
    scores = [1, 3, 6, 12, 24, 48, 96, 200, 420, 900, 2000]
    # `icon` tells the art generator what kind of decoration to draw.
    icons = [
        "dust",
        "crater",
        "moon",
        "ocean",
        "continent",
        "ring",
        "storm",
        "flare",
        "sun",
        "nova",
        "crown",
    ]
    # `mood` tells the face drawer what expression style to use.
    moods = [
        "cheery",
        "cheery",
        "curious",
        "calm",
        "smile",
        "wry",
        "sleepy",
        "proud",
        "bright",
        "spark",
        "cosmic",
    ]
    # Palette is stored as HSV-style triples so it is easier to tune color identity.
    palette = [
        (28, 72, 100),
        (42, 76, 100),
        (58, 16, 90),
        (193, 72, 98),
        (120, 54, 95),
        (286, 46, 100),
        (336, 62, 100),
        (14, 74, 100),
        (49, 82, 100),
        (326, 64, 100),
        (215, 56, 100),
    ]

    tiers: list[TierInfo] = []
    for idx, name in enumerate(names):
        # Pull one palette entry for this tier and build both its main body color
        # and a slightly shifted accent color for outlines/facial features.
        hue, saturation, value = palette[idx]
        color = hsv_rgb(hue, saturation, value)
        accent = hsv_rgb((hue + 18) % 360, min(100, saturation + 6), max(22, value - 22))

        # Package every property into an immutable data object.
        # Because all lists share the same index, `idx` selects the matching
        # name/radius/score/icon/mood for this tier.
        tiers.append(
            TierInfo(
                name=name,
                radius=radii[idx],
                color=color,
                accent=accent,
                score=scores[idx],
                icon=icons[idx],
                mood=moods[idx],
            )
        )
    return tiers


# Build the tier list once at import time so every other file can reuse it.
TIERS = build_tiers()
