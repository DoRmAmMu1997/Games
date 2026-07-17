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
BOARD_RECT = (30, 30, 840, 840)
BOARD_CENTER = (450, 450)
BOARD_RADIUS = 330
PANEL_X = 900
PANEL_WIDTH = SCREEN_WIDTH - PANEL_X - 30

# AI delay is intentionally visible so human players can follow what happened
# instead of seeing computer turns flash by instantly.
AI_TURN_DELAY_MS = 650
DICE_ANIM_MS = 350
TOKEN_ANIM_SPEED = 9.0


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
BG = (28, 35, 39)
BOARD_BG = (232, 226, 205)
BOARD_LINE = (37, 43, 48)
TRACK_FILL = (247, 245, 235)
HOME_FILL = (245, 239, 216)
PANEL_BG = (20, 27, 31)
PANEL_CARD = (35, 45, 51)
PANEL_EDGE = (82, 102, 112)
WHITE = (248, 248, 242)
SOFT = (185, 196, 196)
INK = (20, 24, 26)
GOLD = (224, 181, 76)
SUCCESS = (110, 205, 140)
DANGER = (224, 84, 84)
DISABLED = (88, 98, 102)

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
# Save data
# ---------------------------------------------------------------------------
def _user_save_dir() -> Path:
    """Return the per-user folder used for saves and lifetime stats."""

    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "Ludo"


SAVE_DIR = _user_save_dir()
STATS_PATH = SAVE_DIR / "stats.json"          # lifetime games and wins
SAVEGAME_PATH = SAVE_DIR / "savegame.json"    # one resumable in-progress game
