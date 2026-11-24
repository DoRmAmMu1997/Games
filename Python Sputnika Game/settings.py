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

from audio import Note, midi

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
# Extra pixels added to the broad-phase margin (see `_broad_phase_pairs` in
# physics.py). The margin already covers the largest body and the furthest a
# body can move in one physics slice; this small slop guards against solver
# corrections nudging a pair into contact that the grid skipped.
BROAD_PHASE_SLOP = 4.0

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

# Launcher overlay drawing.
# Each preview dot gets a soft glow `PREVIEW_GLOW_EXTRA` pixels wider than the
# dot itself. Translucent overlays are drawn on small surfaces sized to their
# contents; `OVERLAY_PADDING` adds a few spare pixels around them so line caps
# and antialiased edges are never clipped.
PREVIEW_GLOW_EXTRA = 4
OVERLAY_PADDING = 4

# Merge rules.
# `MERGE_ARM_TIME` stops fresh bodies (newly launched or newly merged) from
# instantly re-merging; every body is created with `created_at = now`, so this
# one age check covers merged results too.
# `MERGE_CONTACT_SLOP` slightly widens the allowed merge distance so collisions
# feel more forgiving than strict perfect circle contact.
MERGE_ARM_TIME = 0.18
MERGE_CONTACT_SLOP = 4.0
# The merged body keeps this fraction of the two parents' combined velocity,
# so chain merges stay exciting but readable instead of ricocheting.
MERGE_VELOCITY_DAMP = 0.42

# Combo scoring: merges that happen within this many seconds of the previous
# merge build an escalating score multiplier (see `combo_multiplier` in rules.py).
COMBO_WINDOW = 1.1
# Each extra link in a combo chain adds this much to the 1.0x base multiplier,
# so a 2-chain pays 1.5x and a 3-chain pays 2.0x.
COMBO_STEP = 0.5
# Long chains stop growing here so a lucky cascade cannot dwarf honest play.
COMBO_MAX_MULTIPLIER = 3.0

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

# The danger beep repeats faster as the fail timer fills, so danger is heard
# as well as seen. A fresh danger spell waits `WARNING_BEEP_MAX_INTERVAL`
# seconds between beeps; each unit of fail ratio shortens that gap by
# `WARNING_BEEP_INTERVAL_SPAN`, but never below `WARNING_BEEP_MIN_INTERVAL`
# (a faster beep would blur into one continuous tone).
WARNING_BEEP_MAX_INTERVAL = 0.66
WARNING_BEEP_INTERVAL_SPAN = 0.46
WARNING_BEEP_MIN_INTERVAL = 0.2

# Miscellaneous gameplay limits.
# `IMPACT_EVENT_SPEED` controls how hard a collision must be before it creates
# particles or other feedback.
# `MAX_BODIES` is a safety limit for performance/readability.
# `SPAWN_WEIGHTS` control how often the first few tiers appear in the queue.
IMPACT_EVENT_SPEED = 140.0
MAX_BODIES = 80
SPAWN_WEIGHTS = [38, 28, 18, 11, 5]

# Floating score/combo popups stay fully opaque until only this share of
# their lifetime is left, then fade out. They get a dark outline in
# `POPUP_OUTLINE` so they stay readable over bright orbs.
POPUP_FADE_SHARE = 0.5
POPUP_OUTLINE = (8, 12, 26)
# Popups spawned on top of each other (a merge cascade) stack upward instead
# of overlapping: each is treated as a box this tall (before its scale), and
# popups closer than `POPUP_STACK_WIDTH` sideways share one column.
POPUP_LINE_HEIGHT = 38
POPUP_STACK_WIDTH = 170

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


# ---- Sound ----
# Every sound is a recipe: a list of `Note`s that audio.py renders into
# samples when the game starts (no audio files ship with the game). Pitches
# are written as MIDI note numbers through `midi()`: 69 is A4 (440 Hz), +12 is
# one octave up. The palette lives in A minor pentatonic (A C D E G), which
# has no clashing notes, so overlapping effects always sound consonant.
#
# Beginner note:
# - A "pluck" note below has no sustain: it rises over a few milliseconds and
#   then rings down over `ring` seconds, like a struck bell or a marimba bar.
# - Volumes stay well under 1.0 on purpose: several effects often play at
#   once and their samples add up.
SFX_PLUCK_ATTACK = 0.004  # A struck note reaches full volume this fast (s).
SFX_PLUCK_RELEASE = 0.02  # Tail after a pluck's ring, so it never ends abruptly (s).
# The merge ladder: tier n merges at A3 plus the n-th step of the pentatonic
# scale, so every evolution sounds a little higher than the one before.
MERGE_ROOT_NOTE = 57  # A3.
PENTATONIC_STEPS = (0, 3, 5, 7, 10)


def pluck(pitch: float, start: float, ring: float, volume: float, voice: str = "pluck") -> Note:
    """Return a struck note: a near-instant attack, then a ring down to silence."""
    return Note(
        midi(pitch),
        start,
        SFX_PLUCK_ATTACK + ring,
        voice,
        volume,
        attack=SFX_PLUCK_ATTACK,
        decay=ring,
        sustain=0.0,
        release=SFX_PLUCK_RELEASE,
    )


def ladder_note(step: int) -> int:
    """Return the MIDI note `step` places up the A minor pentatonic ladder."""
    octave, degree = divmod(step, len(PENTATONIC_STEPS))
    return MERGE_ROOT_NOTE + 12 * octave + PENTATONIC_STEPS[degree]


def merge_notes(tier: int) -> list[Note]:
    """Return the merge sound for reaching `tier`: a rising fifth with a shimmer."""
    root = ladder_note(tier)
    return [
        pluck(root, 0.0, 0.16, 0.3),
        pluck(root + 7, 0.055, 0.22, 0.26),
        pluck(root + 12, 0.055, 0.3, 0.1, voice="sine"),
    ]


def big_merge_notes(tier: int) -> list[Note]:
    """Return the big-merge sound for `tier`: a quick minor arpeggio over a soft swell."""
    root = ladder_note(tier)
    notes = [pluck(root + offset, index * 0.05, 0.3, 0.24) for index, offset in enumerate((0, 3, 7, 12))]
    notes.append(Note(midi(root - 12), 0.0, 0.25, "triangle", 0.18, attack=0.06, decay=0.2, sustain=0.5, release=0.3))
    return notes


SFX_RECIPES: dict[str, list[Note]] = {
    # A soft launcher "thup": a sine falling in pitch with a bright tick on top.
    "drop": [
        Note(midi(64), 0.0, 0.08, "sine", 0.32, glide=-1400.0, attack=0.003, decay=0.08, sustain=0.0, release=0.02),
        pluck(76, 0.0, 0.05, 0.1),
    ],
    "merge": merge_notes(1),
    "big_merge": big_merge_notes(len(TIERS) - 3),
    # A short, soft two-note click for every button.
    "button": [pluck(84, 0.0, 0.05, 0.22, voice="sine"), pluck(91, 0.012, 0.04, 0.08, voice="sine")],
    # Game over without a record: a gentle descending A minor phrase over a low pad.
    "game_over": [
        Note(midi(64), 0.0, 0.28, "triangle", 0.26, attack=0.015, decay=0.1, sustain=0.6, release=0.2),
        Note(midi(60), 0.3, 0.28, "triangle", 0.26, attack=0.015, decay=0.1, sustain=0.6, release=0.2),
        Note(midi(57), 0.6, 0.7, "triangle", 0.28, attack=0.015, decay=0.2, sustain=0.6, release=0.5),
        Note(midi(45), 0.6, 0.7, "sine", 0.2, attack=0.2, decay=0.2, sustain=0.8, release=0.5),
        Note(midi(52), 0.6, 0.7, "sine", 0.12, attack=0.3, decay=0.2, sustain=0.8, release=0.5),
    ],
    # A record (new best tier or high score): an ascending A major fanfare
    # that settles into a ringing chord.
    "record": [
        *(pluck(pitch, index * 0.11, 0.35, 0.26) for index, pitch in enumerate((69, 73, 76, 81))),
        Note(midi(81), 0.44, 0.5, "triangle", 0.16, attack=0.05, decay=0.2, sustain=0.6, release=0.45),
        Note(midi(76), 0.44, 0.5, "sine", 0.14, attack=0.05, decay=0.2, sustain=0.6, release=0.45),
        Note(midi(85), 0.44, 0.5, "sine", 0.08, attack=0.05, decay=0.2, sustain=0.6, release=0.45),
    ],
    # The danger beep: a hollow low fourth, short enough to repeat quickly.
    "warning": [
        Note(midi(55), 0.0, 0.08, "square", 0.17, attack=0.006, decay=0.04, sustain=0.6, release=0.04),
        Note(midi(60), 0.0, 0.08, "square", 0.12, attack=0.006, decay=0.04, sustain=0.6, release=0.04),
    ],
}
# The fewest seconds between two plays of the same effect. A cascade can merge
# several pairs in one frame; one merge sound per frame reads better than a
# pile of identical sounds stacked on top of each other.
SFX_COOLDOWNS: dict[str, float] = {
    "merge": 0.03,
    "big_merge": 0.03,
    # Aim ticks and impact thuds can fire every frame; these keep them a
    # gentle texture instead of a buzz.
    "aim_tick": 0.045,
    "impact": 0.07,
    # Mashing launch during the cooldown gets one "not yet" per beat.
    "launch_blocked": 0.25,
}

# The warning beep grows louder as the fail timer fills: it starts at
# `WARNING_VOLUME_MIN` and climbs by up to `WARNING_VOLUME_SPAN` at the brink.
WARNING_VOLUME_MIN = 0.28
WARNING_VOLUME_SPAN = 0.3

# Seconds the danger check must stay in a new state before the player HEARS
# the change (the danger cue and the calm/tense music switch). A body resting
# right on the fail line can jitter across it every frame; without this hold
# the cues would chatter and the music would restart over and over. The red
# label, warning beeps and fail timer still react at once.
DANGER_MOOD_HOLD = 0.6

# The launcher clicks once each time the aim crosses a multiple of this many
# degrees, like the detents on a dial.
AIM_TICK_DEGREES = 5.0
# Impact thuds come in three weights. A collision at or above each speed (in
# pixels per second) uses the next heavier thud; `IMPACT_EVENT_SPEED` is the
# softest hit that makes any sound at all.
IMPACT_SOUND_BANDS = (420.0, 800.0)
# Thud loudness grows with speed from the quietest to the loudest value,
# reaching the top at `IMPACT_LOUDEST_SPEED`.
IMPACT_VOLUME_RANGE = (0.12, 0.4)
IMPACT_LOUDEST_SPEED = 1100.0
# Combo chimes climb with the chain: a chain of n plays variant "combo@n",
# up to this many (longer chains keep the top chime).
COMBO_CHIME_TOP = 6
# How loud each newer event sound plays (0 to 1).
SFX_VOLUMES: dict[str, float] = {
    "button": 0.4,
    # Starting a run is the one button that gets a slightly fuller click.
    "start_run": 0.45,
    "drop": 0.35,
    "merge": 0.36,
    "big_merge": 0.42,
    # Reaching the top tier is the loudest moment in the game; a new
    # lifetime-best tier and the game-over jingles sit just under it.
    "record_top_tier": 0.45,
    "record": 0.42,
    "jingle": 0.42,
    "whoosh": 0.3,
    "launch_blocked": 0.34,
    "aim_tick": 0.22,
    "combo": 0.34,
    "high_score": 0.4,
    "danger_on": 0.34,
    "danger_off": 0.3,
    "pause": 0.32,
    "resume": 0.32,
}


def impact_notes(weight: int) -> list[Note]:
    """Return an impact thud: a falling low sine with a dull noise burst.

    `weight` 0 is a light tap; each step up is lower, longer and noisier.
    """
    ring = 0.07 + 0.03 * weight
    return [
        Note(midi(52 - 5 * weight), 0.0, ring, "sine", 0.4, glide=-160.0, attack=0.002, decay=ring, sustain=0.0),
        Note(380.0 + 120.0 * weight, 0.0, 0.03, "noise", 0.08 + 0.04 * weight, attack=0.001, decay=0.03, sustain=0.0),
    ]


def combo_notes(chain: int) -> list[Note]:
    """Return the combo chime for a chain of `chain`: a bright third, higher each link."""
    root = ladder_note(8 + chain)
    return [pluck(root, 0.0, 0.3, 0.26, voice="sine"), pluck(root + 4, 0.07, 0.4, 0.22, voice="sine")]


# Beginner note: a name such as "merge@3" is a pitch variant of "merge".
# `SoundBank.play(name, volume, pitch_step=3)` plays "merge@3" when it exists
# and falls back to plain "merge" otherwise. Every variant is rendered ahead
# of time at start-up, because rendering on the fly would stall a frame.
SFX_RECIPES.update(
    {
        # Launch: a breathy whoosh that rises as the body leaves the launcher.
        "whoosh": [
            Note(1200.0, 0.0, 0.16, "noise", 0.16, glide=26000.0, attack=0.06, decay=0.1, sustain=0.4, release=0.08),
            Note(midi(69), 0.0, 0.14, "sine", 0.05, glide=900.0, attack=0.05, decay=0.08, sustain=0.3, release=0.06),
        ],
        # A launch refused by the cooldown: a soft, low "not yet" double bump.
        "launch_blocked": [pluck(45, 0.0, 0.06, 0.26, voice="square"), pluck(45, 0.08, 0.06, 0.2, voice="square")],
        # One detent click of the aiming dial.
        "aim_tick": [pluck(96, 0.0, 0.016, 0.18, voice="sine")],
        "impact": impact_notes(0),
        **{f"impact@{weight}": impact_notes(weight) for weight in range(1, len(IMPACT_SOUND_BANDS) + 1)},
        "combo": combo_notes(2),
        **{f"combo@{chain}": combo_notes(chain) for chain in range(3, COMBO_CHIME_TOP + 1)},
        # Each merge sounds one step higher up the ladder than the tier before.
        **{f"merge@{tier}": merge_notes(tier) for tier in range(1, len(TIERS))},
        **{f"big_merge@{tier}": big_merge_notes(tier) for tier in range(len(TIERS) - 3, len(TIERS))},
        # Passing the old high score mid-run: a quick sparkling A major run.
        "high_score": [
            *(pluck(pitch, index * 0.06, 0.4, 0.2, voice="sine") for index, pitch in enumerate((81, 85, 88, 93))),
            Note(midi(93), 0.24, 0.2, "triangle", 0.08, attack=0.03, decay=0.15, sustain=0.5, release=0.3),
        ],
        # Crossing the danger line: a hollow falling third. Leaving it: a
        # relieved rising sine phrase that resolves home to A.
        "danger_on": [pluck(64, 0.0, 0.16, 0.22, voice="square"), pluck(60, 0.13, 0.22, 0.22, voice="square")],
        "danger_off": [
            pluck(pitch, index * 0.09, 0.25, 0.24, voice="sine") for index, pitch in enumerate((60, 64, 69))
        ],
        "pause": [pluck(76, 0.0, 0.12, 0.22, voice="sine"), pluck(69, 0.08, 0.18, 0.22, voice="sine")],
        "resume": [pluck(69, 0.0, 0.12, 0.22, voice="sine"), pluck(76, 0.08, 0.18, 0.22, voice="sine")],
    }
)

# Music: an ambient space pad with a slow arpeggio, rendered once into a loop
# that plays on reserved mixer channels (see `music_notes`). The tense track
# shares the pad and bass but runs the arpeggio twice as fast over a soft
# heartbeat; the game crossfades to it while the stack is over the danger line.
MUSIC_LOOP_SECONDS = 16.0  # One pass through the four chords below.
MUSIC_CHORD_SECONDS = MUSIC_LOOP_SECONDS / 4
MUSIC_VOLUME = 0.22  # Channel volume: low, so effects sit on top of the music.
# Channel 0 plays the calm track and channel 1 the tense one, so the two can
# crossfade; both are reserved so effects never take them.
MUSIC_CHANNEL_COUNT = 2
MUSIC_CALM_CHANNEL = 0
MUSIC_TENSE_CHANNEL = 1
MUSIC_CROSSFADE_MS = 900  # Fade time when switching between calm and tense.
MUSIC_FADE_IN_MS = 1200  # Fade-in when music starts from silence.
MUSIC_GAME_OVER_FADE_MS = 700  # How quickly the music fades under the game-over jingle.
# Am9 - Fmaj7 - Cmaj7 - G6 in A minor: (bass note, pad notes) per chord, as MIDI numbers.
MUSIC_CHORDS = (
    (45, (57, 60, 64, 71)),
    (41, (53, 57, 60, 64)),
    (48, (55, 60, 64, 71)),
    (43, (55, 59, 62, 64)),
)
MUSIC_PAD_VOLUME = 0.085  # Per pad voice; four of them sound together.
MUSIC_PAD_ATTACK = 1.2  # The pad swells in slowly, like a breath.
MUSIC_PAD_RELEASE = 1.2  # ...and lingers under the start of the next chord.
MUSIC_PAD_DECAY = 0.6  # After the swell the pad settles down to...
MUSIC_PAD_SUSTAIN = 0.8  # ...this share of its peak while the chord is held.
MUSIC_BASS_VOLUME = 0.16
MUSIC_BASS_ATTACK = 0.3  # The bass eases in under each chord (s)...
MUSIC_BASS_SUSTAIN = 0.9  # ...holds nearly full...
MUSIC_BASS_RELEASE = 0.8  # ...and fades out over this long (s).
# The arpeggio climbs and falls through the chord an octave above the pad.
# The calm track plays two notes a second; the tense one four.
MUSIC_ARP_PATTERN = (0, 1, 2, 3, 2, 1, 2, 3)
MUSIC_ARP_STEPS = {False: 8, True: 16}  # Arpeggio notes per chord.
MUSIC_ARP_VOLUME = {False: 0.075, True: 0.07}
MUSIC_ARP_RING = {False: 1.4, True: 0.45}  # How long each arpeggio note rings (s).
MUSIC_HEARTBEAT_VOLUME = 0.16  # The tense track's soft low pulse on every beat.
MUSIC_HEARTBEAT_RING = 0.25  # How long each heartbeat thump rings (s).
MUSIC_BEATS_PER_CHORD = 4


def music_notes(tense: bool) -> list[Note]:
    """Return one loop of the soundtrack: calm, or tense when `tense` is True.

    Every note ends by `MUSIC_LOOP_SECONDS`, so the loop restarts without a
    note being cut off mid-ring. The final chord's pad and bass are held
    `MUSIC_PAD_RELEASE` seconds less, so the pad's release fades out exactly
    at the loop end. Arpeggio notes near the end whose ring would run past
    the loop are left out entirely (the filter on the last line) rather than
    cut short.

    Tempo arithmetic (calm): 16 s / 4 chords = 4 s per chord; 8 arpeggio
    notes per chord = one every 0.5 s. The tense track plays 16 per chord
    (one every 0.25 s) over a heartbeat on each of 4 beats per chord, which
    is one thump a second (60 beats per minute).

    Beginner note:
    - Pad notes are moved up 12 MIDI numbers (one octave) for the arpeggio,
      so it sparkles above the pad instead of muddying it.
    """
    notes: list[Note] = []
    span = MUSIC_CHORD_SECONDS
    for index, (bass, pad) in enumerate(MUSIC_CHORDS):
        start = index * span
        last = index == len(MUSIC_CHORDS) - 1
        hold = span - MUSIC_PAD_RELEASE if last else span
        for pitch in pad:
            notes.append(
                Note(
                    midi(pitch),
                    start,
                    hold,
                    "triangle",
                    MUSIC_PAD_VOLUME,
                    attack=MUSIC_PAD_ATTACK,
                    decay=MUSIC_PAD_DECAY,
                    sustain=MUSIC_PAD_SUSTAIN,
                    release=MUSIC_PAD_RELEASE,
                )
            )
        notes.append(
            Note(
                midi(bass),
                start,
                hold,
                "sine",
                MUSIC_BASS_VOLUME,
                attack=MUSIC_BASS_ATTACK,
                sustain=MUSIC_BASS_SUSTAIN,
                release=MUSIC_BASS_RELEASE,
            )
        )
        steps = MUSIC_ARP_STEPS[tense]
        for step in range(steps):
            pitch = pad[MUSIC_ARP_PATTERN[step % len(MUSIC_ARP_PATTERN)]] + 12
            voice = "pluck" if tense else "sine"
            at = start + step * span / steps
            notes.append(pluck(pitch, at, MUSIC_ARP_RING[tense], MUSIC_ARP_VOLUME[tense], voice))
        if tense:
            for beat in range(MUSIC_BEATS_PER_CHORD):
                at = start + beat * span / MUSIC_BEATS_PER_CHORD
                notes.append(pluck(bass - 12, at, MUSIC_HEARTBEAT_RING, MUSIC_HEARTBEAT_VOLUME, "sine"))
    return [note for note in notes if note.end <= MUSIC_LOOP_SECONDS]
