"""Shared constants for the Ludo desktop game.

The rest of the project imports named values from here instead of scattering
magic numbers through the code. The save paths intentionally live under
``%APPDATA%`` so progress survives both source runs and PyInstaller builds.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from audio import Note, midi

# ---------------------------------------------------------------------------
# Window and timing
# ---------------------------------------------------------------------------
WINDOW_TITLE = "Ludo"
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 900
FPS = 60

# The board lives on the left and the control panel lives on the right. Keeping
# the logical size fixed makes click handling and PyInstaller builds simpler.
# BOARD_CENTER and BOARD_RADIUS shape BoardLayout's plain polygon, which is only
# the headless fallback; the drawn boards come from board_render.DisplayLayout.
BOARD_CENTER = (450, 450)
BOARD_RADIUS = 330
PANEL_X = 900
PANEL_WIDTH = SCREEN_WIDTH - PANEL_X - 30

# AI delay is intentionally visible so human players can follow what happened
# instead of seeing computer turns flash by instantly.
AI_TURN_DELAY_MS = 650
DICE_ANIM_MS = 350
# Tokens hop cell-by-cell along the track. This is the travel speed in pixels
# per second: fast enough not to drag, slow enough to follow each hop.
TOKEN_HOP_SPEED = 460.0

# LUDO_AUTOTEST=1 plays a hidden, seeded all-AI four-player game for this many
# frames (the AI acts every frame there), long enough to roll, enter, move, and
# capture, then exits. The fixed seed makes every autotest run identical.
AUTOTEST_FRAMES = 120
AUTOTEST_SEED = 7

# Token pins (the drawn pawns) and their click targets.
TOKEN_PIN_RADIUS = 15  # radius of a pawn's coloured head, in pixels
# A click selects the nearest highlighted pawn whose drawn centre lies within
# this many pixels: generous enough for quick clicks, and "nearest" keeps it
# exact when neighbouring pawns' circles overlap on the tight 6P board.
TOKEN_HIT_RADIUS = 33
# Pawns sharing one cell fan out around its centre so each stays visible.
# Stacked pawns shrink to STACK_PIN_RADIUS and sit STACK_SPACING pixels apart,
# which keeps every pawn's number at least 2 px clear of the (white-ringed)
# heads drawn after it in any common font, while a six-pawn fan still stays
# within about one cell of its square.
STACK_SPACING = 26
STACK_PIN_RADIUS = 11
# A pair whose nearest occupied cell is within this many pixels lines up side
# by side with it; beyond that it fans out across its own path. 80 px covers a
# neighbouring cell (33-59 px away) plus the reach of a full fan around it.
PAIR_NEIGHBOUR_RANGE = 80


# ---------------------------------------------------------------------------
# Rules defaults
# ---------------------------------------------------------------------------
MIN_PLAYERS = 4
MAX_PLAYERS = 6
TOKENS_PER_PLAYER = 4
# Each player contributes one 13-cell segment to the shared track, then owns a
# private 6-cell home lane. BoardLayout uses these to generalize 4P, 5P, and 6P.
SEGMENT_LENGTH = 13
HOME_LENGTH = 6


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
# Plain RGB tuples are easy to tweak. The palette avoids needing image assets:
# every board cell, panel, token, and highlight is drawn procedurally.
PANEL_BG = (20, 27, 31)
PANEL_CARD = (35, 45, 51)
PANEL_EDGE = (82, 102, 112)
WHITE = (248, 248, 242)
SOFT = (185, 196, 196)
INK = (20, 24, 26)
GOLD = (224, 181, 76)
SUCCESS = (110, 205, 140)
DANGER = (224, 84, 84)
# Labels and markings drawn on a seat colour (pawn numbers, name banners,
# start arrows) use whichever of LABEL_LIGHT or LABEL_DARK contrasts more with
# that colour (WCAG contrast ratio). With pure white and pure black every seat
# colour and start-square tint reaches LABEL_CONTRAST_TARGET = 4.5:1 (WCAG AA
# for normal text; the closest call is purple at 4.6). That leaves real margin
# above MIN_LABEL_CONTRAST = 3:1, the floor rendered pixels must still clear
# after a platform's font antialiasing thins the strokes.
LABEL_LIGHT = (255, 255, 255)
LABEL_DARK = (0, 0, 0)
LABEL_CONTRAST_TARGET = 4.5
MIN_LABEL_CONTRAST = 3.0
# Setup stepper buttons draw their -, +, <, > as shapes rather than font
# glyphs, so they are large and exactly centred whatever font is installed.
STEPPER_SYMBOL_HALF = 8        # half the symbol's span: symbols are 16 px across
STEPPER_SYMBOL_THICKNESS = 4   # stroke width of the - and + bars
DISABLED = (88, 98, 102)        # muted grey for a disabled button's border and label
DISABLED_FILL = (26, 32, 36)    # darker than PANEL_CARD, so a disabled button reads as "off"

# Base token colours. Individual boards pick from these via the seat tables
# below instead of indexing one shared list, because the classic colour wheel
# differs between the 4-, 5-, and 6-player reference boards.
COLOR_BLUE = (46, 101, 218)
COLOR_RED = (215, 55, 55)
COLOR_GREEN = (52, 162, 88)
COLOR_YELLOW = (224, 173, 48)
COLOR_PURPLE = (155, 86, 206)
COLOR_ORANGE = (236, 118, 54)

# Seat 0 is always Player 1 and always sits at the bottom of the screen
# (bottom-left on the square board). The remaining seats proceed clockwise,
# matching the classic Ludo apps this UI is modelled on. Tokens also travel
# clockwise, so seating order and movement direction agree everywhere.
SEAT_COLORS: dict[int, tuple[tuple[int, int, int], ...]] = {
    4: (COLOR_BLUE, COLOR_RED, COLOR_GREEN, COLOR_YELLOW),
    5: (COLOR_BLUE, COLOR_ORANGE, COLOR_GREEN, COLOR_RED, COLOR_YELLOW),
    6: (COLOR_BLUE, COLOR_YELLOW, COLOR_PURPLE, COLOR_RED, COLOR_GREEN, COLOR_ORANGE),
}

SEAT_COLOR_NAMES: dict[int, tuple[str, ...]] = {
    4: ("Blue", "Red", "Green", "Yellow"),
    5: ("Blue", "Orange", "Green", "Red", "Yellow"),
    6: ("Blue", "Yellow", "Purple", "Red", "Green", "Orange"),
}


def seat_colors(total_players: int) -> tuple[tuple[int, int, int], ...]:
    """Return the clockwise seat colours for one supported player count."""

    return SEAT_COLORS[total_players]


def seat_name(total_players: int, seat: int) -> str:
    """Return the colour name for one seat, used in default AI player names."""

    return SEAT_COLOR_NAMES[total_players][seat]


# ---------------------------------------------------------------------------
# Window icon
# ---------------------------------------------------------------------------
# The window icon is the 256px PNG taken from ludo_icon.ico (pygame cannot
# decode the .ico itself). If the PNG ever fails to load, main._make_icon draws
# a simple stand-in: a cream board square holding one dot per classic seat.
ICON_FILE = "ludo_icon.png"
ICON_SIZE = 64                      # fallback icon canvas, in pixels
ICON_BOARD_INSET = 4                # gap between the canvas edge and the board
ICON_BOARD_SIZE = 56                # side of the cream board square
ICON_BOARD_RADIUS = 12              # rounded-corner radius of the board
ICON_BOARD_COLOR = (238, 232, 209)  # cream, like the real board
ICON_DOT_ORIGIN = 22                # centre of the top-left seat dot
ICON_DOT_SPACING = 20               # distance between neighbouring dots
ICON_DOT_RADIUS = 9                 # radius of each seat dot


# ---------------------------------------------------------------------------
# Save data
# ---------------------------------------------------------------------------
def _user_save_dir() -> Path:
    """Return the per-user folder used for saves and lifetime stats."""

    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "Ludo"


SAVE_DIR = _user_save_dir()
STATS_PATH = SAVE_DIR / "stats.json"          # lifetime games and wins
SAVEGAME_PATH = SAVE_DIR / "savegame.json"    # one resumable in-progress game


# ---------------------------------------------------------------------------
# Sound
# ---------------------------------------------------------------------------
# Every sound is a recipe: a list of `Note`s that audio.py renders into
# samples when the game starts (no audio files ship with the game). Pitches
# are MIDI note numbers through `midi()`: 69 is A4 (440 Hz), +12 is one octave
# up. The palette is bright marimba-like plucks in G major, the same key as
# the music, so effects that overlap the tune or each other stay in harmony.
#
# Beginner note:
# - A "pluck" note below has no sustain: it rises over a few milliseconds and
#   then rings down over `ring` seconds, like a mallet striking a marimba bar.
# - Volumes stay well under 1.0 on purpose: several effects often play at
#   once (a hop, a capture and a turn change) and their samples add up.
# - A name such as "hop@3" or "dice@5" is a *pitch variant*: the same sound
#   pre-rendered at another pitch. `SoundBank.play(name, pitch_step=n)` plays
#   "name@n" when it exists and falls back to the plain "name" otherwise, so
#   the plain entry doubles as step 0 ("hop") or face 1 ("dice").
SFX_PLUCK_ATTACK = 0.004  # A struck note reaches full volume this fast (s).
# Fade used when a pluck is cut short before it has rung down (the music loop
# trims notes at its end); a pluck that rings out fully is already silent here.
SFX_PLUCK_RELEASE = 0.02  # Seconds.
SFX_ROOT_NOTE = 67  # G4: the home note of the effects' G major ladder.
G_MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)  # Semitones above G for each degree of the scale.
# The dice sound is a rattle of short noise ticks (the die tumbling), then the
# face's own note lands DICE_RESULT_AT seconds in, as the tray animation stops.
# Each tick is drawn at a different noise rate, so the rattle sounds uneven.
DICE_RATTLE_TICKS = ((0.0, 3200.0), (0.05, 2400.0), (0.1, 3600.0), (0.16, 2800.0), (0.22, 3000.0), (0.27, 2200.0))
DICE_RESULT_AT = 0.33  # Seconds; a little under DICE_ANIM_MS so the note lands with the last face.
# The note each die face lands on (faces 1 to 6): the G major pentatonic
# ladder G A B D E G, so a 6 lands an octave above a 1.
DICE_FACE_NOTES = (67, 69, 71, 74, 76, 79)
# A token's hops climb the G major ladder one degree per cell, so the player
# hears the count: hop n of a move plays variant "hop@n". A move is at most
# six hops; HOP_PITCH_STEPS variants cover that.
HOP_PITCH_STEPS = 6


def pluck(pitch: float, start: float, ring: float, volume: float, voice: str = "pluck") -> Note:
    """Return a struck note: a near-instant attack, then a ring down to silence.

    Args:
        pitch: MIDI note number (converted to Hz with `midi`).
        start: Seconds from the start of the sound.
        ring: Seconds the note takes to fade from full volume to silence.
        volume: Peak loudness, 0 to 1.
        voice: Wavetable name from audio.py; "pluck" is the marimba-like tone.

    Beginner note:
    - In ADSR terms this is attack `SFX_PLUCK_ATTACK`, decay `ring`, and
      sustain 0: the note is held just long enough (attack plus ring) for the
      decay to reach silence, so nothing is left for the release to fade.
    """

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


def scale_note(degree: int) -> int:
    """Return the MIDI note `degree` steps up the G major ladder from SFX_ROOT_NOTE.

    Degrees past the seventh wrap into the next octave: degree 0 is G4 (67),
    degree 6 is F#5 (78) and degree 7 is G5 (79).
    """

    octave, step = divmod(degree, len(G_MAJOR_STEPS))
    return SFX_ROOT_NOTE + 12 * octave + G_MAJOR_STEPS[step]


def dice_notes(face: int) -> list[Note]:
    """Return the dice sound for `face` (1 to 6): a noise rattle, then the face's marimba note."""

    notes = [
        Note(rate, at, 0.012, "noise", 0.16, attack=0.001, decay=0.025, sustain=0.0, release=0.01)
        for at, rate in DICE_RATTLE_TICKS
    ]
    pitch = DICE_FACE_NOTES[face - 1]
    notes.append(pluck(pitch, DICE_RESULT_AT, 0.2, 0.3))
    notes.append(pluck(pitch + 12, DICE_RESULT_AT, 0.12, 0.08, voice="sine"))
    return notes


def hop_notes(step: int) -> list[Note]:
    """Return one hop of a token: a short marimba tap `step` degrees up the ladder, with a wooden knock."""

    return [
        pluck(scale_note(step), 0.0, 0.07, 0.22),
        Note(900.0, 0.0, 0.008, "noise", 0.05, attack=0.001, decay=0.015, sustain=0.0, release=0.005),
    ]


SFX_RECIPES: dict[str, list[Note]] = {
    "dice": dice_notes(1),
    **{f"dice@{face}": dice_notes(face) for face in range(2, 7)},
    # A rolled 6: a quick high G major sparkle, timed to land with the die.
    "six": [
        pluck(pitch, DICE_RESULT_AT + 0.06 + index * 0.05, 0.25, 0.16, voice="sine")
        for index, pitch in enumerate((79, 83, 86, 91))
    ],
    # A third 6 in a row forfeits the roll: a deflating G minor fall, also
    # timed to follow the die.
    "three_sixes": [
        pluck(74, DICE_RESULT_AT + 0.06, 0.14, 0.2, voice="square"),
        pluck(70, DICE_RESULT_AT + 0.2, 0.14, 0.2, voice="square"),
        Note(midi(67), DICE_RESULT_AT + 0.34, 0.2, "triangle", 0.24, glide=-40.0, attack=0.01, decay=0.2,
             sustain=0.4, release=0.15),
    ],
    # A token leaves its yard: a bouncy rising pop G - D - G.
    "leave_yard": [
        Note(midi(55), 0.0, 0.06, "sine", 0.18, glide=900.0, attack=0.004, decay=0.06, sustain=0.0, release=0.02),
        *(pluck(pitch, 0.03 + index * 0.06, 0.14, 0.24) for index, pitch in enumerate((67, 74, 79))),
    ],
    "hop": hop_notes(0),
    **{f"hop@{step}": hop_notes(step) for step in range(1, HOP_PITCH_STEPS)},
    # A capture: two falling "bonks" with a dull thud, as the token is knocked home.
    "capture": [
        Note(midi(62), 0.0, 0.14, "triangle", 0.34, glide=-520.0, attack=0.002, decay=0.14, sustain=0.0,
             release=0.02),
        Note(500.0, 0.0, 0.03, "noise", 0.12, attack=0.001, decay=0.03, sustain=0.0, release=0.01),
        Note(midi(55), 0.13, 0.2, "triangle", 0.3, glide=-260.0, attack=0.002, decay=0.2, sustain=0.0,
             release=0.03),
    ],
    # A token reaches home: a ringing G major chord, struck low to high.
    "home": [
        *(pluck(pitch, index * 0.07, 0.4, 0.22) for index, pitch in enumerate((67, 71, 74, 79))),
        Note(midi(83), 0.28, 0.12, "sine", 0.1, attack=0.02, decay=0.1, sustain=0.6, release=0.2),
    ],
    # A bonus roll earned by a capture or a token home: a bright rising fifth.
    "bonus": [pluck(86, 0.0, 0.16, 0.16, voice="sine"), pluck(93, 0.07, 0.24, 0.14, voice="sine")],
    # No legal move: a soft, low "nope" double bump.
    "no_move": [pluck(50, 0.0, 0.07, 0.24, voice="square"), pluck(50, 0.1, 0.09, 0.2, voice="square")],
    # The turn passes: a quiet two-note woodblock knock.
    "turn": [pluck(74, 0.0, 0.05, 0.12), pluck(79, 0.06, 0.07, 0.1)],
    # A short, soft two-note click for every button.
    "click": [pluck(84, 0.0, 0.05, 0.2, voice="sine"), pluck(91, 0.012, 0.04, 0.07, voice="sine")],
}
# The fewest seconds between two plays of the same effect (variants share
# their base name's cooldown). A slow frame can finish several hops at once,
# and the autotest fires an AI action every frame; these keep such bursts a
# gentle patter instead of a pile of identical sounds.
SFX_COOLDOWNS: dict[str, float] = {
    "hop": 0.05,
    "dice": 0.1,
    "turn": 0.15,
    "no_move": 0.2,
    "click": 0.04,
}

# Game-over jingles: the music fades out and one of these plays.
SFX_RECIPES.update(
    {
        # A human won (or the AI table finished): an ascending G major
        # fanfare that settles into a ringing chord over a low G.
        "win": [
            *(pluck(pitch, index * 0.12, 0.3, 0.24) for index, pitch in enumerate((67, 71, 74, 79))),
            *(
                Note(midi(pitch), 0.5, 0.7, "triangle", 0.13, attack=0.03, decay=0.2, sustain=0.6, release=0.6)
                for pitch in (79, 83, 86)
            ),
            Note(midi(43), 0.5, 0.7, "sine", 0.22, attack=0.05, decay=0.2, sustain=0.8, release=0.6),
            pluck(91, 0.5, 0.5, 0.1, voice="sine"),
        ],
        # A computer beat the humans: a gentle descending G minor phrase.
        "lose": [
            Note(midi(74), 0.0, 0.26, "triangle", 0.24, attack=0.015, decay=0.1, sustain=0.6, release=0.2),
            Note(midi(70), 0.32, 0.26, "triangle", 0.24, attack=0.015, decay=0.1, sustain=0.6, release=0.2),
            Note(midi(67), 0.64, 0.7, "triangle", 0.26, attack=0.015, decay=0.2, sustain=0.6, release=0.5),
            Note(midi(43), 0.64, 0.7, "sine", 0.2, attack=0.2, decay=0.2, sustain=0.8, release=0.5),
            Note(midi(50), 0.64, 0.7, "sine", 0.1, attack=0.3, decay=0.2, sustain=0.8, release=0.5),
        ],
    }
)

# Music: an upbeat folk tune in G major, rendered once into a loop that plays
# on the reserved mixer channel 0 (see `music_notes`). A marimba melody rides
# an "oom-pah" accompaniment: the bass plays the chord's root on beat 1 and
# its fifth on beat 3, a soft chord answers on beats 2 and 4, and a quiet
# shaker ticks on every off-beat.
MUSIC_BPM = 128  # Beats per minute: a brisk walking-dance pace.
MUSIC_BEATS_PER_BAR = 4
MUSIC_BEAT_SECONDS = 60.0 / MUSIC_BPM
MUSIC_VOLUME = 0.22  # Channel volume: low, so effects sit on top of the music.
MUSIC_FADE_IN_MS = 1500  # The tune eases in when the app opens or a new game is set up.
MUSIC_GAME_OVER_FADE_MS = 700  # How quickly the tune fades under the game-over jingle.
# Each chord: (bass root, bass fifth, the three notes of the off-beat "pah"), as MIDI numbers.
# The fifth sits above or below the root, whichever keeps the bass in one low
# register (E2 to D3), so the "oom" never jumps around.
MUSIC_CHORDS: dict[str, tuple[int, int, tuple[int, int, int]]] = {
    "G": (43, 50, (55, 59, 62)),
    "C": (48, 43, (55, 60, 64)),
    "D": (50, 45, (54, 57, 62)),
    "Em": (40, 47, (55, 59, 64)),
}
# The tune, one bar per entry: the chord, then the melody notes as (beat in
# the bar, length in beats, MIDI pitch). Bars 1-8 are the A part, 9-16 the B
# part that wanders to E minor before coming home to G.
MUSIC_SCORE: tuple[tuple[str, tuple[tuple[float, float, int], ...]], ...] = (
    ("G", ((0, 0.5, 74), (0.5, 0.5, 71), (1, 0.5, 67), (1.5, 0.5, 71), (2, 1, 74), (3, 1, 79))),
    ("C", ((0, 1, 76), (1, 0.5, 72), (1.5, 0.5, 76), (2, 1, 79), (3, 1, 76))),
    ("G", ((0, 0.5, 74), (0.5, 0.5, 71), (1, 0.5, 74), (1.5, 0.5, 79), (2, 1, 71), (3, 0.5, 69), (3.5, 0.5, 67))),
    ("D", ((0, 1, 69), (1, 0.5, 66), (1.5, 0.5, 69), (2, 2, 74))),
    ("G", ((0, 0.5, 74), (0.5, 0.5, 71), (1, 0.5, 67), (1.5, 0.5, 71), (2, 1, 74), (3, 1, 79))),
    ("C", ((0, 0.5, 76), (0.5, 0.5, 79), (1, 0.5, 76), (1.5, 0.5, 72), (2, 1, 76), (3, 0.5, 74), (3.5, 0.5, 72))),
    ("D", ((0, 0.5, 69), (0.5, 0.5, 66), (1, 0.5, 69), (1.5, 0.5, 74), (2, 1, 78), (3, 1, 74))),
    ("G", ((0, 2, 67), (2, 0.5, 67), (2.5, 0.5, 71), (3, 1, 74))),
    ("Em", ((0, 1, 71), (1, 0.5, 67), (1.5, 0.5, 71), (2, 1, 76), (3, 0.5, 74), (3.5, 0.5, 71))),
    ("C", ((0, 1, 72), (1, 0.5, 76), (1.5, 0.5, 79), (2, 1, 76), (3, 1, 72))),
    ("G", ((0, 0.5, 71), (0.5, 0.5, 74), (1, 0.5, 79), (1.5, 0.5, 74), (2, 1, 71), (3, 1, 67))),
    ("D", ((0, 0.5, 69), (0.5, 0.5, 71), (1, 0.5, 69), (1.5, 0.5, 66), (2, 2, 62))),
    ("Em", ((0, 1, 76), (1, 0.5, 71), (1.5, 0.5, 76), (2, 1, 79), (3, 1, 76))),
    ("C", ((0, 0.5, 79), (0.5, 0.5, 76), (1, 0.5, 72), (1.5, 0.5, 76), (2, 1, 79), (3, 1, 81))),
    ("D", ((0, 1, 78), (1, 0.5, 76), (1.5, 0.5, 74), (2, 1, 69), (3, 1, 66))),
    ("G", ((0, 1, 67), (1, 1, 71), (2, 2, 67))),
)
MUSIC_BARS = len(MUSIC_SCORE)
# 16 bars x 4 beats = 64 beats, and one beat is 60 / 128 s, so 64 x 0.46875 = 30 s exactly.
MUSIC_LOOP_SECONDS = MUSIC_BARS * MUSIC_BEATS_PER_BAR * MUSIC_BEAT_SECONDS
MUSIC_MELODY_VOLUME = 0.22
MUSIC_MELODY_RING = 1.5  # A melody note rings this many times its written length (legato marimba).
MUSIC_BASS_VOLUME = 0.26
MUSIC_BASS_RING = 0.8  # Beats a bass note rings, so "oom" stays short and bouncy.
MUSIC_CHORD_VOLUME = 0.06  # Per chord note; three of them sound together.
MUSIC_CHORD_RING = 0.35  # Beats an off-beat chord rings: a light "pah".
MUSIC_SHAKER_VOLUME = 0.03
MUSIC_SHAKER_RATE = 6000.0  # Noise values per second: a high, airy hiss.
# The shaker tick's decay time (s). Each tick is held only 5 ms and then
# released over 10 ms, so it is cut long before this decay ends: the value
# just tilts the tick slightly downward, and each tick lasts about 15 ms.
MUSIC_SHAKER_RING = 0.06


def music_notes() -> list[Note]:
    """Return one loop of the folk tune (see `MUSIC_SCORE`).

    Every note ends by `MUSIC_LOOP_SECONDS`: a note that would ring past the
    end is shortened so its release fade finishes exactly there, so the loop
    restarts without a click.

    Each bar adds four layers: the melody, the bass "oom" on beats 1 and 3,
    the soft chord "pah" on beats 2 and 4, and a shaker tick on each off-beat
    (halfway between beats).

    Beginner note:
    - Times are worked out in beats and turned into seconds by multiplying
      by `MUSIC_BEAT_SECONDS`, so changing `MUSIC_BPM` speeds up or slows
      down the whole tune (and the loop length) together.
    - The loop is rendered to exactly `MUSIC_LOOP_SECONDS`, so a note still
      ringing there would be cut off mid-sound every time the loop restarts
      (only the renderer's 3 ms edge fade would soften the cut). Trimming
      notes to end in their own release fade makes the seam clean.
    """

    beat = MUSIC_BEAT_SECONDS
    notes: list[Note] = []
    for bar, (chord, melody) in enumerate(MUSIC_SCORE):
        start = bar * MUSIC_BEATS_PER_BAR * beat
        root, fifth, triad = MUSIC_CHORDS[chord]
        for at, length, pitch in melody:
            notes.append(pluck(pitch, start + at * beat, length * beat * MUSIC_MELODY_RING, MUSIC_MELODY_VOLUME))
        for beat_index, bass in ((0, root), (2, fifth)):
            notes.append(pluck(bass, start + beat_index * beat, MUSIC_BASS_RING * beat, MUSIC_BASS_VOLUME, "triangle"))
        for beat_index in (1, 3):
            for pitch in triad:
                notes.append(pluck(pitch, start + beat_index * beat, MUSIC_CHORD_RING * beat, MUSIC_CHORD_VOLUME))
        for beat_index in range(MUSIC_BEATS_PER_BAR):
            at = start + (beat_index + 0.5) * beat
            notes.append(
                Note(MUSIC_SHAKER_RATE, at, 0.005, "noise", MUSIC_SHAKER_VOLUME, attack=0.003,
                     decay=MUSIC_SHAKER_RING, sustain=0.0, release=0.01)
            )
    # Fit every note inside the loop: one that would ring past the end gets a
    # shorter held part so its release ends exactly at MUSIC_LOOP_SECONDS; one
    # that starts too late for even its release to fit is dropped.
    fitted = []
    for note in notes:
        room = MUSIC_LOOP_SECONDS - note.start - note.release
        if note.end > MUSIC_LOOP_SECONDS:
            if room <= 0:
                continue
            note = replace(note, length=room)
        fitted.append(note)
    return fitted
