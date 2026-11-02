"""Shared constants for the Ludo desktop game.

The rest of the project imports named values from here instead of scattering
magic numbers through the code. The save paths intentionally live under
``%APPDATA%`` so progress survives both source runs and PyInstaller builds.
"""

from __future__ import annotations

import os
from pathlib import Path

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
