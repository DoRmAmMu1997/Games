"""
Simple Klondike Solitaire built with tkinter.

Everything lives in this one file so it is easy to run and study.
The code is split into:
1. A game model (`KlondikeGame`) that knows the rules and scoring. It never
   imports or touches tkinter, so tests can drive it directly.
2. A tkinter app (`SolitaireApp`) that draws the cards and handles input.
   It only translates clicks into calls on the model and repaints the canvas.

Small dataclasses (`Card`, `Selection`, `HintMove`, `AnimationState`) carry
data between the two halves, and the constants at the top of the file hold
every layout size, colour and timing value, plus the sound recipes that
``audio.py`` (the game's small synthesizer) turns into effects.

Beginner note: Klondike vocabulary used throughout the code.
- Stock: the face-down pile at top left. Clicking it turns one card over
  onto the waste; when it is empty, a click recycles the waste back into it.
- Waste: the face-up pile beside the stock. Only its top card can be played.
- Foundations: the four piles at top right, one per suit. Each builds up
  from Ace to King; filling all four wins the game.
- Tableau: the seven columns below. Cards stack downward in alternating
  colours (a red 6 on a black 7), and only a King may fill an empty column.
  A face-down tableau card turns face up once nothing covers it.
"""

import contextlib
import json
import math
import os
import random
import sys
import time
import tkinter as tk
from dataclasses import dataclass, replace
from pathlib import Path
from tkinter import messagebox
from typing import Any

import audio
from audio import Note, midi

# Card size in pixels.
CARD_WIDTH = 88
CARD_HEIGHT = 120

# Vertical spacing between cards in a tableau column.
# Face-down cards overlap more tightly so columns stay compact.
FACE_DOWN_SPACING = 16
FACE_UP_SPACING = 24
# The corner index starts this far inside the card's top (and bottom) edge.
# A stacked card covers everything below FACE_UP_SPACING, so the index must
# sit high enough that the next card's outline never clips the rank or suit.
CORNER_INDEX_INSET_Y = 4

# General layout values used to place piles on the canvas.
TOP_ROW_Y = 28
COLUMN_GAP = 18
# Pile names are centred this far above the top row of cards, and the
# "N cards" counts this far below it, so neither touches a card, its shadow,
# the canvas edge or the divider line.
PILE_LABEL_OFFSET = 14
PILE_COUNT_OFFSET = 16
# The lighter top band ends at the divider line, which sits just below the
# counts; the tableau starts a little further down so cards never touch it.
TOP_BAND_HEIGHT = TOP_ROW_Y + CARD_HEIGHT + PILE_COUNT_OFFSET + 14
DIVIDER_HEIGHT = 4
TABLEAU_Y = TOP_BAND_HEIGHT + DIVIDER_HEIGHT + 10

# One font for every header label and button, so the whole row fits.
HEADER_FONT = ("Arial", 11, "bold")
# Gap after each header label; kept small so long-term stats still fit.
HEADER_LABEL_GAP = 10

# Window and canvas sizes.
WINDOW_WIDTH = 860
WINDOW_HEIGHT = 860
CANVAS_HEIGHT = 760

# Derived spacing values that are reused in several layout helpers.
TABLEAU_STEP = CARD_WIDTH + COLUMN_GAP

# Colors used by the simple felt-style interface.
BACKGROUND_COLOR = "#0B6E4F"
TABLE_TOP_COLOR = "#0D7857"
TABLE_ACCENT_DARK = "#09573E"
TABLE_ACCENT_LIGHT = "#128562"
CARD_BACK_COLOR = "#274C77"
CARD_BACK_ACCENT = "#86ADD8"
# Card-back stripes: the gap between stripes, and how far inside the card
# edge they are clipped (inside the 5 px inner frame and its round corners).
CARD_BACK_STRIPE_SPACING = 14
CARD_BACK_STRIPE_INSET = 8
CARD_OUTLINE = "#1E1E1E"
CARD_FILL = "#FFFDF8"
CARD_SHADOW = "#083725"
PLACEHOLDER_FILL = "#0A6248"
EMPTY_OUTLINE = "#DCECC9"
HIGHLIGHT_COLOR = "#FFD24D"
# A separate colour for hint highlights so a hinted destination is never
# confused with the yellow selection highlight on the card the player lifted.
HINT_COLOR = "#FF8A3D"
# Selected and hinted piles (cards and empty placeholders) share this outline.
HIGHLIGHT_OUTLINE_WIDTH = 4
# Empty-pile text: a single symbol ("K", a suit) is large; the words "Reset"
# and "Waste" are smaller so they fit inside the 88 px placeholder.
EMPTY_PILE_SYMBOL_FONT_SIZE = 20
EMPTY_PILE_WORD_FONT_SIZE = 14

# The "YOU WIN!" banner plate: big enough to frame 56pt text with room to
# spare on any font, dark so the yellow text and rim stand out.
WIN_PLATE_WIDTH = 520
WIN_PLATE_HEIGHT = 130
WIN_PLATE_RADIUS = 18
WIN_PLATE_RIM_WIDTH = 4
WIN_PLATE_COLOR = "#06301F"

# Animation timing. More steps means smoother movement.
ANIMATION_STEPS = 18
ANIMATION_DELAY_MS = 16

# Limit the number of undo snapshots so memory use stays reasonable.
UNDO_HISTORY_LIMIT = 300

# Human-friendly symbols for each suit.
SUIT_SYMBOLS = {
    "hearts": "\u2665",
    "diamonds": "\u2666",
    "clubs": "\u2663",
    "spades": "\u2660",
}

SUIT_COLORS = {
    "hearts": "#C62828",
    "diamonds": "#C62828",
    "clubs": "#1A1A1A",
    "spades": "#1A1A1A",
}

RANK_LABELS = {
    1: "A",
    11: "J",
    12: "Q",
    13: "K",
}

FOUNDATION_SUITS = ["hearts", "diamonds", "clubs", "spades"]

# Board structure for a standard Klondike layout.
TABLEAU_COLUMNS = 7
FOUNDATION_COUNT = 4

# The tableau's columns plus the gaps between them. The side margin is the
# width left over, split evenly, so the board sits centred in the window.
BOARD_WIDTH = TABLEAU_COLUMNS * CARD_WIDTH + (TABLEAU_COLUMNS - 1) * COLUMN_GAP
MARGIN_X = (WINDOW_WIDTH - BOARD_WIDTH) // 2

# --------------------------------------------------------------------------
# Sound
# --------------------------------------------------------------------------
# Every sound is a recipe: a list of `Note`s that audio.py renders into
# samples when the app starts (no audio files ship with the game). Pitches
# are MIDI note numbers through `midi()`: 69 is A4 (440 Hz), +12 is one octave
# up. The palette is soft felt and paper: quiet noise ticks for cards sliding
# and landing, and a gentle piano-like chime in C major, the key of the music.
#
# Beginner note:
# - A "strike" note below has no sustain: it rises over a few milliseconds
#   and then rings down over `ring` seconds, like a hammer hitting a string.
# - A "paper" note is a burst of noise. Its rate (new random values per
#   second) sets the colour: a low rate is a dull felt thud, a high one a
#   crisp paper tick.
# - Volumes stay well under 1.0 on purpose: auto-solve fires a chime every
#   few frames, and overlapping sounds add up.
SFX_STRIKE_ATTACK = 0.006  # A struck note reaches full volume this fast (s).
SFX_STRIKE_RELEASE = 0.03  # Tail after a strike's ring, so it never ends abruptly (s).
SFX_ROOT_NOTE = 60  # C4: the Ace's chime; every higher rank climbs the C major ladder.
C_MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)  # Semitones above C for each degree of the scale.
# One foundation chime per rank, Ace to King: the chime climbs one degree of
# the ladder per rank, so a foundation filling up sounds like a rising scale.
FOUNDATION_CHIME_STEPS = 13
CHIME_OVERTONE_LEVEL = 0.22  # The bright octave overtone, as a share of the chime's volume.
CHIME_OVERTONE_RING = 0.4  # The overtone rings for this share of the chime's ring, then fades.
# The new-game deal: a cascade of soft paper ticks, one per card dealt to the
# top of a column, alternating two noise rates so it sounds like real cards.
DEAL_TICKS = 10
DEAL_TICK_SPACING = 0.045  # Seconds between two dealt cards.
# Recycling the waste: a quick riffle of ticks under a falling paper sweep.
RECYCLE_TICKS = 8
RECYCLE_TICK_SPACING = 0.03


def strike(pitch: float, start: float, ring: float, volume: float, voice: str = "sine", glide: float = 0.0) -> Note:
    """Return a struck note: a near-instant attack, then a ring down to silence."""
    return Note(
        midi(pitch),
        start,
        SFX_STRIKE_ATTACK + ring,
        voice,
        volume,
        glide=glide,
        attack=SFX_STRIKE_ATTACK,
        decay=ring,
        sustain=0.0,
        release=SFX_STRIKE_RELEASE,
    )


def chime(pitch: float, start: float, ring: float, volume: float) -> list[Note]:
    """Return one soft piano-like note: a round sine body plus a brief bright overtone an octave up.

    Beginner note:
    - A real piano string sounds mostly at its own pitch, with a short burst
      of brighter overtones as the hammer strikes. Two notes played together,
      one short and quiet an octave higher, imitate that without samples.
    """
    return [
        strike(pitch, start, ring, volume),
        strike(pitch + 12, start, ring * CHIME_OVERTONE_RING, volume * CHIME_OVERTONE_LEVEL, "pluck"),
    ]


def paper(start: float, rate: float, volume: float, ring: float = 0.03, glide: float = 0.0) -> Note:
    """Return a short noise burst: a card tick, a slide or a soft thud on the felt."""
    return Note(rate, start, 0.004, "noise", volume, glide=glide, attack=0.001, decay=ring, sustain=0.0,
                release=0.01)


def scale_note(degree: int) -> int:
    """Return the MIDI note `degree` steps up the C major ladder from SFX_ROOT_NOTE."""
    octave, step = divmod(degree, len(C_MAJOR_STEPS))
    return SFX_ROOT_NOTE + 12 * octave + C_MAJOR_STEPS[step]


def foundation_chime(rank: int) -> list[Note]:
    """Return the chime for a card of `rank` landing on its foundation, with a soft landing tick."""
    return [*chime(scale_note(rank - 1), 0.0, 0.35, 0.16), paper(0.0, 2400.0, 0.06, 0.02)]


def auto_step_chime(rank: int) -> list[Note]:
    """Return auto-solve's quicker, lighter version of the foundation chime."""
    return chime(scale_note(rank - 1), 0.0, 0.14, 0.12)


SFX_RECIPES: dict[str, list[Note]] = {
    # Picking a card up: a light paper tick with a faint high glint.
    "select": [paper(0.0, 5000.0, 0.12, 0.03), strike(84, 0.0, 0.04, 0.05)],
    # Setting cards down on a tableau column: a soft felt thud.
    "place": [
        paper(0.0, 1200.0, 0.18, 0.05),
        strike(48, 0.0, 0.06, 0.1, "triangle"),
        paper(0.012, 3000.0, 0.06, 0.02),
    ],
    # A card reaching its foundation: a chime that climbs with the rank
    # ("foundation@1" for an Ace up to "foundation@13" for a King).
    "foundation": foundation_chime(1),
    **{f"foundation@{rank}": foundation_chime(rank) for rank in range(1, FOUNDATION_CHIME_STEPS + 1)},
    # Auto-solve sending a card home: the same ladder, quicker and lighter.
    "auto_step": auto_step_chime(1),
    **{f"auto_step@{rank}": auto_step_chime(rank) for rank in range(1, FOUNDATION_CHIME_STEPS + 1)},
    # A hidden card turning face up: a quick upward paper flip and a tick.
    "flip": [
        Note(3500.0, 0.0, 0.05, "noise", 0.1, glide=9000.0, attack=0.008, decay=0.05, sustain=0.2, release=0.02),
        paper(0.05, 6000.0, 0.06, 0.02),
    ],
    # Drawing from the stock: a card sliding off the pile, landing with a tick.
    "draw": [
        Note(2500.0, 0.0, 0.08, "noise", 0.1, glide=-6000.0, attack=0.01, decay=0.07, sustain=0.2, release=0.02),
        paper(0.08, 4000.0, 0.08, 0.02),
    ],
    # Recycling the waste into the stock: a quick riffle under a falling
    # sweep, settling with a soft low note.
    "recycle": [
        *(paper(index * RECYCLE_TICK_SPACING, 3000.0 + 600.0 * (index % 3), 0.08, 0.02)
          for index in range(RECYCLE_TICKS)),
        Note(4000.0, 0.0, 0.25, "noise", 0.05, glide=-3000.0, attack=0.03, decay=0.2, sustain=0.4, release=0.05),
        strike(48, RECYCLE_TICKS * RECYCLE_TICK_SPACING, 0.1, 0.1, "triangle"),
    ],
    # Clicking an empty stock with no waste left: two dull knocks.
    "empty": [paper(0.0, 700.0, 0.14, 0.05), paper(0.09, 650.0, 0.12, 0.05), strike(45, 0.0, 0.08, 0.08, "triangle")],
    # A move the rules do not allow: a soft falling "uh-uh", never harsh.
    "invalid": [strike(62, 0.0, 0.1, 0.16, "triangle"), strike(59, 0.11, 0.16, 0.16, "triangle")],
    # Undo: a short rewind, a falling glide over a falling paper sweep.
    "undo": [
        Note(midi(76), 0.0, 0.12, "sine", 0.12, glide=-900.0, attack=0.01, decay=0.1, sustain=0.3, release=0.04),
        Note(4000.0, 0.0, 0.1, "noise", 0.06, glide=-15000.0, attack=0.01, decay=0.09, sustain=0.2, release=0.02),
    ],
    # A hint: a gentle two-note sparkle rising a fifth (E5 to B5).
    "hint": [*chime(76, 0.0, 0.2, 0.12), *chime(83, 0.09, 0.3, 0.11)],
    # A new deal: a cascade of soft paper ticks, then a settling thud.
    "deal": [
        *(paper(index * DEAL_TICK_SPACING, 4200.0 if index % 2 else 3400.0, 0.1, 0.025) for index in range(DEAL_TICKS)),
        paper(DEAL_TICKS * DEAL_TICK_SPACING, 1200.0, 0.12, 0.05),
    ],
    # A short, soft two-note click for the Help and Sound buttons.
    "click": [strike(84, 0.0, 0.05, 0.18), strike(91, 0.012, 0.04, 0.06)],
}
# The fewest seconds between two plays of the same effect (variants share
# their base name's cooldown). Auto-solve can land a card and click the stock
# within a few frames; these keep such bursts a gentle patter.
SFX_COOLDOWNS: dict[str, float] = {
    "select": 0.04,
    "place": 0.04,
    "foundation": 0.03,
    "auto_step": 0.06,
    "flip": 0.05,
    "draw": 0.05,
    "recycle": 0.2,
    "invalid": 0.15,
    "click": 0.04,
}
# The sound for each answer `KlondikeGame.draw_from_stock` can give.
STOCK_SOUNDS = {"draw": "draw", "reset": "recycle", "empty": "empty"}

# Game-over jingles: the music fades out and one of these plays. The win
# jingle sounds together with the confetti.
SFX_RECIPES.update(
    {
        # A win: a rising C major arpeggio that blooms into a held chord over
        # a low C, with a high sparkle on top.
        "win": [
            *(
                note
                for index, pitch in enumerate((60, 64, 67, 72, 76))
                for note in chime(pitch, index * 0.1, 0.4, 0.15)
            ),
            *(
                Note(midi(pitch), 0.5, 0.8, "triangle", 0.08, attack=0.04, decay=0.25, sustain=0.6, release=0.8)
                for pitch in (72, 76, 79, 84)
            ),
            Note(midi(36), 0.5, 0.8, "sine", 0.2, attack=0.06, decay=0.25, sustain=0.8, release=0.8),
            strike(96, 0.5, 0.6, 0.06),
        ],
        # A loss: a gentle descending A minor phrase settling on a soft low A.
        "lose": [
            Note(midi(76), 0.0, 0.28, "triangle", 0.2, attack=0.015, decay=0.1, sustain=0.6, release=0.2),
            Note(midi(72), 0.34, 0.28, "triangle", 0.2, attack=0.015, decay=0.1, sustain=0.6, release=0.2),
            Note(midi(69), 0.68, 0.7, "triangle", 0.22, attack=0.015, decay=0.2, sustain=0.6, release=0.55),
            Note(midi(45), 0.68, 0.7, "sine", 0.18, attack=0.2, decay=0.2, sustain=0.8, release=0.55),
            Note(midi(52), 0.68, 0.7, "sine", 0.08, attack=0.3, decay=0.2, sustain=0.8, release=0.55),
        ],
    }
)

# Music: a calm lo-fi piano loop in C major, rendered once (off the main
# thread) and played on the reserved mixer channel 0 (see `music_notes`).
# Soft piano chords drift down Fmaj7 - Em7 - Dm7 - Cmaj7, a round sine bass
# holds the roots, a sparse melody wanders on top, and a muffled kick, brush
# and hi-hat keep a slow, lightly swung pulse.
#
# Beginner note:
# - "Swing" plays pairs of eighth notes long-short instead of evenly: the
#   off-beat note arrives late, at MUSIC_SWING of the beat instead of half
#   way. Lo-fi music swings only a little, which makes it feel lazy.
# - A seventh chord (maj7, m7) stacks one more third on a plain chord; that
#   soft, unresolved colour is what makes this style sound mellow.
MUSIC_BPM = 72  # Beats per minute: slow and relaxed.
MUSIC_BEATS_PER_BAR = 4
MUSIC_BEAT_SECONDS = 60.0 / MUSIC_BPM
MUSIC_SWING = 0.58  # Where the off-beat eighth lands inside the beat ("lightly swung").
MUSIC_VOLUME = 0.2  # Channel volume: low, so the card sounds sit on top of the music.
MUSIC_FADE_IN_MS = 2000  # The tune eases in when the app opens or a new game is dealt.
MUSIC_GAME_OVER_FADE_MS = 800  # How quickly the tune fades under a game-over jingle.
# How often the app lets the music player turn a finished render into a
# playing sound (ms). It is checked on the tkinter main thread, which is the
# only thread allowed to create pygame sounds.
AUDIO_TICK_MS = 50
# Each chord: (bass root as a MIDI number, the piano's voicing as MIDI
# numbers). The voicings step down together, so the chords glide smoothly.
MUSIC_CHORDS: dict[str, tuple[int, tuple[int, ...]]] = {
    "Fmaj7": (41, (53, 57, 60, 64)),
    "Em7": (40, (52, 55, 59, 62)),
    "Dm7": (38, (50, 53, 57, 60)),
    "Cmaj7": (36, (48, 52, 55, 59)),
    "G7sus4": (43, (50, 53, 55, 60)),
}
# The tune, one bar per entry: the bar's chord, then the melody as (beat in
# the bar, length in beats, MIDI pitch). Half beats are swung by
# `music_notes`. The last bar (G7sus4) leans back into the Fmaj7 at the top.
MUSIC_SCORE: tuple[tuple[str, tuple[tuple[float, float, int], ...]], ...] = (
    ("Fmaj7", ((0, 1, 76), (1.5, 0.5, 74), (2, 1, 72), (3, 1, 69))),
    ("Em7", ((0.5, 1, 71), (2, 1.5, 67), (3.5, 0.5, 69))),
    ("Dm7", ((0, 1, 72), (1, 0.5, 74), (1.5, 1.5, 77), (3, 1, 76))),
    ("Cmaj7", ((0, 2, 74), (2.5, 1.5, 71))),
    ("Fmaj7", ((0, 1, 81), (1, 0.5, 79), (1.5, 0.5, 76), (2, 2, 77))),
    ("Em7", ((0, 1, 76), (1, 1, 74), (2.5, 1.5, 71))),
    ("Dm7", ((0, 0.5, 69), (0.5, 0.5, 72), (1, 1, 74), (2, 1, 77), (3, 1, 76))),
    ("G7sus4", ((0, 2, 74), (2, 1, 72), (3, 1, 67))),
)
MUSIC_BARS = len(MUSIC_SCORE)
MUSIC_LOOP_SECONDS = MUSIC_BARS * MUSIC_BEATS_PER_BAR * MUSIC_BEAT_SECONDS  # About 26.7 s at 72 BPM.
MUSIC_CHORD_VOLUME = 0.05  # Per chord note; four of them sound together.
MUSIC_CHORD_RING = 1.8  # Beats a struck chord rings.
MUSIC_CHORD_ROLL = 0.025  # Seconds between the chord's notes, low to high, like a gently rolled chord.
MUSIC_PUSH_VOLUME = 0.03  # The softer repeat of the chord on the swung "and" of beat 3.
MUSIC_MELODY_VOLUME = 0.11
MUSIC_MELODY_RING = 1.3  # A melody note rings this many times its written length.
MUSIC_BASS_VOLUME = 0.22
MUSIC_BASS_RING = 1.7  # Beats the bass root rings from beat 1.
MUSIC_KICK_VOLUME = 0.12
MUSIC_KICK_GLIDE = -120.0  # Hz per second: the kick's pitch drops for a soft "thump".
MUSIC_BRUSH_VOLUME = 0.035
MUSIC_BRUSH_RATE = 3000.0  # Noise values per second: a dull, papery brush on beats 2 and 4.
MUSIC_BRUSH_RING = 0.09
MUSIC_HAT_VOLUME = 0.014
MUSIC_HAT_RATE = 7000.0  # A light, airy hi-hat on every swung eighth.
MUSIC_HAT_RING = 0.03


def swung(beat: float) -> float:
    """Return where a written beat position is played: half beats are swung late."""
    whole = math.floor(beat)
    return whole + MUSIC_SWING if beat - whole == 0.5 else beat


def music_notes() -> list[Note]:
    """Return one loop of the lo-fi tune (see `MUSIC_SCORE`).

    Every note ends by `MUSIC_LOOP_SECONDS`: a note that would ring past the
    end is shortened so its release fade finishes exactly there, so the loop
    restarts without a click.
    """
    beat = MUSIC_BEAT_SECONDS
    notes: list[Note] = []
    for bar, (chord, melody) in enumerate(MUSIC_SCORE):
        start = bar * MUSIC_BEATS_PER_BAR * beat
        root, voicing = MUSIC_CHORDS[chord]
        # Piano chords: rolled on beat 1, pushed softly on the swung "and" of 3.
        for at, volume in ((0.0, MUSIC_CHORD_VOLUME), (2.5, MUSIC_PUSH_VOLUME)):
            for index, pitch in enumerate(voicing):
                notes.append(strike(pitch, start + swung(at) * beat + index * MUSIC_CHORD_ROLL,
                                    MUSIC_CHORD_RING * beat, volume))
        notes.append(strike(root, start, MUSIC_BASS_RING * beat, MUSIC_BASS_VOLUME))
        notes.append(strike(root + 7, start + 2 * beat, MUSIC_BASS_RING * beat / 2, MUSIC_BASS_VOLUME * 0.7))
        for at, length, pitch in melody:
            notes += chime(pitch, start + swung(at) * beat, length * beat * MUSIC_MELODY_RING, MUSIC_MELODY_VOLUME)
        # Drums: kick on 1 and 3, brush on 2 and 4, hi-hat on every swung eighth.
        for at in (0.0, 2.0):
            notes.append(strike(33, start + at * beat, 0.18, MUSIC_KICK_VOLUME, glide=MUSIC_KICK_GLIDE))
        for at in (1.0, 3.0):
            notes.append(paper(start + at * beat, MUSIC_BRUSH_RATE, MUSIC_BRUSH_VOLUME, MUSIC_BRUSH_RING))
        for eighth in range(MUSIC_BEATS_PER_BAR * 2):
            notes.append(paper(start + swung(eighth / 2) * beat, MUSIC_HAT_RATE, MUSIC_HAT_VOLUME, MUSIC_HAT_RING))
    fitted = []
    for note in notes:
        if note.end > MUSIC_LOOP_SECONDS:
            room = MUSIC_LOOP_SECONDS - note.start - note.release
            if room <= 0:
                continue
            note = replace(note, length=room)
        fitted.append(note)
    return fitted


def _user_save_dir() -> str:
    """Return a stable per-user folder for save data, creating it if needed.

    This must not be derived from __file__: a PyInstaller --onefile build
    resolves __file__ into a temporary folder that Windows deletes when the
    .exe closes, which is why the high score used to reset every session.
    %APPDATA% persists across runs whether the game runs as a script or a
    frozen .exe.
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    save_dir = os.path.join(base, "Klondike Solitaire")
    os.makedirs(save_dir, exist_ok=True)
    return save_dir


def _resource_path(name: str) -> str:
    """Return the path to a bundled read-only resource file, such as the icon.

    PyInstaller unpacks bundled data into sys._MEIPASS at runtime; running from
    source the file simply sits next to this script.
    """
    base = getattr(sys, "_MEIPASS", None)
    base_dir = base if base else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, name)


def _log_error(error: Exception, save_dir: Path) -> None:
    """Write save/load failures to a small per-user error log.

    Save errors should not crash the game window. If the log itself cannot be
    written, the final ``except`` keeps that secondary failure invisible too.
    """

    try:
        save_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with (save_dir / "error.log").open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {error}\n")
    except OSError:
        pass


@dataclass
class Card:
    """One playing card, including whether it is face up on the board."""

    suit: str
    rank: int
    face_up: bool = False

    def color(self) -> str:
        """Return the card color used by Solitaire move rules."""
        return "red" if self.suit in ("hearts", "diamonds") else "black"

    def label(self) -> str:
        """Build a short text label like 'Q♥' or '10♣'."""
        rank_text = RANK_LABELS.get(self.rank, str(self.rank))
        return f"{rank_text}{SUIT_SYMBOLS[self.suit]}"


@dataclass
class Selection:
    """A group of currently selected cards and where they came from.

    `source_type` is "waste", "foundation" or "tableau". `pile_index` says
    which foundation or tableau column (it is always 0 for the waste), and
    `card_index` is the position of the first selected card inside that
    pile. `cards` is the moving stack itself, front card first: one card
    for the waste or a foundation, possibly several for a tableau run.
    """

    source_type: str
    pile_index: int
    card_index: int
    cards: list[Card]


@dataclass
class HintMove:
    """A possible move plus a ready-to-show explanation for the player.

    The source fields mirror `Selection`, with one extra source type:
    "future_waste" means the card is not on the waste yet and only arrives
    there after `stock_clicks` clicks on the stock (0 for every other move).
    `destination_type` is "foundation" or "tableau", and `description` is
    the finished hint sentence shown in the status bar.
    """

    source_type: str
    source_index: int
    source_card_index: int
    cards: list[Card]
    destination_type: str
    destination_index: int
    stock_clicks: int
    description: str


@dataclass
class AnimationState:
    """Information needed to draw cards moving between two positions.

    `start_positions` and `end_positions` hold one top-left canvas point per
    moving card. `frame` counts up from 0 to `steps`; the drawing code turns
    that ratio into how far along its path each card is. The destination
    fields tell the board which pile must hide the cards while they are
    still in flight, and `completion_message` is shown once they land.
    """

    cards: list[Card]
    start_positions: list[tuple[float, float]]
    end_positions: list[tuple[float, float]]
    destination_type: str
    destination_index: int
    completion_message: str
    frame: int = 0
    steps: int = ANIMATION_STEPS


class KlondikeGame:
    """Game model: stores the board and enforces the Klondike rules.

    This class has no tkinter code at all. The app, the tests and any
    simulation drive it only through its methods, so the rules live in one
    place and can be checked without opening a window.

    Key attributes:
    - `stock`, `waste`: lists of `Card`; the LAST item is the top card.
    - `foundations`: four lists, one per suit in `FOUNDATION_SUITS` order.
    - `tableau`: seven lists; index 0 is the card at the back of a column
      and the last item is the uncovered card at its front.
    - `score`, `high_score`, `wins`, `losses`: scoring and statistics; the
      last three are saved to JSON at `high_score_path`.
    - `won`, `lost`: set by the app when a game ends; they freeze input.
    - `rng`: the random generator used to shuffle (seedable for tests).
    - `_seen_positions`: every board this deal has left behind, used by
      the hint engine to avoid suggesting moves that undo earlier ones.

    The methods fall into three groups: dealing and saving, the move rules
    (selections, legality checks, moving cards), and the hint engine, which
    also decides when a game is lost (see the banner comment further down).
    """

    # Score values used by the game.
    FOUNDATION_POINTS = 10
    REVEAL_POINTS = 5
    WIN_BONUS = 100
    # The time bonus starts at this many points and drops by one per second
    # of play, so a win after 700 seconds (11:40) or more earns no time bonus.
    TIME_BONUS_CAP = 700

    def __init__(self, high_score_path: str, rng: random.Random | None = None) -> None:
        """Create a new game model and load saved score/statistics data.

        Beginner note: `rng` is the random-number generator used to shuffle.
        The real app passes nothing and gets a fresh, unpredictable one; tests
        and simulations pass `random.Random(seed)` so the same seed always
        deals exactly the same cards, which makes results reproducible.
        """
        # Remember where score/statistics JSON should be saved.
        self.high_score_path = high_score_path
        self.rng = rng if rng is not None else random.Random()

        # Load any previously saved high score and win/loss counts.
        saved_data = self.load_saved_data()
        self.high_score = saved_data["high_score"]
        self.wins = saved_data["wins"]
        self.losses = saved_data["losses"]

        # These values are reset for each new deal.
        self.score = 0
        self.stock: list[Card] = []
        self.waste: list[Card] = []
        self.foundations: list[list[Card]] = [[] for _ in range(FOUNDATION_COUNT)]
        self.tableau: list[list[Card]] = [[] for _ in range(TABLEAU_COLUMNS)]
        self.won = False
        self.lost = False
        # Every board position this deal has left behind; see find_best_move.
        self._seen_positions: set[tuple] = set()

        # Start with a fresh shuffled board.
        self.new_game()

    def new_game(self) -> None:
        """Reset the board and deal a standard Klondike opening layout.

        The deal gives column 1 one card, column 2 two cards, and so on up to
        seven cards in column 7 (28 cards in all). Only the last card dealt to
        each column is face up. The remaining 24 cards become the face-down
        stock. The score and the seen-position memory are cleared, but the
        saved high score and win/loss counts are kept.
        """
        # Reset score and all piles for a fresh deal.
        self.score = 0
        self.stock = []
        self.waste = []
        self.foundations = [[] for _ in range(FOUNDATION_COUNT)]
        self.tableau = [[] for _ in range(TABLEAU_COLUMNS)]
        self.won = False
        self.lost = False
        self._seen_positions = set()

        # Build and shuffle a full 52-card deck.
        deck = self.create_shuffled_deck()

        # Deal 1 card to the first column, 2 to the second, and so on.
        for column_index in range(TABLEAU_COLUMNS):
            for row_index in range(column_index + 1):
                # Pop from the end because it is the cheapest list operation.
                card = deck.pop()

                # Only the last dealt card in each column starts face up.
                card.face_up = row_index == column_index
                self.tableau[column_index].append(card)

        # Whatever is left becomes the stock pile.
        self.stock = deck

        # Make sure all stock cards are face down.
        for card in self.stock:
            card.face_up = False

    def create_shuffled_deck(self) -> list[Card]:
        """Create a normal 52-card deck and shuffle it in place."""
        deck = [Card(suit=suit, rank=rank) for suit in FOUNDATION_SUITS for rank in range(1, 14)]
        self.rng.shuffle(deck)
        return deck

    def load_saved_data(self) -> dict:
        """Read saved high score and statistics from JSON, if possible.

        Returns a dict with the integer keys "high_score", "wins" and
        "losses". The method never raises: a missing, unreadable or
        malformed file, or a field that is not a usable number, simply
        reads as 0, and negative numbers are clamped up to 0. That way a
        damaged save costs the player their statistics, never the game.
        """
        try:
            with open(self.high_score_path, encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError, TypeError, RecursionError, json.JSONDecodeError):
            # If the file is missing or broken, silently start from zeros.
            # RecursionError covers absurdly deep nesting such as "[[[[...".
            data = {}
        if not isinstance(data, dict):
            # Valid JSON of the wrong shape (a list, a number, null) is as
            # useless as a broken file, so it also starts from zeros.
            data = {}

        def safe_int(name: str) -> int:
            """Read one numeric field safely and clamp it to 0 or higher.

            OverflowError covers JSON numbers such as 1e400 that load as
            infinity, which int() cannot convert.
            """
            try:
                return max(0, int(data.get(name, 0)))
            except (ValueError, TypeError, OverflowError):
                return 0

        return {
            "high_score": safe_int("high_score"),
            "wins": safe_int("wins"),
            "losses": safe_int("losses"),
        }

    def save_high_score(self) -> None:
        """Write best score and win/loss counts with a crash-safe atomic write.

        Beginner note: an "atomic" write means other code (or the next run of
        the game) sees either the complete old file or the complete new file,
        never a half-written mix. The data goes to a temporary file first and
        `os.replace` then swaps it into place in a single step.
        """
        payload = {
            "high_score": self.high_score,
            "wins": self.wins,
            "losses": self.losses,
        }
        try:
            os.makedirs(os.path.dirname(self.high_score_path), exist_ok=True)
            # Write to a temp file first, then atomically replace the real file
            # so a crash mid-write can never leave a half-written save behind.
            tmp_path = self.high_score_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2)
            os.replace(tmp_path, self.high_score_path)
        except OSError as error:
            # Saving should never crash the game; log the failure and move on.
            _log_error(error, Path(self.high_score_path).parent)

    def add_score(self, points: int) -> None:
        """Add points to the current score; save only when the high score rises."""
        self.score += points
        if self.score > self.high_score:
            self.high_score = self.score
            self.save_high_score()

    def record_win(self) -> None:
        """Increase the saved win counter."""
        self.wins += 1
        self.save_high_score()

    def record_loss(self) -> None:
        """Increase the saved loss counter."""
        self.losses += 1
        self.save_high_score()

    def snapshot(self) -> dict:
        """Capture the entire game state so Undo can restore it later.

        Cards are copied into plain dictionaries, so later moves (which
        mutate `Card` objects, for example flipping them face up) cannot
        reach back and change a snapshot that is already stored.
        """
        return {
            "score": self.score,
            "high_score": self.high_score,
            "wins": self.wins,
            "losses": self.losses,
            "won": self.won,
            "lost": self.lost,
            "stock": self.serialize_cards(self.stock),
            "waste": self.serialize_cards(self.waste),
            "foundations": [self.serialize_cards(pile) for pile in self.foundations],
            "tableau": [self.serialize_cards(column) for column in self.tableau],
            # Undo must also forget the positions it takes back, or the hint
            # engine would keep avoiding moves the player never really made.
            "seen_positions": frozenset(self._seen_positions),
        }

    def restore_snapshot(self, snapshot: dict) -> None:
        """Restore a previously saved game state.

        Everything goes back to the snapshot, including the win/loss counts
        (so undoing out of a lost game also takes that loss back off the
        statistics), with one exception: the high score never goes down.
        The result is saved straight away so the file matches the board.
        """
        # Keep the best score the player has ever reached in this session/file.
        previous_high_score = self.high_score
        self.score = int(snapshot["score"])
        self.high_score = max(previous_high_score, int(snapshot["high_score"]))
        self.wins = int(snapshot["wins"])
        self.losses = int(snapshot["losses"])
        self.won = bool(snapshot["won"])
        self.lost = bool(snapshot["lost"])
        self.stock = self.deserialize_cards(snapshot["stock"])
        self.waste = self.deserialize_cards(snapshot["waste"])
        self.foundations = [self.deserialize_cards(pile) for pile in snapshot["foundations"]]
        self.tableau = [self.deserialize_cards(column) for column in snapshot["tableau"]]
        self._seen_positions = set(snapshot["seen_positions"])
        self.save_high_score()

    def serialize_cards(self, cards: list[Card]) -> list[dict]:
        """Turn Card objects into plain dictionaries that JSON can store."""
        return [
            {
                "suit": card.suit,
                "rank": card.rank,
                "face_up": card.face_up,
            }
            for card in cards
        ]

    def deserialize_cards(self, serialized_cards: list[dict]) -> list[Card]:
        """Rebuild Card objects from saved dictionaries."""
        return [
            Card(
                suit=str(card_data["suit"]),
                rank=int(card_data["rank"]),
                face_up=bool(card_data["face_up"]),
            )
            for card_data in serialized_cards
        ]

    def draw_from_stock(self) -> str:
        """Draw from the stock or recycle waste back into stock.

        Returns "draw" when one card moved to the waste, "reset" when the
        waste was turned back over into the stock, and "empty" when both
        piles are empty and nothing changed. The app uses this word to pick
        its status message and to decide whether an Undo step is needed.
        """
        if self.stock or self.waste:
            # Only a click that really changes the board is remembered.
            self.remember_position()
        if self.stock:
            # Normal draw: reveal one card and place it on the waste pile.
            card = self.stock.pop()
            card.face_up = True
            self.waste.append(card)
            return "draw"

        if self.waste:
            # When stock is empty, recycle the waste pile back into stock.
            # Popping from the waste's top and appending to the stock
            # reverses the order, so the first card drawn this time round
            # is the one that was drawn first last time, as in a real deck.
            while self.waste:
                card = self.waste.pop()
                card.face_up = False
                self.stock.append(card)
            return "reset"

        # No cards anywhere means no draw action is possible.
        return "empty"

    def selection_from_waste(self) -> Selection | None:
        """Return the selectable top waste card, if one exists."""
        if not self.waste:
            return None
        return Selection("waste", 0, len(self.waste) - 1, [self.waste[-1]])

    def selection_from_foundation(self, foundation_index: int) -> Selection | None:
        """Return the top card of a foundation as a Selection."""
        pile = self.foundations[foundation_index]
        if not pile:
            return None
        return Selection("foundation", foundation_index, len(pile) - 1, [pile[-1]])

    def selection_from_tableau(self, column_index: int, card_index: int) -> Selection | None:
        """Build a selection from the real tableau currently on the board."""
        return self.selection_from_tableau_cards(self.tableau, column_index, card_index)

    def selection_from_tableau_cards(
        self, tableau: list[list[Card]], column_index: int, card_index: int
    ) -> Selection | None:
        """
        Build a movable tableau stack from any supplied tableau-like board.

        This helper is used both on the real board and on simulated boards
        created while the hint system tests future situations.
        """
        column = tableau[column_index]
        if card_index < 0 or card_index >= len(column):
            return None

        # A tableau move can include the clicked card and every card below it.
        stack = column[card_index:]
        if not stack or not stack[0].face_up:
            return None
        if not self.is_valid_tableau_stack(stack):
            return None
        return Selection("tableau", column_index, card_index, list(stack))

    def selection_from_hint(self, move: HintMove) -> Selection | None:
        """Translate a stored hint back into a live selectable stack."""
        if move.source_type == "waste":
            return self.selection_from_waste()
        if move.source_type == "foundation":
            return self.selection_from_foundation(move.source_index)
        if move.source_type == "tableau":
            return self.selection_from_tableau(move.source_index, move.source_card_index)
        return None

    def is_valid_tableau_stack(self, cards: list[Card]) -> bool:
        """Check the red-black descending order required in tableau stacks."""
        if not cards or not all(card.face_up for card in cards):
            return False
        for index in range(len(cards) - 1):
            current_card = cards[index]
            next_card = cards[index + 1]
            if current_card.color() == next_card.color():
                return False
            if current_card.rank != next_card.rank + 1:
                return False
        return True

    def can_move_to_tableau(self, cards: list[Card], column_index: int) -> bool:
        """Convenience wrapper that checks a move against one real tableau column."""
        return self.can_move_to_tableau_cards(cards, self.tableau[column_index])

    def can_move_to_tableau_cards(self, cards: list[Card], destination: list[Card]) -> bool:
        """Check the standard tableau rule for any destination pile."""
        if not cards:
            return False
        moving_card = cards[0]
        if not destination:
            # Only a king can start an empty tableau column.
            return moving_card.rank == 13
        top_card = destination[-1]
        if not top_card.face_up:
            return False
        if top_card.color() == moving_card.color():
            return False
        return top_card.rank == moving_card.rank + 1

    def can_move_to_foundation(self, card: Card, foundation_index: int) -> bool:
        """Convenience wrapper for checking one real foundation pile."""
        return self.can_move_to_foundation_piles(card, foundation_index, self.foundations)

    def can_move_to_foundation_piles(
        self,
        card: Card,
        foundation_index: int,
        foundations: list[list[Card]],
    ) -> bool:
        """Check whether a card can be placed on a given foundation pile."""
        expected_suit = FOUNDATION_SUITS[foundation_index]
        if card.suit != expected_suit:
            return False
        destination = foundations[foundation_index]
        if not destination:
            # Empty foundations must start with an Ace.
            return card.rank == 1
        return card.rank == destination[-1].rank + 1

    def move_selection_to_tableau(self, selection: Selection, column_index: int) -> bool:
        """Move a selected stack to another tableau column if legal."""
        if selection.source_type == "tableau" and selection.pile_index == column_index:
            return False
        if not self.can_move_to_tableau(selection.cards, column_index):
            return False
        self.remember_position()
        moving_cards = self.remove_selection(selection)
        self.tableau[column_index].extend(moving_cards)
        return True

    def move_selection_to_foundation(self, selection: Selection, foundation_index: int) -> bool:
        """Move one selected card to a foundation pile if legal."""
        if len(selection.cards) != 1:
            return False
        if selection.source_type == "foundation" and selection.pile_index == foundation_index:
            return False
        card = selection.cards[0]
        if not self.can_move_to_foundation(card, foundation_index):
            return False
        self.remember_position()
        moving_cards = self.remove_selection(selection)
        self.foundations[foundation_index].extend(moving_cards)
        self.add_score(self.FOUNDATION_POINTS)
        return True

    def remove_selection(self, selection: Selection) -> list[Card]:
        """
        Remove the selected cards from their source pile and return them.

        For tableau columns, this method also flips the newly uncovered top
        card if needed.
        """
        if selection.source_type == "waste":
            return [self.waste.pop()]
        if selection.source_type == "foundation":
            # Taking a card back off a foundation refunds the points it earned,
            # so moving it down and up again can never farm score. The score
            # may dip below zero; the high score is deliberately left alone.
            self.score -= self.FOUNDATION_POINTS
            return [self.foundations[selection.pile_index].pop()]
        column = self.tableau[selection.pile_index]
        moving_cards = column[selection.card_index:]
        del column[selection.card_index:]
        self.reveal_top_tableau_card(selection.pile_index)
        return moving_cards

    def reveal_top_tableau_card(self, column_index: int) -> None:
        """Flip the top hidden card in a tableau column and award points."""
        column = self.tableau[column_index]
        if column and not column[-1].face_up:
            column[-1].face_up = True
            self.add_score(self.REVEAL_POINTS)

    def position_key(self) -> tuple:
        """Return the whole board as one hashable value.

        Beginner note: Python sets can only hold hashable (unchangeable)
        values, and lists are changeable, so every pile is turned into a
        tuple of (suit, rank, face_up) tuples before it goes into the set.
        """
        return self.position_key_for(self.stock, self.waste, self.foundations, self.tableau)

    def position_key_for(
        self,
        stock: list[Card],
        waste: list[Card],
        foundations: list[list[Card]],
        tableau: list[list[Card]],
    ) -> tuple:
        """Build a hashable position key from any supplied set of piles."""

        def pile_key(cards: list[Card]) -> tuple:
            """Freeze one pile into a tuple of card tuples."""
            return tuple((card.suit, card.rank, card.face_up) for card in cards)

        return (
            pile_key(stock),
            pile_key(waste),
            tuple(pile_key(pile) for pile in foundations),
            tuple(pile_key(column) for column in tableau),
        )

    def remember_position(self) -> None:
        """Record the current board just before a draw, recycle, or move changes it."""
        self._seen_positions.add(self.position_key())

    def position_after(self, move: HintMove) -> tuple:
        """Return the position key the board would have after playing `move`.

        Everything happens on copied cards, so the real board never changes.
        A future-waste move first replays its stock clicks the same way
        `draw_from_stock` would, then plays the top waste card.
        """
        stock = [Card(card.suit, card.rank, card.face_up) for card in self.stock]
        waste = [Card(card.suit, card.rank, card.face_up) for card in self.waste]
        foundations = [[Card(card.suit, card.rank, card.face_up) for card in pile] for pile in self.foundations]
        tableau = [[Card(card.suit, card.rank, card.face_up) for card in column] for column in self.tableau]

        for _ in range(move.stock_clicks):
            if stock:
                card = stock.pop()
                card.face_up = True
                waste.append(card)
            else:
                while waste:
                    card = waste.pop()
                    card.face_up = False
                    stock.append(card)

        if move.source_type in ("waste", "future_waste"):
            moving = [waste.pop()]
        elif move.source_type == "foundation":
            moving = [foundations[move.source_index].pop()]
        else:
            column = tableau[move.source_index]
            moving = column[move.source_card_index:]
            del column[move.source_card_index:]
            if column and not column[-1].face_up:
                column[-1].face_up = True

        if move.destination_type == "foundation":
            foundations[move.destination_index].extend(moving)
        else:
            tableau[move.destination_index].extend(moving)
        return self.position_key_for(stock, waste, foundations, tableau)

    def has_won(self) -> bool:
        """The game is won when every foundation contains 13 cards."""
        return all(len(pile) == 13 for pile in self.foundations)

    def all_tableau_cards_face_up(self) -> bool:
        """Auto-solve begins only after no hidden tableau cards remain."""
        return all(card.face_up for column in self.tableau for card in column)

    def next_auto_foundation_move(self) -> tuple[Selection, int] | None:
        """
        Return the next direct move to a foundation for auto-complete mode.

        When every tableau card is already face up, a simple foundation-first
        sweep gives the familiar Solitaire auto-finish behavior.
        """
        if self.waste:
            waste_selection = self.selection_from_waste()
            if waste_selection is not None:
                for foundation_index in range(FOUNDATION_COUNT):
                    if self.can_move_to_foundation(waste_selection.cards[0], foundation_index):
                        return waste_selection, foundation_index

        for column_index, column in enumerate(self.tableau):
            if not column or not column[-1].face_up:
                continue
            selection = self.selection_from_tableau(column_index, len(column) - 1)
            if selection is None:
                continue
            for foundation_index in range(FOUNDATION_COUNT):
                if self.can_move_to_foundation(selection.cards[0], foundation_index):
                    return selection, foundation_index

        return None

    # ------------------------------------------------------------------
    # The hint engine
    # ------------------------------------------------------------------
    # Everything from here to `follow_up_creates_concrete_progress` is one
    # subsystem: the hint engine that also powers loss detection. It is a
    # pipeline of four stages:
    #
    #   1. GENERATE  - `current_legal_moves` lists every legal move on the
    #      board right now; `future_waste_moves` simulates clicking through
    #      the stock to find waste cards that become playable later.
    #   2. FILTER    - `is_meaningful_move` throws away legal-but-pointless
    #      shuffles (ace diversions, king shuffles between empty columns,
    #      redundant transfers, unproductive foundation returns).
    #   3. RANK      - `hint_sort_key` / `hint_priority` order what survived;
    #      the lowest priority number wins, except that `find_best_move`
    #      skips any move whose result (`position_after`) is a position the
    #      deal has already been in, so hint play does not loop.
    #   4. DESCRIBE  - `describe_hint` turns the winning move into the text
    #      the player reads.
    #
    # Naming convention: many checks exist twice, as a thin wrapper that
    # reads the REAL board (`is_redundant_tableau_transfer`) plus an
    # `..._on_board` version that takes tableau/foundations as parameters so
    # the same rule can run against SIMULATED "what if" boards. When editing
    # a rule, edit the `_on_board` version - the wrapper only forwards.
    #
    # If no move survives the pipeline (and the stock look-ahead), the game
    # declares the deal lost - so a filter that is too aggressive can cause
    # false "no more moves" verdicts. The filters deliberately allow any
    # move that reveals a hidden card or unlocks a foundation play.
    def find_best_move(self) -> HintMove | None:
        """
        Find the best move for the hint system and loss detection.

        We first prefer moves that are possible right now. If none exist, we
        also look ahead through future stock draws so the hint button can say
        how many clicks away the next useful waste move is.

        Beginner note: without a memory, a hint engine can happily suggest
        moving a card one way and then straight back again, forever. The
        game remembers every position it has left (`_seen_positions`), and
        a move whose result is already in that set is skipped in favour of
        the next-best move. This only changes WHICH move is suggested, never
        WHETHER one exists, so loss detection is unaffected.
        """
        current_moves = self.current_legal_moves()
        current_moves.sort(key=self.hint_sort_key)
        for move in current_moves:
            if self.position_after(move) not in self._seen_positions:
                return move

        future_moves = self.future_waste_moves()
        future_moves.sort(key=self.hint_sort_key)
        for move in future_moves:
            if self.position_after(move) not in self._seen_positions:
                return move

        # Every candidate repeats a position. A repeat still beats declaring
        # the game lost while legal useful moves remain, so offer the best.
        candidates = current_moves or future_moves
        return candidates[0] if candidates else None

    def current_legal_moves(self) -> list[HintMove]:
        """Collect all useful moves that can be made immediately.

        This is stage 1 (GENERATE) for moves that need no stock clicks. It
        looks at three kinds of source in turn: the top waste card, the top
        card of each foundation (moving back down to the tableau), and every
        face-up card in each tableau column together with the cards below
        it. Every legal move found is wrapped in a `HintMove`, and the list
        is then passed through `is_meaningful_move` (stage 2) before it is
        returned, so legal but pointless shuffles never reach the ranking.
        """
        moves: list[HintMove] = []

        if self.waste:
            # The player may only move the top waste card.
            moves.extend(
                self.single_card_moves(
                    self.waste[-1],
                    source_type="waste",
                    source_index=0,
                    source_card_index=len(self.waste) - 1,
                    stock_clicks=0,
                )
            )

        for foundation_index, pile in enumerate(self.foundations):
            if not pile:
                continue
            # Foundation returns are allowed, but later filtered heavily so
            # hints do not suggest pointless back-and-forth moves.
            card = pile[-1]
            for column_index in range(TABLEAU_COLUMNS):
                if self.can_move_to_tableau([card], column_index):
                    moves.append(
                        self.build_hint_move(
                            source_type="foundation",
                            source_index=foundation_index,
                            source_card_index=len(pile) - 1,
                            cards=[card],
                            destination_type="tableau",
                            destination_index=column_index,
                            stock_clicks=0,
                        )
                    )

        for column_index, column in enumerate(self.tableau):
            if not column:
                continue

            top_card = column[-1]
            if top_card.face_up:
                # The top face-up card can move by itself to tableau/foundation.
                moves.extend(
                    self.single_card_moves(
                        top_card,
                        source_type="tableau",
                        source_index=column_index,
                        source_card_index=len(column) - 1,
                        stock_clicks=0,
                    )
                )

            # Every face-up card can lead a run: the card plus everything on
            # top of it. This includes the single top card again, but only
            # its tableau destinations are added here; the foundation moves
            # for it already came from `single_card_moves` above. The repeat
            # tableau entries are harmless, because the sorted list simply
            # holds two equal candidates.
            for card_index, card in enumerate(column):
                if not card.face_up:
                    continue

                selection = self.selection_from_tableau(column_index, card_index)
                if selection is None:
                    continue

                for destination_index in range(TABLEAU_COLUMNS):
                    if destination_index == column_index:
                        continue
                    # Larger face-up stacks can move between tableau columns.
                    if self.can_move_to_tableau(selection.cards, destination_index):
                        moves.append(
                            self.build_hint_move(
                                source_type="tableau",
                                source_index=column_index,
                                source_card_index=card_index,
                                cards=selection.cards,
                                destination_type="tableau",
                                destination_index=destination_index,
                                stock_clicks=0,
                            )
                        )

        return [move for move in moves if self.is_meaningful_move(move)]

    def future_waste_moves(self) -> list[HintMove]:
        """
        Simulate future stock clicks and collect useful waste-based moves.

        This helps the hint system say things like "click the stock twice,
        then move 5♥ to the Hearts foundation."

        The simulation clicks through copies of the stock and waste one card
        at a time, recycling the waste when the stock runs out, exactly as
        `draw_from_stock` would. After each click it tries the new top waste
        card against the real tableau and foundations. It stops as soon as a
        stock/waste arrangement repeats, which means a full cycle has been
        seen. The resulting moves go through `is_meaningful_move` as well.
        """
        future_moves: list[HintMove] = []
        # Keyed by (suit, rank, destination type, destination index); the
        # value is the cheapest (fewest stock clicks) move for that card.
        best_seen: dict[tuple[str, int, str, int], HintMove] = {}

        # Work on copies so the real game state is not changed.
        simulated_stock = list(self.stock)
        simulated_waste = list(self.waste)
        seen_states = set()
        stock_clicks = 0

        while True:
            # If we reach the same stock/waste arrangement again, we would
            # loop forever, so stop the simulation here.
            state_key = (
                tuple((card.suit, card.rank) for card in simulated_stock),
                tuple((card.suit, card.rank) for card in simulated_waste),
            )
            if state_key in seen_states:
                break
            seen_states.add(state_key)

            # With zero clicks the top waste card is the one already on the
            # board; `current_legal_moves` covers it, so only later cards count.
            if simulated_waste and stock_clicks > 0:
                card = simulated_waste[-1]
                for move in self.single_card_moves(
                    card,
                    source_type="future_waste",
                    source_index=0,
                    source_card_index=0,
                    stock_clicks=stock_clicks,
                ):
                    move_key = (
                        move.cards[0].suit,
                        move.cards[0].rank,
                        move.destination_type,
                        move.destination_index,
                    )
                    # The same card can become reachable on several different
                    # stock cycles; keep only the cheapest (fewest clicks) one.
                    old_move = best_seen.get(move_key)
                    if old_move is None or move.stock_clicks < old_move.stock_clicks:
                        best_seen[move_key] = move

            if simulated_stock:
                simulated_waste.append(simulated_stock.pop())
                stock_clicks += 1
                continue

            if simulated_waste:
                # Recycle waste back into stock the same way the real game does.
                while simulated_waste:
                    simulated_stock.append(simulated_waste.pop())
                stock_clicks += 1
                continue

            break

        future_moves.extend(best_seen.values())
        return [move for move in future_moves if self.is_meaningful_move(move)]

    def single_card_moves(
        self,
        card: Card,
        source_type: str,
        source_index: int,
        source_card_index: int,
        stock_clicks: int,
    ) -> list[HintMove]:
        """Build every one-card move available for a given card.

        The card is tried on each foundation and on each tableau column, and
        every legal placement becomes a `HintMove`. The source arguments are
        copied into those moves unchanged, which lets the same helper serve
        the waste, a tableau top card, and simulated "future_waste" cards.
        Two placements are skipped: a foundation card is never offered to a
        foundation, and a tableau card is never offered to its own column.
        The legality checks always use the REAL board, which is fine for
        future-waste cards because stock clicks do not change the tableau
        or the foundations.
        """
        moves: list[HintMove] = []

        if source_type != "foundation":
            # Cards already on a foundation are not suggested back to another foundation.
            for foundation_index in range(FOUNDATION_COUNT):
                if self.can_move_to_foundation(card, foundation_index):
                    moves.append(
                        self.build_hint_move(
                            source_type=source_type,
                            source_index=source_index,
                            source_card_index=source_card_index,
                            cards=[card],
                            destination_type="foundation",
                            destination_index=foundation_index,
                            stock_clicks=stock_clicks,
                        )
                    )

        for column_index in range(TABLEAU_COLUMNS):
            if source_type == "tableau" and source_index == column_index:
                continue
            if self.can_move_to_tableau([card], column_index):
                moves.append(
                    self.build_hint_move(
                        source_type=source_type,
                        source_index=source_index,
                        source_card_index=source_card_index,
                        cards=[card],
                        destination_type="tableau",
                        destination_index=column_index,
                        stock_clicks=stock_clicks,
                    )
                )

        return moves

    def build_hint_move(
        self,
        source_type: str,
        source_index: int,
        source_card_index: int,
        cards: list[Card],
        destination_type: str,
        destination_index: int,
        stock_clicks: int,
    ) -> HintMove:
        """Package move information and its human-readable hint text together.

        The hint sentence is written now, while the board still looks the
        way it did when the move was found, so the text always matches the
        move. `cards` is copied into a new list so later changes to the
        caller's list cannot alter the stored move.
        """
        description = self.describe_hint(
            source_type,
            source_index,
            cards,
            destination_type,
            destination_index,
            stock_clicks,
        )
        return HintMove(
            source_type=source_type,
            source_index=source_index,
            source_card_index=source_card_index,
            cards=list(cards),
            destination_type=destination_type,
            destination_index=destination_index,
            stock_clicks=stock_clicks,
            description=description,
        )

    # ------------------------------------------------------------------
    # Hint engine stage 4: player-facing descriptions
    # ------------------------------------------------------------------
    def describe_hint(
        self,
        source_type: str,
        source_index: int,
        cards: list[Card],
        destination_type: str,
        destination_index: int,
        stock_clicks: int,
    ) -> str:
        """Create the text shown when the player asks for a hint."""
        card_text = self.describe_cards(cards)
        target_text = self.describe_destination(destination_type, destination_index)

        if source_type == "future_waste":
            prefix = "Click the stock once" if stock_clicks == 1 else f"Click the stock {stock_clicks} times"
            return f"Hint: {prefix}, then move {card_text} to {target_text}."

        source_text = self.describe_source(source_type, source_index)
        return f"Hint: Move {card_text} from {source_text} to {target_text}."

    def describe_source(self, source_type: str, source_index: int) -> str:
        """Convert an internal source location into player-friendly text."""
        if source_type == "waste":
            return "the waste"
        if source_type == "foundation":
            suit_name = FOUNDATION_SUITS[source_index].capitalize()
            return f"the {suit_name} foundation"
        return f"tableau column {source_index + 1}"

    def describe_destination(self, destination_type: str, destination_index: int) -> str:
        """Convert an internal destination into player-friendly text."""
        if destination_type == "foundation":
            suit_name = FOUNDATION_SUITS[destination_index].capitalize()
            return f"the {suit_name} foundation"
        return f"tableau column {destination_index + 1}"

    def describe_cards(self, cards: list[Card]) -> str:
        """Describe either one card or the front card of a moving stack."""
        if len(cards) == 1:
            return cards[0].label()
        return f"{len(cards)} cards starting with {cards[0].label()}"

    # ------------------------------------------------------------------
    # Hint engine stage 3: ranking
    # ------------------------------------------------------------------
    def hint_sort_key(self, move: HintMove) -> tuple[int, int, int, int]:
        """Build the sort key that decides which hint move is shown.

        Python sorts tuples item by item, so this orders moves by priority
        first; ties are then broken by fewest stock clicks, and finally by
        pile index so the chosen hint stays stable instead of jumping around.
        """
        return (
            self.hint_priority(move),
            move.stock_clicks,
            move.source_index,
            move.destination_index,
        )

    def hint_priority(self, move: HintMove) -> int:
        """Assign a priority score to a move; the lower the number, the better.

        The hint system shows the move with the lowest priority number. The
        tiers below rank moves roughly from "always do this" (0) down to
        "only if nothing else helps" (90). Beginners can read this method as
        the game's built-in opinion on what a good next move looks like.
        """
        reveals_hidden = self.move_reveals_hidden(move)
        moving_card = move.cards[0]

        # Moves that need future stock clicks are weak: they cost extra clicks,
        # so they rank well below anything that can be played right now.
        if move.source_type == "future_waste":
            if move.destination_type == "foundation":
                return 50 + move.stock_clicks
            return 60 + move.stock_clicks

        # Taking a card back off a foundation is almost never useful.
        if move.source_type == "foundation":
            return 90

        # Sending a card up to a foundation is good, and best when it also
        # uncovers a face-down card that was sitting underneath it.
        if move.destination_type == "foundation":
            if reveals_hidden:
                return 5
            if move.source_type == "waste":
                return 10
            return 15

        # The single most valuable tableau move: it flips a face-down card.
        if reveals_hidden:
            return 0

        # Playing the waste card frees the waste for the next draw.
        if move.source_type == "waste":
            return 20

        # Moving a King into an empty column opens that column for later use.
        if not self.tableau[move.destination_index] and moving_card.rank == 13:
            return 25

        # Any other legal tableau-to-tableau shuffle is the lowest useful tier.
        return 30

    def move_reveals_hidden(self, move: HintMove) -> bool:
        """True when moving this stack would expose a face-down tableau card."""
        if move.source_type != "tableau":
            return False
        if move.source_card_index == 0:
            return False
        return not self.tableau[move.source_index][move.source_card_index - 1].face_up

    # ------------------------------------------------------------------
    # Hint engine stage 2: meaningfulness filters
    # ------------------------------------------------------------------
    def is_meaningful_move(self, move: HintMove) -> bool:
        """
        Filter out technically legal moves that are strategically pointless.

        This is stage 2 (FILTER). The hint system and loss detection both
        ignore several "to and fro" moves that could be repeated forever
        without changing anything that matters, so a move is dropped if it
        is any of: a lone tableau Ace moved to another column, a King-led
        column moved into an empty column, a redundant transfer between
        equivalent tableau cards, or a foundation card pulled back down
        without unlocking real progress. Returns True if the move survives.
        """
        if self.is_tableau_ace_diversion(move):
            return False
        if self.is_empty_king_shuffle(move):
            return False
        if self.is_redundant_tableau_transfer(move):
            return False
        return not self.is_unproductive_foundation_return(move)

    def is_tableau_ace_diversion(self, move: HintMove) -> bool:
        """Never prefer moving a tableau Ace to another tableau.

        An Ace's only useful destination is a foundation, which is always
        open to it, so parking it on another column just wastes a move.
        """
        if move.source_type != "tableau" or move.destination_type != "tableau":
            return False
        return len(move.cards) == 1 and move.cards[0].rank == 1

    def is_empty_king_shuffle(self, move: HintMove) -> bool:
        """Ignore moving a full king-starting pile between empty columns.

        The filter only applies when the King is the bottom card of its column
        (`source_card_index == 0`) and the destination is empty: the source
        column then ends up empty instead, so the board is effectively the
        same as before.
        """
        if move.source_type != "tableau" or move.destination_type != "tableau":
            return False
        if move.source_card_index != 0:
            return False
        if move.cards[0].rank != 13:
            return False
        return len(self.tableau[move.destination_index]) == 0

    def is_redundant_tableau_transfer(self, move: HintMove) -> bool:
        """Wrapper for testing whether a tableau-to-tableau move is pointless."""
        if move.source_type != "tableau" or move.destination_type != "tableau":
            return False
        return self.is_redundant_tableau_transfer_on_board(
            move.source_index,
            move.source_card_index,
            move.cards,
            move.destination_index,
            self.tableau,
            self.foundations,
        )

    def is_redundant_tableau_transfer_on_board(
        self,
        source_index: int,
        source_card_index: int,
        cards: list[Card],
        destination_index: int,
        tableau: list[list[Card]],
        foundations: list[list[Card]],
    ) -> bool:
        """
        Detect tableau shuffles that do not create new opportunities.

        Example: moving a red 6 onto one black 7 when another identical black 7
        is available and neither resulting top card can immediately advance to a
        foundation.

        The checks run in order: a move that reveals a hidden card or goes to
        an empty column is never redundant; a swap between equivalent anchors
        that frees no foundation play (see `is_equivalent_anchor_loop_on_board`)
        always is; otherwise the
        move is redundant only when it targets a non-canonical one of several
        same-rank, same-colour destinations and none of them can feed a
        foundation. Returns True when the move should be filtered out.
        """
        if self.move_reveals_hidden_on_board(source_index, source_card_index, tableau):
            return False

        destination_column = tableau[destination_index]
        if not destination_column:
            return False

        if self.is_equivalent_anchor_loop_on_board(
            source_index, source_card_index, destination_index, tableau, foundations
        ):
            return True

        destination_top = destination_column[-1]
        equivalent_destinations = []

        for column_index, column in enumerate(tableau):
            if column_index == source_index or not column:
                continue
            top_card = column[-1]
            if top_card.rank != destination_top.rank or top_card.color() != destination_top.color():
                continue
            if self.can_move_to_tableau_cards(cards, column):
                equivalent_destinations.append(column_index)

        # One of several equal destinations must stay available: the lowest
        # column is the canonical choice, so the move itself is never hidden
        # just because there is more than one place to put it.
        if len(equivalent_destinations) < 2 or destination_index == min(equivalent_destinations):
            return False

        return not any(
            self.tableau_top_can_move_to_foundation_on_board(column_index, tableau, foundations)
            for column_index in equivalent_destinations
        )

    def is_equivalent_anchor_loop(self, move: HintMove) -> bool:
        """Wrapper for detecting reversible stack swaps between equal anchors."""
        return self.is_equivalent_anchor_loop_on_board(
            move.source_index,
            move.source_card_index,
            move.destination_index,
            self.tableau,
            self.foundations,
        )

    def is_equivalent_anchor_loop_on_board(
        self,
        source_index: int,
        source_card_index: int,
        destination_index: int,
        tableau: list[list[Card]],
        foundations: list[list[Card]],
    ) -> bool:
        """
        Detect moving a tableau stack from one equivalent anchor to another.

        Example:
        - source column: K black, Q red, J black
        - destination column: K black

        Moving the Q-J stack between the two kings is just a reversible shuffle
        unless exposing the source king creates a foundation move.

        Beginner note: an "anchor" is the card a moving stack rests on: the
        card just above it in the source column, or the top card of the
        destination column. Two anchors are equivalent when they share rank
        and colour, because the same stacks fit on both. The move is still
        allowed if either anchor could go to a foundation, since that turns
        the shuffle into real progress.
        """
        if source_card_index <= 0:
            return False

        source_column = tableau[source_index]
        source_anchor = source_column[source_card_index - 1]
        destination_anchor = tableau[destination_index][-1]

        if not self.cards_are_equivalent_anchors(source_anchor, destination_anchor):
            return False

        if self.card_can_move_to_any_foundation_in_piles(source_anchor, foundations):
            return False

        return not self.card_can_move_to_any_foundation_in_piles(destination_anchor, foundations)

    def cards_are_equivalent_anchors(self, first: Card, second: Card) -> bool:
        """Two anchors are equivalent when rank and color match."""
        return first.rank == second.rank and first.color() == second.color()

    def tableau_top_can_move_to_foundation(self, column_index: int) -> bool:
        """Convenience wrapper for checking one real tableau column."""
        return self.tableau_top_can_move_to_foundation_on_board(
            column_index, self.tableau, self.foundations
        )

    def tableau_top_can_move_to_foundation_on_board(
        self,
        column_index: int,
        tableau: list[list[Card]],
        foundations: list[list[Card]],
    ) -> bool:
        """Check whether the top tableau card can move to any foundation."""
        column = tableau[column_index]
        if not column or not column[-1].face_up:
            return False
        return self.card_can_move_to_any_foundation_in_piles(column[-1], foundations)

    def card_can_move_to_any_foundation(self, card: Card) -> bool:
        """Convenience wrapper for the real foundation piles."""
        return self.card_can_move_to_any_foundation_in_piles(card, self.foundations)

    def card_can_move_to_any_foundation_in_piles(
        self, card: Card, foundations: list[list[Card]]
    ) -> bool:
        """Return True if this card fits on at least one foundation pile."""
        return any(
            self.can_move_to_foundation_piles(card, foundation_index, foundations)
            for foundation_index in range(FOUNDATION_COUNT)
        )

    def move_reveals_hidden_on_board(
        self,
        source_index: int,
        source_card_index: int,
        tableau: list[list[Card]],
    ) -> bool:
        """Version of the reveal check that works on a simulated tableau."""
        if source_card_index == 0:
            return False
        return not tableau[source_index][source_card_index - 1].face_up

    def is_unproductive_foundation_return(self, move: HintMove) -> bool:
        """Ignore foundation-to-tableau moves unless they unlock real progress."""
        if move.source_type != "foundation" or move.destination_type != "tableau":
            return False
        return not self.foundation_return_enables_tableau_follow_up(move)

    def is_meaningful_tableau_transfer_on_board(
        self,
        source_index: int,
        source_card_index: int,
        cards: list[Card],
        destination_index: int,
        tableau: list[list[Card]],
        foundations: list[list[Card]],
    ) -> bool:
        """Check whether a simulated tableau transfer would still be useful.

        This bundles the legality check with the same filters that
        `is_meaningful_move` applies to real moves (the empty-column King
        shuffle and the redundant-transfer check), but runs them against the
        supplied simulated `tableau` and `foundations`.
        """
        if source_index == destination_index:
            return False
        if not self.can_move_to_tableau_cards(cards, tableau[destination_index]):
            return False
        if source_card_index == 0 and cards[0].rank == 13 and not tableau[destination_index]:
            return False
        return not self.is_redundant_tableau_transfer_on_board(
            source_index, source_card_index, cards, destination_index, tableau, foundations
        )

    def foundation_return_enables_tableau_follow_up(self, move: HintMove) -> bool:
        """
        Allow a foundation return only if it enables a new useful tableau move.

        This prevents hints like "pull J♥ down from foundation" unless doing so
        immediately creates some concrete new opportunity on the tableau.

        A stock or waste card that fits on the returned card also counts, but
        only when that card cannot simply go up to a foundation right now:
        otherwise the foundation play is the better move and the return is
        just a detour.
        """
        returned_card = move.cards[0]
        # First test: would a stock or waste card that is otherwise stuck
        # have a new home on top of the returned card?
        if any(
            self.can_move_to_tableau_cards([card], [returned_card]) and not self.card_can_move_to_any_foundation(card)
            for card in self.stock + self.waste
        ):
            return True

        # Remember the destination column before the foundation card is added.
        destination_before = list(self.tableau[move.destination_index])

        # Build simulated board states that represent the move after it happens.
        tableau_after = [list(column) for column in self.tableau]
        tableau_after[move.destination_index] = destination_before + list(move.cards)

        foundations_after = [list(pile) for pile in self.foundations]
        foundations_after[move.source_index] = foundations_after[move.source_index][:-1]

        # Second test: look for a tableau run in another column that could
        # follow the returned card onto its new column, and that then makes
        # visible progress. Only the first such follow-up is needed.
        for column_index, column in enumerate(tableau_after):
            if column_index == move.destination_index:
                continue

            for card_index, card in enumerate(column):
                if not card.face_up:
                    continue

                selection = self.selection_from_tableau_cards(tableau_after, column_index, card_index)
                if selection is None:
                    continue

                # We only care about moves that become possible because of the
                # returned foundation card, not moves that were already legal.
                can_move_before = self.can_move_to_tableau_cards(selection.cards, destination_before)
                can_move_after = self.can_move_to_tableau_cards(
                    selection.cards, tableau_after[move.destination_index]
                )
                if can_move_after and not can_move_before and self.is_meaningful_tableau_transfer_on_board(
                    column_index,
                    card_index,
                    selection.cards,
                    move.destination_index,
                    tableau_after,
                    foundations_after,
                ) and self.follow_up_creates_concrete_progress(
                    column_index,
                    card_index,
                    selection.cards,
                    tableau_after,
                    foundations_after,
                ):
                    return True

        return False

    def follow_up_creates_concrete_progress(
        self,
        source_index: int,
        source_card_index: int,
        cards: list[Card],
        tableau: list[list[Card]],
        foundations: list[list[Card]],
    ) -> bool:
        """Check whether a follow-up move creates immediate visible progress.

        Progress means revealing a hidden card, emptying a whole column (which
        a King can then use), or exposing a card that can go to a foundation.
        """
        if self.move_reveals_hidden_on_board(source_index, source_card_index, tableau):
            return True
        if source_card_index == 0:
            # Moving the bottom card of a column empties that column.
            return True

        # If the moved-away source exposes a card that can now go to foundation,
        # that also counts as concrete progress.
        source_after = list(tableau[source_index])
        del source_after[source_card_index:]

        return bool(source_after and self.card_can_move_to_any_foundation_in_piles(source_after[-1], foundations))


class SilentAudio:
    """A stand-in for `SolitaireAudio` that ignores every request.

    The app uses it when pygame is missing or the machine has no audio
    device, and it is also the app's default, so an app built without
    `__init__` (as the tests do) simply plays nothing.

    Beginner note: this is the "null object" pattern. Instead of checking
    "is there any sound?" before every call, the app always has an object
    with the same methods; this one just does nothing.
    """

    def play(self, name: str, pitch_step: int = 0) -> None:
        """Ignore a request to play a sound."""

    def start_music(self) -> None:
        """Ignore a request to start the music."""

    def stop_music(self, fade_ms: int) -> None:
        """Ignore a request to stop the music."""

    def update(self) -> None:
        """Nothing to update."""

    def close(self) -> None:
        """Nothing to shut down."""


class SolitaireAudio:
    """The app's sound: the effects bank and the music loop behind a few small calls.

    Attributes:
        bank: The `audio.SoundBank` built from `SFX_RECIPES`. It is silent by
            itself when the mixer is unavailable.
        music: The `audio.MusicPlayer` looping the lo-fi tune.
    """

    def __init__(self, threaded: bool = True) -> None:
        """Render every effect, and start rendering the music (in a background thread when `threaded`)."""
        self.bank = audio.SoundBank(SFX_RECIPES, SFX_COOLDOWNS)
        self.music = audio.MusicPlayer(music_notes, MUSIC_LOOP_SECONDS, MUSIC_VOLUME, threaded=threaded)

    def play(self, name: str, pitch_step: int = 0) -> None:
        """Play the effect `name` (or its `name@pitch_step` variant)."""
        self.bank.play(name, pitch_step=pitch_step)

    def start_music(self) -> None:
        """Fade the music in as soon as it has rendered (nothing changes if it is already playing)."""
        self.music.start(MUSIC_FADE_IN_MS)

    def stop_music(self, fade_ms: int) -> None:
        """Fade the music out over `fade_ms` milliseconds."""
        self.music.stop(fade_ms)

    def update(self) -> None:
        """Let the music player turn a finished render into sound; call it from the tkinter thread."""
        self.music.update()

    def close(self) -> None:
        """Shut the mixer down so the audio device is released when the window closes."""
        import pygame

        with contextlib.suppress(pygame.error):
            pygame.mixer.quit()


def open_audio() -> SolitaireAudio | SilentAudio:
    """Start pygame's mixer (never its display) and return the app's sound.

    Returns `SilentAudio` when pygame is not installed or the mixer cannot
    start (no audio device), so the game always runs, just silently.

    Beginner note: tkinter owns the window here, so only `pygame.mixer` is
    started; `pygame.init()` would also start pygame's display, which this
    app never uses. pygame is imported here, not at the top of the file, so
    the rules engine and the tests can load this module without it, and the
    environment variable set first stops pygame printing its greeting.
    """
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    try:
        import pygame
    except ImportError:
        return SilentAudio()
    audio.init_mixer()
    try:
        pygame.mixer.init()
    except pygame.error:
        return SilentAudio()
    audio.reserve_channels()
    return SolitaireAudio()


class SolitaireApp:
    """tkinter user interface that draws the board and reacts to clicks.

    The app owns everything the rules do not care about: the window and its
    widgets, which card the player has picked up, hint highlights, card
    animation, the auto-solve loop, the game clock, and the Undo history.
    Every rule question is forwarded to `self.game` (a `KlondikeGame`).

    Key attributes:
    - `game`: the rules model.
    - `selection`: the card or run the player has picked up, or None.
    - `hint_move`: the move the Hint button last suggested, or None.
    - `animation`: the cards currently gliding to a new pile, or None.
      While it is set, clicks, Undo and Hint are refused.
    - `auto_solving` / `auto_solve_seen_states`: the automatic finish that
      starts once every tableau card is face up, and its loop detector.
    - `history`: Undo snapshots, newest last, capped at UNDO_HISTORY_LIMIT.
    - `started_at` / `elapsed_seconds`: the game clock.
    - `canvas`: the tk.Canvas that the whole board is painted on.
    - `audio`: the sound effects (`SolitaireAudio`), or `SilentAudio` when
      there is no sound. The class-level default is silent, so an app built
      without `__init__` still runs every handler.

    Beginner note: tkinter is event driven. After `root.mainloop()` starts,
    the program only runs code when something happens: a click calls a
    bound handler, and `root.after(ms, func)` asks tkinter to call `func`
    later. Animation, the clock and auto-solve are all chains of `after`
    calls, each step scheduling the next, because there is no game loop.
    The board itself is redrawn from scratch from the model after every
    change (`redraw`), so the picture can never drift from the real state.
    """

    audio: SolitaireAudio | SilentAudio = SilentAudio()

    def __init__(self, root: tk.Tk) -> None:
        """Create the window, game model, and all UI state.

        The order matters: the model must exist before `build_ui` and
        `redraw` read from it, and the first `check_for_loss` runs last,
        after the board is visible, because a hopeless deal ends the game
        and opens a message box straight away.
        """
        self.root = root
        self.root.title("Klondike Solitaire")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(False, False)
        self.root.configure(bg=BACKGROUND_COLOR)

        # Save data must live in a stable per-user folder. A PyInstaller
        # --onefile build unpacks into a temporary folder that Windows deletes
        # when the .exe closes, so a save written next to __file__ is lost every
        # session. The icon, by contrast, is a bundled read-only resource.
        high_score_path = os.path.join(_user_save_dir(), "solitaire_high_score.json")
        icon_path = _resource_path("solitaire_icon.ico")

        # Load the custom window icon when it is available.
        if os.path.exists(icon_path):
            with contextlib.suppress(tk.TclError):
                self.root.iconbitmap(icon_path)

        # Create the game logic object.
        self.game = KlondikeGame(high_score_path)

        # Sound uses pygame's mixer only; without it the game runs silently.
        # Closing the window shuts the mixer down cleanly first.
        self.audio = open_audio()
        self.audio.start_music()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        # Selection/hint/animation state belongs to the UI layer.
        self.selection: Selection | None = None
        self.hint_move: HintMove | None = None
        self.animation: AnimationState | None = None
        self.auto_solving = False
        self.auto_solve_seen_states: set = set()
        self.history: list[dict] = []

        # tkinter StringVar objects let labels update automatically.
        self.score_var = tk.StringVar()
        self.high_score_var = tk.StringVar()
        self.time_var = tk.StringVar()
        self.stats_var = tk.StringVar()
        self.status_var = tk.StringVar(
            value="Click a face-up card to select it, then click a destination pile."
        )

        self.started_at = time.time()
        self.elapsed_seconds = 0

        # Build widgets, connect shortcuts, and paint the first board.
        self.build_ui()
        self.root.bind("<Control-z>", self.undo_last_action)
        self.root.bind("<Control-Z>", self.undo_last_action)
        # Ctrl+N starts a new game and Ctrl+H asks for a hint. The lambdas
        # absorb the key-event object, which these methods do not expect.
        self.root.bind("<Control-n>", lambda event: self.start_new_game())
        self.root.bind("<Control-N>", lambda event: self.start_new_game())
        self.root.bind("<Control-h>", lambda event: self.show_hint())
        self.root.bind("<Control-H>", lambda event: self.show_hint())
        self.refresh_header_labels()
        self.redraw()
        self.audio.play("deal")
        self.schedule_clock_update()
        self.schedule_audio_update()
        self.check_for_loss()

    def close(self) -> None:
        """Release the audio device, then close the window and end the app."""
        self.audio.close()
        self.root.destroy()

    def build_ui(self) -> None:
        """Create the labels, buttons, status text, and drawing canvas.

        The window is built from top to bottom: a header row (score, high
        score, clock and statistics on the left; Undo, Hint, New Game and
        Help on the right), then a one-line status bar, then the canvas
        that fills the rest. Single and double left-clicks on the canvas are
        bound to `on_canvas_click` and `on_canvas_double_click`.

        Beginner note: `pack` is one of tkinter's layout managers. Each
        `pack(side=...)` call pushes a widget against one side of the space
        that is still free, in the order the calls are made.
        """
        top_frame = tk.Frame(self.root, bg=BACKGROUND_COLOR, padx=12, pady=10)
        top_frame.pack(fill="x")

        # Pack the button group FIRST. tkinter's packer hands out space in
        # packing order, so packing the buttons before the labels guarantees
        # they keep their full width; if the long statistics labels came
        # first they could squeeze the last button ("Help") off the window.
        button_frame = tk.Frame(top_frame, bg=BACKGROUND_COLOR)
        button_frame.pack(side="right")

        # `Any` values let the same dict splat into every tk.Label call below
        # without fighting tkinter's very specific per-option stub types. The
        # labels share the buttons' font so the whole header row fits.
        label_style: dict[str, Any] = {
            "bg": BACKGROUND_COLOR,
            "fg": "white",
            "font": HEADER_FONT,
        }

        label_gap = (0, HEADER_LABEL_GAP)
        tk.Label(top_frame, textvariable=self.score_var, **label_style).pack(side="left", padx=label_gap)
        tk.Label(top_frame, textvariable=self.high_score_var, **label_style).pack(side="left", padx=label_gap)
        tk.Label(top_frame, textvariable=self.time_var, **label_style).pack(side="left", padx=label_gap)
        tk.Label(top_frame, textvariable=self.stats_var, **label_style).pack(side="left")

        tk.Button(
            button_frame,
            text="Undo",
            command=self.undo_last_action,
            font=HEADER_FONT,
            padx=12,
            pady=4,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            button_frame,
            text="Hint",
            command=self.show_hint,
            font=HEADER_FONT,
            padx=12,
            pady=4,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            button_frame,
            text="New Game",
            command=self.start_new_game,
            font=HEADER_FONT,
            padx=12,
            pady=4,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            button_frame,
            text="Help",
            command=self.show_help,
            font=HEADER_FONT,
            padx=12,
            pady=4,
        ).pack(side="left")

        tk.Label(
            self.root,
            textvariable=self.status_var,
            bg=BACKGROUND_COLOR,
            fg="white",
            anchor="w",
            padx=14,
            font=("Arial", 10),
        ).pack(fill="x")

        self.canvas = tk.Canvas(
            self.root,
            width=WINDOW_WIDTH,
            height=CANVAS_HEIGHT,
            bg=BACKGROUND_COLOR,
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Double-Button-1>", self.on_canvas_double_click)

    def show_help(self) -> None:
        """Show a dialog explaining the objective, controls, and scoring.

        The text is one long string built from adjacent string literals,
        which Python joins together automatically. The `parent` argument
        ties the dialog to the game window so it opens over it.
        """
        self.audio.play("click")
        messagebox.showinfo(
            "How to Play",
            "Objective\n"
            "Move all 52 cards onto the four foundation piles. Each foundation "
            "builds up in one suit from Ace to King.\n\n"
            "Moving cards\n"
            "Click a face-up card to select it, then click where it should go. "
            "Tableau columns build downward in alternating colors. Only a King, "
            "or a run led by a King, can move onto an empty column.\n\n"
            "Stock and waste\n"
            "Click the stock pile to draw a card onto the waste pile. When the "
            "stock is empty, click it again to recycle the waste back into it.\n\n"
            "Controls\n"
            "Undo button or Ctrl+Z  -  take back the last move\n"
            "Hint button  -  highlight a useful move\n"
            "New Game button  -  deal a fresh game\n\n"
            "Scoring\n"
            "+10 for every card sent to a foundation, +5 for revealing a "
            "face-down card, plus a time bonus and a 100-point win bonus for "
            "finishing the game. Taking a card back off a foundation costs "
            "the 10 points it earned.",
            parent=self.root,
        )

    def schedule_clock_update(self) -> None:
        """Refresh the visible timer a few times per second.

        The clock keeps rescheduling itself for as long as the window is
        open. Once a game is won or lost, `elapsed_seconds` simply stops
        changing, so the final time stays on screen.
        """
        if not self.game.won and not self.game.lost:
            self.elapsed_seconds = int(time.time() - self.started_at)
        self.time_var.set(f"Time: {self.format_time(self.elapsed_seconds)}")

        # Ask tkinter to call this method again later.
        self.root.after(250, self.schedule_clock_update)

    def schedule_audio_update(self) -> None:
        """Give the music player a moment on the main thread, again every AUDIO_TICK_MS.

        Beginner note: the music renders in a background thread, but pygame
        sounds may only be created on the main thread. This small `after`
        loop is where the finished samples become sound and start playing.
        """
        self.audio.update()
        self.root.after(AUDIO_TICK_MS, self.schedule_audio_update)

    def start_new_game(self) -> None:
        """Deal a fresh game and clear all UI-only state."""
        # Guard an in-progress game: a non-empty history with no win/loss yet
        # means real moves would be discarded. Covers the button and Ctrl+N.
        # `and` stops at the first False, so the question is only asked when
        # there is real progress to lose; answering "No" cancels the deal.
        if self.history and not self.game.won and not self.game.lost and not messagebox.askyesno(
                "New Game",
                "Start a new game? Your current progress will be lost."):
            return
        self.game.new_game()
        self.selection = None
        self.hint_move = None
        self.animation = None
        self.auto_solving = False
        self.auto_solve_seen_states = set()
        self.history = []
        self.started_at = time.time()
        self.elapsed_seconds = 0
        self.status_var.set("Started a new game.")
        self.refresh_header_labels()
        self.redraw()
        self.audio.play("deal")
        self.audio.start_music()
        self.check_for_loss()

    def refresh_header_labels(self) -> None:
        """Copy the latest score/statistics/timer values into the top labels."""
        self.score_var.set(f"Score: {self.game.score}")
        self.high_score_var.set(f"High Score: {self.game.high_score}")
        self.time_var.set(f"Time: {self.format_time(self.elapsed_seconds)}")
        self.stats_var.set(f"Stats: W {self.game.wins} / L {self.game.losses}")

    def capture_history_state(self) -> dict:
        """Create one Undo snapshot before a state-changing action."""
        return {"game": self.game.snapshot()}

    def remember_history_state(self, history_state: dict) -> None:
        """Push a snapshot onto the Undo stack and trim old entries."""
        self.history.append(history_state)
        if len(self.history) > UNDO_HISTORY_LIMIT:
            self.history = self.history[-UNDO_HISTORY_LIMIT:]

    def undo_last_action(self, event: tk.Event | None = None) -> None:
        """Restore the most recent saved snapshot.

        Called by the Undo button (no argument) and by Ctrl+Z (with the key
        event, which is ignored). Undo is refused while cards are animating
        and after a win. Otherwise the newest history entry is popped and
        restored, all UI-only state (selection, hint, auto-solve) is reset,
        and the clock resumes from the time already shown. Undoing out of a
        lost game is allowed; the restored snapshot also brings back the
        loss count from before the loss was recorded.
        """
        if self.animation is not None:
            self.status_var.set("Please wait for the card animation to finish.")
            return

        if self.game.won:
            # A win is final: its bonus and win count are already saved, so
            # Undo is refused. A loss, by contrast, can be undone below.
            self.status_var.set("You already won. Click New Game to play again.")
            return

        if not self.history:
            self.status_var.set("There is nothing to undo yet.")
            self.audio.play("invalid")
            return

        history_state = self.history.pop()
        was_lost = self.game.lost
        self.auto_solving = False
        self.auto_solve_seen_states = set()
        self.selection = None
        self.hint_move = None
        self.animation = None
        self.game.restore_snapshot(history_state["game"])
        if not self.game.won and not self.game.lost:
            # Restart the live timer from the already elapsed number of seconds.
            self.started_at = time.time() - self.elapsed_seconds
        self.refresh_header_labels()
        self.status_var.set("Undid the previous move.")
        self.audio.play("undo")
        if was_lost and not self.game.lost:
            # The game is open again, so the music faded at the loss returns.
            self.audio.start_music()
        self.redraw()
        if not self.game.won and not self.game.lost:
            self.check_for_loss()

    def on_canvas_click(self, event: tk.Event) -> None:
        """Main mouse handler: decide which pile the player clicked.

        Clicks are refused (with a status message) while cards animate,
        while auto-solve runs, and after the game has ended. Otherwise the
        click point is tested against the piles in this order: stock, waste,
        the four foundations, then the tableau. The first pile hit gets the
        click. A click on bare felt just drops the current selection.

        Beginner note: Solitaire here is "click to pick up, click to put
        down". The first click on a card stores a `Selection`; the next
        click on a pile tries to move that selection there.
        """
        if self.animation is not None:
            self.status_var.set("Please wait for the card animation to finish.")
            return

        if self.auto_solving:
            self.status_var.set("Auto-solve is running.")
            return

        if self.game.won:
            self.status_var.set("You already won. Click New Game to play again.")
            return

        if self.game.lost:
            self.status_var.set("No more productive moves remain. Click New Game to try again.")
            return

        x, y = event.x, event.y

        if self.point_in_rect(x, y, self.stock_rect()):
            # Clicking the stock draws a card or recycles the waste pile.
            self.selection = None
            self.hint_move = None
            history_state = self.capture_history_state()
            action = self.game.draw_from_stock()
            if action in ("draw", "reset"):
                # Only keep an undo snapshot if the click actually changed something.
                self.remember_history_state(history_state)
            if action == "draw":
                self.status_var.set("Drew a card from the stock.")
            elif action == "reset":
                self.status_var.set("Recycled the waste pile back into the stock.")
            else:
                self.status_var.set("There are no cards left to draw.")
            self.audio.play(STOCK_SOUNDS[action])
            self.refresh_header_labels()
            self.redraw()
            if self.should_auto_solve():
                self.begin_auto_solve()
            else:
                self.check_for_loss()
            return

        if self.point_in_rect(x, y, self.waste_rect()) and self.game.waste:
            self.handle_waste_click()
            return

        # Check each foundation rectangle.
        for foundation_index in range(FOUNDATION_COUNT):
            if self.point_in_rect(x, y, self.foundation_rect(foundation_index)):
                self.handle_foundation_click(foundation_index)
                return

        # If it was not a top-row pile, see whether it hit the tableau.
        column_index, card_index = self.find_tableau_hit(x, y)
        if column_index is not None:
            self.handle_tableau_click(column_index, card_index)
            return

        if self.selection is not None:
            self.selection = None
            self.status_var.set("Selection cleared.")
            self.redraw()

    def on_canvas_double_click(self, event: tk.Event) -> None:
        """Double-click a card to send it straight to a foundation if it fits.

        This is a convenience shortcut: instead of selecting the card and then
        clicking the foundation pile, one double-click does both at once.

        Beginner note: tkinter reports the second press of a fast double-click
        ONLY as a double-click, never as a normal click. So every double-click
        that does not send a card home is passed on to `on_canvas_click`;
        otherwise that second click would silently vanish (a quick second
        stock click would not draw, a busy board would not explain itself).
        """
        if self.animation is not None or self.auto_solving or self.game.won or self.game.lost:
            # The normal click handler explains why nothing can happen now.
            self.on_canvas_click(event)
            return

        selection = self._selection_under_point(event.x, event.y)
        # Only a single face-up card can ever move onto a foundation.
        if selection is None or len(selection.cards) != 1:
            self.on_canvas_click(event)
            return

        card = selection.cards[0]
        for foundation_index in range(FOUNDATION_COUNT):
            if self.game.can_move_to_foundation(card, foundation_index):
                suit_name = FOUNDATION_SUITS[foundation_index].capitalize()
                self.selection = None
                self.hint_move = None
                self.animate_move(
                    selection=selection,
                    destination_type="foundation",
                    destination_index=foundation_index,
                    completion_message=f"Moved {card.label()} to the {suit_name} foundation.",
                )
                return

        # No foundation fits, so treat the second press as an ordinary click.
        self.on_canvas_click(event)

    def _selection_under_point(self, x: int, y: int) -> Selection | None:
        """Return a Selection for the card under a click, or None if there is none.

        Used by the double-click shortcut to find which card was clicked. Only
        the waste pile and the tableau columns are checked, because those are
        the only places a card is ever picked up from to send to a foundation.
        """
        if self.point_in_rect(x, y, self.waste_rect()) and self.game.waste:
            return self.game.selection_from_waste()
        column_index, card_index = self.find_tableau_hit(x, y)
        if column_index is not None and card_index is not None:
            return self.game.selection_from_tableau(column_index, card_index)
        return None

    def handle_waste_click(self) -> None:
        """Select or deselect the top waste card."""
        waste_selection = self.game.selection_from_waste()
        if waste_selection is None:
            return
        if self.is_same_selection(waste_selection):
            self.selection = None
            self.status_var.set("Selection cleared.")
        else:
            self.selection = waste_selection
            self.status_var.set(f"Selected {waste_selection.cards[0].label()} from the waste.")
            self.audio.play("select")
        self.redraw()

    def handle_foundation_click(self, foundation_index: int) -> None:
        """Either select a foundation card or place the current selection there.

        With a card already picked up, a legal placement animates it onto
        this foundation; clicking the foundation the card came from cancels
        the selection; any other click explains that the move does not fit.
        With nothing picked up, the top foundation card is selected so it
        can be moved back down to the tableau.
        """
        if self.selection is not None:
            current_selection = self.selection
            moved_card_label = self.describe_cards(current_selection.cards)
            suit_name = FOUNDATION_SUITS[foundation_index].capitalize()

            if self.can_place_selection_on_foundation(current_selection, foundation_index):
                # Clear selection immediately so the UI does not show stale highlights.
                self.selection = None
                self.hint_move = None
                self.animate_move(
                    selection=current_selection,
                    destination_type="foundation",
                    destination_index=foundation_index,
                    completion_message=f"Moved {moved_card_label} to the {suit_name} foundation.",
                )
                return

            same_foundation = (
                current_selection.source_type == "foundation"
                and current_selection.pile_index == foundation_index
            )
            if same_foundation:
                self.selection = None
                self.status_var.set("Selection cleared.")
            else:
                self.status_var.set("That move does not fit the foundation rules.")
                self.audio.play("invalid")
            self.redraw()
            return

        foundation_selection = self.game.selection_from_foundation(foundation_index)
        if foundation_selection is not None:
            self.selection = foundation_selection
            self.status_var.set(
                f"Selected {foundation_selection.cards[0].label()} from the foundation."
            )
            self.audio.play("select")
            self.redraw()

    def handle_tableau_click(self, column_index: int, card_index: int | None) -> None:
        """Handle selection, deselection, and placement inside the tableau.

        `card_index` is None when the click hit the column but no card (an
        empty column, or the space below a column's last card). With a
        selection held, the click first tries to place it on this column;
        failing that, clicking the same card again deselects it, and
        clicking another valid card switches the selection to that card.
        With nothing held, a click on a face-up card that leads a valid run
        selects the card and everything on top of it.
        """
        if self.selection is not None:
            current_selection = self.selection
            moved_label = self.describe_cards(current_selection.cards)
            if self.can_place_selection_on_tableau(current_selection, column_index):
                self.selection = None
                self.hint_move = None
                self.animate_move(
                    selection=current_selection,
                    destination_type="tableau",
                    destination_index=column_index,
                    completion_message=f"Moved {moved_label} to tableau column {column_index + 1}.",
                )
                return

            if (
                current_selection.source_type == "tableau"
                and current_selection.pile_index == column_index
                and current_selection.card_index == card_index
            ):
                self.selection = None
                self.status_var.set("Selection cleared.")
                self.redraw()
                return

            new_selection = None
            if card_index is not None:
                new_selection = self.game.selection_from_tableau(column_index, card_index)

            if new_selection is not None:
                self.selection = new_selection
                self.status_var.set(
                    f"Selected {self.describe_cards(new_selection.cards)} from tableau column {column_index + 1}."
                )
                self.audio.play("select")
            else:
                self.status_var.set("That move does not fit the tableau rules.")
                self.audio.play("invalid")
            self.redraw()
            return

        if card_index is None:
            # Clicking empty space in a tableau column does nothing if nothing is selected.
            return

        new_selection = self.game.selection_from_tableau(column_index, card_index)
        if new_selection is not None:
            self.selection = new_selection
            self.status_var.set(
                f"Selected {self.describe_cards(new_selection.cards)} from tableau column {column_index + 1}."
            )
            self.audio.play("select")
        else:
            self.status_var.set("Only face-up cards in a valid stack can be selected.")
            self.audio.play("invalid")
        self.redraw()

    def show_hint(self) -> None:
        """Ask the model for the best current move and highlight it.

        The suggested source cards become the current selection (yellow) and
        the destination pile gets the orange hint outline, so the player can
        carry the hint out with a single click on the destination. If the
        engine finds no move at all, the game is over and is recorded as a
        loss. For a "future_waste" hint nothing is selected yet, because the
        card is still in the stock; the status text says how many stock
        clicks it needs.
        """
        if self.animation is not None:
            self.status_var.set("Please wait for the current animation to finish.")
            return

        if self.auto_solving:
            self.status_var.set("Auto-solve is already running.")
            return

        if self.game.won:
            self.status_var.set("You already won. Click New Game to play again.")
            return

        if self.game.lost:
            self.status_var.set("This game is already over. Click New Game to try again.")
            return

        best_move = self.game.find_best_move()
        if best_move is None:
            self.end_game_as_loss()
            return

        self.hint_move = best_move
        self.selection = self.game.selection_from_hint(best_move)
        self.status_var.set(best_move.description)
        self.audio.play("hint")
        self.redraw()

    def can_place_selection_on_tableau(self, selection: Selection, column_index: int) -> bool:
        """UI wrapper around the model's tableau move rule."""
        if selection.source_type == "tableau" and selection.pile_index == column_index:
            return False
        return self.game.can_move_to_tableau(selection.cards, column_index)

    def can_place_selection_on_foundation(
        self, selection: Selection, foundation_index: int
    ) -> bool:
        """UI wrapper around the model's foundation move rule."""
        if len(selection.cards) != 1:
            return False
        if selection.source_type == "foundation" and selection.pile_index == foundation_index:
            return False
        return self.game.can_move_to_foundation(selection.cards[0], foundation_index)

    def animate_move(
        self,
        selection: Selection,
        destination_type: str,
        destination_index: int,
        completion_message: str,
    ) -> None:
        """Move cards in the model, then animate them on screen.

        The order of the first three lines matters: the start and end pixel
        positions and the Undo snapshot are all taken from the board BEFORE
        the move, because afterwards the cards are already somewhere else.
        The model is then updated at once (the animation is only a picture
        of a move that has already happened), and the first frame is
        scheduled with `root.after`. An illegal move changes nothing and
        leaves no Undo entry.
        """
        start_positions = self.selection_positions(selection)
        end_positions = self.destination_positions(selection.cards, destination_type, destination_index)
        history_state = self.capture_history_state()
        # Moving the last card off a face-down tableau card turns it over.
        # The board shows that at once, so its flip sound plays at once too.
        reveals_hidden_card = (
            selection.source_type == "tableau"
            and selection.card_index > 0
            and not self.game.tableau[selection.pile_index][selection.card_index - 1].face_up
        )

        # Update the model immediately, then draw the animation over the new board.
        if destination_type == "foundation":
            moved = self.game.move_selection_to_foundation(selection, destination_index)
        else:
            moved = self.game.move_selection_to_tableau(selection, destination_index)

        if not moved:
            self.status_var.set("That move is not legal.")
            self.audio.play("invalid")
            self.redraw()
            return

        if reveals_hidden_card:
            self.audio.play("flip")
        self.remember_history_state(history_state)
        self.animation = AnimationState(
            cards=list(selection.cards),
            start_positions=start_positions,
            end_positions=end_positions,
            destination_type=destination_type,
            destination_index=destination_index,
            completion_message=completion_message,
        )
        self.refresh_header_labels()
        self.status_var.set("Moving cards...")
        self.redraw()
        self.root.after(ANIMATION_DELAY_MS, self.advance_animation)

    def advance_animation(self) -> None:
        """Advance one frame of the in-progress card animation.

        Each call bumps the frame counter and redraws. After the last frame
        the animation is cleared and `finish_turn` runs the end-of-move
        checks; until then the method schedules itself again.
        """
        if self.animation is None:
            return

        self.animation.frame += 1
        if self.animation.frame >= self.animation.steps:
            self.play_landing_sound(self.animation)
            completion_message = self.animation.completion_message
            self.animation = None
            self.status_var.set(completion_message)
            self.refresh_header_labels()
            self.redraw()
            self.finish_turn()
            return

        self.redraw()
        self.root.after(ANIMATION_DELAY_MS, self.advance_animation)

    def play_landing_sound(self, animation: AnimationState) -> None:
        """Play the sound of cards arriving on their pile.

        A tableau move thuds onto the felt. A foundation card chimes at the
        pitch of its rank (Ace lowest, King highest), so a suit filling up
        sounds like a rising scale; auto-solve uses a quicker, lighter chime
        because it sends cards home in a fast run.
        """
        if animation.destination_type != "foundation":
            self.audio.play("place")
            return
        name = "auto_step" if self.auto_solving else "foundation"
        self.audio.play(name, pitch_step=animation.cards[-1].rank)

    def finish_turn(self) -> None:
        """Run end-of-turn checks after a move or animation finishes.

        In priority order: a full set of foundations wins the game; a
        running auto-solve takes its next step; a board with every tableau
        card face up starts auto-solve; otherwise the loss check runs.
        """
        if self.game.has_won() and not self.game.won:
            self.end_game_as_win()
            return
        if self.auto_solving:
            self.root.after(120, self.advance_auto_solve)
            return
        if self.should_auto_solve():
            self.begin_auto_solve()
            return
        self.check_for_loss()

    def should_auto_solve(self) -> bool:
        """Auto-solve starts only after every tableau card is face up."""
        return (
            not self.auto_solving
            and not self.game.won
            and not self.game.lost
            and self.game.all_tableau_cards_face_up()
        )

    def begin_auto_solve(self) -> None:
        """Switch the UI into auto-solve mode."""
        if self.auto_solving or self.game.won or self.game.lost:
            return
        self.auto_solving = True
        self.auto_solve_seen_states = set()
        self.selection = None
        self.hint_move = None
        self.status_var.set("All tableau cards are face up. Auto-solving...")
        self.redraw()
        self.root.after(140, self.advance_auto_solve)

    def advance_auto_solve(self) -> None:
        """Perform one auto-solve step, then schedule the next one.

        Each step does exactly one thing. If a card can go straight to a
        foundation, it is animated there, and `finish_turn` schedules the
        next step once it lands. Otherwise the step clicks the stock and
        schedules itself. A board summary is remembered before each stock
        click; meeting the same summary again means a whole stock cycle
        brought no foundation move, so auto-solve stops instead of cycling
        forever. When the stock and waste are both empty and no foundation
        move exists, auto-solve also stops (or declares the win if the
        foundations are already full).

        Beginner note: once every tableau card is face up, each column is a
        neat descending run whose lowest card is on top, and every stock
        card comes round again as the stock is cycled. Sending cards home
        one at a time is then enough to finish, which is why this simple
        loop can complete the game for the player.
        """
        if not self.auto_solving or self.game.won or self.game.lost:
            return
        if self.animation is not None:
            return

        next_move = self.game.next_auto_foundation_move()
        if next_move is not None:
            # If a direct foundation move exists, animate that before anything else.
            # Real progress was made, so the stock-cycle memory starts afresh.
            self.auto_solve_seen_states.clear()
            selection, foundation_index = next_move
            suit_name = FOUNDATION_SUITS[foundation_index].capitalize()
            self.animate_move(
                selection=selection,
                destination_type="foundation",
                destination_index=foundation_index,
                completion_message=(
                    f"Auto-solve moved {selection.cards[0].label()} to the {suit_name} foundation."
                ),
            )
            return

        state_key = self.auto_solve_state_key()
        if state_key in self.auto_solve_seen_states:
            # Repeating the same stock/waste cycle means auto-solve is stuck.
            self.auto_solving = False
            self.status_var.set("Auto-solve stopped because it reached a repeated stock cycle.")
            self.check_for_loss()
            return

        self.auto_solve_seen_states.add(state_key)
        history_state = self.capture_history_state()
        stock_action = self.game.draw_from_stock()
        if stock_action in ("draw", "reset"):
            # Auto-solve stock clicks should also be undoable.
            self.remember_history_state(history_state)
            if stock_action == "draw":
                self.status_var.set("Auto-solve is drawing from the stock.")
            else:
                self.status_var.set("Auto-solve is recycling the stock.")
            self.audio.play(STOCK_SOUNDS[stock_action])
            self.refresh_header_labels()
            self.redraw()
            self.root.after(140, self.advance_auto_solve)
            return

        self.auto_solving = False
        if self.game.has_won():
            self.end_game_as_win()
            return
        self.status_var.set("Auto-solve stopped because no direct foundation move is available.")
        self.check_for_loss()

    def auto_solve_state_key(self) -> tuple:
        """Build a hashable summary of the board for loop detection.

        Auto-solve cycles the stock looking for cards it can send to a
        foundation. If a full stock cycle finishes without making progress,
        every pile is in exactly the situation it was in last time -- which
        means the next cycle will do the same nothing and we should give up.
        Bundling stock, waste, foundations and tableau into one tuple gives a
        single value we can drop in a `set` and check against on each step.
        """
        return (
            tuple((card.suit, card.rank) for card in self.game.stock),
            tuple((card.suit, card.rank) for card in self.game.waste),
            tuple(tuple((card.suit, card.rank) for card in pile) for pile in self.game.foundations),
            tuple(tuple((card.suit, card.rank) for card in column) for column in self.game.tableau),
        )

    def check_for_loss(self) -> None:
        """End the game if no meaningful move remains.

        This reuses the hint engine: if `find_best_move` cannot suggest
        anything, not even a move that needs stock clicks, the deal is lost.
        """
        if self.game.won or self.game.lost:
            return
        if self.game.find_best_move() is None:
            self.end_game_as_loss()

    def end_game_as_win(self) -> None:
        """Freeze the game, apply bonuses, update stats, and celebrate the win.

        Setting `game.won` first is what freezes the board: every click
        handler, Undo and the clock check that flag. The win bonus and the
        time bonus are added through `add_score`, so they can raise and save
        the high score, and the win is saved to the statistics before the
        confetti starts. The congratulations dialog is passed to the
        celebration as a callback and only appears once the confetti ends.
        """
        self.game.won = True
        self.auto_solving = False
        self.auto_solve_seen_states = set()

        # The faster the player finishes, the bigger the bonus.
        time_bonus = self.calculate_time_bonus()
        self.game.add_score(self.game.WIN_BONUS)
        self.game.add_score(time_bonus)
        self.game.record_win()
        self.selection = None
        self.hint_move = None
        self.refresh_header_labels()
        self.status_var.set(
            f"You win! Time: {self.format_time(self.elapsed_seconds)}. Time bonus: {time_bonus}."
        )
        self.redraw()
        self.audio.stop_music(MUSIC_GAME_OVER_FADE_MS)
        self.audio.play("win")

        # Capture the summary values now, then play a short confetti
        # celebration; the win dialog appears once the animation finishes.
        final_score = self.game.score
        elapsed = self.format_time(self.elapsed_seconds)
        self._play_win_celebration(
            lambda: messagebox.showinfo(
                "You Win!",
                (
                    f"Congratulations! You won with a score of {final_score}.\n"
                    f"Time: {elapsed}\n"
                    f"Time bonus: {time_bonus}"
                ),
            )
        )

    def _play_win_celebration(self, on_finished) -> None:
        """Rain confetti and show a banner, then run `on_finished` (the dialog).

        tkinter has no game loop, so the animation is driven by `root.after`:
        each tick nudges every confetti piece downward and schedules the next
        tick, until the celebration has run for its fixed number of frames.
        """
        confetti_colors = ["#FFD24D", "#FF6B6B", "#4DD0E1", "#A5D6A7", "#CE93D8", "#FFFFFF"]
        # Confetti is purely cosmetic, so it uses the module-level `random`
        # rather than the game's seeded `rng`; deals stay reproducible.
        # Pieces start above the canvas (negative y) so they fall into view.
        pieces = []
        for _ in range(60):
            piece_x = random.randint(0, WINDOW_WIDTH)
            piece_y = random.randint(-CANVAS_HEIGHT, 0)
            size = random.randint(6, 13)
            item = self.canvas.create_rectangle(
                piece_x,
                piece_y,
                piece_x + size,
                piece_y + size,
                fill=random.choice(confetti_colors),
                outline="",
                tags="celebration",
            )
            # Each piece drifts sideways slightly while falling at its own speed.
            pieces.append({
                "item": item,
                "vx": random.uniform(-2.0, 2.0),
                "vy": random.uniform(6.0, 13.0),
            })

        # A bold banner across the upper third of the board, on a dark rounded
        # plate with a yellow rim so it stays readable over cards and confetti.
        banner_x = WINDOW_WIDTH / 2
        banner_y = CANVAS_HEIGHT / 3
        self.rounded_rect(
            banner_x - WIN_PLATE_WIDTH / 2,
            banner_y - WIN_PLATE_HEIGHT / 2,
            banner_x + WIN_PLATE_WIDTH / 2,
            banner_y + WIN_PLATE_HEIGHT / 2,
            WIN_PLATE_RADIUS,
            fill=WIN_PLATE_COLOR,
            outline=HIGHLIGHT_COLOR,
            width=WIN_PLATE_RIM_WIDTH,
            tags="celebration",
        )
        self.canvas.create_text(
            banner_x,
            banner_y,
            text="YOU WIN!",
            fill="#FFD24D",
            font=("Arial", 56, "bold"),
            tags="celebration",
        )

        # A one-item list so the nested `step` function can change the counter.
        # 96 frames at ANIMATION_DELAY_MS (16 ms) each is roughly 1.5 seconds.
        frames_left = [96]

        def step() -> None:
            """Move every confetti piece one frame, or finish the celebration."""
            if not self.game.won:
                # New Game was started mid-celebration: stop quietly so no
                # stale "You Win!" dialog pops up over the fresh deal.
                return
            for piece in pieces:
                self.canvas.move(piece["item"], piece["vx"], piece["vy"])
            frames_left[0] -= 1
            if frames_left[0] > 0:
                self.root.after(ANIMATION_DELAY_MS, step)
            else:
                # Clear the celebration art, then hand control to the dialog.
                self.canvas.delete("celebration")
                on_finished()

        step()

    def end_game_as_loss(self) -> None:
        """Freeze the game, record the loss, and show the final result.

        Setting `game.lost` blocks further clicks and stops the clock. The
        board is redrawn before the dialog opens because `showinfo` waits
        until the player closes it. Undo still works after a loss.
        """
        self.game.lost = True
        self.auto_solving = False
        self.auto_solve_seen_states = set()
        self.game.record_loss()
        self.selection = None
        self.hint_move = None
        self.refresh_header_labels()
        self.redraw()
        self.status_var.set("No more productive moves remain. You lost this game.")
        self.audio.stop_music(MUSIC_GAME_OVER_FADE_MS)
        self.audio.play("lose")
        messagebox.showinfo(
            "Game Over",
            (
                "No more productive moves remain.\n"
                f"Final score: {self.game.score}\n"
                f"Time played: {self.format_time(self.elapsed_seconds)}"
            ),
        )

    def calculate_time_bonus(self) -> int:
        """Convert elapsed time into a simple decreasing bonus."""
        return max(0, self.game.TIME_BONUS_CAP - self.elapsed_seconds)

    def redraw(self) -> None:
        """Repaint the entire canvas from scratch.

        Beginner note: a tkinter Canvas remembers every shape drawn on it as
        a separate item, and later items are painted on top of earlier ones.
        Deleting "all" and drawing everything again, back to front (felt,
        labels, piles, then any moving cards), is simpler and less bug-prone
        than updating individual items, and this board is small enough for
        a full repaint to be quick.
        """
        self.canvas.delete("all")
        self.draw_table_surface()
        self.draw_top_labels()
        self.draw_stock()
        self.draw_waste()
        self.draw_foundations()
        self.draw_tableau()
        if self.animation is not None:
            self.draw_animation()

    def draw_table_surface(self) -> None:
        """Paint the green table background and a few simple accents.

        The felt ovals are painted first so the top band and its divider
        line are drawn over them and stay one clean, even colour.
        """
        self.canvas.create_rectangle(
            0,
            0,
            WINDOW_WIDTH,
            CANVAS_HEIGHT,
            fill=BACKGROUND_COLOR,
            outline="",
        )
        self.canvas.create_oval(
            -120,
            220,
            270,
            600,
            fill=TABLE_ACCENT_DARK,
            outline="",
        )
        self.canvas.create_oval(
            500,
            120,
            940,
            520,
            fill=TABLE_ACCENT_LIGHT,
            outline="",
        )
        self.canvas.create_rectangle(
            0,
            0,
            WINDOW_WIDTH,
            TOP_BAND_HEIGHT,
            fill=TABLE_TOP_COLOR,
            outline="",
        )
        self.canvas.create_rectangle(
            0,
            TOP_BAND_HEIGHT,
            WINDOW_WIDTH,
            TOP_BAND_HEIGHT + DIVIDER_HEIGHT,
            fill="#0A6246",
            outline="",
        )

    def draw_top_labels(self) -> None:
        """Draw the text labels above stock, waste, and foundations.

        Each label is centred horizontally over its pile and sits
        PILE_LABEL_OFFSET pixels above the top row of cards. The foundation
        labels show the suit symbol of the pile, for example "♥ Foundation".
        """
        self.canvas.create_text(
            self.stock_rect()[0] + CARD_WIDTH / 2,
            TOP_ROW_Y - PILE_LABEL_OFFSET,
            text="Stock",
            fill="white",
            font=("Arial", 10, "bold"),
        )
        self.canvas.create_text(
            self.waste_rect()[0] + CARD_WIDTH / 2,
            TOP_ROW_Y - PILE_LABEL_OFFSET,
            text="Waste",
            fill="white",
            font=("Arial", 10, "bold"),
        )

        for foundation_index, suit in enumerate(FOUNDATION_SUITS):
            x1, _, _, _ = self.foundation_rect(foundation_index)
            self.canvas.create_text(
                x1 + CARD_WIDTH / 2,
                TOP_ROW_Y - PILE_LABEL_OFFSET,
                text=f"{SUIT_SYMBOLS[suit]} Foundation",
                fill="white",
                font=("Arial", 10, "bold"),
            )

    def draw_stock(self) -> None:
        """Draw either the stock pile or an empty placeholder."""
        rect = self.stock_rect()
        if self.game.stock:
            self.draw_card(rect[0], rect[1], self.game.stock[-1], face_up=False, selected=False)
            self.canvas.create_text(
                rect[0] + CARD_WIDTH / 2,
                rect[3] + PILE_COUNT_OFFSET,
                text=f"{len(self.game.stock)} cards",
                fill="white",
                font=("Arial", 10),
            )
        else:
            self.draw_empty_pile(rect[0], rect[1], "Reset", font_size=EMPTY_PILE_WORD_FONT_SIZE)

    def draw_waste(self) -> None:
        """Draw the top waste card or the empty waste placeholder."""
        rect = self.waste_rect()
        if self.game.waste:
            selected = self.selection is not None and self.selection.source_type == "waste"
            self.draw_card(rect[0], rect[1], self.game.waste[-1], face_up=True, selected=selected)
            self.canvas.create_text(
                rect[0] + CARD_WIDTH / 2,
                rect[3] + PILE_COUNT_OFFSET,
                text=f"{len(self.game.waste)} cards",
                fill="white",
                font=("Arial", 10),
            )
        else:
            self.draw_empty_pile(rect[0], rect[1], "Waste", font_size=EMPTY_PILE_WORD_FONT_SIZE)

    def draw_foundations(self) -> None:
        """Draw all four foundation piles.

        Only the top card of each pile is drawn, since the cards beneath it
        are completely covered. A card that is still flying in is left out
        (see `visible_foundation_pile`). An empty foundation shows its suit
        symbol, and either kind of pile gets the orange outline when it is
        the destination of the current hint.
        """
        for foundation_index, suit in enumerate(FOUNDATION_SUITS):
            rect = self.foundation_rect(foundation_index)
            pile = self.visible_foundation_pile(foundation_index)
            hint_target = self.is_hint_destination("foundation", foundation_index)

            if pile:
                # A foundation card can be the yellow "selected" card (the
                # player lifted it) and/or the orange hinted destination.
                selected = (
                    self.selection is not None
                    and self.selection.source_type == "foundation"
                    and self.selection.pile_index == foundation_index
                )
                self.draw_card(
                    rect[0],
                    rect[1],
                    pile[-1],
                    face_up=True,
                    selected=selected,
                    hint=hint_target,
                )
            else:
                self.draw_empty_pile(
                    rect[0],
                    rect[1],
                    SUIT_SYMBOLS[suit],
                    highlighted=hint_target,
                )

    def draw_tableau(self) -> None:
        """Draw the seven tableau columns from left to right.

        Within a column the cards are drawn back to front, so each card
        overlaps the one before it and only a strip at the top of the
        covered cards stays visible. Cards still in flight are left out
        (see `visible_tableau_column`), and an empty column shows a "K"
        placeholder as a reminder that only a King can go there.
        """
        for column_index in range(TABLEAU_COLUMNS):
            x = self.tableau_x(column_index)
            column = self.visible_tableau_column(column_index)
            positions = self.tableau_positions_for_cards(column)
            hint_target = self.is_hint_destination("tableau", column_index)

            if not column:
                self.draw_empty_pile(x, TABLEAU_Y, "K", highlighted=hint_target)
                continue

            for card_index, card in enumerate(column):
                y = positions[card_index]
                selected = self.is_tableau_card_selected(column_index, card_index)
                # The orange hint highlight marks only the top card of the
                # destination column, kept separate from the yellow selection.
                hint = hint_target and card_index == len(column) - 1
                self.draw_card(
                    x,
                    y,
                    card,
                    face_up=card.face_up,
                    selected=selected,
                    hint=hint,
                )

    def rounded_rect(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        radius: float,
        **options,
    ) -> int:
        """Draw a rectangle with rounded corners and return its canvas id.

        tkinter's Canvas has no rounded-rectangle command, so we fake one with
        a polygon: each corner is listed as three close-together points, and
        asking tkinter to draw a smooth curve through them turns the sharp
        corners into gentle arcs while the straight edges stay straight.
        `**options` forwards styling such as `fill`, `outline`, and `width`.
        """
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1,
            x2, y1 + radius, x2, y2 - radius, x2, y2,
            x2 - radius, y2, x1 + radius, y2, x1, y2,
            x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, **options)

    def draw_empty_pile(
        self,
        x: int,
        y: int,
        text: str = "",
        highlighted: bool = False,
        font_size: int = EMPTY_PILE_SYMBOL_FONT_SIZE,
    ) -> None:
        """Draw an outlined placeholder where an empty pile sits.

        A normal placeholder has a thin dashed outline. A hinted one gets the
        same solid 4 px orange outline as a hinted card, so the player sees
        one consistent "put it here" marker whether the pile is empty or not.
        """
        outline_options: dict[str, Any] = (
            {"outline": HINT_COLOR, "width": HIGHLIGHT_OUTLINE_WIDTH}
            if highlighted
            else {"outline": EMPTY_OUTLINE, "width": 2, "dash": (6, 3)}
        )
        self.rounded_rect(
            x,
            y,
            x + CARD_WIDTH,
            y + CARD_HEIGHT,
            10,
            fill=PLACEHOLDER_FILL,
            **outline_options,
        )
        if text:
            self.canvas.create_text(
                x + CARD_WIDTH / 2,
                y + CARD_HEIGHT / 2,
                text=text,
                fill=EMPTY_OUTLINE,
                font=("Arial", font_size, "bold"),
            )

    def draw_card(
        self,
        x: float,
        y: float,
        card: Card,
        face_up: bool,
        selected: bool,
        hint: bool = False,
    ) -> None:
        """Draw one card face or card back.

        `selected` highlights the card the player has picked up (yellow);
        `hint` highlights a destination the hint system suggests (orange).
        Keeping the two colours separate makes the board easier to read.
        """
        if hint:
            outline_color = HINT_COLOR
            outline_width = HIGHLIGHT_OUTLINE_WIDTH
        elif selected:
            outline_color = HIGHLIGHT_COLOR
            outline_width = HIGHLIGHT_OUTLINE_WIDTH
        else:
            outline_color = CARD_OUTLINE
            outline_width = 2

        # Draw the shadow first so the card appears to sit on top of it.
        self.draw_card_shadow(x, y)

        if face_up:
            # Outer white card body with gently rounded corners.
            self.rounded_rect(
                x,
                y,
                x + CARD_WIDTH,
                y + CARD_HEIGHT,
                10,
                fill=CARD_FILL,
                outline=outline_color,
                width=outline_width,
            )

            # Inner border adds a little visual polish (no fill, just an edge).
            self.rounded_rect(
                x + 4,
                y + 4,
                x + CARD_WIDTH - 4,
                y + CARD_HEIGHT - 4,
                7,
                fill="",
                outline="#EFE7D9",
                width=1,
            )

            text_color = SUIT_COLORS[card.suit]
            label = card.label()
            suit_symbol = SUIT_SYMBOLS[card.suit]

            # Top-left corner index: the rank and suit together (for example
            # "Q♥"). Only this top strip shows when cards are stacked, so it
            # carries everything; a second pip below it would be hidden.
            self.canvas.create_text(
                x + 9,
                y + CORNER_INDEX_INSET_Y,
                text=label,
                anchor="nw",
                fill=text_color,
                font=("Arial", 13, "bold"),
            )

            # Large centered suit symbol.
            self.canvas.create_text(
                x + CARD_WIDTH / 2,
                y + CARD_HEIGHT / 2,
                text=suit_symbol,
                fill=text_color,
                font=("Arial", 28, "bold"),
            )

            # Bottom-right corner index: the same rank and suit, mirrored so
            # the card still reads correctly when viewed from the other side.
            self.canvas.create_text(
                x + CARD_WIDTH - 9,
                y + CARD_HEIGHT - CORNER_INDEX_INSET_Y,
                text=label,
                anchor="se",
                fill=text_color,
                font=("Arial", 13, "bold"),
            )
            return

        # Face-down cards use a dark blue rounded back.
        self.rounded_rect(
            x,
            y,
            x + CARD_WIDTH,
            y + CARD_HEIGHT,
            10,
            fill=CARD_BACK_COLOR,
            outline=outline_color,
            width=outline_width,
        )
        self.rounded_rect(
            x + 5,
            y + 5,
            x + CARD_WIDTH - 5,
            y + CARD_HEIGHT - 5,
            7,
            fill="",
            outline=CARD_BACK_ACCENT,
            width=1,
        )

        # Decorative diagonal lines make the card back easier to distinguish.
        self.draw_card_back_pattern(x, y)

        self.canvas.create_text(
            x + CARD_WIDTH / 2,
            y + CARD_HEIGHT / 2,
            text="SOL",
            fill="white",
            font=("Arial", 14, "bold"),
        )

    def draw_card_shadow(self, x: float, y: float) -> None:
        """Draw a simple offset rounded shadow under a card."""
        self.rounded_rect(
            x + 4,
            y + 5,
            x + CARD_WIDTH + 4,
            y + CARD_HEIGHT + 5,
            10,
            fill=CARD_SHADOW,
            outline="",
        )

    def draw_card_back_pattern(self, x: float, y: float) -> None:
        """Draw clipped diagonal stripes inside a face-down card's inner frame.

        The pattern is a family of parallel 45-degree lines. Along a 45-degree
        line, (x - y) stays constant, so each stripe is identified by that
        offset and consecutive offsets differ by exactly `CARD_BACK_STRIPE_SPACING`,
        which keeps the gaps even. Each stripe is clipped to a box inset
        `CARD_BACK_STRIPE_INSET` pixels from the card edge: that box sits
        inside the inner frame, rounded corners included.
        """
        left = x + CARD_BACK_STRIPE_INSET
        top = y + CARD_BACK_STRIPE_INSET
        width = CARD_WIDTH - 2 * CARD_BACK_STRIPE_INSET
        height = CARD_HEIGHT - 2 * CARD_BACK_STRIPE_INSET

        # Offsets run from the bottom-left corner (-height) to the top-right
        # corner (+width); the end points themselves would be zero-length.
        for offset in range(-height + CARD_BACK_STRIPE_SPACING, width, CARD_BACK_STRIPE_SPACING):
            # Start on the left edge for negative offsets, else on the top edge.
            start_u = max(0, offset)
            start_v = start_u - offset
            # Travel down-right until the right or bottom edge, whichever is first.
            length = min(width - start_u, height - start_v)
            self.canvas.create_line(
                left + start_u,
                top + start_v,
                left + start_u + length,
                top + start_v + length,
                fill=CARD_BACK_ACCENT,
                width=2,
            )

    def draw_animation(self) -> None:
        """Draw cards that are currently moving between piles.

        Each card is placed part of the way along a straight line from its
        start point to its end point. These are drawn after (so on top of)
        every pile, which is why they appear to fly over the board.
        """
        if self.animation is None:
            return

        # Use smoothstep easing so motion starts and ends gently.
        # Beginner note: `progress` runs evenly from 0 to 1. The formula
        # 3p^2 - 2p^3 also runs from 0 to 1, but slowly near both ends and
        # fastest in the middle, so cards ease out and settle in softly.
        progress = self.animation.frame / self.animation.steps
        eased_progress = progress * progress * (3 - 2 * progress)
        for card, start, end in zip(
            self.animation.cards,
            self.animation.start_positions,
            self.animation.end_positions,
            strict=True,
        ):
            x = start[0] + (end[0] - start[0]) * eased_progress
            y = start[1] + (end[1] - start[1]) * eased_progress
            # Lift the card up to 6 px at the start and set it down on
            # landing, so it looks picked up rather than slid across.
            y -= (1.0 - eased_progress) * 6
            self.draw_card(x, y, card, face_up=card.face_up, selected=False)

    def visible_foundation_pile(self, foundation_index: int) -> list[Card]:
        """Hide destination cards that are being animated on top of a foundation."""
        pile = self.game.foundations[foundation_index]
        hidden_count = self.animation_hidden_count("foundation", foundation_index)
        if hidden_count == 0:
            return pile
        return pile[:-hidden_count]

    def visible_tableau_column(self, column_index: int) -> list[Card]:
        """Hide destination cards that are being animated on top of a tableau."""
        column = self.game.tableau[column_index]
        hidden_count = self.animation_hidden_count("tableau", column_index)
        if hidden_count == 0:
            return column
        return column[:-hidden_count]

    def animation_hidden_count(self, pile_type: str, pile_index: int) -> int:
        """Return how many cards should be hidden in a destination during animation.

        The model moves cards before the animation starts, so the moving
        cards are already the top cards of their destination pile. Hiding
        that many cards from the pile while they are drawn in flight stops
        the player from seeing each moving card twice.
        """
        if self.animation is None:
            return 0
        if self.animation.destination_type != pile_type:
            return 0
        if self.animation.destination_index != pile_index:
            return 0
        return len(self.animation.cards)

    def is_hint_destination(self, pile_type: str, pile_index: int) -> bool:
        """True when the hint system wants this pile highlighted."""
        if self.hint_move is None:
            return False
        return (
            self.hint_move.destination_type == pile_type
            and self.hint_move.destination_index == pile_index
        )

    def is_tableau_card_selected(self, column_index: int, card_index: int) -> bool:
        """Highlight every card in the currently selected tableau stack."""
        if self.selection is None or self.selection.source_type != "tableau":
            return False
        if self.selection.pile_index != column_index:
            return False
        return card_index >= self.selection.card_index

    def selection_positions(self, selection: Selection) -> list[tuple[float, float]]:
        """Find the on-screen positions of the currently selected cards."""
        if selection.source_type == "waste":
            x1, y1, _, _ = self.waste_rect()
            return [(x1, y1)]

        if selection.source_type == "foundation":
            x1, y1, _, _ = self.foundation_rect(selection.pile_index)
            return [(x1, y1)]

        x = self.tableau_x(selection.pile_index)
        positions = self.tableau_positions(selection.pile_index)
        return [(x, positions[index]) for index in range(selection.card_index, len(positions))]

    def destination_positions(
        self,
        cards: list[Card],
        destination_type: str,
        destination_index: int,
    ) -> list[tuple[float, float]]:
        """Compute where each moving card should end up after a move.

        This must be called BEFORE the model applies the move (see
        `animate_move`): it reads the destination column as it is now and
        places the first moving card one spacing step below the current top
        card, then each further card FACE_UP_SPACING lower again.
        """
        if destination_type == "foundation":
            x1, y1, _, _ = self.foundation_rect(destination_index)
            return [(x1, y1)]

        x = self.tableau_x(destination_index)
        destination_column = self.game.tableau[destination_index]
        if not destination_column:
            start_y = TABLEAU_Y
        else:
            # The next card goes just below the current top card.
            positions = self.tableau_positions(destination_index)
            top_card = destination_column[-1]
            spacing = FACE_UP_SPACING if top_card.face_up else FACE_DOWN_SPACING
            start_y = positions[-1] + spacing

        return [(x, start_y + FACE_UP_SPACING * offset) for offset in range(len(cards))]

    def point_in_rect(self, x: int, y: int, rect: tuple[int, int, int, int]) -> bool:
        """Basic hit-test helper for rectangular areas."""
        x1, y1, x2, y2 = rect
        return x1 <= x <= x2 and y1 <= y <= y2

    def stock_rect(self) -> tuple[int, int, int, int]:
        """Return the stock pile rectangle."""
        return (MARGIN_X, TOP_ROW_Y, MARGIN_X + CARD_WIDTH, TOP_ROW_Y + CARD_HEIGHT)

    def waste_rect(self) -> tuple[int, int, int, int]:
        """Return the waste pile rectangle."""
        x = MARGIN_X + TABLEAU_STEP
        return (x, TOP_ROW_Y, x + CARD_WIDTH, TOP_ROW_Y + CARD_HEIGHT)

    def foundation_rect(self, foundation_index: int) -> tuple[int, int, int, int]:
        """Return the rectangle for one foundation pile.

        The four foundations sit exactly above the last four tableau columns.
        """
        x = self.tableau_x(TABLEAU_COLUMNS - FOUNDATION_COUNT + foundation_index)
        return (x, TOP_ROW_Y, x + CARD_WIDTH, TOP_ROW_Y + CARD_HEIGHT)

    def tableau_x(self, column_index: int) -> int:
        """Return the left x-position of a tableau column."""
        return MARGIN_X + column_index * TABLEAU_STEP

    def tableau_positions(self, column_index: int) -> list[int]:
        """Return every y-position in one real tableau column."""
        return self.tableau_positions_for_cards(self.game.tableau[column_index])

    def tableau_positions_for_cards(self, cards: list[Card]) -> list[int]:
        """Return stacked y-positions for any supplied list of cards.

        Face-down cards can overlap more tightly because nothing on them needs
        to be readable, while face-up cards step further down so their rank
        and suit still show at the top edge. That is why two different
        spacings (FACE_UP_SPACING and FACE_DOWN_SPACING) are used here.
        """
        y_positions: list[int] = []
        y = TABLEAU_Y
        for card in cards:
            y_positions.append(y)
            y += FACE_UP_SPACING if card.face_up else FACE_DOWN_SPACING
        return y_positions

    def find_tableau_hit(self, x: int, y: int) -> tuple[int | None, int | None]:
        """
        Figure out which tableau column/card a mouse click landed on.

        Returns `(column_index, card_index)`. `card_index` is None when the
        click is inside a column's area but not on a card (an empty column's
        placeholder), and both are None when no column was hit.

        Cards overlap, so a covered card only "owns" the visible strip
        between its top edge and the top edge of the next card, while the
        front (last) card owns its whole face. The scan starts from that
        front card and works back toward the first card, so the card the
        player can actually see wins the hit test.
        """
        for column_index in range(TABLEAU_COLUMNS):
            x1 = self.tableau_x(column_index)
            x2 = x1 + CARD_WIDTH
            if not (x1 <= x <= x2):
                continue

            column = self.game.tableau[column_index]
            if not column:
                if TABLEAU_Y <= y <= TABLEAU_Y + CARD_HEIGHT:
                    return column_index, None
                continue

            positions = self.tableau_positions(column_index)
            last_bottom = positions[-1] + CARD_HEIGHT
            if not (TABLEAU_Y <= y <= last_bottom):
                continue

            # Walk backward so the topmost visible card wins the hit test.
            for card_index in range(len(column) - 1, -1, -1):
                top = positions[card_index]
                bottom = top + CARD_HEIGHT if card_index == len(column) - 1 else positions[card_index + 1]

                if top <= y <= bottom:
                    return column_index, card_index

            return column_index, None

        return None, None

    def is_same_selection(self, other: Selection) -> bool:
        """Check whether the user clicked the exact same selection again."""
        if self.selection is None:
            return False
        return (
            self.selection.source_type == other.source_type
            and self.selection.pile_index == other.pile_index
            and self.selection.card_index == other.card_index
        )

    def describe_cards(self, cards: list[Card]) -> str:
        """Small UI wrapper around the model helper."""
        return self.game.describe_cards(cards)

    def format_time(self, seconds: int) -> str:
        """Format elapsed time as MM:SS."""
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        return f"{minutes:02d}:{remaining_seconds:02d}"


def main() -> None:
    """Start the tkinter application."""
    root = tk.Tk()
    SolitaireApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
