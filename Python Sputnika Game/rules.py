"""Pure scoring and danger rules, kept free of pygame.

`game.py` is the pygame shell: it owns the window, sounds, and effects. The
small pieces of arithmetic that decide *how the game plays* live here
instead, so they can be tested directly without opening a window:
- combo tracking and the combo score multiplier,
- the fail timer that fills while the stack is too high,
- the HUD stress level and the danger-beep rhythm,
- which impact thud and aim tick to play,
- cleaning up saved progress loaded from disk.

Beginner note:
- Every function here takes plain numbers (or a plain dict) and returns a new
  value. None of them change game state themselves.
- `game.py` calls these functions and then stores the results, plays sounds,
  or spawns effects. Keeping "decide" separate from "show" is what makes the
  rules easy to test.
"""

from __future__ import annotations

import math
from typing import Any

from settings import (
    AIM_TICK_DEGREES,
    COMBO_MAX_MULTIPLIER,
    COMBO_STEP,
    COMBO_WINDOW,
    FAIL_DECAY,
    FAIL_GRACE,
    FAIL_LINE_Y,
    IMPACT_EVENT_SPEED,
    IMPACT_LOUDEST_SPEED,
    IMPACT_SOUND_BANDS,
    IMPACT_VOLUME_RANGE,
    STRESS_PREVIEW_RANGE,
    STRESS_PREVIEW_SHARE,
    STRESS_TIMER_SHARE,
    TIERS,
    WARNING_BEEP_INTERVAL_SPAN,
    WARNING_BEEP_MAX_INTERVAL,
    WARNING_BEEP_MIN_INTERVAL,
    clamp,
)


def next_combo_count(combo_count: int, last_merge_time: float, now: float) -> int:
    """Return the combo chain length after a merge that happens at `now`.

    Merges chained within `COMBO_WINDOW` seconds of the previous merge extend
    the chain. A multi-merge frame shares one timestamp, so cascades naturally
    chain together. A slower merge starts a fresh chain of one.
    """
    if now - last_merge_time <= COMBO_WINDOW:
        return combo_count + 1
    return 1


def combo_multiplier(combo_count: int) -> float:
    """Return the score multiplier for a chain of `combo_count` merges.

    The first merge pays 1.0x; every further link adds `COMBO_STEP`, capped at
    `COMBO_MAX_MULTIPLIER`.
    """
    return min(COMBO_MAX_MULTIPLIER, 1.0 + COMBO_STEP * (combo_count - 1))


def combo_points(score_gain: int, combo_count: int) -> int:
    """Return the points a merge earns once the combo multiplier is applied.

    Beginner note:
    - Python's `round()` sends exact halves to the nearest even number, so
      4.5 rounds to 4. That matches the game's original behaviour.
    """
    return round(score_gain * combo_multiplier(combo_count))


def advance_fail_timer(fail_timer: float, dt: float, warning: bool) -> float:
    """Return the fail timer after `dt` seconds of danger (or of recovery).

    While `warning` is active the timer fills in real time, capped at
    `FAIL_GRACE` (which means game over). When the player recovers it drains
    `FAIL_DECAY` times faster than it filled, never dropping below zero.
    """
    if warning:
        return min(FAIL_GRACE, fail_timer + dt)
    return max(0.0, fail_timer - dt * FAIL_DECAY)


def fail_ratio(fail_timer: float) -> float:
    """Return how much of the grace period is used up, as 0.0 to 1.0."""
    return fail_timer / FAIL_GRACE if FAIL_GRACE > 0.0 else 0.0


def warning_beep_interval(ratio: float) -> float:
    """Return the gap in seconds before the next danger beep.

    `ratio` is the fail ratio (0.0 calm, 1.0 game over). The gap shrinks as the
    ratio grows, so the beeps speed up the closer the player is to losing.
    """
    return max(WARNING_BEEP_MIN_INTERVAL, WARNING_BEEP_MAX_INTERVAL - ratio * WARNING_BEEP_INTERVAL_SPAN)


def stress_level(highest_top: float, fail_timer: float, warning: bool) -> float:
    """Return the HUD stress meter level from 0.0 (calm) to 1.0 (game over).

    The meter has two phases (their shares are defined in settings.py):
    - the live stack height fills the preview share as the tallest point in
      the stack (`highest_top`, a screen Y) rises toward the fail line,
    - once the line is actually crossed (`warning`), the fail countdown fills
      the remaining timer share on top.
    """
    # `highest_top` shrinks as the stack grows (screen y points down). The
    # ratio is 0 while the top is `STRESS_PREVIEW_RANGE` or more below the
    # fail line, and reaches 1 when the top touches the line.
    preview_ratio = clamp(
        (FAIL_LINE_Y + STRESS_PREVIEW_RANGE - highest_top) / STRESS_PREVIEW_RANGE,
        0.0,
        1.0,
    )
    preview_stress = preview_ratio * STRESS_PREVIEW_SHARE
    danger_stress = STRESS_PREVIEW_SHARE + fail_ratio(fail_timer) * STRESS_TIMER_SHARE if warning else 0.0
    return max(preview_stress, danger_stress)


def impact_sound(speed: float) -> tuple[int, float]:
    """Return (thud weight, volume) for a collision at `speed` pixels per second.

    The weight counts how many `IMPACT_SOUND_BANDS` the speed reaches (0 is
    the lightest thud). The volume rises in a straight line across
    `IMPACT_VOLUME_RANGE`, from the softest audible hit
    (`IMPACT_EVENT_SPEED`) up to `IMPACT_LOUDEST_SPEED`, and stays there.
    """
    weight = sum(1 for band in IMPACT_SOUND_BANDS if speed >= band)
    share = clamp((speed - IMPACT_EVENT_SPEED) / (IMPACT_LOUDEST_SPEED - IMPACT_EVENT_SPEED), 0.0, 1.0)
    low, high = IMPACT_VOLUME_RANGE
    return weight, low + (high - low) * share


def aim_tick_crossed(old_angle: float, new_angle: float) -> bool:
    """Return True when the aim moved past a multiple of `AIM_TICK_DEGREES`.

    Beginner note:
    - `math.floor(angle / step)` numbers the "detent" the angle sits in
      (-1 for -5..0, 0 for 0..5 with a 5 degree step). The aim crossed a
      detent exactly when that number changed.
    """
    return math.floor(old_angle / AIM_TICK_DEGREES) != math.floor(new_angle / AIM_TICK_DEGREES)


def sanitize_progress(data: Any) -> dict[str, int]:
    """Clean raw saved-progress data into safe values.

    The three counters become non-negative integers: missing fields default
    to zero and `best_tier` is clamped onto the tier ladder. `muted` (the
    sound setting) is True only for a real JSON `true`; anything else,
    including a missing key, leaves sound on. Data that cannot be cleaned (not a JSON object, or a field that
    `int()` cannot convert) raises, and the caller falls back to fresh progress.
    """
    return {
        "high_score": max(0, int(data.get("high_score", 0))),
        "games_played": max(0, int(data.get("games_played", 0))),
        "best_tier": max(0, min(len(TIERS) - 1, int(data.get("best_tier", 0)))),
        "muted": data.get("muted") is True,
    }
