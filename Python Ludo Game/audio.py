"""Procedural sound: a tiny synthesizer, a sound-effect bank and a music looper.

Everything Ludo plays is generated here from numbers, so the project ships
without a single audio file. The game describes each sound as a list of
`Note`s (see `SFX_RECIPES` and `music_notes` in settings.py); this module
turns those notes into sample buffers and plays them through `pygame.mixer`.
The window (``main.py``) decides when each sound plays; the rules engine
never touches audio.

The block between the "shared audio core" markers is copied word for word into
every game folder (each game stays self-contained, so nothing is imported
across folders). Keep the copies identical: change one, change them all.

Beginner note:
- Digital audio is a long list of numbers ("samples"). Each one is where the
  speaker cone should be at one instant. The *sample rate* says how many
  samples make one second: at 22050 Hz, one second is 22050 numbers per
  speaker channel.
- With stereo (2 channels) or more, the samples are *interleaved*: left,
  right, left, right, ... one sample per channel for every instant.
"""
# ---- shared audio core ----

from __future__ import annotations

import contextlib
import math
import random
import threading
import time
from array import array
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - only read by the type checker
    import pygame

# Mixer format asked for before pygame starts: 22050 samples per second,
# signed 16-bit samples, stereo, and a 512-sample buffer. A small buffer keeps
# the delay between an action and its sound short; 22050 Hz is plenty for
# these soft synth voices and halves the synthesis work of 44100 Hz.
MIXER_RATE = 22050
MIXER_SIZE = -16
MIXER_CHANNELS = 2
MIXER_BUFFER = 512
# How many sounds can play at once, and how many of those channels are kept
# for music by default (channel 0), so an effect can never cut the music off.
MIXER_VOICES = 16
MUSIC_CHANNELS = 1

# The loudest sample the limiter lets through, as a share of full scale. The
# soft limiter bends loud peaks smoothly toward this instead of clipping them.
LIMIT = 0.9
# Seconds faded in at the start and out at the end of every buffer, so no
# sound starts or stops with an audible click.
EDGE_FADE = 0.003
# Points in one cycle of each stored waveform. A power of two lets the
# renderer wrap the read position with a fast bit mask.
TABLE_SIZE = 2048
FULL_SCALE = 32767


def _table(harmonics: Sequence[tuple[int, float]]) -> list[float]:
    """Return one cycle of a waveform built from (harmonic, strength) pairs.

    The result is scaled so its loudest point is exactly 1.0.
    """
    points = [
        sum(strength * math.sin(math.tau * harmonic * index / TABLE_SIZE) for harmonic, strength in harmonics)
        for index in range(TABLE_SIZE)
    ]
    peak = max(abs(point) for point in points)
    return [point / peak for point in points]


# Each voice is one stored waveform cycle (a "wavetable"):
# - sine: a pure, soft tone,
# - triangle: odd harmonics falling off fast, a mellow flute-like tone,
# - square: only a few odd harmonics, a hollow tone without the harsh buzz
#   of a true square wave,
# - pluck: a bright tone with a strong fourth harmonic, like a mallet or a
#   plucked string when paired with a quick decay.
# "noise" has no table: it is random values (see `_add_noise`).
WAVETABLES: dict[str, list[float]] = {
    "sine": _table([(1, 1.0)]),
    "triangle": _table([(1, 1.0), (3, -1 / 9), (5, 1 / 25), (7, -1 / 49)]),
    "square": _table([(1, 1.0), (3, 1 / 3), (5, 1 / 5), (7, 1 / 7)]),
    "pluck": _table([(1, 1.0), (2, 0.45), (3, 0.2), (4, 0.3)]),
}
VOICES = (*WAVETABLES, "noise")


def midi(number: float) -> float:
    """Return the frequency in Hz of a MIDI note number (69 is A4, 440 Hz).

    Beginner note:
    - MIDI numbers count piano keys: +1 is one semitone up, +12 is one octave
      (double the frequency). 60 is middle C. Writing recipes as MIDI numbers
      makes them read like music instead of like physics.
    """
    return 440.0 * 2.0 ** ((number - 69) / 12.0)


@dataclass(frozen=True, slots=True)
class Note:
    """One sound event inside a recipe: a pitch played by a voice for a while.

    Attributes:
        freq: Pitch in Hz; 0 is a rest (silence that still takes up time).
            For the "noise" voice it is how many new random values are drawn
            per second, so a low value gives a dull rumble and a high one a hiss.
        start: When the note begins, in seconds from the start of the sound.
        length: How long the note is held before its release begins, in seconds.
        voice: "sine", "triangle", "square", "pluck" or "noise".
        volume: Peak loudness, from 0 to 1 (keep effects around 0.2 to 0.45).
        glide: Pitch slide in Hz per second (negative slides down), for
            whooshes, drops and sirens.
        attack, decay, sustain, release: The ADSR envelope (see below).

    Beginner note:
    - An ADSR envelope shapes loudness over time. The note rises from silence
      to full volume over `attack` seconds, falls to the `sustain` level (a
      share of full volume) over `decay` seconds, holds there until `length`
      runs out, then fades to silence over `release` seconds.
    - A quick attack sounds like a click or a hit; a slow one like a swell.
      `sustain=0` with a short decay gives a plucked or struck sound.
    """

    freq: float
    start: float
    length: float
    voice: str
    volume: float
    glide: float = 0.0
    attack: float = 0.01
    decay: float = 0.05
    sustain: float = 0.7
    release: float = 0.05

    @property
    def end(self) -> float:
        """Return when the note falls fully silent, release included."""
        return self.start + self.length + self.release


def _envelope_points(note: Note) -> list[tuple[float, float]]:
    """Return the note's envelope as (seconds from note start, level) corners.

    The envelope is straight lines between these corners. A note held for
    less time than its attack and decay is released from wherever its level
    has reached at that moment.
    """
    attack = max(note.attack, 1e-4)
    decay = max(note.decay, 1e-4)

    def level(at: float) -> float:
        """Return the envelope level `at` seconds into the held part of the note."""
        if at < attack:
            return at / attack
        if at < attack + decay:
            return 1.0 - (1.0 - note.sustain) * (at - attack) / decay
        return note.sustain

    corners = [(0.0, 0.0)]
    for moment in (attack, attack + decay):
        if moment < note.length:
            corners.append((moment, level(moment)))
    corners.append((note.length, level(note.length)))
    corners.append((note.length + max(note.release, 1e-4), 0.0))
    return corners


def _segments(note: Note, sample_rate: int, first: int, limit: int) -> list[tuple[int, int, float, float]]:
    """Return the note's envelope as sample ranges with a straight-line gain.

    Each entry is (first index, end index, gain at the first index, gain
    change per sample), with the note's volume already applied. Ranges are
    clipped to `limit`, the length of the mix buffer.
    """
    corners = _envelope_points(note)
    segments = []
    for (begin, level), (finish, target) in pairwise(corners):
        lo = first + round(begin * sample_rate)
        hi = first + round(finish * sample_rate)
        if hi > lo:
            gain_step = (target - level) * note.volume / (hi - lo)
            segments.append((lo, min(hi, limit), level * note.volume, gain_step))
    return segments


def _add_note(mix: list[float], note: Note, sample_rate: int) -> None:
    """Add one note's samples into the mono float buffer `mix`, in place.

    The waveform is read from the voice's wavetable at a moving position (its
    "phase"); the step size sets the pitch and the glide changes that step a
    little every sample. Notes that run past the end of `mix` are cut off
    there (the final edge fade in `render` keeps the cut silent).
    """
    first = round(note.start * sample_rate)
    if note.voice == "noise":
        _add_noise(mix, note, sample_rate, first)
        return
    table = WAVETABLES[note.voice]
    mask = TABLE_SIZE - 1
    phase = 0.0
    step = note.freq * TABLE_SIZE / sample_rate
    step_change = note.glide * TABLE_SIZE / sample_rate / sample_rate
    for lo, hi, gain, gain_step in _segments(note, sample_rate, first, len(mix)):
        for index in range(lo, hi):
            mix[index] += table[int(phase) & mask] * gain
            phase += step
            step += step_change
            gain += gain_step


def _add_noise(mix: list[float], note: Note, sample_rate: int, first: int) -> None:
    """Add a noise note: random values held for 1/`freq` seconds each.

    The random generator is seeded from the note itself, so the same recipe
    always renders the same buffer (tests and replays stay exact).
    """
    rng = random.Random(repr((note.freq, note.start, note.length, note.volume, note.glide)))
    hold = 1.0
    rate = note.freq / sample_rate
    rate_change = note.glide / sample_rate / sample_rate
    value = 0.0
    for lo, hi, gain, gain_step in _segments(note, sample_rate, first, len(mix)):
        for index in range(lo, hi):
            hold += rate
            if hold >= 1.0:
                hold -= int(hold)
                value = rng.random() * 2.0 - 1.0
            mix[index] += value * gain
            rate += rate_change
            gain += gain_step


def render(notes: Sequence[Note], sample_rate: int, channels: int, *, total: float | None = None) -> array:
    """Mix `notes` into one interleaved signed 16-bit buffer.

    Args:
        notes: The recipe. Rests (`freq` 0) and silent notes add nothing.
        sample_rate: Samples per second, from `pygame.mixer.get_init()`.
        channels: Speaker channels; every channel gets the same samples.
        total: Length in seconds. Defaults to when the last note falls
            silent. Music loops pass their exact loop length, and anything
            still ringing at that point is cut by the closing fade.

    Returns:
        An `array("h")` of `round(total * sample_rate) * channels` samples.

    Beginner note:
    - Mixing is just adding: two sounds playing together are the sum of
      their samples. Sums can grow past full scale, so a soft limiter (a
      `tanh` curve) gently squeezes loud parts below `LIMIT` instead of
      chopping them flat, which would sound harsh ("clipping").
    """
    if total is None:
        total = max((note.end for note in notes), default=0.0)
    frames = round(total * sample_rate)
    mix = [0.0] * frames
    for note in notes:
        if note.freq > 0.0 and note.volume > 0.0:
            _add_note(mix, note, sample_rate)
    edge = min(frames // 2, round(EDGE_FADE * sample_rate))
    for index in range(edge):
        fade = index / edge
        mix[index] *= fade
        mix[frames - 1 - index] *= fade
    scale = LIMIT * FULL_SCALE
    tanh = math.tanh
    samples = [int(scale * tanh(value / LIMIT)) for value in mix]
    if channels == 1:
        return array("h", samples)
    return array("h", [sample for sample in samples for _ in range(channels)])


# Rendered buffers by (notes, sample rate, channels, total). Building a second
# bank or player with the same recipes (tests do this a lot) reuses the work.
_BUFFERS: dict[tuple, bytes] = {}
_BUFFERS_LOCK = threading.Lock()


def render_bytes(notes: Sequence[Note], sample_rate: int, channels: int, total: float | None = None) -> bytes:
    """Return `render(...)` as raw bytes, remembering the result for reuse.

    The lock makes a second caller wait for a render already in progress
    instead of doing the same work twice at the same time.
    """
    key = (tuple(notes), sample_rate, channels, total)
    with _BUFFERS_LOCK:
        cached = _BUFFERS.get(key)
        if cached is None:
            cached = render(notes, sample_rate, channels, total=total).tobytes()
            _BUFFERS[key] = cached
    return cached


def init_mixer() -> None:
    """Ask for the mixer format; call this BEFORE `pygame.init()` (or `pygame.mixer.init()`).

    Errors are ignored: a machine without audio simply plays silently.

    Beginner note:
    - `pre_init` only records the wished-for settings. The mixer actually
      opens when pygame starts, which is why the order matters.
    """
    import pygame

    with contextlib.suppress(pygame.error):
        pygame.mixer.pre_init(MIXER_RATE, MIXER_SIZE, MIXER_CHANNELS, MIXER_BUFFER)


def reserve_channels(music_channels: int = MUSIC_CHANNELS) -> None:
    """Open `MIXER_VOICES` channels and keep the first `music_channels` for music.

    Call this AFTER the mixer has started. Errors (or no mixer at all) are
    ignored, so a machine without audio simply plays silently.

    Beginner note:
    - A mixer *channel* plays one sound at a time; 16 channels means up to
      16 overlapping sounds. *Reserved* channels are never handed out for
      effects, so a burst of effects can never steal the music's channel.
    """
    import pygame

    if pygame.mixer.get_init() is None:
        return
    with contextlib.suppress(pygame.error):
        pygame.mixer.set_num_channels(MIXER_VOICES)
        pygame.mixer.set_reserved(music_channels)


class SoundBank:
    """Builds named sound effects from recipes and plays them on demand.

    Attributes:
        enabled: False when the mixer is unavailable or a sound failed to
            build; `play()` then does nothing, so the game still runs silently.
        sounds: Name to `pygame.mixer.Sound`. A name such as "merge@3" is a
            pre-rendered pitch variant of "merge" (see `play`).
        cooldowns: Base name to the fewest seconds between two plays of it.
    """

    def __init__(
        self,
        recipes: dict[str, list[Note]],
        cooldowns: dict[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Render every recipe for the running mixer, or disable sound."""
        import pygame

        self.cooldowns = dict(cooldowns or {})
        self.clock = clock
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        self._muted = False
        self._last_played: dict[str, float] = {}
        mixer_state = pygame.mixer.get_init()
        self.enabled = mixer_state is not None
        if mixer_state is None:
            return
        sample_rate, _, channels = mixer_state
        try:
            for name, notes in recipes.items():
                self.sounds[name] = pygame.mixer.Sound(buffer=render_bytes(notes, sample_rate, channels))
        except pygame.error:
            self.enabled = False
            self.sounds.clear()

    @property
    def muted(self) -> bool:
        """True while effects are switched off by the player."""
        return self._muted

    @muted.setter
    def muted(self, value: bool) -> None:
        """Switch effects off (True) or back on (False)."""
        self._muted = bool(value)

    def play(self, name: str, volume: float = 1.0, pitch_step: int = 0) -> None:
        """Play the sound `name` once at `volume` (0 to 1).

        `pitch_step` picks the pre-rendered variant `name@step` when the bank
        has one (for example a merge that rises with the tier), otherwise the
        plain sound. Nothing happens while disabled or muted, for an unknown
        name, or when the same base name played less than its cooldown ago.
        """
        if not self.enabled or self._muted:
            return
        sound = self.sounds.get(f"{name}@{pitch_step}")
        if sound is None:
            sound = self.sounds.get(name)
        if sound is None:
            return
        now = self.clock()
        last = self._last_played.get(name)
        if last is not None and now - last < self.cooldowns.get(name, 0.0):
            return
        import pygame

        channel = pygame.mixer.find_channel(True)
        if channel is None:
            return
        self._last_played[name] = now
        channel.set_volume(max(0.0, min(1.0, volume)))
        channel.play(sound)


class MusicPlayer:
    """Renders one looping music track off the main thread and plays it.

    Usage from the game shell: build it once, call `start()` when the music
    should play, `stop()` when it should not, and `update()` once per frame.

    Attributes:
        enabled: False without a working mixer; every method is then a no-op.
        total: Loop length in seconds (the track is rendered exactly this long).
        volume: Channel volume, from 0 to 1.
        channel: Which reserved mixer channel the track plays on.

    Beginner note:
    - Rendering a whole track takes a few seconds of pure Python, so by
      default it happens in a background *thread*: the game keeps running
      while the track is made. pygame objects are only created on the main
      thread, in `update()`, once the samples are ready.
    - A *daemon* thread does not keep the program alive: closing the game
      while the track is still rendering simply ends it.
    """

    def __init__(
        self,
        build_notes: Callable[[], list[Note]],
        total: float,
        volume: float,
        threaded: bool = True,
        channel: int = 0,
    ) -> None:
        """Start rendering the track (in a daemon thread when `threaded`)."""
        import pygame

        self.total = total
        self.volume = volume
        self.channel = channel
        self._sound: pygame.mixer.Sound | None = None
        self._samples: bytes | None = None
        self._wanted = False
        self._playing = False
        self._muted = False
        self._fade_ms = 0
        mixer_state = pygame.mixer.get_init()
        self.enabled = mixer_state is not None
        if mixer_state is None:
            return
        sample_rate, _, channels = mixer_state
        if threaded:
            worker = threading.Thread(target=self._render, args=(build_notes, sample_rate, channels), daemon=True)
            worker.start()
        else:
            self._render(build_notes, sample_rate, channels)

    def _render(self, build_notes: Callable[[], list[Note]], sample_rate: int, channels: int) -> None:
        """Render the track's samples; runs on the worker thread when threaded."""
        self._samples = render_bytes(build_notes(), sample_rate, channels, self.total)

    @property
    def is_ready(self) -> bool:
        """True once the track has finished rendering."""
        return self._sound is not None or self._samples is not None

    def start(self, fade_ms: int = 0) -> None:
        """Ask for the music to play (fading in over `fade_ms`) as soon as it is ready."""
        self._wanted = True
        self._fade_ms = fade_ms
        self.update()

    def stop(self, fade_ms: int = 0) -> None:
        """Stop the music, fading out over `fade_ms` milliseconds (0 stops at once)."""
        self._wanted = False
        self._halt(fade_ms)

    def set_muted(self, muted: bool) -> None:
        """Silence the music at once (True), or resume it if it was wanted (False)."""
        self._muted = muted
        if muted:
            self._halt(0)
        else:
            self.update()

    def _halt(self, fade_ms: int) -> None:
        """Stop the track's channel if this player is playing on it."""
        if not self.enabled or not self._playing:
            return
        import pygame

        self._playing = False
        channel = pygame.mixer.Channel(self.channel)
        if fade_ms > 0:
            channel.fadeout(fade_ms)
        else:
            channel.stop()

    def update(self) -> None:
        """Turn finished samples into a Sound, and start it if it should play."""
        if not self.enabled:
            return
        import pygame

        if self._sound is None and self._samples is not None:
            try:
                self._sound = pygame.mixer.Sound(buffer=self._samples)
            except pygame.error:
                self.enabled = False
                return
            self._samples = None
        if self._sound is not None and self._wanted and not self._muted and not self._playing:
            channel = pygame.mixer.Channel(self.channel)
            channel.set_volume(self.volume)
            channel.play(self._sound, loops=-1, fade_ms=self._fade_ms)
            self._playing = True


# ---- end shared audio core ----
