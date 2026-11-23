"""Shared constants, colours, layout values, and save-file locations.

Keeping every tunable value in one file means the rest of the game can import
a named constant instead of hard-coding numbers. Re-balancing or re-skinning
the game then only touches this file.

Beginner note:
- Most numbers here are "design knobs" -- safe to change to tweak the look
  and feel without rewriting any game logic.
- The rules-critical numbers (starting cash, tax amounts, ...) are grouped
  together and labelled so you do not change them by accident.
"""

from __future__ import annotations

import os
from pathlib import Path

from audio import Note, midi

# --------------------------------------------------------------------------
# Window and timing
# --------------------------------------------------------------------------
WINDOW_TITLE = "Monopoly"
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 880
FPS = 60

# The board is a square drawn on the left; an information panel sits to its
# right. These values are derived once so the rest of the UI lines up.
BOARD_MARGIN = 20
BOARD_SIZE = SCREEN_HEIGHT - BOARD_MARGIN * 2          # 840 -- a square board
PANEL_X = BOARD_SIZE + BOARD_MARGIN * 2                # left edge of the panel
PANEL_WIDTH = SCREEN_WIDTH - PANEL_X - BOARD_MARGIN

# A standard Monopoly board has 40 spaces: 11 along each side counting the
# four shared corner squares. The corner squares are bigger than edge tiles.
SPACES_PER_SIDE = 11
CORNER_SIZE = BOARD_SIZE * 0.16
TILE_LONG = (BOARD_SIZE - CORNER_SIZE * 2) / (SPACES_PER_SIDE - 2)   # tile length
TILE_SHORT = CORNER_SIZE                                            # tile depth

# Radii, in pixels, of the round shapes (all drawn antialiased): a player's
# token on the board, the token-colour disc on a player card, and one pip
# on a die face.
# All four tokens can stand on one tile in a 2x2 grid without overlapping:
# an edge tile is only about 63 px wide, and two tokens of radius 13 with
# TOKEN_GAP between them take 54 px, which fits inside its ownership border.
TOKEN_RADIUS = 13
TOKEN_GAP = 2
PLAYER_DISC_RADIUS = 14
PIP_RADIUS = 5

# A tile's name and price keep this many pixels clear of every tile edge:
# the 4 px ownership border drawn inside an owned tile, plus 2 px so the
# text never touches that border.
TILE_LABEL_INSET = 6


# --------------------------------------------------------------------------
# Core Monopoly rules numbers (changing these changes the game balance)
# --------------------------------------------------------------------------
TOTAL_PLAYERS = 4
STARTING_CASH = 1500
GO_SALARY = 200
JAIL_FINE = 50
INCOME_TAX = 200
LUXURY_TAX = 100
MAX_JAIL_TURNS = 3        # after this many failed escape rolls you must pay
BANK_HOUSES = 32          # houses the bank owns at the start of a game
BANK_HOTELS = 12          # hotels the bank owns at the start of a game

# Fixed board positions that the rules refer to directly.
GO_POSITION = 0
JAIL_POSITION = 10
FREE_PARKING_POSITION = 20
GO_TO_JAIL_POSITION = 30


# --------------------------------------------------------------------------
# AI timing (difficulty/profile tuning lives in ai.py)
# --------------------------------------------------------------------------
AI_TURN_DELAY_MS = 750        # pause between AI actions so a human can watch

# After a player rejects an AI's offer for a title, that AI waits this many
# turns before asking the same player for the same title again. Without it
# the AI re-sends the identical offer every turn; 16 turns is about four
# laps of a 4-player table, long enough for cash and boards to change.
TRADE_RETRY_COOLDOWN_TURNS = 16

# Tokens hop space-by-space around the board after a dice roll. This is the
# travel speed in pixels per second; teleports (jail, some cards) slide
# directly instead of hopping.
TOKEN_HOP_SPEED = 540.0


# --------------------------------------------------------------------------
# Colours -- plain (red, green, blue) tuples, each channel 0-255
# --------------------------------------------------------------------------
# Window / surfaces.
BG = (24, 38, 32)
BOARD_FACE = (203, 223, 205)        # the classic pale-green board face
TILE_FACE = (247, 247, 240)         # off-white property tiles
PANEL_BG = (16, 26, 22)
PANEL_CARD = (30, 46, 39)
INK = (24, 27, 30)                  # near-black text / outlines
WHITE = (248, 248, 244)
SOFT = (170, 186, 178)              # muted text
GOLD = (224, 188, 92)
SHADOW = (0, 0, 0)

# The eight property colour groups, keyed by the group name used in board_data.
GROUP_COLORS = {
    "brown": (122, 74, 46),
    "light_blue": (171, 224, 244),
    "pink": (212, 64, 150),
    "orange": (242, 150, 58),
    "red": (226, 49, 45),
    "yellow": (255, 231, 86),
    "green": (52, 166, 84),
    "dark_blue": (44, 92, 200),
}

# Non-street ownable spaces and special tiles.
RAIL_COLOR = (38, 40, 44)
UTILITY_COLOR = (180, 196, 205)
TAX_COLOR = (210, 210, 200)

# Up to four player tokens -- deliberately distinct from the group colours.
TOKEN_COLORS = [
    (208, 48, 48),     # player 1 - crimson
    (44, 86, 200),     # player 2 - royal blue
    (40, 150, 74),     # player 3 - green
    (150, 78, 188),    # player 4 - purple
]
TOKEN_NAMES = ["Red", "Blue", "Green", "Purple"]

# Chance / Community Chest card faces shown in the board's middle. White
# header and body text reads at better than 4.5:1 on both.
CHANCE_CARD_COLOR = (70, 96, 150)
CHEST_CARD_COLOR = (130, 90, 45)

# Building colours.
HOUSE_COLOR = (60, 170, 90)
HOTEL_COLOR = (208, 52, 52)

# Highlights.
HIGHLIGHT = (240, 206, 110)         # selected / actionable
DANGER = (224, 84, 84)             # warning fills and strokes
# Warning TEXT is a lighter coral of the same red: it reaches 4.5:1 contrast
# on every dark surface it is drawn on (DANGER itself only manages 2.5:1 on
# the current player's card).
DANGER_TEXT = (255, 182, 170)
PANEL_CARD_CURRENT = (52, 74, 60)   # the current player's card in the side panel
BUTTON_FILL = (54, 86, 72)          # an ordinary button
SUCCESS = (120, 210, 140)


# --------------------------------------------------------------------------
# Save data -- a stable per-user folder, NOT next to the source/executable
# --------------------------------------------------------------------------
def _user_save_dir() -> Path:
    """Return the per-user folder that holds Monopoly's save data.

    This must never be derived from ``__file__``. A PyInstaller --onefile
    build unpacks into a temporary folder that Windows deletes when the .exe
    closes, so a save written there would vanish every session. ``%APPDATA%``
    persists across runs and resolves the same from source or a frozen .exe.
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "Monopoly"


SAVE_DIR = _user_save_dir()
STATS_PATH = SAVE_DIR / "stats.json"          # lifetime games played / wins
SAVEGAME_PATH = SAVE_DIR / "savegame.json"    # one in-progress game


# --------------------------------------------------------------------------
# Sound
# --------------------------------------------------------------------------
# Every sound is a recipe: a list of `Note`s that audio.py renders into
# samples when the game starts (no audio files ship with the game). Pitches
# are MIDI note numbers through `midi()`: 69 is A4 (440 Hz), +12 is one octave
# up. The palette is a warm jazz lounge in F major, the key of the music:
# electric-piano chimes, coin clinks, paper flips and wooden knocks, with the
# soft brassy "square" voice kept low and rare.
#
# Beginner note:
# - A "strike" note below has no sustain: it rises over a few milliseconds
#   and then rings down over `ring` seconds, like a hammer hitting a tine.
# - Volumes stay well under 1.0 on purpose: an AI turn can fire a roll, a
#   few hops, rent and a card in one breath, and their samples add up.
SFX_STRIKE_ATTACK = 0.006  # A struck note reaches full volume this fast (s).
SFX_STRIKE_RELEASE = 0.03  # Tail after a strike's ring, so it never ends abruptly (s).
SFX_ROOT_NOTE = 65  # F4: the home note of the effects' F major ladder.
F_MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)  # Semitones above F for each degree of the scale.
# The dice sound is a rattle of short noise ticks (two dice tumbling), each
# at a different noise rate so the rattle sounds uneven; the dice land with
# a double clack DICE_RESULT_AT seconds in, as the on-screen shuffle settles.
DICE_RATTLE_TICKS = ((0.0, 2600.0), (0.05, 3400.0), (0.11, 2200.0), (0.18, 3000.0), (0.25, 2500.0), (0.31, 3200.0))
DICE_RESULT_AT = 0.4  # Seconds; a little under the shell's 480 ms dice shuffle.
DICE_SECOND_CLACK = 0.035  # The second die lands this long after the first (s).
# A token's hops climb the F major ladder one degree per space, so the
# player hears the count: hop n of a move plays variant "hop@n". Two dice
# move a token at most 12 spaces; HOP_PITCH_STEPS variants cover that.
HOP_PITCH_STEPS = 12
RHODES_TINE_LEVEL = 0.25  # The bell-like overtone an octave up, as a share of the note's volume.
RHODES_TINE_RING = 0.35  # The overtone rings for this share of the note's ring, then fades.


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


def rhodes(pitch: float, start: float, ring: float, volume: float) -> list[Note]:
    """Return one electric-piano note: a soft sine body plus a quick bell-like tine an octave up.

    Beginner note:
    - A Rhodes piano's tone is mostly a pure, round fundamental; the metal
      tine adds a brief bright "ding" on top. Two notes played together, one
      short and quiet an octave higher, imitate that without any samples.
    """

    return [
        strike(pitch, start, ring, volume),
        strike(pitch + 12, start, ring * RHODES_TINE_RING, volume * RHODES_TINE_LEVEL, "pluck"),
    ]


def knock(start: float, rate: float, volume: float, ring: float = 0.03) -> Note:
    """Return a short noise burst: a wooden knock, a stamp or a die hitting the board.

    A low `rate` (new random values per second) sounds dull and woody; a
    high one sounds like a crisp tick.
    """

    return Note(rate, start, 0.004, "noise", volume, attack=0.001, decay=ring, sustain=0.0, release=0.01)


def scale_note(degree: int) -> int:
    """Return the MIDI note `degree` steps up the F major ladder from SFX_ROOT_NOTE."""

    octave, step = divmod(degree, len(F_MAJOR_STEPS))
    return SFX_ROOT_NOTE + 12 * octave + F_MAJOR_STEPS[step]


def hop_notes(step: int) -> list[Note]:
    """Return one hop of a token: a short chime `step` degrees up the ladder, with a light tap."""

    return [*rhodes(scale_note(step), 0.0, 0.08, 0.16), knock(0.0, 1100.0, 0.05, 0.012)]


def jail_bars(start: float) -> list[Note]:
    """Return the jail clang: two low, clashing "bars" with a metal rattle, struck twice.

    Each strike is a tritone (F + B, then E + Bb), the most unsettled
    interval, played on the low brassy square voice.
    """

    notes: list[Note] = []
    for offset, (low, high), ring in ((0.0, (41, 47), 0.3), (0.17, (40, 46), 0.45)):
        notes += [
            strike(low, start + offset, ring, 0.22, "square"),
            strike(high, start + offset, ring, 0.15, "square"),
            knock(start + offset, 900.0, 0.16, 0.07),
        ]
    return notes


SFX_RECIPES: dict[str, list[Note]] = {
    # Two dice tumbling, then landing with a double clack and a soft thud.
    "dice": [
        *(knock(at, rate, 0.14, 0.022) for at, rate in DICE_RATTLE_TICKS),
        knock(DICE_RESULT_AT, 1600.0, 0.2, 0.04),
        knock(DICE_RESULT_AT + DICE_SECOND_CLACK, 1400.0, 0.18, 0.04),
        strike(41, DICE_RESULT_AT, 0.08, 0.1, "triangle"),
    ],
    # Doubles: a bright "ding-ding" up to high F once the dice have landed.
    "doubles": [
        *rhodes(84, DICE_RESULT_AT + 0.05, 0.14, 0.15),
        *rhodes(84, DICE_RESULT_AT + 0.14, 0.14, 0.15),
        *rhodes(89, DICE_RESULT_AT + 0.23, 0.35, 0.15),
    ],
    # A third double in a row: a muted "wah-wah" and then the jail bars clang.
    "three_doubles": [
        Note(midi(58), DICE_RESULT_AT + 0.05, 0.16, "square", 0.14, glide=-12.0, attack=0.03, decay=0.08,
             sustain=0.7, release=0.06),
        Note(midi(57), DICE_RESULT_AT + 0.27, 0.22, "square", 0.14, glide=-16.0, attack=0.03, decay=0.08,
             sustain=0.7, release=0.08),
        *jail_bars(DICE_RESULT_AT + 0.6),
    ],
    "hop": hop_notes(0),
    **{f"hop@{step}": hop_notes(step) for step in range(1, HOP_PITCH_STEPS)},
    # Passing GO: a cash-register "cha" (drawer thud and a noise burst), then a bell "ching".
    "cha_ching": [
        knock(0.0, 600.0, 0.12, 0.05),
        Note(7000.0, 0.0, 0.05, "noise", 0.14, glide=-20000.0, attack=0.003, decay=0.05, sustain=0.0,
             release=0.01),
        strike(96, 0.07, 0.5, 0.13),
        strike(100, 0.07, 0.45, 0.09),
        strike(103, 0.13, 0.35, 0.06),
    ],
    # Buying a title: a quick rising F major arpeggio over a rubber-stamp thud.
    "buy": [
        knock(0.0, 700.0, 0.14, 0.05),
        *(note for index, pitch in enumerate((65, 69, 72, 77)) for note in rhodes(pitch, index * 0.06, 0.3, 0.17)),
    ],
    # Rent changing hands: three coins clinking down onto a pile.
    "rent": [
        note
        for at, pitch in ((0.0, 93), (0.07, 89), (0.14, 96))
        for note in (strike(pitch, at, 0.12, 0.11, "pluck"), knock(at, 6000.0, 0.05, 0.015))
    ],
    # A tax: a low, official "dum-dum" falling a fifth, with a stamp.
    "tax": [
        strike(53, 0.0, 0.18, 0.24, "triangle"),
        strike(48, 0.16, 0.3, 0.26, "triangle"),
        knock(0.16, 650.0, 0.14, 0.05),
    ],
    # A Chance card: a paper flip swept upward, then a curious rising fourth.
    "card_chance": [
        Note(3000.0, 0.0, 0.07, "noise", 0.11, glide=12000.0, attack=0.01, decay=0.06, sustain=0.2, release=0.02),
        *rhodes(72, 0.08, 0.16, 0.15),
        *rhodes(77, 0.17, 0.3, 0.15),
    ],
    # A Community Chest card: a lower flip swept downward, then a warm strummed F major chord.
    "card_chest": [
        Note(2200.0, 0.0, 0.09, "noise", 0.11, glide=-6000.0, attack=0.01, decay=0.08, sustain=0.2, release=0.02),
        *(note for index, pitch in enumerate((60, 65, 69)) for note in rhodes(pitch, 0.1 + index * 0.03, 0.35, 0.12)),
    ],
    "jail": jail_bars(0.0),
    # Leaving jail: a quick upward swoop and a free-and-easy F major run.
    "leave_jail": [
        Note(midi(53), 0.0, 0.08, "sine", 0.12, glide=900.0, attack=0.01, decay=0.08, sustain=0.0, release=0.02),
        *(note for index, pitch in enumerate((65, 69, 72, 77))
          for note in rhodes(pitch, 0.06 + index * 0.05, 0.2, 0.15)),
    ],
    # A house: two hammer taps and a chime.
    "build_house": [knock(0.0, 1400.0, 0.15), knock(0.09, 1400.0, 0.15), *rhodes(72, 0.18, 0.25, 0.16)],
    # A hotel: three hammer taps and a ringing F major seventh chord.
    "build_hotel": [
        *(knock(index * 0.08, 1400.0, 0.15) for index in range(3)),
        *(note for pitch in (65, 69, 72, 76) for note in rhodes(pitch, 0.27, 0.5, 0.1)),
    ],
    # Selling a building back: a falling chime and a coin.
    "sell": [
        *(note for index, pitch in enumerate((72, 69, 65)) for note in rhodes(pitch, index * 0.08, 0.18, 0.15)),
        strike(89, 0.22, 0.12, 0.09, "pluck"),
    ],
    # Mortgaging: a stamp, then a soft falling third (A to F).
    "mortgage": [knock(0.0, 700.0, 0.18, 0.05), strike(69, 0.05, 0.16, 0.2, "triangle"),
                 strike(65, 0.17, 0.28, 0.2, "triangle")],
    # Lifting a mortgage: the same voice rising F - A - C, with a little sparkle.
    "unmortgage": [
        *(strike(pitch, index * 0.1, 0.18, 0.18, "triangle") for index, pitch in enumerate((65, 69, 72))),
        strike(84, 0.3, 0.2, 0.07),
    ],
    # An auction opens: a short, soft brass "ta-da" (C up to F).
    "auction_start": [
        strike(60, 0.0, 0.12, 0.13, "square"),
        strike(60, 0.0, 0.12, 0.1, "triangle"),
        strike(65, 0.14, 0.3, 0.15, "square"),
        strike(65, 0.14, 0.3, 0.12, "triangle"),
    ],
    # A bid: one quick high chime (rate-limited, auctions can be brisk).
    "bid": rhodes(81, 0.0, 0.1, 0.13),
    # Sold at auction: two gavel bangs and a settled F major chord.
    "gavel": [
        knock(0.0, 1000.0, 0.26, 0.05),
        strike(45, 0.0, 0.1, 0.2, "triangle", glide=-200.0),
        knock(0.22, 1000.0, 0.3, 0.06),
        strike(45, 0.22, 0.14, 0.22, "triangle", glide=-200.0),
        *(note for pitch in (65, 69, 72) for note in rhodes(pitch, 0.34, 0.4, 0.09)),
    ],
    # A trade offer: an open, questioning rise (A up to D) left unresolved.
    "trade_proposed": [*rhodes(69, 0.0, 0.16, 0.15), *rhodes(74, 0.12, 0.3, 0.15)],
    # Trade accepted: the rise resolves home, C up to F with A on top.
    "trade_accepted": [*rhodes(72, 0.0, 0.16, 0.15), *rhodes(77, 0.1, 0.4, 0.14), *rhodes(81, 0.1, 0.4, 0.1)],
    # Trade rejected: a soft falling "no thanks".
    "trade_rejected": [strike(70, 0.0, 0.12, 0.2, "triangle"), strike(65, 0.13, 0.25, 0.2, "triangle", glide=-30.0)],
    # Short of cash: a gentle two-tone alert (a tritone), sounded twice.
    "raise_funds": [
        note
        for at in (0.0, 0.2)
        for note in (strike(76, at, 0.12, 0.13, "triangle"), strike(70, at, 0.12, 0.13, "triangle"))
    ],
    # Bankruptcy: a muted "sad trombone", four falling semitones, the last one sagging.
    "bankrupt": [
        *(
            Note(midi(pitch), index * 0.3, 0.22, "square", 0.15, attack=0.03, decay=0.08, sustain=0.7, release=0.06)
            for index, pitch in enumerate((58, 57, 56))
        ),
        Note(midi(55), 0.9, 0.55, "square", 0.15, glide=-18.0, attack=0.03, decay=0.1, sustain=0.7, release=0.25),
    ],
    # A short, soft two-note click for every button.
    "click": [strike(84, 0.0, 0.05, 0.2), strike(91, 0.012, 0.04, 0.07)],
}
# The fewest seconds between two plays of the same effect (variants share
# their base name's cooldown). A slow frame can finish several hops at once,
# and the self-test runs an AI action every frame; these keep such bursts a
# gentle patter instead of a pile of identical sounds.
SFX_COOLDOWNS: dict[str, float] = {
    "hop": 0.05,
    "dice": 0.1,
    "bid": 0.08,
    "rent": 0.15,
    "cha_ching": 0.2,
    "build_house": 0.06,
    "sell": 0.06,
    "mortgage": 0.08,
    "unmortgage": 0.08,
    "raise_funds": 0.4,
    "click": 0.04,
}
