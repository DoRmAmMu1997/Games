"""Headless tests for the procedural audio in ``audio.py`` and its game wiring.

Nothing here listens to sound. The tests check the sample buffers the
synthesizer produces and the calls the bank makes on (mocked) mixer channels,
under SDL's dummy audio driver.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import pygame
from test_engine_regressions import rig_rolls

import audio
import main
from audio import LIMIT, MusicPlayer, Note, SoundBank, midi, render
from game import EVENT_KINDS, MonopolyGame
from settings import DICE_RESULT_AT, HOP_PITCH_STEPS, SFX_COOLDOWNS, SFX_RECIPES

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



class MonopolyRecipeTests(unittest.TestCase):
    """Monopoly's own effect recipes are complete, well formed and well behaved."""

    def test_every_event_sound_has_a_recipe(self) -> None:
        """Each effect the shell plays has a recipe."""

        for name in ("dice", "doubles", "three_doubles", "hop", "cha_ching", "buy", "rent", "tax", "card_chance",
                     "card_chest", "jail", "leave_jail", "build_house", "build_hotel", "sell", "mortgage",
                     "unmortgage", "auction_start", "bid", "gavel", "trade_proposed", "trade_accepted",
                     "trade_rejected", "raise_funds", "bankrupt", "click"):
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

    def test_brassy_squares_stay_low_and_soft(self) -> None:
        """The square voice is used sparingly: never above E5 and never loud, so nothing buzzes."""

        for name, notes in SFX_RECIPES.items():
            for note in notes:
                if note.voice == "square":
                    with self.subTest(name=name, freq=note.freq):
                        self.assertLessEqual(note.freq, midi(76) + 0.01)
                        self.assertLessEqual(note.volume, 0.25)

    def test_cooldowns_name_real_sounds(self) -> None:
        """Every cooldown belongs to a sound that exists."""

        for name in SFX_COOLDOWNS:
            with self.subTest(name=name):
                self.assertIn(name, SFX_RECIPES)

    def test_dice_rattle_then_land(self) -> None:
        """The dice tumble as noise ticks, then land with a clack at DICE_RESULT_AT."""

        notes = SFX_RECIPES["dice"]
        early = [note for note in notes if note.start < DICE_RESULT_AT]
        self.assertGreaterEqual(len(early), 4)
        self.assertTrue(all(note.voice == "noise" for note in early))
        self.assertTrue(any(note.start == DICE_RESULT_AT for note in notes))

    def test_doubles_cues_wait_for_the_dice_to_land(self) -> None:
        """The doubles chime and the three-doubles groan start once the dice have landed."""

        for name in ("doubles", "three_doubles"):
            with self.subTest(name=name):
                self.assertGreaterEqual(min(note.start for note in SFX_RECIPES[name]), DICE_RESULT_AT)

    def test_hops_climb_along_the_path(self) -> None:
        """Hop variants 1.. are built, and each hop sounds higher than the one before."""

        names = ["hop", *(f"hop@{step}" for step in range(1, HOP_PITCH_STEPS))]
        pitches = [SFX_RECIPES[name][0].freq for name in names]
        self.assertEqual(pitches, sorted(pitches))
        self.assertEqual(len(set(pitches)), HOP_PITCH_STEPS)
        self.assertGreaterEqual(HOP_PITCH_STEPS, 12, "two dice move a token up to 12 spaces")

    def test_go_is_a_cha_ching(self) -> None:
        """Passing GO plays a noise "cha" first, then a high bell "ching"."""

        notes = SFX_RECIPES["cha_ching"]
        first = min(notes, key=lambda note: note.start)
        bells = [note for note in notes if note.voice != "noise"]
        self.assertEqual(first.voice, "noise")
        self.assertTrue(bells)
        self.assertTrue(all(note.start > first.start for note in bells))
        self.assertTrue(all(note.freq >= midi(84) for note in bells))

    def test_the_two_card_decks_sound_different(self) -> None:
        """Chance and Community Chest each open with a paper flip, swept in opposite directions."""

        chance, chest = SFX_RECIPES["card_chance"], SFX_RECIPES["card_chest"]
        self.assertNotEqual(chance, chest)
        flips = [min(notes, key=lambda note: note.start) for notes in (chance, chest)]
        self.assertTrue(all(flip.voice == "noise" for flip in flips))
        self.assertGreater(flips[0].glide, 0)
        self.assertLess(flips[1].glide, 0)

    def test_jail_bars_are_low(self) -> None:
        """Every pitched note of the jail clang sits below middle C."""

        pitched = [note for note in SFX_RECIPES["jail"] if note.voice != "noise"]
        self.assertTrue(pitched)
        self.assertTrue(all(note.freq < midi(60) for note in pitched))

    def test_auction_win_bangs_a_gavel(self) -> None:
        """The auction win opens with two wooden knocks a moment apart."""

        knocks = sorted(note.start for note in SFX_RECIPES["gavel"] if note.voice == "noise")
        self.assertGreaterEqual(len(knocks), 2)
        self.assertEqual(knocks[0], 0.0)
        self.assertGreater(knocks[1], 0.1)

    def test_every_effect_is_fast_to_build(self) -> None:
        """Rendering every effect stays well inside the startup budget (generous for slow CI)."""

        import time

        start = time.perf_counter()
        for notes in SFX_RECIPES.values():
            render(notes, RATE, 2)
        self.assertLess(time.perf_counter() - start, 2.0)


def make_app_with_game(human_seats: int = 1) -> tuple[main.MonopolyApp, MonopolyGame, mock.Mock]:
    """Return a non-persisting app playing a seeded 4-seat game, with a mock sound bank.

    The first ``human_seats`` seats are human. The mock replaces the real
    bank, so tests can read exactly which sounds were asked for.
    """

    app = main.MonopolyApp(persist=False)
    game = MonopolyGame([(f"P{seat + 1}", seat < human_seats) for seat in range(4)], seed=3)
    app.start_game(game)
    app.sounds = mock.Mock()
    return app, game, app.sounds


def played(bank: mock.Mock) -> list[tuple[str, int]]:
    """Return ``(name, pitch_step)`` for every ``play`` call on a mock bank, in order."""

    return [(call.args[0], call.kwargs.get("pitch_step", 0)) for call in bank.play.call_args_list]


def names(bank: mock.Mock) -> list[str]:
    """Return just the effect names asked of a mock bank, in order."""

    return [name for name, _step in played(bank)]


class EventSoundMapTests(unittest.TestCase):
    """``main.event_sounds`` turns one frame's engine events into effect names."""

    def test_each_event_kind_has_its_sound(self) -> None:
        """Every sounding kind maps to its own effect."""

        cases = {
            "roll": "dice",
            "doubles": "doubles",
            "three_doubles_jail": "three_doubles",
            "go_salary": "cha_ching",
            "buy": "buy",
            "rent": "rent",
            "tax": "tax",
            "card_chance": "card_chance",
            "card_chest": "card_chest",
            "go_to_jail": "jail",
            "leave_jail": "leave_jail",
            "build_house": "build_house",
            "build_hotel": "build_hotel",
            "sell_building": "sell",
            "mortgage": "mortgage",
            "unmortgage": "unmortgage",
            "auction_start": "auction_start",
            "auction_bid": "bid",
            "auction_won": "gavel",
            "trade_proposed": "trade_proposed",
            "trade_accepted": "trade_accepted",
            "trade_rejected": "trade_rejected",
            "raise_funds": "raise_funds",
            "bankrupt": "bankrupt",
        }
        for kind, sound in cases.items():
            with self.subTest(kind=kind):
                self.assertEqual(main.event_sounds([kind]), [sound])

    def test_game_over_has_no_effect_of_its_own(self) -> None:
        """The end of the game is answered by the game-over jingle instead."""

        self.assertEqual(main.event_sounds(["bankrupt", "game_over"]), ["bankrupt"])

    def test_every_event_kind_is_known_to_the_map(self) -> None:
        """Each engine kind either has a sound or is the silent game_over."""

        self.assertEqual(set(main.EVENT_SOUNDS) | {"game_over"}, set(EVENT_KINDS))
        for name in main.EVENT_SOUNDS.values():
            with self.subTest(name=name):
                self.assertIn(name, SFX_RECIPES)

    def test_third_double_replaces_the_chime_and_the_clang(self) -> None:
        """A third double plays its own groan (which ends in the bars), not doubles and jail too."""

        kinds = ["roll", "doubles", "three_doubles_jail", "go_to_jail"]
        self.assertEqual(main.event_sounds(kinds), ["dice", "three_doubles"])

    def test_doubles_out_of_jail_sound_like_freedom(self) -> None:
        """Escaping Jail on doubles plays the release, not the doubles chime."""

        self.assertEqual(main.event_sounds(["roll", "doubles", "leave_jail"]), ["dice", "leave_jail"])

    def test_a_card_to_jail_flips_then_clangs(self) -> None:
        """A Go to Jail card still plays its flip and the jail bars."""

        self.assertEqual(main.event_sounds(["roll", "card_chance", "go_to_jail"]),
                         ["dice", "card_chance", "jail"])


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

    def test_app_builds_its_bank_from_the_monopoly_recipes(self) -> None:
        """The real app's bank is a SoundBank with every recipe (when a mixer is running)."""

        app = main.MonopolyApp(persist=False)
        self.assertIsInstance(app.sounds, SoundBank)
        if app.sounds.enabled:
            self.assertEqual(set(app.sounds.sounds), set(SFX_RECIPES))

    def test_update_plays_this_frame_s_events_once(self) -> None:
        """A human's roll onto Income Tax plays the dice and the tax, and the queue is emptied."""

        app, game, bank = make_app_with_game()
        rig_rolls(game, 1, 3)
        game.roll_dice()
        app._update(False)
        self.assertEqual([name for name in names(bank) if name != "hop"], ["dice", "tax"])
        self.assertEqual(game.events, [])
        bank.reset_mock()
        app._update(False)
        self.assertNotIn("dice", names(bank))

    def test_human_roll_button_rattles_the_dice(self) -> None:
        """Clicking Roll Dice plays the click, then the dice on the next update."""

        app, _game, bank = make_app_with_game()
        app._draw()
        button = next(button for button in app.buttons if button.key == "roll")
        app._handle_click(button.rect.center)
        app._update(False)
        self.assertEqual(names(bank)[:2], ["click", "dice"])

    def test_ai_turns_are_heard_too(self) -> None:
        """An AI roll goes through the engine, so the next frame plays its dice."""

        app, _game, bank = make_app_with_game(human_seats=0)
        app._update(True)
        app._update(True)
        self.assertIn("dice", names(bank))

    def test_finished_game_plays_its_last_events(self) -> None:
        """The bankruptcy that ends the game is still heard as the screen changes."""

        app, game, bank = make_app_with_game()
        for player in game.players[1:3]:
            player.bankrupt = True
        game._bankrupt(game.players[3], game.players[0])
        app._update(False)
        self.assertEqual(app.screen, "over")
        self.assertIn("bankrupt", names(bank))

    def hops_after(self, app: main.MonopolyApp, bank: mock.Mock, elapsed_ms: int) -> list[tuple[str, int]]:
        """Run one update lasting ``elapsed_ms`` and return the hop sounds asked of ``bank`` so far."""

        with mock.patch.object(app, "clock") as clock:
            clock.get_time.return_value = elapsed_ms
            app._update(False)
        return [sound for sound in played(bank) if sound[0] == "hop"]

    def test_each_hop_climbs_in_pitch(self) -> None:
        """A 4-space roll taps four rising hops as the token reaches each space."""

        app, game, bank = make_app_with_game()
        self.hops_after(app, bank, 0)
        rig_rolls(game, 1, 3)
        game.roll_dice()
        self.assertEqual(self.hops_after(app, bank, 2000), [("hop", 0), ("hop", 1), ("hop", 2), ("hop", 3)])

    def test_hops_wait_for_the_token_to_reach_each_space(self) -> None:
        """A tiny frame that reaches no space taps no hop yet."""

        app, game, bank = make_app_with_game()
        self.hops_after(app, bank, 0)
        rig_rolls(game, 1, 3)
        game.roll_dice()
        self.assertEqual(self.hops_after(app, bank, 1), [])

    def test_jumps_slide_without_hopping(self) -> None:
        """A long jump (Go To Jail, a card) is one silent slide; its event has its own sound."""

        app, game, bank = make_app_with_game()
        game.players[0].position = 30
        self.hops_after(app, bank, 0)
        game.go_to_jail(game.players[0])
        self.assertEqual(self.hops_after(app, bank, 5000), [])

    def test_every_button_clicks(self) -> None:
        """A setup button press plays the click."""

        app = main.MonopolyApp(persist=False)
        app.sounds = mock.Mock()
        app._draw()
        button = next(button for button in app.buttons if button.key == "humans_up")
        app._handle_click(button.rect.center)
        self.assertEqual(names(app.sounds), ["click"])

    def test_clicks_off_any_button_are_silent(self) -> None:
        """A click on empty wallpaper plays nothing."""

        app = main.MonopolyApp(persist=False)
        app.sounds = mock.Mock()
        app._draw()
        app._handle_click((5, 5))
        app.sounds.play.assert_not_called()


class MixerStartupTests(unittest.TestCase):
    """``main.main`` asks for the mixer format before pygame starts, and reserves music after."""

    def test_mixer_is_set_up_around_pygame_init(self) -> None:
        """Order: init_mixer, pygame.init, reserve_channels, then the app is built."""

        order = mock.Mock()
        with (
            mock.patch.object(main.audio, "init_mixer", order.init_mixer),
            mock.patch.object(main.pygame, "init", order.init),
            mock.patch.object(main.audio, "reserve_channels", order.reserve_channels),
            mock.patch.object(main, "MonopolyApp", order.MonopolyApp),
            mock.patch.object(main.pygame, "quit", order.quit),
            mock.patch.dict(os.environ, {"MONOPOLY_AUTOTEST": ""}),
        ):
            main.main()
        calls = [name for name, _args, _kwargs in order.mock_calls]
        self.assertEqual(calls[:3], ["init_mixer", "init", "reserve_channels"])
        self.assertIn("MonopolyApp", calls)


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
