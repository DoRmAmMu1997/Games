"""Headless tests for the procedural audio in ``audio.py`` and its game wiring.

Nothing here listens to sound. The tests check the sample buffers the
synthesizer produces and the calls the bank makes on (mocked) mixer channels,
under SDL's dummy audio driver.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import pygame

import audio
import main
import visual_theme as theme
from audio import LIMIT, MusicPlayer, Note, SoundBank, midi, render
from game import LudoGame, LudoRules
from settings import (
    DICE_RESULT_AT,
    HOP_PITCH_STEPS,
    LABEL_CONTRAST_TARGET,
    MUSIC_BARS,
    MUSIC_BEATS_PER_BAR,
    MUSIC_BPM,
    MUSIC_FADE_IN_MS,
    MUSIC_GAME_OVER_FADE_MS,
    MUSIC_LOOP_SECONDS,
    MUSIC_VOLUME,
    SFX_COOLDOWNS,
    SFX_RECIPES,
    music_notes,
)

RATE = 22050


class FakeClock:
    """A settable stand-in for ``time.monotonic``."""

    def __init__(self) -> None:
        """Start the clock at zero seconds."""

        self.now = 0.0

    def __call__(self) -> float:
        """Return the current fake time."""

        return self.now


class RenderTests(unittest.TestCase):
    """The synthesizer produces full, bounded, repeatable buffers."""

    def test_length_matches_every_channel_layout(self) -> None:
        """Mono, stereo, 4, 6 and 8 channels each get one sample per channel per frame."""

        notes = [Note(440.0, 0.0, 0.04, "sine", 0.3, release=0.01)]
        for channels in (1, 2, 4, 6, 8):
            with self.subTest(channels=channels):
                self.assertEqual(len(render(notes, RATE, channels)), round(0.05 * RATE) * channels)

    def test_channels_carry_the_same_samples(self) -> None:
        """Every channel of a frame holds the same value."""

        samples = render([Note(330.0, 0.0, 0.05, "triangle", 0.4)], RATE, 2)
        self.assertEqual(samples[0::2], samples[1::2])

    def test_explicit_total_sets_the_length(self) -> None:
        """``total`` fixes the length; a note still ringing at the end is cut off."""

        samples = render([Note(220.0, 0.0, 2.0, "sine", 0.3)], RATE, 1, total=0.5)
        self.assertEqual(len(samples), round(0.5 * RATE))

    def test_loud_stack_stays_below_full_scale(self) -> None:
        """Ten full-volume notes at once are squeezed under the limiter ceiling."""

        notes = [Note(110.0 * (index + 1), 0.0, 0.1, "square", 1.0) for index in range(10)]
        peak = max(abs(value) for value in render(notes, RATE, 1))
        self.assertLessEqual(peak, LIMIT * 32767)
        self.assertGreater(peak, 0.8 * 32767)

    def test_rendering_is_deterministic(self) -> None:
        """The same recipe, noise included, always renders the same samples."""

        notes = [Note(3000.0, 0.0, 0.05, "noise", 0.3), Note(midi(64), 0.01, 0.05, "pluck", 0.3, glide=-200.0)]
        self.assertEqual(render(notes, RATE, 2), render(list(notes), RATE, 2))

    def test_noise_differs_between_notes(self) -> None:
        """Two different noise notes do not share one random sequence."""

        first = render([Note(3000.0, 0.0, 0.05, "noise", 0.3)], RATE, 1)
        second = render([Note(3000.0, 0.0, 0.05, "noise", 0.31)], RATE, 1)
        self.assertNotEqual(first, second)

    def test_edges_are_faded_to_silence(self) -> None:
        """The first and last samples are near zero, so nothing clicks."""

        samples = render([Note(440.0, 0.0, 0.2, "square", 0.8, attack=0.0001)], RATE, 1, total=0.1)
        self.assertLess(abs(samples[0]), 300)
        self.assertLess(abs(samples[-1]), 300)

    def test_rests_and_silent_notes_add_nothing_but_time(self) -> None:
        """A rest still sets the length; the buffer stays silent."""

        samples = render([Note(0.0, 0.0, 0.1, "sine", 0.5), Note(440.0, 0.0, 0.1, "sine", 0.0)], RATE, 1)
        self.assertEqual(len(samples), round(0.15 * RATE))
        self.assertEqual(max(samples), 0)

    def test_short_note_is_released_from_its_current_level(self) -> None:
        """A note shorter than its attack still sounds and then fades out."""

        samples = render([Note(440.0, 0.0, 0.01, "sine", 0.5, attack=0.1, release=0.02)], RATE, 1)
        self.assertGreater(max(samples), 0)
        self.assertEqual(len(samples), round(0.03 * RATE))

    def test_empty_recipe_is_empty(self) -> None:
        """No notes means no samples."""

        self.assertEqual(len(render([], RATE, 2)), 0)

    def test_midi_reference_pitches(self) -> None:
        """MIDI 69 is A4 at 440 Hz and 12 steps up is one octave."""

        self.assertAlmostEqual(midi(69), 440.0)
        self.assertAlmostEqual(midi(81), 880.0)
        self.assertAlmostEqual(midi(60), 261.6256, places=3)


class MixerSetupTests(unittest.TestCase):
    """The mixer helpers ask for the shared format and reserve music channels."""

    def test_init_mixer_requests_the_shared_format(self) -> None:
        """``init_mixer`` pre-initialises 22050 Hz, 16-bit, stereo, 512 samples."""

        with mock.patch.object(pygame.mixer, "pre_init") as pre_init:
            audio.init_mixer()
        pre_init.assert_called_once_with(22050, -16, 2, 512)

    def test_init_mixer_ignores_mixer_errors(self) -> None:
        """A mixer error while configuring is swallowed, not raised."""

        with mock.patch.object(pygame.mixer, "pre_init", side_effect=pygame.error("no audio")):
            audio.init_mixer()

    def test_reserve_channels_keeps_music_channels(self) -> None:
        """After init: 16 channels open, the first ``music_channels`` reserved."""

        with (
            mock.patch.object(pygame.mixer, "get_init", return_value=(RATE, -16, 2)),
            mock.patch.object(pygame.mixer, "set_num_channels") as set_num,
            mock.patch.object(pygame.mixer, "set_reserved") as set_reserved,
        ):
            audio.reserve_channels(2)
        set_num.assert_called_once_with(16)
        set_reserved.assert_called_once_with(2)

    def test_reserve_channels_without_mixer_does_nothing(self) -> None:
        """No mixer: nothing is configured and nothing raises."""

        with (
            mock.patch.object(pygame.mixer, "get_init", return_value=None),
            mock.patch.object(pygame.mixer, "set_reserved") as set_reserved,
        ):
            audio.reserve_channels()
        set_reserved.assert_not_called()

    def test_reserve_channels_ignores_mixer_errors(self) -> None:
        """A mixer error while reserving is swallowed, not raised."""

        with (
            mock.patch.object(pygame.mixer, "get_init", return_value=(RATE, -16, 2)),
            mock.patch.object(pygame.mixer, "set_num_channels", side_effect=pygame.error("busy")),
        ):
            audio.reserve_channels()


class SoundBankTests(unittest.TestCase):
    """The bank builds sounds for the running mixer and plays them politely."""

    RECIPES = {
        "beep": [Note(440.0, 0.0, 0.02, "sine", 0.3)],
        "beep@2": [Note(660.0, 0.0, 0.02, "sine", 0.3)],
        "tick": [Note(4000.0, 0.0, 0.01, "noise", 0.2)],
    }

    def setUp(self) -> None:
        """Start the dummy mixer and capture every channel the bank plays on."""

        pygame.mixer.init()
        self.addCleanup(pygame.mixer.quit)
        self.channel = mock.Mock()
        patcher = mock.patch.object(pygame.mixer, "find_channel", return_value=self.channel)
        self.find_channel = patcher.start()
        self.addCleanup(patcher.stop)
        self.clock = FakeClock()
        self.bank = SoundBank(self.RECIPES, {"beep": 0.05}, clock=self.clock)

    def played(self) -> list[pygame.mixer.Sound]:
        """Return the sounds started on the captured channel, in order."""

        return [call.args[0] for call in self.channel.play.call_args_list]

    def test_bank_buffers_match_every_channel_layout(self) -> None:
        """Each built sound holds one 16-bit sample per channel per frame."""

        for channels in (1, 2, 4, 6, 8):
            with (
                self.subTest(channels=channels),
                mock.patch.object(pygame.mixer, "get_init", return_value=(RATE, -16, channels)),
                mock.patch.object(pygame.mixer, "Sound") as fake_sound,
            ):
                SoundBank({"beep": self.RECIPES["beep"]})
                buffer = fake_sound.call_args.kwargs["buffer"]
                self.assertEqual(len(buffer), round(0.07 * RATE) * channels * 2)

    def test_play_uses_a_free_channel_at_the_given_volume(self) -> None:
        """``play`` asks for any free channel and clamps the volume to 0..1."""

        self.bank.play("beep", 1.7)
        self.find_channel.assert_called_once_with(True)
        self.channel.set_volume.assert_called_once_with(1.0)
        self.assertEqual(self.played(), [self.bank.sounds["beep"]])

    def test_cooldown_drops_a_quick_repeat(self) -> None:
        """A repeat inside the cooldown is dropped; one after it plays."""

        self.bank.play("beep")
        self.clock.now = 0.02
        self.bank.play("beep")
        self.clock.now = 0.08
        self.bank.play("beep")
        self.assertEqual(len(self.played()), 2)

    def test_names_without_cooldown_always_play(self) -> None:
        """A sound with no cooldown can repeat in the same instant."""

        self.bank.play("tick")
        self.bank.play("tick")
        self.assertEqual(len(self.played()), 2)

    def test_pitch_step_picks_a_variant_or_falls_back(self) -> None:
        """``pitch_step`` plays ``name@step`` when built, else the base sound."""

        self.bank.play("beep", pitch_step=2)
        self.clock.now = 1.0
        self.bank.play("beep", pitch_step=5)
        self.assertEqual(self.played(), [self.bank.sounds["beep@2"], self.bank.sounds["beep"]])

    def test_variants_share_their_base_cooldown(self) -> None:
        """A variant played right after its base sound is dropped too."""

        self.bank.play("beep")
        self.bank.play("beep", pitch_step=2)
        self.assertEqual(len(self.played()), 1)

    def test_mute_blocks_play(self) -> None:
        """Nothing plays while muted; unmuting restores playback."""

        self.bank.muted = True
        self.bank.play("tick")
        self.assertTrue(self.bank.muted)
        self.assertEqual(self.played(), [])
        self.bank.muted = False
        self.bank.play("tick")
        self.assertEqual(len(self.played()), 1)

    def test_unknown_name_is_silent(self) -> None:
        """An unknown sound name is ignored."""

        self.bank.play("nope")
        self.find_channel.assert_not_called()

    def test_no_free_channel_is_silent(self) -> None:
        """When no channel is free the sound is skipped without error."""

        self.find_channel.return_value = None
        self.bank.play("tick")
        self.assertEqual(self.played(), [])

    def test_bank_is_disabled_without_a_mixer(self) -> None:
        """No mixer: the bank is disabled, empty and silent."""

        with mock.patch.object(pygame.mixer, "get_init", return_value=None):
            bank = SoundBank(self.RECIPES)
        bank.play("beep")
        self.assertFalse(bank.enabled)
        self.assertEqual(bank.sounds, {})
        self.find_channel.assert_not_called()

    def test_bank_is_disabled_when_a_sound_fails_to_build(self) -> None:
        """A mixer error while building disables the whole bank."""

        with mock.patch.object(pygame.mixer, "Sound", side_effect=pygame.error("broken")):
            bank = SoundBank(self.RECIPES)
        self.assertFalse(bank.enabled)
        self.assertEqual(bank.sounds, {})


class ImportTests(unittest.TestCase):
    """The audio core can be imported without loading pygame."""

    def test_pygame_is_only_imported_inside_functions(self) -> None:
        """No top-level statement of ``audio.py`` imports pygame.

        settings.py imports ``Note`` and ``midi`` from the core, and the
        pygame-free rules engine imports settings, so the core must not pull
        pygame in at import time.
        """

        tree = ast.parse(Path(audio.__file__).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                self.assertNotIn("pygame", [alias.name.split(".")[0] for alias in node.names])
            if isinstance(node, ast.ImportFrom):
                self.assertNotEqual((node.module or "").split(".")[0], "pygame")


class LudoRecipeTests(unittest.TestCase):
    """Ludo's own effect recipes are complete, well formed and well behaved."""

    def test_every_event_sound_has_a_recipe(self) -> None:
        """Each effect the shell plays has a recipe."""

        for name in ("dice", "six", "three_sixes", "leave_yard", "hop", "capture", "home", "bonus", "no_move",
                     "turn", "click", "win", "lose"):
            with self.subTest(name=name):
                self.assertIn(name, SFX_RECIPES)

    def test_recipes_use_known_voices_and_fit_their_length(self) -> None:
        """Every note uses a real voice; effects last 40 ms to 3 s and never clip."""

        for name, notes in SFX_RECIPES.items():
            samples = render(notes, RATE, 1)
            with self.subTest(name=name):
                self.assertTrue(all(note.voice in audio.VOICES for note in notes))
                self.assertGreaterEqual(len(samples), 0.04 * RATE)
                self.assertLessEqual(len(samples), 3.0 * RATE)
                self.assertLess(max(abs(value) for value in samples), 0.95 * 32767)

    def test_cooldowns_name_real_sounds(self) -> None:
        """Every cooldown belongs to a sound that exists."""

        for name in SFX_COOLDOWNS:
            with self.subTest(name=name):
                self.assertIn(name, SFX_RECIPES)

    def test_every_die_face_has_its_own_result_note(self) -> None:
        """Faces 2 to 6 have variants; each lands higher than the face below it."""

        def landing_pitch(notes: list[Note]) -> float:
            """Return the pitch of the first pitched (non-noise) note: the die landing."""

            return next(note.freq for note in notes if note.voice != "noise")

        pitches = [landing_pitch(SFX_RECIPES["dice"])]
        pitches += [landing_pitch(SFX_RECIPES[f"dice@{face}"]) for face in range(2, 7)]
        self.assertEqual(pitches, sorted(pitches))
        self.assertEqual(len(set(pitches)), 6)

    def test_dice_rattles_before_the_result_lands(self) -> None:
        """The noise rattle comes first and the face's note lands at DICE_RESULT_AT."""

        notes = SFX_RECIPES["dice@4"]
        rattle = [note for note in notes if note.voice == "noise"]
        landing = [note for note in notes if note.voice != "noise"]
        self.assertGreaterEqual(len(rattle), 4)
        self.assertTrue(all(note.start < DICE_RESULT_AT for note in rattle))
        self.assertTrue(all(note.start >= DICE_RESULT_AT for note in landing))

    def test_six_cues_wait_for_the_die_to_land(self) -> None:
        """The six sparkle and the three-sixes groan start once the die has landed."""

        for name in ("six", "three_sixes"):
            with self.subTest(name=name):
                self.assertGreaterEqual(min(note.start for note in SFX_RECIPES[name]), DICE_RESULT_AT)

    def test_hops_climb_along_the_path(self) -> None:
        """Hop variants 1.. are built, and each hop sounds higher than the one before."""

        names = ["hop", *(f"hop@{step}" for step in range(1, HOP_PITCH_STEPS))]
        pitches = [SFX_RECIPES[name][0].freq for name in names]
        self.assertEqual(pitches, sorted(pitches))
        self.assertEqual(len(set(pitches)), HOP_PITCH_STEPS)
        self.assertGreaterEqual(HOP_PITCH_STEPS, 6, "a 6 hops six cells")


def make_app_with_game(human_seats: int = 1) -> tuple[main.LudoApp, LudoGame, mock.Mock]:
    """Return a non-persisting app playing a seeded 4-seat game, with a mock sound bank.

    The first ``human_seats`` seats are human. The mock replaces the real
    bank, so tests can read exactly which sounds were asked for.
    """

    app = main.LudoApp(persist=False)
    players = [(f"P{seat + 1}", seat < human_seats) for seat in range(4)]
    game = LudoGame(players, LudoRules(total_players=4), seed=3)
    app.start_game(game)
    app.sounds = mock.Mock()
    return app, game, app.sounds


def played(bank: mock.Mock) -> list[tuple[str, int]]:
    """Return ``(name, pitch_step)`` for every ``play`` call on a mock bank, in order."""

    return [(call.args[0], call.kwargs.get("pitch_step", 0)) for call in bank.play.call_args_list]


class EventSoundMapTests(unittest.TestCase):
    """``main.event_sounds`` turns one frame's engine events into effect names."""

    def test_each_event_kind_has_its_sound(self) -> None:
        """Every sounding kind maps to its effect; the roll carries the die face."""

        cases = {
            "roll": ("dice", 4),
            "rolled_six": ("six", 0),
            "three_sixes": ("three_sixes", 0),
            "leave_yard": ("leave_yard", 0),
            "capture": ("capture", 0),
            "home": ("home", 0),
            "bonus_turn": ("bonus", 0),
            "no_move": ("no_move", 0),
            "turn_change": ("turn", 0),
        }
        for kind, sound in cases.items():
            with self.subTest(kind=kind):
                self.assertEqual(main.event_sounds([kind], 4, human_to_play=True), [sound])

    def test_moves_and_wins_have_no_effect_of_their_own(self) -> None:
        """A move sounds through its hops, a win through the game-over jingle."""

        self.assertEqual(main.event_sounds(["move", "game_won"], 3, human_to_play=True), [])

    def test_every_event_kind_is_known_to_the_map(self) -> None:
        """Each engine kind either has a sound or is one of the two silent kinds."""

        from game import EVENT_KINDS

        self.assertEqual(set(main.EVENT_SOUNDS) | {"move", "game_won"}, set(EVENT_KINDS))
        for name in main.EVENT_SOUNDS.values():
            with self.subTest(name=name):
                self.assertIn(name, SFX_RECIPES)

    def test_third_six_replaces_the_six_sparkle(self) -> None:
        """A forfeited third 6 groans instead of sparkling."""

        kinds = ["roll", "rolled_six", "three_sixes", "turn_change"]
        self.assertEqual(
            main.event_sounds(kinds, 6, human_to_play=True), [("dice", 6), ("three_sixes", 0), ("turn", 0)]
        )

    def test_bonus_after_a_six_is_not_announced_twice(self) -> None:
        """A 6 already sparkled when it was rolled, so its bonus roll stays quiet."""

        self.assertEqual(main.event_sounds(["leave_yard", "bonus_turn"], 6, human_to_play=True), [("leave_yard", 0)])
        self.assertEqual(main.event_sounds(["capture", "bonus_turn"], 3, human_to_play=True),
                         [("capture", 0), ("bonus", 0)])

    def test_turn_knock_only_calls_a_human(self) -> None:
        """The turn knock tells a human it is their go; AI-to-AI changes stay quiet."""

        self.assertEqual(main.event_sounds(["turn_change"], 2, human_to_play=False), [])


class ShellSoundTests(unittest.TestCase):
    """The window plays the engine's events, token hops and button clicks."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once so the app can open its dummy window."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after these tests."""

        pygame.quit()

    def test_app_builds_its_bank_from_the_ludo_recipes(self) -> None:
        """The real app's bank is a SoundBank with every recipe (when a mixer is running)."""

        app = main.LudoApp(persist=False)
        self.assertIsInstance(app.sounds, SoundBank)
        if app.sounds.enabled:
            self.assertEqual(set(app.sounds.sounds), set(SFX_RECIPES))

    def test_update_plays_this_frame_s_events_once(self) -> None:
        """A human's 6 plays the dice for face 6 and the sparkle, and the queue is emptied."""

        app, game, bank = make_app_with_game()
        game.record_roll(6)
        app._update(autotest=False)
        self.assertEqual(played(bank), [("dice", 6), ("six", 0)])
        self.assertEqual(game.events, [])
        app._update(autotest=False)
        self.assertEqual(len(played(bank)), 2)

    def test_human_roll_button_rattles_the_dice(self) -> None:
        """Clicking Roll plays the click, then the dice for the rolled face on the next update."""

        app, game, bank = make_app_with_game()
        app._handle_click(main.PLAY_ROLL_RECT.center)
        app._update(autotest=False)
        names = [name for name, _ in played(bank)]
        self.assertEqual(names[0], "click")
        self.assertIn(("dice", game.last_roll), played(bank))

    def test_ai_turns_are_heard_too(self) -> None:
        """An AI roll goes through the engine, so the next frame plays its dice."""

        app, _game, bank = make_app_with_game(human_seats=0)
        app._update(autotest=True)
        app._update(autotest=True)
        self.assertIn("dice", [name for name, _ in played(bank)])

    def test_finished_game_plays_its_last_events_before_the_jingle(self) -> None:
        """The winning move's home sound still plays as the game ends."""

        app, game, bank = make_app_with_game()
        for token in game.players[0].tokens[1:]:
            token.steps = game.layout.finish_steps
        game.players[0].tokens[0].steps = game.layout.finish_steps - 2
        game.record_roll(2)
        game.apply_move(game.legal_moves(2)[0])
        app._update(autotest=False)
        self.assertIn(("home", 0), played(bank))

    def hop_sounds(self, bank: mock.Mock) -> list[tuple[str, int]]:
        """Return only the hop sounds asked of a mock bank."""

        return [sound for sound in played(bank) if sound[0] == "hop"]

    def test_each_hop_climbs_in_pitch(self) -> None:
        """A 4-cell move taps four rising hops as the token reaches each cell."""

        app, game, bank = make_app_with_game()
        game.players[0].tokens[0].steps = 0
        app._update_token_pixels(0)
        game.record_roll(4)
        game.apply_move(next(move for move in game.legal_moves(4) if move.token_index == 0))
        for _ in range(4):
            app._update_token_pixels(1000)
        self.assertEqual(self.hop_sounds(bank), [("hop", 0), ("hop", 1), ("hop", 2), ("hop", 3)])

    def test_hops_wait_for_the_token_to_reach_each_cell(self) -> None:
        """A tiny frame that reaches no cell taps no hop yet."""

        app, game, bank = make_app_with_game()
        game.players[0].tokens[0].steps = 0
        app._update_token_pixels(0)
        game.record_roll(3)
        game.apply_move(next(move for move in game.legal_moves(3) if move.token_index == 0))
        app._update_token_pixels(1)
        self.assertEqual(self.hop_sounds(bank), [])

    def test_hops_stop_once_the_screen_leaves_play(self) -> None:
        """A token still easing home after the game ends taps no hops over the jingle.

        The winning move ends the game at once, and the shell switches to the
        game-over screen while the token is still animating; its remaining
        hop taps must not play on top of the win jingle. The same holds after
        Save or New sends the player back to setup mid-hop.
        """

        app, game, bank = make_app_with_game()
        game.players[0].tokens[0].steps = 0
        app._update_token_pixels(0)
        game.record_roll(4)
        game.apply_move(next(move for move in game.legal_moves(4) if move.token_index == 0))
        app.screen = "over"
        app._update_token_pixels(1000)
        self.assertEqual(self.hop_sounds(bank), [])

    def test_slides_into_and_out_of_the_yard_do_not_hop(self) -> None:
        """Leaving the yard and being captured are single slides with their own sounds."""

        app, game, bank = make_app_with_game()
        app._update_token_pixels(0)
        game.record_roll(6)
        game.apply_move(game.legal_moves(6)[0])
        app._update_token_pixels(5000)
        game.players[0].tokens[0].steps = -1
        app._update_token_pixels(5000)
        self.assertEqual(self.hop_sounds(bank), [])

    def test_every_button_clicks(self) -> None:
        """A setup button press plays the click."""

        app = main.LudoApp(persist=False)
        app.sounds = mock.Mock()
        buttons = {button.key: button for button in app.setup_buttons()}
        app._handle_click(buttons["toggle_blockades"].rect.center)
        self.assertEqual(played(app.sounds), [("click", 0)])

    def test_clicks_off_any_button_are_silent(self) -> None:
        """A click on empty wallpaper plays nothing."""

        app = main.LudoApp(persist=False)
        app.sounds = mock.Mock()
        app._handle_click((5, 5))
        app.sounds.play.assert_not_called()


class LudoMusicTests(unittest.TestCase):
    """The folk loop is the right length, loops seamlessly and stays in bounds."""

    def test_loop_length_matches_its_bars_and_tempo(self) -> None:
        """The loop is MUSIC_BARS bars at MUSIC_BPM, between 16 and 32 seconds."""

        self.assertAlmostEqual(MUSIC_LOOP_SECONDS, MUSIC_BARS * MUSIC_BEATS_PER_BAR * 60.0 / MUSIC_BPM)
        self.assertGreaterEqual(MUSIC_LOOP_SECONDS, 16.0)
        self.assertLessEqual(MUSIC_LOOP_SECONDS, 32.0)

    def test_track_loops_cleanly(self) -> None:
        """The loop renders to its length, starts and ends near silence and never clips."""

        notes = music_notes()
        samples = render(notes, RATE, 1, total=MUSIC_LOOP_SECONDS)
        self.assertEqual(len(samples), round(MUSIC_LOOP_SECONDS * RATE))
        self.assertLess(abs(samples[0]), 300)
        self.assertLess(abs(samples[-1]), 300)
        self.assertLess(max(abs(value) for value in samples), 0.95 * 32767)

    def test_every_note_fits_inside_the_loop(self) -> None:
        """No note rings past the loop's end, so the restart never cuts one off."""

        notes = music_notes()
        self.assertTrue(all(note.start >= 0.0 and note.end <= MUSIC_LOOP_SECONDS + 1e-9 for note in notes))
        self.assertTrue(all(note.voice in audio.VOICES for note in notes))

    def test_track_is_deterministic(self) -> None:
        """Building the loop twice gives the same notes."""

        self.assertEqual(music_notes(), music_notes())

    def test_jingles_are_major_up_and_minor_down(self) -> None:
        """The win jingle climbs and the lose jingle falls, each 1.2 to 3 seconds long."""

        for name, rising in (("win", True), ("lose", False)):
            notes = SFX_RECIPES[name]
            melody = sorted((note for note in notes if note.voice != "noise"), key=lambda note: note.start)
            first, last = melody[0].freq, max(melody, key=lambda note: note.start).freq
            with self.subTest(name=name):
                self.assertEqual(last > first, rising)
                self.assertGreaterEqual(max(note.end for note in notes), 1.2)
                self.assertLessEqual(max(note.end for note in notes), 3.0)


class ShellMusicTests(unittest.TestCase):
    """The window plays the loop, and answers the end of a game with a jingle."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once so the app can open its dummy window."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after these tests."""

        pygame.quit()

    def test_music_starts_when_the_app_opens(self) -> None:
        """The app builds the loop's player and asks it to fade in at once."""

        with mock.patch.object(main.audio, "MusicPlayer") as player_class:
            main.LudoApp(persist=False)
        player_class.assert_called_once_with(music_notes, MUSIC_LOOP_SECONDS, MUSIC_VOLUME)
        player_class.return_value.start.assert_called_once_with(MUSIC_FADE_IN_MS)

    def test_every_frame_updates_the_music(self) -> None:
        """``_update`` gives the music player its per-frame turn, on every screen."""

        app = main.LudoApp(persist=False)
        music = app.music = mock.Mock()
        app._update(autotest=False)
        app._update(autotest=False)
        self.assertEqual(music.update.call_count, 2)

    def finish(self, human_seats: int, winner: int) -> tuple[main.LudoApp, mock.Mock, mock.Mock]:
        """Return an app whose game seat ``winner`` has just won, after one update.

        Also returns the mock bank and the mock music player standing in for
        the real ones.
        """

        app, game, bank = make_app_with_game(human_seats)
        music = app.music = mock.Mock()
        for token in game.players[winner].tokens:
            token.steps = game.layout.finish_steps
        game._finish_game(winner)
        app._update(autotest=False)
        return app, bank, music

    def test_a_human_win_fades_the_music_under_the_win_jingle(self) -> None:
        """A human winner: music fades out and the win jingle plays, once."""

        app, bank, music = self.finish(human_seats=1, winner=0)
        self.assertEqual(app.screen, "over")
        music.stop.assert_called_once_with(MUSIC_GAME_OVER_FADE_MS)
        self.assertEqual([name for name, _ in played(bank)], ["win"])
        app._update(autotest=False)
        self.assertEqual([name for name, _ in played(bank)], ["win"])

    def test_an_ai_win_over_humans_plays_the_lose_jingle(self) -> None:
        """A computer beat the human table: the gentle lose jingle plays."""

        _app, bank, music = self.finish(human_seats=1, winner=2)
        music.stop.assert_called_once_with(MUSIC_GAME_OVER_FADE_MS)
        self.assertEqual([name for name, _ in played(bank)], ["lose"])

    def test_an_all_computer_game_ends_with_the_win_jingle(self) -> None:
        """With nobody to disappoint, an all-AI game celebrates its winner."""

        _app, bank, _music = self.finish(human_seats=0, winner=1)
        self.assertEqual([name for name, _ in played(bank)], ["win"])

    def test_new_game_after_the_end_brings_the_music_back(self) -> None:
        """Leaving the game-over screen for setup fades the loop back in."""

        app, _bank, music = self.finish(human_seats=1, winner=0)
        music.reset_mock()
        app._on_button("new_game")
        self.assertEqual(app.screen, "setup")
        music.start.assert_called_once_with(MUSIC_FADE_IN_MS)


class SoundSettingTests(unittest.TestCase):
    """Ctrl+M and the Sound buttons switch all sound off and on, and the choice is saved."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once so the app can open its dummy window."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after these tests."""

        pygame.quit()

    def setUp(self) -> None:
        """Point the app's save folder and stats file at a fresh temp folder."""

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.save_dir = Path(temp.name) / "Ludo"
        self.stats_path = self.save_dir / "stats.json"
        for name, value in (("SAVE_DIR", self.save_dir), ("STATS_PATH", self.stats_path)):
            patcher = mock.patch.object(main, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_stats(self, payload: object) -> None:
        """Write ``payload`` as the on-disk stats JSON."""

        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.stats_path.write_text(json.dumps(payload), encoding="utf-8")

    def make_app(self, persist: bool = False) -> tuple[main.LudoApp, mock.Mock, mock.Mock]:
        """Return an app with a mock bank and mock music player (whose mute state starts applied)."""

        with mock.patch.object(main.audio, "MusicPlayer") as player_class:
            app = main.LudoApp(persist=persist)
        app.sounds = bank = mock.Mock()
        return app, bank, player_class.return_value

    def ctrl_m(self, app: main.LudoApp) -> None:
        """Press Ctrl+M."""

        app._handle_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_m, mod=pygame.KMOD_LCTRL, unicode="\r"))

    def test_sound_is_on_without_a_saved_choice(self) -> None:
        """A missing stats file, or one without the key, leaves sound on."""

        self.assertIs(main.load_stats()["sound"], True)
        self.write_stats({"games": 2})
        self.assertIs(main.load_stats()["sound"], True)

    def test_only_a_real_false_turns_sound_off(self) -> None:
        """JSON false mutes; damaged values (text, numbers, null, lists) fall back to on."""

        for value, expected in ((False, False), (True, True), ("off", True), (0, True), (None, True), ([], True)):
            with self.subTest(value=value):
                self.write_stats({"sound": value})
                self.assertIs(main.load_stats()["sound"], expected)

    def test_saved_off_starts_the_app_silent(self) -> None:
        """A saved "sound": false mutes the effects bank and the music from the first frame."""

        self.write_stats({"sound": False})
        with mock.patch.object(main.audio, "MusicPlayer") as player_class:
            app = main.LudoApp(persist=False)
        self.assertTrue(app.sounds.muted)
        player_class.return_value.set_muted.assert_called_with(True)

    def test_ctrl_m_switches_sound_off_and_back_on(self) -> None:
        """Ctrl+M mutes the bank and stops the music; again unmutes, resumes and clicks."""

        app, bank, music = self.make_app()
        music.reset_mock()
        self.ctrl_m(app)
        self.assertIs(app.stats["sound"], False)
        self.assertTrue(bank.muted)
        music.set_muted.assert_called_once_with(True)
        bank.play.assert_not_called()
        self.ctrl_m(app)
        self.assertIs(app.stats["sound"], True)
        self.assertFalse(bank.muted)
        music.set_muted.assert_called_with(False)
        bank.play.assert_called_once_with("click")

    def test_ctrl_m_works_on_every_screen(self) -> None:
        """Setup, a game, and the game-over screen all accept Ctrl+M."""

        app, _bank, _music = self.make_app()
        for screen in ("setup", "playing", "over"):
            with self.subTest(screen=screen):
                if screen == "playing":
                    app.start_game(LudoGame([("A", True), ("B", False), ("C", False), ("D", False)],
                                            LudoRules(total_players=4), seed=1))
                app.screen = screen
                before = app.stats["sound"]
                self.ctrl_m(app)
                self.assertIs(app.stats["sound"], not before)

    def test_ctrl_m_does_not_type_into_a_name_and_plain_m_still_does(self) -> None:
        """With a name field focused, Ctrl+M toggles sound and plain M types an m."""

        app, _bank, _music = self.make_app()
        app.active_field = 0
        app.name_fields[0] = "Ann"
        self.ctrl_m(app)
        self.assertEqual(app.name_fields[0], "Ann")
        self.assertIs(app.stats["sound"], False)
        app._handle_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_m, mod=0, unicode="m"))
        self.assertEqual(app.name_fields[0], "Annm")
        self.assertIs(app.stats["sound"], False)

    def test_setup_toggle_shows_and_flips_the_setting(self) -> None:
        """The setup screen's Sound button reads On/Off and a click flips it."""

        app, _bank, _music = self.make_app()
        button = next(button for button in app.setup_buttons() if button.key == "toggle_sound")
        self.assertEqual(button.text, "Sound: On")
        app._handle_click(button.rect.center)
        self.assertIs(app.stats["sound"], False)
        button = next(button for button in app.setup_buttons() if button.key == "toggle_sound")
        self.assertEqual(button.text, "Sound: Off")

    def test_play_screen_pill_flips_the_setting(self) -> None:
        """During a game the Sound pill beside the dice tray flips the setting too."""

        app, _bank, _music = self.make_app()
        app.start_game(LudoGame([("A", True), ("B", False), ("C", False), ("D", False)],
                                LudoRules(total_players=4), seed=1))
        keys = {button.key: button for button in app._buttons_for_screen()}
        self.assertEqual(keys["toggle_sound"].text, "Sound: On")
        app._handle_click(main.PLAY_SOUND_RECT.center)
        self.assertIs(app.stats["sound"], False)
        self.assertEqual(app.screen, "playing")

    def test_choice_survives_a_restart(self) -> None:
        """A persisting app saves the choice to stats.json, and the next app starts muted."""

        app, _bank, _music = self.make_app(persist=True)
        self.ctrl_m(app)
        self.assertIs(json.loads(self.stats_path.read_text(encoding="utf-8"))["sound"], False)
        self.assertTrue(main.LudoApp(persist=False).sounds.muted)
        self.ctrl_m(app)
        self.assertIs(json.loads(self.stats_path.read_text(encoding="utf-8"))["sound"], True)

    def test_choice_keeps_the_lifetime_stats(self) -> None:
        """Saving the sound choice rewrites stats.json without losing any counter."""

        self.write_stats({"games": 5, "human_wins": 2, "ai_wins": 3, "turn_total": 77})
        app, _bank, _music = self.make_app(persist=True)
        self.ctrl_m(app)
        saved = json.loads(self.stats_path.read_text(encoding="utf-8"))
        self.assertEqual((saved["games"], saved["human_wins"], saved["turn_total"], saved["sound"]), (5, 2, 77, False))

    def test_non_persisting_app_never_writes_the_choice(self) -> None:
        """persist=False (the autotest) toggles in memory only."""

        app, _bank, _music = self.make_app(persist=False)
        self.ctrl_m(app)
        self.assertIs(app.stats["sound"], False)
        self.assertFalse(self.stats_path.exists())


class SoundToggleLayoutTests(unittest.TestCase):
    """The Sound buttons fit their labels and stay clear of everything around them."""

    app: main.LudoApp

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame and build one app for the layout checks."""

        pygame.init()
        cls.app = main.LudoApp(persist=False)

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the layout checks."""

        pygame.quit()

    def test_labels_fit_with_margin(self) -> None:
        """Both labels leave at least 8 px each side in either button, in this platform's font."""

        font = self.app.fonts["button"]
        for rect in (main.SETUP_SOUND_RECT, main.PLAY_SOUND_RECT):
            for label in ("Sound: On", "Sound: Off"):
                with self.subTest(rect=rect, label=label):
                    width, height = font.size(label)
                    self.assertLessEqual(width + 16, rect.width)
                    self.assertLessEqual(height + 4, rect.height)

    def test_setup_toggle_clears_the_title_and_every_control(self) -> None:
        """The setup Sound button overlaps no other button, name field, title or option label."""

        self.app.total_players = 6
        self.app.human_count = 6
        buttons = self.app.setup_buttons()
        sound = next(button.rect for button in buttons if button.key == "toggle_sound")
        others = [(button.key, button.rect) for button in buttons if button.key != "toggle_sound"]
        others += [(f"name {index}", main._name_rect(index)) for index in range(6)]
        title = pygame.Rect((main.PANEL_X + 24, 42), self.app.fonts["title"].size("Setup"))
        label = pygame.Rect((main.SETUP_CONTROL_X, main.SETUP_OPTION_LABEL_START_Y),
                            self.app.fonts["body"].size("Total Players"))
        others += [("Setup title", title.inflate(16, 0)), ("Total Players label", label.inflate(16, 8))]
        for name, rect in others:
            with self.subTest(other=name):
                self.assertFalse(sound.colliderect(rect), f"Sound {sound} overlaps {name} {rect}")

    def test_play_pill_clears_the_other_table_controls(self) -> None:
        """The in-game Sound pill sits on the canvas, clear of the tray, Save, New, moves and log."""

        pill = main.PLAY_SOUND_RECT
        self.assertTrue(pygame.Rect(0, 0, main.SCREEN_WIDTH, main.SCREEN_HEIGHT).contains(pill))
        others = [
            ("dice tray", main.PLAY_DICE_TRAY_RECT),
            ("save", main.PLAY_SAVE_RECT),
            ("new", main.PLAY_NEW_RECT),
            ("log", main.PLAY_LOG_RECT),
            *((f"move {index}", main._move_button_rect(index)) for index in range(4)),
        ]
        for name, rect in others:
            with self.subTest(other=name):
                self.assertFalse(pill.inflate(8, 8).colliderect(rect), f"Sound pill overlaps {name}")

    def test_pill_labels_are_readable_on_and_off(self) -> None:
        """Both pill fills, idle or hovered, give a label colour above the contrast target."""

        for on in (True, False):
            for hovered in (False, True):
                color = main._sound_pill_color(on, hovered)
                fill = theme.darken(color, theme.PILL_SHADE)
                with self.subTest(on=on, hovered=hovered):
                    self.assertGreaterEqual(theme.contrast_ratio(theme.readable_on(fill), fill), LABEL_CONTRAST_TARGET)
                    self.assertNotEqual(main._sound_pill_color(True, hovered), main._sound_pill_color(False, hovered))


class MixerStartupTests(unittest.TestCase):
    """``main.main`` asks for the mixer format before pygame starts, and reserves music after."""

    def test_mixer_is_set_up_around_pygame_init(self) -> None:
        """Order: init_mixer, pygame.init, reserve_channels, then the app runs."""

        order = mock.Mock()
        with (
            mock.patch.object(main.audio, "init_mixer", order.init_mixer),
            mock.patch.object(main.pygame, "init", order.init),
            mock.patch.object(main.audio, "reserve_channels", order.reserve_channels),
            mock.patch.object(main, "LudoApp", order.LudoApp),
            mock.patch.object(main.pygame, "quit", order.quit),
            mock.patch.dict(os.environ, {"LUDO_AUTOTEST": ""}),
        ):
            main.main()
        names = [name for name, _args, _kwargs in order.mock_calls]
        self.assertEqual(names[:4], ["init_mixer", "init", "reserve_channels", "LudoApp"])


class MusicPlayerTests(unittest.TestCase):
    """The music player renders its loop once and drives one reserved channel."""

    NOTES = [Note(220.0, 0.0, 0.1, "sine", 0.2), Note(330.0, 0.05, 0.1, "triangle", 0.2)]

    def setUp(self) -> None:
        """Start the dummy mixer and capture the music channel."""

        pygame.mixer.init()
        self.addCleanup(pygame.mixer.quit)
        self.channel = mock.Mock()
        patcher = mock.patch.object(pygame.mixer, "Channel", return_value=self.channel)
        self.channel_factory = patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, threaded: bool = False) -> MusicPlayer:
        """Build a short 0.25 s loop on reserved channel 1."""

        return MusicPlayer(lambda: list(self.NOTES), 0.25, 0.2, threaded=threaded, channel=1)

    def test_start_plays_the_loop_forever_on_its_channel(self) -> None:
        """``start`` loops the track on its channel at its volume, with the fade-in."""

        player = self.make()
        self.assertTrue(player.is_ready)
        player.start(300)
        self.channel_factory.assert_called_with(1)
        self.channel.set_volume.assert_called_once_with(0.2)
        sound = self.channel.play.call_args.args[0]
        self.assertEqual(self.channel.play.call_args.kwargs, {"loops": -1, "fade_ms": 300})
        self.assertAlmostEqual(sound.get_length(), 0.25, places=3)
        player.update()
        self.assertEqual(self.channel.play.call_count, 1)

    def test_loop_is_rendered_exactly_its_length(self) -> None:
        """The loop buffer is ``total`` seconds long for every channel layout."""

        for channels in (1, 2, 4, 6, 8):
            with (
                self.subTest(channels=channels),
                mock.patch.object(pygame.mixer, "get_init", return_value=(RATE, -16, channels)),
                mock.patch.object(pygame.mixer, "Sound") as fake_sound,
            ):
                self.make().update()
                self.assertEqual(len(fake_sound.call_args.kwargs["buffer"]), round(0.25 * RATE) * channels * 2)

    def test_stop_fades_or_cuts(self) -> None:
        """``stop`` fades out over the given time, or stops at once for 0."""

        player = self.make()
        player.start()
        player.stop(500)
        self.channel.fadeout.assert_called_once_with(500)
        player.start()
        player.stop()
        self.channel.stop.assert_called_once_with()
        player.stop()
        self.assertEqual(self.channel.stop.call_count, 1)

    def test_mute_stops_the_music_and_unmute_resumes_it(self) -> None:
        """Muting stops the channel at once; unmuting restarts a wanted track."""

        player = self.make()
        player.start()
        player.set_muted(True)
        self.channel.stop.assert_called_once_with()
        player.update()
        self.assertEqual(self.channel.play.call_count, 1)
        player.set_muted(False)
        self.assertEqual(self.channel.play.call_count, 2)

    def test_muted_player_does_not_start(self) -> None:
        """A track started while muted stays silent until unmuted."""

        player = self.make()
        player.set_muted(True)
        player.start()
        self.channel.play.assert_not_called()

    def test_threaded_render_plays_once_ready(self) -> None:
        """A daemon thread renders the loop; ``update`` starts it once it is done."""

        with mock.patch.object(audio.threading, "Thread") as thread_class:
            player = self.make(threaded=True)
        kwargs = thread_class.call_args.kwargs
        self.assertTrue(kwargs["daemon"])
        thread_class.return_value.start.assert_called_once_with()
        player.start()
        self.assertFalse(player.is_ready)
        self.channel.play.assert_not_called()
        kwargs["target"](*kwargs["args"])
        self.assertTrue(player.is_ready)
        player.update()
        self.assertEqual(self.channel.play.call_count, 1)

    def test_player_is_disabled_without_a_mixer(self) -> None:
        """No mixer: no render, no thread, and every call is a no-op."""

        with (
            mock.patch.object(pygame.mixer, "get_init", return_value=None),
            mock.patch.object(audio.threading, "Thread") as thread_class,
        ):
            player = self.make(threaded=True)
            player.start()
            player.update()
            player.stop(100)
        self.assertFalse(player.enabled)
        thread_class.assert_not_called()
        self.channel_factory.assert_not_called()

    def test_sound_build_error_disables_the_player(self) -> None:
        """A mixer error while making the Sound disables the player quietly."""

        player = self.make()
        with mock.patch.object(pygame.mixer, "Sound", side_effect=pygame.error("broken")):
            player.start()
        self.assertFalse(player.enabled)
        self.channel.play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
