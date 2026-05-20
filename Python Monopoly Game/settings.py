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
# AI tuning knobs (see ai.py)
# --------------------------------------------------------------------------
AI_CASH_CUSHION = 200         # cash an AI tries to keep spare before spending
AI_BUILD_RESERVE = 250        # cash kept back before spending on houses
AI_TURN_DELAY_MS = 750        # pause between AI actions so a human can watch
AI_TRADE_ACCEPT_MARGIN = 60   # an offer must beat the status quo by this much


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

# Building colours.
HOUSE_COLOR = (60, 170, 90)
HOTEL_COLOR = (208, 52, 52)

# Highlights.
HIGHLIGHT = (240, 206, 110)         # selected / actionable
DANGER = (224, 84, 84)
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
