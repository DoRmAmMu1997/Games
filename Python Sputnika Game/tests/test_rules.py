"""Engine tests for the pygame-free scoring and danger rules in ``rules.py``.

These rules used to live inline inside the pygame shell (``game.py``), where
they could only be exercised by running the whole game. Pulling them into a
plain module lets these tests pin down the exact numbers: how combos build,
how the fail timer fills and drains, how the stress meter is split, and how a
damaged save file is cleaned up.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import rules
from settings import (
    AIM_TICK_DEGREES,
    COMBO_MAX_MULTIPLIER,
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
    WARNING_BEEP_MAX_INTERVAL,
    WARNING_BEEP_MIN_INTERVAL,
)


class RulesModuleTests(unittest.TestCase):
    """The rules module must stay usable without any UI toolkit."""

    def test_rules_module_does_not_import_pygame(self) -> None:
        """``rules.py`` is UI-free, so its source never imports pygame."""

        source = Path(rules.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import pygame", source)


class ComboTests(unittest.TestCase):
    """Quick back-to-back merges build an escalating score multiplier."""

    def test_first_merge_starts_a_chain_of_one(self) -> None:
        """With no recent merge, the chain restarts at one."""

        self.assertEqual(rules.next_combo_count(0, -999.0, 10.0), 1)

    def test_merge_inside_the_window_extends_the_chain(self) -> None:
        """A merge within ``COMBO_WINDOW`` seconds adds one to the chain."""

        self.assertEqual(rules.next_combo_count(2, 10.0, 10.0 + COMBO_WINDOW), 3)

    def test_merge_after_the_window_restarts_the_chain(self) -> None:
        """A merge after the window has closed starts a fresh chain."""

        self.assertEqual(rules.next_combo_count(4, 10.0, 10.0 + COMBO_WINDOW + 0.01), 1)

    def test_same_frame_cascade_chains_together(self) -> None:
        """Merges sharing one timestamp count as one quick chain."""

        self.assertEqual(rules.next_combo_count(1, 5.0, 5.0), 2)

    def test_multiplier_grows_by_half_per_link(self) -> None:
        """Each extra link adds 0.5x on top of the base 1.0x."""

        self.assertEqual(rules.combo_multiplier(1), 1.0)
        self.assertEqual(rules.combo_multiplier(2), 1.5)
        self.assertEqual(rules.combo_multiplier(3), 2.0)

    def test_multiplier_is_capped(self) -> None:
        """Very long chains never exceed ``COMBO_MAX_MULTIPLIER``."""

        self.assertEqual(rules.combo_multiplier(50), COMBO_MAX_MULTIPLIER)
        self.assertEqual(COMBO_MAX_MULTIPLIER, 3.0)

    def test_combo_points_round_the_scaled_gain(self) -> None:
        """Points are the tier score scaled by the multiplier, then rounded."""

        # 3 * 1.5 = 4.5, and Python's round() sends exact halves to the even neighbour.
        self.assertEqual(rules.combo_points(3, 2), 4)
        self.assertEqual(rules.combo_points(12, 3), 24)


class FailTimerTests(unittest.TestCase):
    """The fail timer fills while in danger and drains when the player recovers."""

    def test_timer_fills_with_elapsed_time_while_warning(self) -> None:
        """Danger adds exactly ``dt`` seconds to the timer."""

        self.assertAlmostEqual(rules.advance_fail_timer(0.5, 0.1, warning=True), 0.6)

    def test_timer_never_exceeds_the_grace_period(self) -> None:
        """The timer is capped at ``FAIL_GRACE``."""

        self.assertEqual(rules.advance_fail_timer(FAIL_GRACE - 0.01, 1.0, warning=True), FAIL_GRACE)

    def test_timer_decays_faster_than_it_fills(self) -> None:
        """Recovery drains the timer at ``FAIL_DECAY`` times real speed."""

        self.assertAlmostEqual(rules.advance_fail_timer(1.0, 0.1, warning=False), 1.0 - 0.1 * FAIL_DECAY)

    def test_timer_never_goes_negative(self) -> None:
        """Draining stops at zero."""

        self.assertEqual(rules.advance_fail_timer(0.05, 1.0, warning=False), 0.0)

    def test_fail_ratio_is_the_fraction_of_grace_used(self) -> None:
        """Half the grace period used reads as 0.5."""

        self.assertAlmostEqual(rules.fail_ratio(FAIL_GRACE / 2), 0.5)


class WarningBeepTests(unittest.TestCase):
    """The danger beep repeats faster as game over approaches."""

    def test_calm_start_uses_the_longest_gap(self) -> None:
        """A fresh danger spell beeps at the slowest rate."""

        self.assertAlmostEqual(rules.warning_beep_interval(0.0), WARNING_BEEP_MAX_INTERVAL)

    def test_gap_shrinks_but_never_below_the_minimum(self) -> None:
        """At a full timer the gap is clamped to ``WARNING_BEEP_MIN_INTERVAL``."""

        self.assertAlmostEqual(rules.warning_beep_interval(1.0), WARNING_BEEP_MIN_INTERVAL)
        self.assertLess(rules.warning_beep_interval(0.5), WARNING_BEEP_MAX_INTERVAL)

    def test_original_tuning_is_preserved(self) -> None:
        """The extracted maths matches the original ``max(0.2, 0.66 - r * 0.46)``."""

        for ratio in (0.0, 0.25, 0.5, 0.75, 0.99, 1.0):
            self.assertAlmostEqual(rules.warning_beep_interval(ratio), max(0.2, 0.66 - ratio * 0.46))


class StressTests(unittest.TestCase):
    """The HUD stress meter blends stack height with the fail countdown."""

    def test_low_stack_reads_as_zero(self) -> None:
        """A stack far below the preview range shows no stress."""

        self.assertEqual(rules.stress_level(FAIL_LINE_Y + STRESS_PREVIEW_RANGE + 50, 0.0, warning=False), 0.0)

    def test_stack_height_fills_the_preview_share(self) -> None:
        """Halfway into the preview range fills half the preview share."""

        top = FAIL_LINE_Y + STRESS_PREVIEW_RANGE / 2
        self.assertAlmostEqual(rules.stress_level(top, 0.0, warning=False), STRESS_PREVIEW_SHARE / 2)

    def test_danger_adds_the_timer_share_on_top(self) -> None:
        """Once in danger, the countdown fills the remaining timer share."""

        level = rules.stress_level(FAIL_LINE_Y - 10, FAIL_GRACE / 2, warning=True)
        self.assertAlmostEqual(level, STRESS_PREVIEW_SHARE + STRESS_TIMER_SHARE / 2)

    def test_full_timer_fills_the_meter(self) -> None:
        """A full countdown reads as a completely full meter."""

        self.assertAlmostEqual(rules.stress_level(FAIL_LINE_Y - 10, FAIL_GRACE, warning=True), 1.0)


class SoundCueTests(unittest.TestCase):
    """Pure helpers that decide which variant of a sound to play, and how loud."""

    def test_impacts_get_heavier_and_louder_with_speed(self) -> None:
        """Slow hits are light and quiet; each band up is heavier; loudness tops out."""

        low, high = IMPACT_VOLUME_RANGE
        self.assertEqual(rules.impact_sound(IMPACT_EVENT_SPEED), (0, low))
        self.assertEqual(rules.impact_sound(IMPACT_SOUND_BANDS[0])[0], 1)
        self.assertEqual(rules.impact_sound(IMPACT_SOUND_BANDS[1])[0], 2)
        self.assertEqual(rules.impact_sound(IMPACT_LOUDEST_SPEED * 3), (2, high))
        middle = rules.impact_sound((IMPACT_EVENT_SPEED + IMPACT_LOUDEST_SPEED) / 2)[1]
        self.assertAlmostEqual(middle, (low + high) / 2)

    def test_aim_ticks_only_when_a_detent_is_crossed(self) -> None:
        """Small moves inside one detent are silent; crossing one (either way) ticks."""

        step = AIM_TICK_DEGREES
        self.assertFalse(rules.aim_tick_crossed(0.5, step - 0.5))
        self.assertTrue(rules.aim_tick_crossed(step - 0.5, step + 0.5))
        self.assertTrue(rules.aim_tick_crossed(0.5, -0.5))
        self.assertFalse(rules.aim_tick_crossed(-step * 2, -step * 2))


class ProgressSanitizingTests(unittest.TestCase):
    """Saved progress is cleaned so odd values can never break the game."""

    def test_good_data_passes_through(self) -> None:
        """Valid fields are kept as integers."""

        data = {"high_score": 120, "games_played": 4, "best_tier": 3}
        self.assertEqual(rules.sanitize_progress(data), data)

    def test_missing_fields_default_to_zero(self) -> None:
        """An empty save means no progress yet."""

        self.assertEqual(rules.sanitize_progress({}), {"high_score": 0, "games_played": 0, "best_tier": 0})

    def test_negative_values_are_clamped_to_zero(self) -> None:
        """Counters and scores cannot be negative."""

        cleaned = rules.sanitize_progress({"high_score": -5, "games_played": -1, "best_tier": -3})
        self.assertEqual(cleaned, {"high_score": 0, "games_played": 0, "best_tier": 0})

    def test_best_tier_is_clamped_to_the_ladder(self) -> None:
        """A best tier past the top of the ladder becomes the top tier."""

        self.assertEqual(rules.sanitize_progress({"best_tier": 999})["best_tier"], len(TIERS) - 1)

    def test_numeric_strings_are_converted(self) -> None:
        """A hand-edited ``"42"`` still loads as the number 42."""

        self.assertEqual(rules.sanitize_progress({"high_score": "42"})["high_score"], 42)

    def test_non_mapping_data_raises(self) -> None:
        """A save that is not a JSON object is rejected for the caller to handle."""

        with self.assertRaises(AttributeError):
            rules.sanitize_progress([1, 2, 3])


if __name__ == "__main__":
    unittest.main()
