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

PLAYER_COLORS = [
    (215, 55, 55),    # red
    (46, 101, 218),   # blue
    (52, 162, 88),    # green
    (224, 173, 48),   # yellow
    (155, 86, 206),   # purple
    (236, 118, 54),   # orange
]

PLAYER_NAMES = ["Red", "Blue", "Green", "Yellow", "Purple", "Orange"]


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
