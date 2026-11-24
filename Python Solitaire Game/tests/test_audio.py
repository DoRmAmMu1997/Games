"""Headless tests for the procedural audio in ``audio.py`` and its game wiring.

Nothing here listens to sound. The tests check the sample buffers the
synthesizer produces and the calls the bank makes on (mocked) mixer channels,
under SDL's dummy audio driver. Solitaire uses pygame for its mixer only; no
test opens a pygame display or a Tk window.
"""

from __future__ import annotations

import array
import ast
import json
import os
import random
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
from audio import LIMIT, MusicPlayer, Note, SoundBank, midi, render
from solitaire import (
    FOUNDATION_CHIME_STEPS,
    MUSIC_BARS,
    MUSIC_BEATS_PER_BAR,
    MUSIC_BPM,
    MUSIC_FADE_IN_MS,
    MUSIC_LOOP_SECONDS,
    MUSIC_VOLUME,
    SFX_COOLDOWNS,
    SFX_RECIPES,
    KlondikeGame,
    SilentAudio,
    SolitaireAudio,
    music_notes,
    open_audio,
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
        patcher = mock.patch.object(SoundBank, "_effect_channel", return_value=self.channel)
        self.effect_channel = patcher.start()
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
        self.effect_channel.assert_called_once_with()
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
        self.effect_channel.assert_not_called()

    def test_no_free_channel_is_silent(self) -> None:
        """When no channel is free the sound is skipped without error."""

        self.effect_channel.return_value = None
        self.bank.play("tick")
        self.assertEqual(self.played(), [])

    def test_bank_is_disabled_without_a_mixer(self) -> None:
        """No mixer: the bank is disabled, empty and silent."""

        with mock.patch.object(pygame.mixer, "get_init", return_value=None):
            bank = SoundBank(self.RECIPES)
        bank.play("beep")
        self.assertFalse(bank.enabled)
        self.assertEqual(bank.sounds, {})
        self.effect_channel.assert_not_called()

    def test_bank_is_disabled_when_a_sound_fails_to_build(self) -> None:
        """A mixer error while building disables the whole bank."""

        with mock.patch.object(pygame.mixer, "Sound", side_effect=pygame.error("broken")):
            bank = SoundBank(self.RECIPES)
        self.assertFalse(bank.enabled)
        self.assertEqual(bank.sounds, {})


class EffectChannelTests(unittest.TestCase):
    """Effects never take the reserved music channel, and muting silences them at once.

    pygame's ``find_channel`` ignores reserved channels (it can return the
    music channel when it is the only one free, or steal it as the longest
    playing when every channel is busy), so the bank picks channels itself.
    These tests use the real dummy mixer, with long silent sounds standing in
    for the music and for effects already playing.
    """

    def setUp(self) -> None:
        """Start the dummy mixer with 16 channels, the first one reserved for music."""

        pygame.mixer.init()
        self.addCleanup(pygame.mixer.quit)
        audio.reserve_channels(1)
        self.long = pygame.mixer.Sound(buffer=array.array("h", [0] * RATE * 2 * 10).tobytes())
        self.music = pygame.mixer.Channel(0)
        self.music.play(self.long, loops=-1)
        self.bank = SoundBank({"beep": [Note(440.0, 0.0, 0.05, "sine", 0.3)]})

    def effect_channels(self) -> list[pygame.mixer.Channel]:
        """Return every channel the bank may use for effects."""

        return [pygame.mixer.Channel(index) for index in range(1, pygame.mixer.get_num_channels())]

    def test_a_busy_mixer_never_steals_the_music_channel(self) -> None:
        """With every effect channel busy, a new effect replaces an effect, not the music."""

        for channel in self.effect_channels():
            channel.play(self.long)
        self.bank.play("beep")
        self.assertIs(self.music.get_sound(), self.long)
        self.assertIn(self.bank.sounds["beep"], [channel.get_sound() for channel in self.effect_channels()])

    def test_an_idle_music_channel_is_still_not_used_for_effects(self) -> None:
        """Even when the reserved channel is the only idle one, effects stay off it."""

        self.music.stop()
        for channel in self.effect_channels():
            channel.play(self.long)
        self.bank.play("beep")
        self.assertFalse(self.music.get_busy())

    def test_muting_stops_effects_already_playing_but_not_the_music(self) -> None:
        """Switching sound off silences a jingle mid-play; the music player handles its own channel."""

        self.bank.play("beep")
        self.assertTrue(any(channel.get_busy() for channel in self.effect_channels()))
        self.bank.muted = True
        self.assertFalse(any(channel.get_busy() for channel in self.effect_channels()))
        self.assertTrue(self.music.get_busy())


class ImportTests(unittest.TestCase):
    """The audio core can be imported without loading pygame."""

    def test_pygame_is_only_imported_inside_functions(self) -> None:
        """No top-level statement of ``audio.py`` imports pygame.

        solitaire.py imports ``Note`` and ``midi`` from the core at the top
        of the file, next to the rules engine, so the core must not pull
        pygame in at import time.
        """

        tree = ast.parse(Path(audio.__file__).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                self.assertNotIn("pygame", [alias.name.split(".")[0] for alias in node.names])
            if isinstance(node, ast.ImportFrom):
                self.assertNotEqual((node.module or "").split(".")[0], "pygame")


class SolitaireRecipeTests(unittest.TestCase):
    """Solitaire's own recipes are complete, well formed and well behaved."""

    def test_every_planned_sound_exists(self) -> None:
        """Each table action in the sound plan has a recipe."""

        for name in ("select", "place", "foundation", "flip", "draw", "recycle", "empty", "invalid", "undo",
                     "hint", "deal", "auto_step", "click"):
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

    def test_foundation_chimes_rise_with_rank(self) -> None:
        """Ace to King each have a chime variant, and each one sits higher than the last."""

        for base in ("foundation", "auto_step"):
            pitches = []
            for rank in range(1, FOUNDATION_CHIME_STEPS + 1):
                with self.subTest(base=base, rank=rank):
                    self.assertIn(f"{base}@{rank}", SFX_RECIPES)
                pitches.append(min(note.freq for note in SFX_RECIPES[f"{base}@{rank}"] if note.voice != "noise"))
            self.assertEqual(pitches, sorted(set(pitches)))

    def test_jingles_last_a_moment_and_point_the_right_way(self) -> None:
        """The win jingle climbs, the loss jingle falls, and each lasts 1.2 to 3 seconds."""

        for name in ("win", "lose"):
            notes = SFX_RECIPES[name]
            with self.subTest(name=name):
                self.assertGreaterEqual(max(note.end for note in notes), 1.2)
                self.assertLessEqual(max(note.end for note in notes), 3.0)
        rising = [note.freq for note in SFX_RECIPES["win"] if note.voice == "sine" and note.start < 0.5]
        falling = [note.freq for note in SFX_RECIPES["lose"] if note.voice == "triangle"]
        self.assertEqual(rising, sorted(rising))
        self.assertGreater(len(rising), 2)
        self.assertEqual(falling, sorted(falling, reverse=True))
        self.assertGreater(len(falling), 2)

    def test_effects_stay_short(self) -> None:
        """Table effects (not the jingles) are over in well under a second."""

        for name, notes in SFX_RECIPES.items():
            if name in ("win", "lose"):
                continue
            with self.subTest(name=name):
                self.assertLessEqual(max(note.end for note in notes), 0.7)


class SolitaireAudioTests(unittest.TestCase):
    """The app's sound wrapper opens pygame's mixer only, and falls back to silence."""

    def setUp(self) -> None:
        """Make sure every test leaves the mixer closed."""

        self.addCleanup(pygame.mixer.quit)

    def test_open_audio_prepares_starts_and_reserves_in_order(self) -> None:
        """The mixer format is requested before the mixer starts; channels are reserved after."""

        order: list[str] = []
        with (
            mock.patch.object(audio, "init_mixer", side_effect=lambda: order.append("pre_init")),
            mock.patch.object(pygame.mixer, "init", side_effect=lambda: order.append("init")),
            mock.patch.object(audio, "reserve_channels", side_effect=lambda: order.append("reserve")),
        ):
            sound = open_audio()
        self.assertIsInstance(sound, SolitaireAudio)
        self.assertEqual(order, ["pre_init", "init", "reserve"])

    def test_open_audio_builds_the_bank_without_a_display(self) -> None:
        """With the dummy driver the bank is live, pygame's display stays closed, and pygame keeps quiet."""

        with mock.patch.dict(os.environ):
            os.environ.pop("PYGAME_HIDE_SUPPORT_PROMPT", None)
            sound = open_audio()
            self.assertEqual(os.environ["PYGAME_HIDE_SUPPORT_PROMPT"], "1")
        assert isinstance(sound, SolitaireAudio)
        self.assertTrue(sound.bank.enabled)
        self.assertIsNotNone(pygame.mixer.get_init())
        self.assertFalse(pygame.display.get_init())

    def test_missing_pygame_gives_silence(self) -> None:
        """Without pygame installed the game runs silently."""

        with mock.patch.dict(sys.modules, {"pygame": None}):
            sound = open_audio()
        self.assertIsInstance(sound, SilentAudio)

    def test_missing_audio_device_gives_silence(self) -> None:
        """A machine whose mixer cannot start runs silently."""

        with mock.patch.object(pygame.mixer, "init", side_effect=pygame.error("no audio device")):
            sound = open_audio()
        self.assertIsInstance(sound, SilentAudio)

    def test_play_forwards_the_name_and_pitch(self) -> None:
        """``play`` hands the sound name and pitch step to the bank."""

        sound = SolitaireAudio()
        bank = sound.bank = mock.Mock()
        sound.play("foundation", pitch_step=4)
        bank.play.assert_called_once_with("foundation", pitch_step=4)

    def test_close_quits_the_mixer(self) -> None:
        """Closing the sound shuts the mixer down, and a mixer error is ignored."""

        pygame.mixer.init()
        sound = SolitaireAudio()
        sound.close()
        self.assertIsNone(pygame.mixer.get_init())
        with mock.patch.object(pygame.mixer, "quit", side_effect=pygame.error("gone")):
            sound.close()

    def test_music_player_loops_the_lofi_tune(self) -> None:
        """The wrapper's music player loops ``music_notes`` for the loop length at the music volume."""

        with mock.patch.object(audio, "MusicPlayer") as player_class:
            SolitaireAudio(threaded=False)
        player_class.assert_called_once_with(music_notes, MUSIC_LOOP_SECONDS, MUSIC_VOLUME, threaded=False)

    def test_music_calls_reach_the_player(self) -> None:
        """Starting fades the tune in, stopping fades it out, and the tick updates the player."""

        sound = SolitaireAudio(threaded=False)
        music = sound.music = mock.Mock()
        sound.start_music()
        sound.stop_music(700)
        sound.update()
        music.start.assert_called_once_with(MUSIC_FADE_IN_MS)
        music.stop.assert_called_once_with(700)
        music.update.assert_called_once_with()

    def test_mute_silences_effects_and_music_together(self) -> None:
        """``set_muted`` mutes the bank and stops the music; unmuting restores both."""

        sound = SolitaireAudio(threaded=False)
        music = sound.music = mock.Mock()
        sound.set_muted(True)
        self.assertTrue(sound.bank.muted)
        music.set_muted.assert_called_once_with(True)
        sound.set_muted(False)
        self.assertFalse(sound.bank.muted)
        music.set_muted.assert_called_with(False)

    def test_silent_audio_ignores_every_request(self) -> None:
        """The silent stand-in accepts every call and does nothing."""

        silent = SilentAudio()
        silent.play("deal")
        silent.play("foundation", pitch_step=3)
        silent.start_music()
        silent.stop_music(500)
        silent.update()
        silent.set_muted(True)
        silent.close()


class SolitaireMusicTests(unittest.TestCase):
    """The lo-fi piano loop is the right length, repeatable and seamless."""

    def test_loop_length_matches_the_bars(self) -> None:
        """The loop is its bars of four beats at the tempo, between 16 and 32 seconds."""

        self.assertAlmostEqual(MUSIC_LOOP_SECONDS, MUSIC_BARS * MUSIC_BEATS_PER_BAR * 60.0 / MUSIC_BPM)
        self.assertGreaterEqual(MUSIC_LOOP_SECONDS, 16.0)
        self.assertLessEqual(MUSIC_LOOP_SECONDS, 32.0)

    def test_loop_renders_cleanly(self) -> None:
        """The loop renders to its length, starts and ends near silence, and never clips."""

        notes = music_notes()
        samples = render(notes, RATE, 1, total=MUSIC_LOOP_SECONDS)
        self.assertEqual(len(samples), round(MUSIC_LOOP_SECONDS * RATE))
        self.assertLess(abs(samples[0]), 300)
        self.assertLess(abs(samples[-1]), 300)
        self.assertLess(max(abs(value) for value in samples), 0.95 * 32767)
        self.assertTrue(all(note.end <= MUSIC_LOOP_SECONDS + 1e-9 for note in notes))
        self.assertTrue(all(note.voice in audio.VOICES for note in notes))

    def test_loop_is_deterministic(self) -> None:
        """Building the loop twice gives exactly the same notes."""

        self.assertEqual(music_notes(), music_notes())

    def test_every_bar_has_music(self) -> None:
        """Each bar of the loop holds notes, so the tune never drops out."""

        bar_seconds = MUSIC_LOOP_SECONDS / MUSIC_BARS
        bars = {int(note.start // bar_seconds) for note in music_notes()}
        self.assertEqual(bars, set(range(MUSIC_BARS)))


class SoundSettingTests(unittest.TestCase):
    """The sound on/off choice is saved in the score file and kept out of Undo."""

    def setUp(self) -> None:
        """Point a game at a score file in a throwaway folder."""

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "scores.json"

    def make_game(self) -> KlondikeGame:
        """Build a seeded game that reads and writes the throwaway score file."""

        return KlondikeGame(str(self.path), rng=random.Random(5))

    def write(self, data: object) -> None:
        """Replace the score file with `data` as JSON."""

        self.path.write_text(json.dumps(data), encoding="utf-8")

    def test_sound_is_on_by_default(self) -> None:
        """A first run (no score file) starts with sound on."""

        self.assertFalse(self.make_game().sound_muted)

    def test_mute_survives_a_save_and_load(self) -> None:
        """A saved mute is read back by the next game, next to the statistics."""

        game = self.make_game()
        game.wins = 4
        game.sound_muted = True
        game.save_high_score()

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIs(saved["muted"], True)
        again = self.make_game()
        self.assertTrue(again.sound_muted)
        self.assertEqual(again.wins, 4)

    def test_only_a_real_true_mutes(self) -> None:
        """Anything but JSON ``true`` in the file reads as sound on."""

        for value in ("yes", 1, None, [True], {"on": False}, False):
            with self.subTest(value=value):
                self.write({"muted": value})
                self.assertIs(self.make_game().sound_muted, False)
        self.write({"muted": True})
        self.assertIs(self.make_game().sound_muted, True)

    def test_mute_stays_out_of_undo(self) -> None:
        """Snapshots do not carry the setting, and restoring one keeps the current choice."""

        game = self.make_game()
        snapshot = game.snapshot()
        self.assertNotIn("muted", snapshot)
        game.sound_muted = True
        game.restore_snapshot(snapshot)
        self.assertTrue(game.sound_muted)
        self.assertTrue(json.loads(self.path.read_text(encoding="utf-8"))["muted"])

    def test_statistics_saves_keep_the_setting(self) -> None:
        """Recording a win or a loss rewrites the file without losing the mute."""

        game = self.make_game()
        game.sound_muted = True
        game.record_win()
        game.record_loss()
        self.assertTrue(self.make_game().sound_muted)


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
