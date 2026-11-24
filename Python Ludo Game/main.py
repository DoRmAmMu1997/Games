"""Program entry point, Pygame window, persistence, input, and AI driver.

This is the "shell" around the rules engine. ``LudoApp`` opens the window,
turns mouse clicks and key presses into calls on ``LudoGame``, paces the
computer players, animates pawns hopping between cells, and saves the game
and lifetime stats under ``%APPDATA%\\Ludo``. It never decides a rule itself.

The app has three screens, held in ``LudoApp.screen``: ``"setup"`` (choose
players and house rules), ``"playing"`` and ``"over"`` (final ranking).

Beginner note: everything is drawn onto a fixed 1280x900 "logical" canvas and
then scaled to the real window. Layout constants below are therefore in
logical pixels, and mouse positions are converted back into logical pixels
before they are compared with buttons.

Sound: ``audio.py`` synthesises every effect and the music; this shell plays
them for the engine's events (``event_sounds``), token hops and buttons.
Ctrl+M, or a Sound button, switches all sound off and on; the choice is
saved as ``"sound"`` in the stats file.

Run ``python main.py`` to play. With the environment variable
``LUDO_AUTOTEST=1`` set, it instead plays a short hidden all-AI game and
exits, which is used as a smoke test.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import math
import os
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pygame

import ai
import audio
import ui
import visual_theme as theme
from board import BoardLayout
from board_render import BoardRenderer
from game import LudoGame, LudoRules
from models import Move
from settings import (
    AI_TURN_DELAY_MS,
    AUTOTEST_FRAMES,
    AUTOTEST_SEED,
    DICE_ANIM_MS,
    DISABLED,
    FPS,
    GOLD,
    ICON_BOARD_COLOR,
    ICON_BOARD_INSET,
    ICON_BOARD_RADIUS,
    ICON_BOARD_SIZE,
    ICON_DOT_ORIGIN,
    ICON_DOT_RADIUS,
    ICON_DOT_SPACING,
    ICON_FILE,
    ICON_SIZE,
    INK,
    MAX_PLAYERS,
    MIN_PLAYERS,
    MUSIC_FADE_IN_MS,
    MUSIC_GAME_OVER_FADE_MS,
    MUSIC_LOOP_SECONDS,
    MUSIC_VOLUME,
    PANEL_BG,
    PANEL_CARD,
    PANEL_EDGE,
    PANEL_WIDTH,
    PANEL_X,
    SAVE_DIR,
    SAVEGAME_PATH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SFX_COOLDOWNS,
    SFX_RECIPES,
    SOFT,
    STATS_PATH,
    SUCCESS,
    TOKEN_HOP_SPEED,
    WHITE,
    WINDOW_TITLE,
    music_notes,
    seat_colors,
    seat_name,
)

# ---------------------------------------------------------------------------
# Screen layout, in logical pixels. Setup screen controls first.
# ---------------------------------------------------------------------------
SETUP_CONTROL_X = PANEL_X + 24
SETUP_CONTROL_WIDTH = 246
SETUP_OPTION_LABEL_START_Y = 112
SETUP_OPTION_STEP = 78
SETUP_OPTION_CONTROL_OFFSET_Y = 32
SETUP_OPTION_CONTROL_HEIGHT = 38
SETUP_OPTION_BUTTON_WIDTH = 46
# Setup title and intro. The intro sits on a see-through dark plate sized to
# its wrapped lines, so it reads on the bright wallpaper glow, and no line is
# ever dropped by a fixed-height box.
SETUP_TITLE_CENTER = (450, 92)
SETUP_INTRO_TEXT = (
    "Classic competitive Ludo for 4 to 6 players. "
    "Choose how many seats are human; the remaining seats use heuristic AI."
)
SETUP_INTRO_COLOR = SOFT
SETUP_INTRO_WIDTH = 560          # widest a wrapped intro line may be
SETUP_INTRO_TOP = 146            # y of the first intro line
SETUP_INTRO_LINE_GAP = 4
SETUP_INTRO_PADDING = (16, 8)    # plate space around the text: horizontal, vertical
SETUP_INTRO_PLATE_ALPHA = 200    # plate opacity (0-255) over the wallpaper
SETUP_INTRO_RADIUS = 12
# The dark setup panel on the right; every setup control must fit inside it.
SETUP_PANEL_RECT = pygame.Rect(PANEL_X, 0, PANEL_WIDTH + 30, SCREEN_HEIGHT).inflate(-14, -18)
# Each section header ("Advanced Rules", "Human Names") gets room above its
# first control for one header line plus a clear gap. The header font's line
# height varies by platform (28 px FreeSans, about 32 px Arial or Liberation
# Sans, 33 px DejaVu Sans), so the allowance is a 36 px line: the tallest
# seen plus 3 spare pixels.
SETUP_HEADER_LINE_ALLOWANCE = 36
SETUP_HEADER_GAP = 4
SETUP_HEADER_ROOM = SETUP_HEADER_LINE_ALLOWANCE + SETUP_HEADER_GAP
# Rows below the option steppers. Six human names plus Resume and Start must
# still fit inside SETUP_PANEL_RECT, so the toggle and name rows are packed
# with small gaps (6 px between toggles, 3 px between name fields).
SETUP_RULES_HEADER_Y = 346
SETUP_TOGGLE_START_Y = SETUP_RULES_HEADER_Y + SETUP_HEADER_ROOM
SETUP_TOGGLE_STEP = 42
SETUP_TOGGLE_HEIGHT = 36
SETUP_NAME_HEADER_Y = 556
SETUP_NAME_START_Y = SETUP_NAME_HEADER_Y + SETUP_HEADER_ROOM
SETUP_NAME_FIELD_HEIGHT = 30
# Name text is inset this far from each side of its field; typing stops once
# the rendered name would cross the inset on the right.
SETUP_NAME_TEXT_PADDING = 10
SETUP_NAME_FIELD_STEP = 33
SETUP_NAME_SECTION_BOTTOM = (
    SETUP_NAME_START_Y + (MAX_PLAYERS - 1) * SETUP_NAME_FIELD_STEP + SETUP_NAME_FIELD_HEIGHT
)
SETUP_ACTION_GAP = 10
SETUP_ACTION_BUTTON_GAP = 6
SETUP_ACTION_HEIGHT = 34
SETUP_RESUME_Y = SETUP_NAME_SECTION_BOTTOM + SETUP_ACTION_GAP
SETUP_START_Y = SETUP_RESUME_Y + SETUP_ACTION_HEIGHT + SETUP_ACTION_BUTTON_GAP
# The setup screen's Sound toggle sits under Quit, right-aligned with it, in
# the corner beside the "Setup" title. 136 px holds "Sound: Off" (117 px in
# DejaVu Sans Bold, the widest font seen) with 9 px to spare each side.
SETUP_SOUND_RECT = pygame.Rect(SCREEN_WIDTH - 168, 68, 136, 34)
WINDOW_FIT_PADDING = 8
PLAY_SAVE_RECT = pygame.Rect(34, 794, 136, 38)
PLAY_PILL_HOVER_BRIGHTEN = 28  # a hovered Save/New pill lights up by this much
PLAY_NEW_RECT = pygame.Rect(34, 842, 136, 34)
PLAY_DICE_TRAY_RECT = pygame.Rect(214, 790, 430, 86)
# The in-game Sound pill sits just right of the dice tray, level with Roll:
# the free strip between the tray and the table log, below every board.
PLAY_SOUND_RECT = pygame.Rect(PLAY_DICE_TRAY_RECT.right + 20, 818, 136, 38)
# The pill is green while sound is on and grey while it is off.
PLAY_SOUND_ON_COLOR = SUCCESS
PLAY_SOUND_OFF_COLOR = DISABLED
PLAY_ROLL_RECT = pygame.Rect(510, 818, 112, 38)
# The tray's player banner, then the turn prompt under it. 48 px holds two
# wrapped lines of the small font (21 px in Windows Arial, Liberation Sans and
# DejaVu Sans) plus the 2 px gap, with 4 px to spare for taller fonts.
PLAY_TRAY_BANNER_RECT = pygame.Rect(PLAY_DICE_TRAY_RECT.x + 104, PLAY_DICE_TRAY_RECT.y + 8, 180, 28)
PLAY_PROMPT_RECT = pygame.Rect(PLAY_DICE_TRAY_RECT.x + 104, PLAY_DICE_TRAY_RECT.y + 38, 300, 48)
PLAY_PROMPT_LINE_GAP = 2
# The right-hand column holds the roster, then the move buttons, then the
# table log. Nothing here may overlap the board: a full six-player roster
# ends at y = 90 + 5 * 54 + 50 = 410, so the move buttons start below it.
PLAY_ROSTER_X = 932
PLAY_ROSTER_Y = 90
PLAY_ROSTER_WIDTH = 254
PLAY_ROSTER_STEP = 54
# A chip holds two text lines (name, then home/captures). 50 px fits them with
# the tallest platform fonts (21 px + 18 px DejaVu Sans) and 4 px to spare at
# the top and bottom.
PLAY_ROSTER_CHIP_HEIGHT = 50
PLAY_ROSTER_TEXT_X = 44         # chip text starts here, right of the colour dot
PLAY_ROSTER_TEXT_PADDING = 10   # clear space between the text and the chip's right edge
PLAY_ROSTER_TAG_GAP = 8         # least space between the name and its Human/AI tag
PLAY_ROSTER_LINE_GAP = 2        # space between the chip's two text lines
PLAY_MOVE_START = (PLAY_ROSTER_X, 420)
PLAY_MOVE_SIZE = (PLAY_ROSTER_WIDTH, 38)
PLAY_MOVE_GAP = 8
# The log's bottom edge lines up with the dice tray and New button (y = 876).
PLAY_LOG_RECT = pygame.Rect(PLAY_ROSTER_X, 744, PLAY_ROSTER_WIDTH, 132)
PLAY_LOG_PADDING = 12  # inset of the log's text from the card's left and right edges
# Game-over screen: the ranking card on the left and the lifetime-stats card
# on the right start at the same height. The stats card is sized to its title
# and five stat lines (with room for taller fonts), and the New Game / Quit
# buttons sit centred just beneath it.
OVER_CARD_TOP = 248
OVER_CARD_PADDING = 18            # inset of a card's text from its edges
OVER_RANKING_RECT = pygame.Rect(210, OVER_CARD_TOP, 480, 360)
OVER_STATS_FIRST_LINE = 70        # first stat line, measured from the card top
OVER_STATS_LINE_STEP = 42
OVER_STATS_HEIGHT = 290           # title + five lines + padding, with font slack
OVER_STATS_RECT = pygame.Rect(PANEL_X + 14, OVER_CARD_TOP, PANEL_WIDTH + 2, OVER_STATS_HEIGHT)
OVER_BUTTON_SIZE = (220, 44)
OVER_BUTTON_TOP = OVER_STATS_RECT.bottom + 24
OVER_BUTTON_STEP = 58
# The winner's name sits on a plaque in their seat colour under "Game Over",
# so it reads on the blue wallpaper whatever the seat colour. The plaque's
# width is capped so it stays clear of the stats card column.
OVER_PLAQUE_CENTER = (450, 178)
OVER_PLAQUE_PADDING = (28, 8)  # space around the text: horizontal, vertical
OVER_PLAQUE_MAX_WIDTH = 620
PREVIEW_CENTERS = ((200, 470), (450, 470), (700, 470))
PREVIEW_SIZE = 216

# Which effect (a name in settings.SFX_RECIPES) each engine event plays; see
# game.EVENT_KINDS. "move" has no entry because a moving token sounds cell by
# cell through its hops, and "game_won" is answered by the game-over jingle.
EVENT_SOUNDS = {
    "roll": "dice",
    "rolled_six": "six",
    "three_sixes": "three_sixes",
    "leave_yard": "leave_yard",
    "capture": "capture",
    "home": "home",
    "bonus_turn": "bonus",
    "no_move": "no_move",
    "turn_change": "turn",
}


def event_sounds(kinds: list[str], last_roll: int | None, human_to_play: bool) -> list[tuple[str, int]]:
    """Return the ``(effect name, pitch step)`` to play for one frame's engine events.

    Args:
        kinds: The events drained from the engine this frame, oldest first.
        last_roll: The engine's current die value; the dice sound uses it as
            its pitch step, so each face lands on its own note.
        human_to_play: Whether a human seat is to play now.

    A few events stay quiet so one moment never sounds twice: a forfeited
    third 6 groans instead of sparkling, a bonus roll earned by a 6 was
    already announced by the six sparkle, and the turn knock only plays when
    it calls a human to the table (AI-to-AI changes are heard as the next
    roll).
    """

    sounds: list[tuple[str, int]] = []
    for kind in kinds:
        name = EVENT_SOUNDS.get(kind)
        if (
            name is None
            or (kind == "rolled_six" and "three_sixes" in kinds)
            or (kind == "bonus_turn" and last_roll == 6)
            or (kind == "turn_change" and not human_to_play)
        ):
            continue
        sounds.append((name, (last_roll or 0) if kind == "roll" else 0))
    return sounds


@dataclass(frozen=True)
class SetupOptionRow:
    """One setup option row with shared label, value, and button geometry.

    Each top setup row (Total Players, Human Players, AI Profile) has a label
    line at ``label_y`` and, below it at ``control_y``, a left button, the
    current value centred at ``value_center``, and a right button. Building
    all three rows from one helper keeps them aligned.
    """

    label_y: int
    control_y: int
    value_center: tuple[int, int]
    left_button: pygame.Rect
    right_button: pygame.Rect


def _setup_option_row(index: int) -> SetupOptionRow:
    """Return aligned geometry for one top setup option row.

    ``index`` 0, 1 and 2 are the Total Players, Human Players and AI Profile
    rows; each row sits ``SETUP_OPTION_STEP`` pixels below the previous one.
    """

    label_y = SETUP_OPTION_LABEL_START_Y + index * SETUP_OPTION_STEP
    control_y = label_y + SETUP_OPTION_CONTROL_OFFSET_Y
    left_button = pygame.Rect(
        SETUP_CONTROL_X,
        control_y,
        SETUP_OPTION_BUTTON_WIDTH,
        SETUP_OPTION_CONTROL_HEIGHT,
    )
    right_button = pygame.Rect(
        SETUP_CONTROL_X + SETUP_CONTROL_WIDTH - SETUP_OPTION_BUTTON_WIDTH,
        control_y,
        SETUP_OPTION_BUTTON_WIDTH,
        SETUP_OPTION_CONTROL_HEIGHT,
    )
    return SetupOptionRow(
        label_y=label_y,
        control_y=control_y,
        value_center=(SETUP_CONTROL_X + SETUP_CONTROL_WIDTH // 2, left_button.centery),
        left_button=left_button,
        right_button=right_button,
    )


def _fit_window_size(
    available_size: tuple[int, int],
    chrome_size: tuple[int, int] = (0, 0),
) -> tuple[int, int]:
    """Return the largest 16:9-ish Ludo client size that fits the desktop.

    The game keeps drawing to a fixed ``SCREEN_WIDTH`` by ``SCREEN_HEIGHT``
    canvas. This helper only decides how large the real OS window should be.
    ``chrome_size`` accounts for the title bar and borders that live outside
    Pygame's client area.
    """

    available_width, available_height = available_size
    chrome_width, chrome_height = chrome_size
    client_width = max(1, available_width - max(0, chrome_width))
    client_height = max(1, available_height - max(0, chrome_height))
    scale = min(client_width / SCREEN_WIDTH, client_height / SCREEN_HEIGHT, 1.0)
    return (
        max(1, min(SCREEN_WIDTH, int(SCREEN_WIDTH * scale))),
        max(1, min(SCREEN_HEIGHT, int(SCREEN_HEIGHT * scale))),
    )


def _logical_to_window_point(pos: tuple[int, int], window_size: tuple[int, int]) -> tuple[int, int]:
    """Map a logical 1280x900 point into the scaled OS window.

    This is the inverse of ``_window_to_logical_point``; tests use it to
    click a logical position on a scaled window.
    """

    width, height = max(1, window_size[0]), max(1, window_size[1])
    return (
        int(pos[0] * width / SCREEN_WIDTH),
        int(pos[1] * height / SCREEN_HEIGHT),
    )


def _window_to_logical_point(pos: tuple[int, int], window_size: tuple[int, int]) -> tuple[int, int]:
    """Map a scaled OS-window point back into logical game coordinates.

    For example, on a window drawn at half size a click at (100, 50) becomes
    logical (200, 100). The result is clamped onto the canvas, so a click on
    the very edge of the window can never land outside it.
    """

    width, height = max(1, window_size[0]), max(1, window_size[1])
    logical_x = int(pos[0] * SCREEN_WIDTH / width)
    logical_y = int(pos[1] * SCREEN_HEIGHT / height)
    return (
        max(0, min(SCREEN_WIDTH - 1, logical_x)),
        max(0, min(SCREEN_HEIGHT - 1, logical_y)),
    )


def _desktop_work_area_size() -> tuple[int, int]:
    """Return usable desktop size, preferring Windows' taskbar-aware value.

    On Windows, ``SystemParametersInfoW(SPI_GETWORKAREA = 0x0030)`` reports the
    desktop minus the taskbar. Everywhere else, or if that call fails, the
    full screen size from pygame is used.
    """

    if sys.platform == "win32":
        try:
            rect = wintypes.RECT()
            ok = ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
            if ok:
                width = int(rect.right - rect.left)
                height = int(rect.bottom - rect.top)
                if width > 0 and height > 0:
                    return width, height
        except (AttributeError, OSError):
            pass
    info = pygame.display.Info()
    return max(1, int(info.current_w or SCREEN_WIDTH)), max(1, int(info.current_h or SCREEN_HEIGHT))


def _window_chrome_size() -> tuple[int, int]:
    """Estimate non-client window chrome so the outer window stays visible.

    Beginner note: "chrome" is the title bar and borders the operating
    system adds around the area pygame draws in. On Windows the sizes come
    from ``GetSystemMetrics``: 32/33 are the resizable frame width/height,
    92 is the extra padded border, and 4 is the caption (title bar) height.
    Other platforms report no chrome.
    """

    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            frame_x = int(user32.GetSystemMetrics(32))
            frame_y = int(user32.GetSystemMetrics(33))
            padded = int(user32.GetSystemMetrics(92))
            caption = int(user32.GetSystemMetrics(4))
            return (
                max(0, 2 * (frame_x + padded) + WINDOW_FIT_PADDING),
                max(0, caption + 2 * (frame_y + padded) + WINDOW_FIT_PADDING),
            )
        except (AttributeError, OSError):
            pass
    return 0, 0


def _log_error(error: Exception) -> None:
    """Write save/load failures to a small per-user error log.

    Save errors should not crash the game window. If the log itself cannot be
    written, the final ``except`` keeps that secondary failure invisible too.
    """

    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with (SAVE_DIR / "error.log").open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {error}\n")
    except OSError:
        pass


def _atomic_write(path: Path, payload: dict) -> None:
    """Write JSON through a temp file, then replace the real file.

    This pattern avoids half-written save files. If Windows or the app closes
    mid-write, the old file is still intact until ``os.replace`` succeeds.
    """

    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, path)
    except OSError as error:
        _log_error(error)


def _stat_count(value: Any, field: str) -> int:
    """Return one stats counter as an int, or 0 (logged) when it is malformed.

    A hand-edited or damaged stats file can hold anything JSON allows: null,
    text, a list, or a huge number that loads as infinity. Repairing the one
    bad field keeps every good counter instead of crashing the game-over
    screen.
    """

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        _log_error(ValueError(f"stats field {field!r} was {value!r}; reset to 0"))
        return 0


def load_stats() -> dict:
    """Read lifetime stats, filling in defaults and repairing malformed fields.

    Returns a dict with ``games``, ``human_wins``, ``ai_wins``,
    ``turn_total``, ``by_player_count`` (games per board size, keyed by
    the strings "4", "5" and "6", because JSON object keys are always
    strings) and ``sound`` (the player's sound on/off choice).

    A missing or unreadable file simply gives the all-zero defaults. Values
    read from the file are merged over the defaults, so older files that
    lack a field still work, and every counter is passed through
    ``_stat_count`` so one damaged value is reset to 0 instead of crashing
    the game-over screen. ``sound`` stays on unless the file holds a real
    JSON ``false``, so a damaged value can never silence the game.
    """

    defaults: dict[str, Any] = {
        "games": 0,
        "human_wins": 0,
        "ai_wins": 0,
        "turn_total": 0,
        "by_player_count": {"4": 0, "5": 0, "6": 0},
        "sound": True,
    }
    try:
        data = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        defaults.update(data)
        # Older stats files may not have every player-count bucket. Merge them
        # over a full default set so the game-over screen can index safely.
        counts = defaults.get("by_player_count")
        if not isinstance(counts, dict):
            counts = {}
        defaults["by_player_count"] = {**{"4": 0, "5": 0, "6": 0}, **counts}
    # RecursionError: a file nested thousands of levels deep ("[[[[...")
    # exhausts the JSON reader's recursion before it can report bad JSON.
    except (OSError, TypeError, ValueError, RecursionError, json.JSONDecodeError):
        pass
    for field in ("games", "human_wins", "ai_wins", "turn_total"):
        defaults[field] = _stat_count(defaults[field], field)
    buckets = defaults["by_player_count"]
    for key in buckets:
        buckets[key] = _stat_count(buckets[key], f"by_player_count[{key}]")
    defaults["sound"] = defaults["sound"] is not False
    return defaults


def save_stats(stats: dict) -> None:
    """Persist lifetime stats under ``%APPDATA%``.

    The write goes through ``_atomic_write``, so a failure is logged rather
    than raised.
    """

    _atomic_write(STATS_PATH, stats)


def save_game(game: LudoGame) -> None:
    """Persist the current game so it can be resumed later."""

    _atomic_write(SAVEGAME_PATH, game.to_dict())


def load_saved_game(*, persist: bool = True) -> LudoGame | None:
    """Load the saved game, returning ``None`` if there is no usable save.

    A missing file simply returns ``None``. A damaged file (bad JSON, wrong
    types, impossible values rejected by ``LudoGame.from_dict``) also
    returns ``None``, but it is first logged to ``error.log`` and renamed to
    ``savegame.bad.json``. That makes ``has_saved_game()`` false, so the
    Resume button greys out instead of silently failing on every click, and
    the file is kept for anyone who wants to inspect it (as in Monopoly).

    A file that cannot be read right now (for example, locked by a virus
    scanner or a sync tool) is only logged: its contents may be fine, so it
    stays where it is and Resume can be tried again.

    Beginner note: ``persist=False`` (used by autotests) still reads the
    save, but never writes anything: no log entry and no rename.
    """

    try:
        raw = SAVEGAME_PATH.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as error:
        if persist:
            _log_error(error)
        return None
    try:
        return LudoGame.from_dict(json.loads(raw.decode("utf-8")))
    # AttributeError covers a damaged entry of the wrong JSON type (a list
    # where a token object belongs). OverflowError covers huge numbers: JSON
    # reads 1e400 as float inf, and int(inf) raises OverflowError.
    # RecursionError covers a file nested thousands of levels deep.
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError,
            json.JSONDecodeError) as error:
        if persist:
            _log_error(error)
            with contextlib.suppress(OSError):
                os.replace(SAVEGAME_PATH, SAVEGAME_PATH.with_name("savegame.bad.json"))
        return None


def has_saved_game() -> bool:
    """Return True when a saved Ludo game exists on disk."""

    return SAVEGAME_PATH.exists()


def clear_saved_game() -> None:
    """Delete the in-progress save after a completed game."""

    with contextlib.suppress(OSError):
        SAVEGAME_PATH.unlink(missing_ok=True)


class LudoApp:
    """Owns screens, input routing, the game loop, and the AI timer.

    ``LudoGame`` owns the rules. ``LudoApp`` owns everything a player sees or
    clicks: setup controls, keyboard shortcuts, drawing order, save/load calls,
    and the paced AI loop.

    Key attributes:
        screen: ``"setup"``, ``"playing"`` or ``"over"``; decides what is
            drawn and which buttons exist.
        game / renderer: The active ``LudoGame`` and its ``BoardRenderer``,
            or ``None`` before the first game starts.
        window: The fixed-size logical canvas everything is drawn on;
            ``screen_surface`` is the real (possibly smaller) OS window.
        visible_moves: The human player's legal moves for the current roll,
            shared by highlights, move buttons, number keys and clicks.
        total_players, human_count, ai_profile_index, rule_*: The setup
            screen's current choices.
        token_pixels / token_steps / token_waypoints / token_hops: Pawn
            animation state (see ``_update_token_pixels``).
        sounds: The ``audio.SoundBank`` of effects (silent without a mixer).
        music: The ``audio.MusicPlayer`` looping the folk tune.
        ai_timer: Milliseconds since the last AI action, used to pace AI turns.
        stats: Lifetime stats loaded from disk, plus the ``"sound"`` setting.
    """

    def __init__(self, persist: bool = True) -> None:
        """Create the pygame window and initialize screen-level state.

        ``persist=False`` makes the app read saves but never write or delete
        the savegame or stats files. The hidden autotest uses it so a quick
        self-check can never disturb a player's real progress.
        """

        self.persist = persist
        self.window_size = _fit_window_size(_desktop_work_area_size(), _window_chrome_size())
        self.screen_surface = pygame.display.set_mode(self.window_size)
        pygame.display.set_caption(WINDOW_TITLE)
        pygame.display.set_icon(_load_icon())
        # The logical canvas. ``convert()`` stores it in the window's pixel
        # format, which makes copying it to the screen each frame faster.
        self.window = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT)).convert()
        self.clock = pygame.time.Clock()
        self.fonts = ui.make_fonts()
        self.running = True
        # Every effect is synthesised once here from the recipes in settings.
        self.sounds = audio.SoundBank(SFX_RECIPES, SFX_COOLDOWNS)
        # The tune renders in a background thread; it starts playing on the
        # first frame after it is ready (``music.update`` in ``_update``).
        self.music = audio.MusicPlayer(music_notes, MUSIC_LOOP_SECONDS, MUSIC_VOLUME)
        self.music.start(MUSIC_FADE_IN_MS)

        self.screen = "setup"
        self.game: LudoGame | None = None
        self.renderer: BoardRenderer | None = None
        self.buttons: list[ui.Button] = []
        # ``visible_moves`` is rebuilt each frame for human turns. Click
        # handling uses it so only currently highlighted tokens are clickable.
        self.visible_moves: list[Move] = []

        self.total_players = 4
        self.human_count = 1
        self.name_fields = ["Player 1", "Player 2", "Player 3", "Player 4", "Player 5", "Player 6"]
        self.active_field: int | None = None
        self.ai_profiles = tuple(ai.AI_PROFILES)
        self.ai_profile_index = self.ai_profiles.index("tactical")
        self.rule_blockades = False
        self.rule_capture_bonus = True
        self.rule_home_bonus = True
        self.rule_three_sixes = True

        self.stats = load_stats()
        # A saved "sound": false silences the bank and the music from the first frame.
        self._apply_sound_setting()
        self.stats_recorded = False
        self.ai_timer = 0
        self.dice_anim_remaining = 0
        # Animation state per (player_index, token_index): the drawn pixel,
        # the engine steps it reflects, and the queue of cells still to hop.
        self.token_pixels: dict[tuple[int, int], tuple[float, float]] = {}
        self.token_steps: dict[tuple[int, int], int] = {}
        self.token_waypoints: dict[tuple[int, int], list[tuple[float, float]]] = {}
        # Per token, the pitch step of its next hop sound, or None while it
        # is sliding (to or from the yard) rather than hopping.
        self.token_hops: dict[tuple[int, int], int | None] = {}
        self.preview_cache: dict[int, pygame.Surface] = {}
        self.message = "Choose a table and start the race."
        self.saved_turns_taken: int | None = None

    @property
    def sound_on(self) -> bool:
        """True unless the player has switched sound off (Ctrl+M or a Sound button)."""

        return bool(self.stats.get("sound", True))

    def _toggle_sound(self) -> None:
        """Switch all sound off or back on, and remember the choice in stats.json.

        Muting stops the music at once and blocks every effect; unmuting
        resumes the music and plays a click so the player hears it worked. A
        non-persisting app (the autotest) only changes the setting in memory,
        so a smoke test never overwrites the player's real stats file.

        The choice is stored as ``"sound"`` in the lifetime stats file rather
        than in the savegame, so it applies to every game and survives
        starting a new one. The shortcut is Ctrl+M rather than plain M
        because M must still type into the setup screen's name fields.
        """

        self.stats["sound"] = not self.sound_on
        self._apply_sound_setting()
        if self.persist:
            save_stats(self.stats)
        if self.sound_on:
            self.sounds.play("click")

    def _apply_sound_setting(self) -> None:
        """Pass the sound setting to the effects bank and the music player."""

        self.sounds.muted = not self.sound_on
        self.music.set_muted(not self.sound_on)

    def setup_buttons(self) -> list[ui.Button]:
        """Build fresh button objects for the setup screen.

        The list is rebuilt every frame instead of being stored, so toggle
        labels ("Blockades: On") and the Resume button's enabled state always
        reflect the current choices and whether a save file exists.

        It contains the -/+ steppers for total and human players, the </>
        stepper for the AI profile, the four house-rule toggles, Start Game,
        Resume Saved Game (disabled without a save), Quit and the Sound
        toggle under it. Each button's
        ``key`` is handled by ``_on_setup_button``.
        """

        total_row = _setup_option_row(0)
        human_row = _setup_option_row(1)
        ai_row = _setup_option_row(2)
        x = SETUP_CONTROL_X

        def toggle_rect(index: int) -> pygame.Rect:
            """Return the rectangle of house-rule toggle ``index`` (0 to 3)."""

            y = SETUP_TOGGLE_START_Y + index * SETUP_TOGGLE_STEP
            return pygame.Rect(x, y, SETUP_CONTROL_WIDTH, SETUP_TOGGLE_HEIGHT)

        return [
            ui.Button(total_row.left_button, "-", "total_players_prev"),
            ui.Button(total_row.right_button, "+", "total_players_next"),
            ui.Button(human_row.left_button, "-", "human_count_prev"),
            ui.Button(human_row.right_button, "+", "human_count_next"),
            ui.Button(ai_row.left_button, "<", "ai_profile_prev"),
            ui.Button(ai_row.right_button, ">", "ai_profile_next"),
            ui.Button(toggle_rect(0), _toggle_label("Blockades", self.rule_blockades), "toggle_blockades"),
            ui.Button(toggle_rect(1), _toggle_label("Capture bonus", self.rule_capture_bonus), "toggle_capture_bonus"),
            ui.Button(toggle_rect(2), _toggle_label("Home bonus", self.rule_home_bonus), "toggle_home_bonus"),
            ui.Button(toggle_rect(3), _toggle_label("Three 6s", self.rule_three_sixes), "toggle_three_sixes"),
            ui.Button(
                pygame.Rect(x, SETUP_START_Y, SETUP_CONTROL_WIDTH, SETUP_ACTION_HEIGHT),
                "Start Game",
                "start",
            ),
            ui.Button(
                pygame.Rect(x, SETUP_RESUME_Y, SETUP_CONTROL_WIDTH, SETUP_ACTION_HEIGHT),
                "Resume Saved Game",
                "resume",
                enabled=has_saved_game(),
            ),
            ui.Button(pygame.Rect(SCREEN_WIDTH - 132, 24, 100, 36), "Quit", "quit"),
            ui.Button(SETUP_SOUND_RECT, _toggle_label("Sound", self.sound_on), "toggle_sound"),
        ]

    def run(self, max_frames: int | None = None) -> None:
        """Run the event loop until the app quits or a test frame limit hits.

        Beginner note: a game loop repeats the same four steps about ``FPS``
        times a second: handle input events, update the state (timers, AI,
        animation), draw the next picture off-screen, then ``flip`` it onto
        the display. ``clock.tick(FPS)`` sleeps just long enough to keep that
        pace and remembers how long the frame took.

        ``max_frames`` is set only by the autotest. It also switches on
        autotest mode, in which the AI acts every frame without its delay.
        """

        frames = 0
        autotest = max_frames is not None
        while self.running:
            self.clock.tick(FPS)
            for event in pygame.event.get():
                # Pygame delivers every input event through this queue. The app
                # translates those low-level events into game actions below.
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self._handle_click(self._window_to_logical(event.pos))
                elif event.type == pygame.KEYDOWN:
                    self._handle_key(event)

            self._update(autotest)
            self._draw()
            self._present()
            pygame.display.flip()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                break

    def _present(self) -> None:
        """Scale the logical canvas onto the actual OS window.

        When the window is full size the canvas is copied as-is; otherwise
        ``smoothscale`` shrinks it with filtering so text stays readable.
        """

        if self.window_size == (SCREEN_WIDTH, SCREEN_HEIGHT):
            self.screen_surface.blit(self.window, (0, 0))
        else:
            pygame.transform.smoothscale(self.window, self.window_size, self.screen_surface)

    def _logical_mouse_pos(self) -> tuple[int, int]:
        """Return mouse position in the same coordinates used by buttons."""

        return self._window_to_logical(pygame.mouse.get_pos())

    def _window_to_logical(self, pos: tuple[int, int]) -> tuple[int, int]:
        """Convert a real-window coordinate into the fixed logical layout."""

        return _window_to_logical_point(pos, self.window_size)

    def start_game(self, game: LudoGame) -> None:
        """Switch from setup into a playable game.

        Used both for new games and for resumed saves. It builds the matching
        renderer, clears all animation and AI timers (so pawns snap to their
        cells on the first frame), and remembers the current turn count so
        the next autosave fires only after a turn really ends.
        """

        self.game = game
        self.renderer = BoardRenderer(game.layout)
        self.screen = "playing"
        self.active_field = None
        self.stats_recorded = False
        self.ai_timer = 0
        self.dice_anim_remaining = 0
        self.token_pixels = {}
        self.token_steps = {}
        self.token_waypoints = {}
        self.token_hops = {}
        self.saved_turns_taken = game.turns_taken
        self.message = "Roll a 6 to bring a token out."

    def _handle_click(self, pos: tuple[int, int]) -> None:
        """Route one left-click to name fields, tokens, or buttons.

        ``pos`` is already in logical canvas coordinates. The checks run in
        priority order and the first match wins:

        1. On the setup screen, a click in a human name field focuses it for
           typing; a click anywhere else removes that focus.
        2. Any enabled button under the click runs its action.
        3. During a human player's move choice, a click near a highlighted
           pawn applies that pawn's move (``BoardRenderer.move_at_pos``).
        """

        if self.screen == "setup":
            for index in range(self.human_count):
                if _name_rect(index).collidepoint(pos):
                    self.active_field = index
                    return
            self.active_field = None

        # Buttons win over tokens: a click inside a button always runs that
        # button, even if a token's generous hit circle reaches under it.
        for button in self._buttons_for_screen():
            if button.contains(pos):
                self.sounds.play("click")
                self._on_button(button.key)
                return

        if (
            self.screen == "playing"
            and self.game
            and self.renderer
            and self.game.current_player.is_human
            and self.game.awaiting == "choose_move"
        ):
            # Human token clicks are only accepted when the engine is
            # waiting for a move after a roll.
            move = self.renderer.move_at_pos(pos, self.visible_moves, self.game)
            if move is not None:
                self._apply_move(move)

    def _handle_key(self, event: pygame.event.Event) -> None:
        """Route keyboard shortcuts for setup typing and human turns.

        Ctrl+M switches sound off and on, on every screen (even while a
        name field has focus, so plain M still types). Escape saves and
        returns to setup during a game, and quits from any other screen.
        While a setup name field has focus, keys type into it. On a human
        turn, R rolls and 1-4 pick the matching move button.
        """

        if event.key == pygame.K_m and event.mod & pygame.KMOD_CTRL:
            self._toggle_sound()
            return
        if event.key == pygame.K_ESCAPE:
            if self.screen == "playing" and self.game:
                self._save_game()
                self.screen = "setup"
            else:
                self.running = False
            return
        if self.screen == "setup" and self.active_field is not None:
            self._type_name(event)
            return
        if self.screen == "playing" and self.game and self.game.current_player.is_human:
            if event.key == pygame.K_r and self.game.awaiting == "pre_roll":
                self._roll_for_human()
            elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4) and self.game.awaiting == "choose_move":
                index = event.key - pygame.K_1
                if 0 <= index < len(self.visible_moves):
                    self._apply_move(self.visible_moves[index])

    def _type_name(self, event: pygame.event.Event) -> None:
        """Edit the active setup-screen name field.

        Backspace deletes a character, Enter or Tab moves focus to the next
        human's field (wrapping around), and any printable character is
        added if the name would still fit inside its field.
        """

        index = self.active_field
        if index is None:
            return
        if event.key == pygame.K_BACKSPACE:
            self.name_fields[index] = self.name_fields[index][:-1]
        elif event.key in (pygame.K_RETURN, pygame.K_TAB):
            self.active_field = (index + 1) % max(1, self.human_count)
        elif event.unicode and event.unicode.isprintable():
            # Measure the rendered name, not its length: ten "W"s are far
            # wider than ten "i"s, and only pixels decide whether it fits.
            candidate = self.name_fields[index] + event.unicode
            if self.fonts["body"].size(candidate)[0] <= SETUP_CONTROL_WIDTH - 2 * SETUP_NAME_TEXT_PADDING:
                self.name_fields[index] = candidate

    def _on_button(self, key: str) -> None:
        """Dispatch a clicked button key to the active screen.

        The Sound toggle works the same on every screen, so it is handled
        here first.
        """

        if key == "toggle_sound":
            self._toggle_sound()
        elif self.screen == "setup":
            self._on_setup_button(key)
        elif self.screen == "playing":
            self._on_play_button(key)
        elif self.screen == "over":
            if key == "new_game":
                self.screen = "setup"
                self.music.start(MUSIC_FADE_IN_MS)
            elif key == "quit":
                self.running = False

    def _on_setup_button(self, key: str) -> None:
        """Handle all setup-screen controls.

        Steppers are clamped rather than wrapped: total players stays within
        ``MIN_PLAYERS``..``MAX_PLAYERS`` and human players within 1..total.
        Lowering the total also lowers the human count if needed, so there
        are never more humans than seats. The AI profile selector does wrap
        around its list. Toggles flip one house rule. ``"resume"`` loads the
        save (staying on setup if it is unusable) and ``"start"`` builds a
        new game from the current choices.
        """

        if key == "total_players_prev":
            self.total_players = max(MIN_PLAYERS, self.total_players - 1)
            self.human_count = min(self.human_count, self.total_players)
        elif key == "total_players_next":
            self.total_players = min(MAX_PLAYERS, self.total_players + 1)
        elif key == "human_count_prev":
            self.human_count = max(1, self.human_count - 1)
        elif key == "human_count_next":
            self.human_count = min(self.total_players, self.human_count + 1)
        elif key == "ai_profile_prev":
            self.ai_profile_index = (self.ai_profile_index - 1) % len(self.ai_profiles)
        elif key == "ai_profile_next":
            self.ai_profile_index = (self.ai_profile_index + 1) % len(self.ai_profiles)
        elif key == "toggle_blockades":
            self.rule_blockades = not self.rule_blockades
        elif key == "toggle_capture_bonus":
            self.rule_capture_bonus = not self.rule_capture_bonus
        elif key == "toggle_home_bonus":
            self.rule_home_bonus = not self.rule_home_bonus
        elif key == "toggle_three_sixes":
            self.rule_three_sixes = not self.rule_three_sixes
        elif key == "resume":
            # Invalid or missing saves simply keep the player on setup.
            saved = load_saved_game(persist=self.persist)
            if saved is not None:
                self.start_game(saved)
        elif key == "start":
            self._start_new_game()
        elif key == "quit":
            self.running = False

    def _on_play_button(self, key: str) -> None:
        """Handle buttons shown during an active game.

        ``"move_<n>"`` keys carry the index into ``visible_moves`` after the
        underscore. Save saves and returns to setup; New returns to setup
        without saving (the last autosave stays on disk).
        """

        if self.game is None:
            return
        if key == "roll":
            self._roll_for_human()
        elif key.startswith("move_"):
            index = int(key.split("_", 1)[1])
            if 0 <= index < len(self.visible_moves):
                self._apply_move(self.visible_moves[index])
        elif key == "save_quit":
            self._save_game()
            self.screen = "setup"
        elif key == "new_game":
            self.screen = "setup"

    def _start_new_game(self) -> None:
        """Create a new rules engine from the setup-screen choices.

        The first ``human_count`` seats are humans (a blank name falls back to
        "Player N"); the rest are AI seats named after their colour. The new
        game is saved straight away so it can be resumed even before the
        first turn ends.
        """

        rules = LudoRules(
            total_players=self.total_players,
            blockades=self.rule_blockades,
            bonus_on_capture=self.rule_capture_bonus,
            bonus_on_home=self.rule_home_bonus,
            three_sixes_penalty=self.rule_three_sixes,
        )
        players: list[tuple[str, bool]] = []
        ai_number = 1
        for index in range(self.total_players):
            if index < self.human_count:
                name = self.name_fields[index].strip() or f"Player {index + 1}"
                players.append((name, True))
            else:
                # AI names include the color so players can map the sidebar to
                # the matching yard on the board.
                players.append((f"AI {ai_number} ({seat_name(self.total_players, index)})", False))
                ai_number += 1
        game = LudoGame(players, rules, ai_profile=self.ai_profiles[self.ai_profile_index])
        self.start_game(game)
        self._save_game()

    def _roll_for_human(self) -> None:
        """Roll for the current human player and handle no-move rolls.

        Starts the short dice animation. If the roll leaves no legal move,
        the engine is told at once (``note_no_move``) so the turn passes (or a
        6 grants another roll) without the player having to click anything.
        """

        if self.game is None or self.game.awaiting != "pre_roll":
            return
        die = self.game.roll_die()
        self.dice_anim_remaining = DICE_ANIM_MS
        # A forfeited third 6 has already passed the turn (awaiting is back to
        # pre_roll), so only a roll that is waiting for a move can be a no-move.
        if self.game.awaiting == "choose_move" and not self.game.legal_moves(die):
            self.game.note_no_move(die)
        self._refresh_visible_moves()
        self._save_if_turn_completed()

    def _apply_move(self, move) -> None:
        """Apply a selected move and surface the result message.

        ``move`` must come from the engine's current legal moves (the visible
        move list), otherwise ``LudoGame.apply_move`` raises ``ValueError``.
        """

        if self.game is None:
            return
        result = self.game.apply_move(move)
        self.message = result.message
        self._refresh_visible_moves()
        self._save_if_turn_completed()

    def _refresh_visible_moves(self) -> None:
        """Rebuild the clickable move list from the engine's current state.

        Beginner note: several key presses can arrive in one frame, before the
        next redraw. Rebuilding the list after every roll or move means key 2
        always refers to the CURRENT roll's second move, never a leftover one
        from the roll before.
        """

        self.visible_moves = []
        if self.game is None or self.game.last_roll is None:
            return
        if self.game.current_player.is_human and self.game.awaiting == "choose_move":
            self.visible_moves = self.game.legal_moves(self.game.last_roll)

    def _update(self, autotest: bool) -> None:
        """Advance animations, sounds, game-over bookkeeping, and AI turns.

        Called once per frame. In order it: lets the music player start the
        tune once it has rendered, counts down the dice animation,
        moves pawns along their hop paths, plays the sounds for everything
        the engine reported since the last frame, switches to the game-over screen
        (recording stats once) when the engine says the game ended, and, if
        an AI seat is to play, waits ``AI_TURN_DELAY_MS`` between AI actions
        so humans can follow them. One AI action is a roll plus, when
        possible, the chosen move. ``autotest`` skips the delay.

        ``clock.get_time()`` is the length of the last frame in
        milliseconds, so timers count real time whatever the frame rate.
        """

        self.music.update()
        elapsed = self.clock.get_time()
        if self.dice_anim_remaining > 0:
            self.dice_anim_remaining = max(0, self.dice_anim_remaining - elapsed)
        self._update_token_pixels(elapsed)
        # Events are played before the game-over check below, so the winning
        # move's own sounds (its token reaching home) are heard before the jingle.
        if self.game is not None:
            self._play_event_sounds()

        if self.screen != "playing" or self.game is None:
            return
        if self.game.phase == "game_over":
            # Stats are recorded here instead of inside the engine because
            # stats are app persistence, not core Ludo rules.
            self._record_finished_game_once()
            self._play_game_over_jingle()
            self.screen = "over"
            return
        if self.game.current_player.is_human:
            return

        self.ai_timer += elapsed
        if not autotest and self.ai_timer < AI_TURN_DELAY_MS:
            return
        self.ai_timer = 0
        self._perform_ai_step()
        self._refresh_visible_moves()
        self._save_if_turn_completed()

    def _play_event_sounds(self) -> None:
        """Drain the engine's event queue and play each event's effect.

        Draining once per frame means every event is heard exactly once,
        whether a human click or an AI step caused it.
        """

        assert self.game is not None
        kinds = self.game.drain_events()
        human_to_play = self.game.current_player.is_human
        for name, step in event_sounds(kinds, self.game.last_roll, human_to_play):
            self.sounds.play(name, pitch_step=step)

    def _play_game_over_jingle(self) -> None:
        """Fade the music out and play the win or lose jingle for the finished game.

        The win jingle plays when a human won, and also when no human played
        at all (an all-AI table); a computer beating the humans gets the
        gentle lose jingle.
        """

        assert self.game is not None and self.game.winner is not None
        self.music.stop(MUSIC_GAME_OVER_FADE_MS)
        humans = [player for player in self.game.players if player.is_human]
        won = not humans or self.game.players[self.game.winner].is_human
        self.sounds.play("win" if won else "lose")

    def _perform_ai_step(self) -> None:
        """Let the current AI player roll or choose one move.

        When the AI is waiting to roll, it rolls and then, in the same call,
        picks a move with ``ai.choose_move`` (or reports that no move
        exists). When it is already waiting for a move, only the move is
        made.
        """

        if self.game is None:
            return
        if self.game.awaiting == "pre_roll":
            # A forfeited third 6 passes the turn, so the move step below is
            # skipped because the engine is no longer awaiting a move.
            self.game.roll_die()
            self.dice_anim_remaining = DICE_ANIM_MS
        if self.game.awaiting == "choose_move" and self.game.last_roll is not None:
            move = ai.choose_move(self.game, self.game.ai_profile, self.game.last_roll)
            if move is None:
                self.game.note_no_move(self.game.last_roll)
            else:
                result = self.game.apply_move(move)
                self.message = result.message

    def _token_position(self, player_index: int, steps: int, token_index: int) -> tuple[float, float]:
        """Return the drawn coordinate for a token's step value.

        The renderer may display a friendlier board shape than the engine's
        raw coordinate grid, so animation targets come from the renderer when
        one is active.
        """

        if self.renderer is not None:
            return self.renderer.position_for(player_index, steps, token_index)
        assert self.game is not None
        return self.game.layout.position_for(player_index, steps, token_index)

    def _token_waypoints(
        self, player_index: int, token_index: int, old_steps: int, new_steps: int
    ) -> list[tuple[float, float]]:
        """Return the cells a token visibly travels through for one move.

        Forward moves hop through every intermediate cell like a real Ludo
        token counting its die roll. Captures (back to the yard) and yard
        exits are single direct slides, matching how players physically pick
        the token up and place it.
        """

        if 0 <= old_steps < new_steps:
            return [
                self._token_position(player_index, steps, token_index)
                for steps in range(old_steps + 1, new_steps + 1)
            ]
        return [self._token_position(player_index, new_steps, token_index)]

    def _update_token_pixels(self, elapsed_ms: int) -> None:
        """Advance drawn token positions along their pending waypoints.

        The engine moves tokens instantly; this method only eases the drawn
        pixels toward the engine's truth. For every token it:

        1. Snaps the token straight onto its cell the first time it is seen.
        2. Notices when the engine's step count changed since last frame and
           queues the cells to hop through (``_token_waypoints``).
        3. Moves the pixel along that queue by ``TOKEN_HOP_SPEED`` pixels per
           second, using the time ``elapsed_ms`` since the last frame.
        4. With nothing queued, glides any leftover gap to the token's cell.

        Each cell reached on a forward move taps a hop sound one step higher
        than the last, so the player hears the count. Slides into or out of
        the yard are silent here: leaving the yard and being captured have
        their own event sounds.

        Beginner note: moving a fixed *distance budget* per frame (speed
        times elapsed time) rather than a fixed number of pixels keeps the
        animation the same speed on fast and slow computers.
        """

        if self.game is None:
            return
        budget = TOKEN_HOP_SPEED * elapsed_ms / 1000
        for player_index, player in enumerate(self.game.players):
            for token_index, token in enumerate(player.tokens):
                key = (player_index, token_index)
                target = self._token_position(player_index, token.steps, token_index)
                if key not in self.token_pixels:
                    # First frame: snap tokens into place so they do not glide
                    # in from the top-left corner of the window.
                    self.token_pixels[key] = target
                    self.token_steps[key] = token.steps
                    self.token_waypoints[key] = []
                    continue
                if token.steps != self.token_steps.get(key):
                    old_steps = self.token_steps.get(key, -1)
                    self.token_waypoints[key] = self._token_waypoints(
                        player_index, token_index, old_steps, token.steps
                    )
                    # Only a forward move between board cells hops (counting from
                    # pitch step 0). Leaving the yard (old steps -1) and being
                    # captured (new steps -1) are silent slides.
                    self.token_hops[key] = 0 if 0 <= old_steps < token.steps else None
                    self.token_steps[key] = token.steps

                # Walk the waypoint queue at constant speed. One frame may
                # consume several waypoints when the frame rate dips.
                current = self.token_pixels[key]
                queue = self.token_waypoints.setdefault(key, [])
                remaining = budget
                while queue and remaining > 0:
                    head = queue[0]
                    dx = head[0] - current[0]
                    dy = head[1] - current[1]
                    length = math.hypot(dx, dy)
                    if length <= remaining:
                        current = head
                        queue.pop(0)
                        remaining -= length
                        self._play_hop(key)
                    else:
                        # Not enough budget left to reach the next cell: move
                        # part of the way along the unit vector (dx, dy) / length.
                        current = (current[0] + dx / length * remaining, current[1] + dy / length * remaining)
                        remaining = 0
                if not queue and current != target and remaining > 0:
                    # No pending hops: keep the token glued to its cell (this
                    # also covers loading a save or renderer changes).
                    dx = target[0] - current[0]
                    dy = target[1] - current[1]
                    length = math.hypot(dx, dy)
                    current = target if length <= remaining else (
                        current[0] + dx / length * remaining,
                        current[1] + dy / length * remaining,
                    )
                self.token_pixels[key] = current

    def _play_hop(self, key: tuple[int, int]) -> None:
        """Tap the hop sound for a token that just reached a cell, one step higher each time.

        Hops only sound on the play screen: the winning move ends the game at
        once, and its token may still be easing home on the game-over screen,
        where its taps would step on the win jingle (likewise after Save or
        New sends the player back to setup mid-hop).
        """

        step = self.token_hops.get(key)
        if step is not None and self.screen == "playing":
            self.sounds.play("hop", pitch_step=step)
            self.token_hops[key] = step + 1

    def _save_if_turn_completed(self) -> None:
        """Autosave after completed turns, not after every animation frame.

        ``turns_taken`` only grows when the turn passes to another player, so
        comparing it with the value at the last save writes at most once per
        turn. Finished games are not saved; their save file is deleted by
        ``_record_finished_game_once`` instead.
        """

        if self.game is None or self.game.phase == "game_over":
            return
        if self.saved_turns_taken != self.game.turns_taken:
            self.saved_turns_taken = self.game.turns_taken
            self._save_game()

    def _save_game(self) -> None:
        """Write the current game to disk, unless this app must not persist."""

        if self.persist and self.game is not None:
            save_game(self.game)

    def _record_finished_game_once(self) -> None:
        """Add the finished game to lifetime stats exactly once.

        Counts the game, a human or AI win, the turns taken and the board
        size, then (when persisting) writes the stats and deletes the save,
        since a finished game cannot be resumed. ``stats_recorded`` guards
        against counting the same game twice.
        """

        if self.stats_recorded or self.game is None or self.game.winner is None:
            return
        self.stats_recorded = True
        winner = self.game.players[self.game.winner]
        self.stats["games"] = int(self.stats.get("games", 0)) + 1
        if winner.is_human:
            self.stats["human_wins"] = int(self.stats.get("human_wins", 0)) + 1
        else:
            self.stats["ai_wins"] = int(self.stats.get("ai_wins", 0)) + 1
        self.stats["turn_total"] = int(self.stats.get("turn_total", 0)) + self.game.turns_taken
        key = str(self.game.rules.total_players)
        self.stats.setdefault("by_player_count", {"4": 0, "5": 0, "6": 0})
        self.stats["by_player_count"][key] = int(self.stats["by_player_count"].get(key, 0)) + 1
        # Stats still count in memory for the game-over card; only the disk
        # writes are skipped for a non-persisting app (the autotest).
        if self.persist:
            save_stats(self.stats)
            clear_saved_game()

    def _draw(self) -> None:
        """Clear the window and draw whichever screen is active."""

        theme.draw_ludo_wallpaper(self.window)
        if self.screen == "setup":
            self._draw_setup()
        elif self.screen == "playing":
            self._draw_playing()
        else:
            self._draw_game_over()

    def _draw_setup(self) -> None:
        """Draw the setup screen, including preview boards and controls.

        The left side shows the "LUDO" title, the intro text on a
        see-through plate, and the three board previews with the current
        choice outlined in gold. The right-hand panel shows the option rows
        with their values, the "Advanced Rules" and "Human Names" headers,
        one name field per human (the focused one outlined in its seat
        colour), and finally all setup buttons, drawn last so they sit on
        top. The button list is rebuilt here so it matches what is drawn.
        """

        self.buttons = self.setup_buttons()
        mouse = self._logical_mouse_pos()
        # The setup screen shares the new wallpaper so the menu feels like the
        # same game as the redesigned board instead of a separate utility page.
        ui.draw_text(self.window, self.fonts["huge"], "LUDO", SETUP_TITLE_CENTER, WHITE, center=True)
        plate, lines = self._setup_intro_layout()
        plate_color = (*theme.HUD_DARK, SETUP_INTRO_PLATE_ALPHA)
        theme.draw_translucent_rect(self.window, plate, SETUP_INTRO_RADIUS, plate_color)
        font = self.fonts["body"]
        for index, line in enumerate(lines):
            y = plate.y + SETUP_INTRO_PADDING[1] + index * (font.get_height() + SETUP_INTRO_LINE_GAP)
            ui.draw_text(self.window, font, line, (plate.centerx - font.size(line)[0] // 2, y), SETUP_INTRO_COLOR)
        self._draw_board_previews()

        theme.draw_shadowed_rect(self.window, SETUP_PANEL_RECT, PANEL_BG, border=PANEL_EDGE, radius=16)
        ui.draw_text(self.window, self.fonts["title"], "Setup", (PANEL_X + 24, 42), WHITE)
        self._setup_value("Total Players", str(self.total_players), 0)
        self._setup_value("Human Players", str(self.human_count), 1)
        self._setup_value("AI Profile", self.ai_profiles[self.ai_profile_index].title(), 2)

        rules_header = (SETUP_CONTROL_X, SETUP_RULES_HEADER_Y)
        ui.draw_text(self.window, self.fonts["header"], "Advanced Rules", rules_header, WHITE)
        ui.draw_text(self.window, self.fonts["header"], "Human Names", (SETUP_CONTROL_X, SETUP_NAME_HEADER_Y), WHITE)
        for index in range(self.human_count):
            # Name fields are lightweight hand-drawn rectangles. The active
            # one gets a colored border so typing focus is visible.
            rect = _name_rect(index)
            color = seat_colors(self.total_players)[index]
            pygame.draw.rect(self.window, PANEL_CARD, rect, border_radius=6)
            pygame.draw.rect(self.window, color if self.active_field == index else PANEL_EDGE, rect, 2, border_radius=6)
            text_pos = (rect.x + SETUP_NAME_TEXT_PADDING, rect.y + 4)
            ui.draw_text(self.window, self.fonts["body"], self.name_fields[index], text_pos, WHITE)

        for button in self.buttons:
            button.draw(self.window, self.fonts, mouse)

    def _setup_intro_layout(self) -> tuple[pygame.Rect, list[str]]:
        """Return the intro plate rect and the wrapped intro lines it holds.

        The plate is measured from this platform's font, so it always fits
        exactly the lines drawn on it, centred under the title.
        """

        font = self.fonts["body"]
        lines = ui.wrap_lines(font, SETUP_INTRO_TEXT, SETUP_INTRO_WIDTH)
        text_width = max(font.size(line)[0] for line in lines)
        text_height = len(lines) * font.get_height() + (len(lines) - 1) * SETUP_INTRO_LINE_GAP
        pad_x, pad_y = SETUP_INTRO_PADDING
        plate = pygame.Rect(0, 0, text_width + 2 * pad_x, text_height + 2 * pad_y)
        plate.midtop = (SETUP_TITLE_CENTER[0], SETUP_INTRO_TOP - pad_y)
        return plate, lines

    def _setup_value(self, label: str, value: str, row_index: int) -> None:
        """Draw one setup label plus its centered current value."""

        row = _setup_option_row(row_index)
        ui.draw_text(self.window, self.fonts["body"], label, (SETUP_CONTROL_X, row.label_y), SOFT)
        ui.draw_text(self.window, self.fonts["header"], value, row.value_center, WHITE, center=True)

    def _board_preview(self, total_players: int) -> pygame.Surface:
        """Return a cached true-to-life thumbnail of one board shape.

        Beginner note: ``subsurface`` is a window onto part of a surface that
        shares its pixels; ``copy()`` makes it an independent image before it
        is scaled down to ``PREVIEW_SIZE``.
        """

        cached = self.preview_cache.get(total_players)
        if cached is None:
            # Render the real board once at full logical size, then crop the
            # board area and shrink it. The preview is therefore always an
            # honest picture of the layout the player is about to get.
            canvas = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
            theme.draw_ludo_wallpaper(canvas)
            renderer = BoardRenderer(BoardLayout.for_player_count(total_players))
            renderer.draw_static(canvas)
            crop = pygame.Rect(120, 90, 660, 660) if total_players == 4 else pygame.Rect(95, 55, 710, 710)
            board = canvas.subsurface(crop).copy()
            cached = pygame.transform.smoothscale(board, (PREVIEW_SIZE, PREVIEW_SIZE))
            self.preview_cache[total_players] = cached
        return cached

    def _draw_board_previews(self) -> None:
        """Draw the 4P/5P/6P board thumbnails, highlighting the selection."""

        for count, center in zip((4, 5, 6), PREVIEW_CENTERS, strict=True):
            thumb = self._board_preview(count)
            rect = thumb.get_rect(center=center)
            self.window.blit(thumb, rect)
            selected = count == self.total_players
            border = GOLD if selected else PANEL_EDGE
            pygame.draw.rect(self.window, border, rect.inflate(10, 10), 4 if selected else 2, border_radius=10)
            ui.draw_text(
                self.window,
                self.fonts["small"],
                f"{count} Players",
                (rect.centerx, rect.bottom + 18),
                WHITE if selected else SOFT,
                center=True,
            )

    def _draw_playing(self) -> None:
        """Draw the board, themed HUD, action buttons, and legal highlights."""

        if self.game is None or self.renderer is None:
            return
        # Recompute visible moves before drawing so the highlights and click
        # targets always match the latest engine state.
        self._refresh_visible_moves()
        self.renderer.draw(self.window, self.game, self.fonts, self.visible_moves, self.token_pixels)

        self._draw_world_hud()
        self.buttons = self._buttons_for_screen()
        mouse = self._logical_mouse_pos()
        for button in self.buttons:
            self._draw_play_button(button, mouse)

    def _draw_world_hud(self) -> None:
        """Draw compact gameplay controls over the wallpaper, not in a sidebar.

        This covers the dice tray at the bottom (die, current player's
        banner, and a one-line prompt), the player roster on the right, and
        the "Table Log" card with the newest four engine messages, each
        coloured by ``ui.status_color`` and shortened to fit. While the dice
        animation runs, the die shows a changing face instead of the roll.
        """

        if self.game is None:
            return
        current = self.game.current_player
        die_value = self.game.last_roll
        if self.dice_anim_remaining > 0:
            # Change face every 70 ms while the roll animation runs; this is
            # cosmetic only, the real roll is already in ``last_roll``.
            die_value = ((pygame.time.get_ticks() // 70) % 6) + 1

        # A single lower tray carries the current player and die, similar to a
        # physical board-game table where the dice sit beside the board.
        tray = PLAY_DICE_TRAY_RECT
        theme.draw_dice_tray(self.window, tray, die_value, self.fonts, accent=current.color)
        theme.draw_player_banner(self.window, PLAY_TRAY_BANNER_RECT, current.color, current.name, self.fonts)

        ui.draw_wrapped(
            self.window,
            self.fonts["small"],
            self._turn_prompt(),
            PLAY_PROMPT_RECT,
            WHITE,
            line_gap=PLAY_PROMPT_LINE_GAP,
        )

        self._draw_player_roster()
        log_panel = PLAY_LOG_RECT
        text_x = log_panel.x + PLAY_LOG_PADDING
        text_width = log_panel.width - 2 * PLAY_LOG_PADDING
        theme.draw_shadowed_rect(self.window, log_panel, theme.HUD_DARK, border=PANEL_EDGE, radius=12)
        ui.draw_text(self.window, self.fonts["small"], "Table Log", (text_x, log_panel.y + 10), WHITE)
        y = log_panel.y + 38
        for line in self.game.event_log[-4:]:
            text = ui.ellipsize(self.fonts["tiny"], line, text_width)
            ui.draw_text(self.window, self.fonts["tiny"], text, (text_x, y), ui.status_color(line))
            y += 22

    def _turn_prompt(self) -> str:
        """Return the one-line instruction shown under the tray's player banner."""

        if self.game is None or not self.game.current_player.is_human:
            return "AI is thinking..."
        if self.game.awaiting == "choose_move":
            return "Pick a highlighted token or use a move button."
        return "Roll the die."

    def _draw_player_roster(self) -> None:
        """Draw compact floating player chips instead of a heavy sidebar.

        One chip per seat, in turn order, with a colour dot, the name, a
        "Human" or AI-profile tag, and a line with tokens home and captures.
        The current player's chip is outlined in their colour. Names are
        ellipsized by rendered width, so long names never overlap the tag.
        """

        if self.game is None:
            return
        ui.draw_text(self.window, self.fonts["header"], "Players", (PLAY_ROSTER_X, PLAY_ROSTER_Y - 42), WHITE)
        name_font, tiny = self.fonts["small"], self.fonts["tiny"]
        # The name line and the stats line are centred as one block, so they
        # stay inside the chip whatever line heights this platform's fonts use.
        block_height = name_font.get_height() + PLAY_ROSTER_LINE_GAP + tiny.get_height()
        for index, player in enumerate(self.game.players):
            rect = _roster_chip_rect(index)
            border = player.color if index == self.game.current else PANEL_EDGE
            theme.draw_shadowed_rect(self.window, rect, theme.HUD_DARK, border=border, radius=12, shadow_offset=(0, 4))
            pygame.draw.circle(self.window, player.color, (rect.x + 22, rect.centery), 12)
            text_x = rect.x + PLAY_ROSTER_TEXT_X
            text_right = rect.right - PLAY_ROSTER_TEXT_PADDING
            name_y = rect.centery - block_height // 2
            stats_y = name_y + name_font.get_height() + PLAY_ROSTER_LINE_GAP
            # The Human/AI-profile tag sits at the right end of the name line;
            # the name gets whatever width is left and is ellipsized to fit.
            tag = "Human" if player.is_human else self.game.ai_profile.title()
            tag_width = tiny.size(tag)[0]
            name_width = text_right - text_x - tag_width - PLAY_ROSTER_TAG_GAP
            name = ui.ellipsize(name_font, player.name, name_width)
            ui.draw_text(self.window, name_font, name, (text_x, name_y), WHITE)
            tag_y = name_y + name_font.get_height() - tiny.get_height()
            ui.draw_text(self.window, tiny, tag, (text_right - tag_width, tag_y), SOFT)
            done = player.finished_count(self.game.layout.finish_steps)
            stats = ui.ellipsize(tiny, f"Home {done}/4  Captures {player.captures}", text_right - text_x)
            ui.draw_text(self.window, tiny, stats, (text_x, stats_y), SOFT)

    def _draw_play_button(self, button: ui.Button, mouse: tuple[int, int]) -> None:
        """Draw gameplay buttons with the new table-HUD treatment.

        Save, New and Sound are drawn as rounded pills; Roll and the move buttons are
        dark cards edged in the current player's colour (Roll in gold) that
        fill with that colour while hovered.
        """

        hovered = button.contains(mouse)
        current_color = self.game.current_player.color if self.game is not None else GOLD
        if button.key == "toggle_sound":
            color = _sound_pill_color(self.sound_on, hovered)
            theme.draw_round_icon_button(self.window, button.rect, color, button.text, self.fonts)
            return
        if button.key in {"save_quit", "new_game"}:
            # These small controls behave like table buttons rather than a
            # rectangular sidebar menu. The key text stays short so it fits
            # after the adaptive window scaling shrinks the game.
            color = GOLD if button.key == "save_quit" else current_color
            if hovered:
                color = theme.brighten(color, PLAY_PILL_HOVER_BRIGHTEN)
            theme.draw_round_icon_button(self.window, button.rect, color, button.text, self.fonts)
            return

        fill = theme.brighten(current_color, 18) if hovered else theme.HUD_DARK
        border = GOLD if button.key == "roll" else current_color
        theme.draw_shadowed_rect(self.window, button.rect, fill, border=border, radius=12, shadow_offset=(0, 4))
        text_color = INK if hovered else WHITE
        ui.draw_text(self.window, self.fonts["button"], button.text, button.rect.center, text_color, center=True)

    def _buttons_for_screen(self) -> list[ui.Button]:
        """Return the buttons that are valid on the current screen.

        During play the buttons follow the engine state: a human waiting to
        roll gets Roll, a human choosing a move gets up to four move buttons
        ("1: Token 2 -> 14", where 14 is the token's new step count), and
        Save, New and Sound are always present. AI turns show only those
        three.
        """

        if self.screen == "setup":
            return self.setup_buttons()
        if self.screen == "over":
            new_rect, quit_rect = _over_button_rects()
            return [ui.Button(new_rect, "New Game", "new_game"), ui.Button(quit_rect, "Quit", "quit")]
        if self.game is None:
            return []
        buttons: list[ui.Button] = []
        if self.game.current_player.is_human and self.game.awaiting == "pre_roll":
            buttons.append(ui.Button(PLAY_ROLL_RECT, "Roll", "roll"))
        elif self.game.current_player.is_human and self.game.awaiting == "choose_move":
            for index, move in enumerate(self.visible_moves[:4]):
                label = f"{index + 1}: Token {move.token_index + 1} -> {move.to_steps}"
                buttons.append(ui.Button(_move_button_rect(index), label, f"move_{index}"))
        buttons.append(ui.Button(PLAY_SAVE_RECT, "Save", "save_quit"))
        buttons.append(ui.Button(PLAY_NEW_RECT, "New", "new_game"))
        buttons.append(ui.Button(PLAY_SOUND_RECT, _toggle_label("Sound", self.sound_on), "toggle_sound"))
        return buttons

    def _winner_plaque(self, winner) -> tuple[pygame.Rect, str]:
        """Return the winner plaque's rect and the (possibly ellipsized) text on it.

        The plaque hugs the text plus ``OVER_PLAQUE_PADDING``; a name too wide
        for ``OVER_PLAQUE_MAX_WIDTH`` is ellipsized, keeping " wins!" intact.
        """

        font = self.fonts["title"]
        pad_x, pad_y = OVER_PLAQUE_PADDING
        suffix = " wins!"
        name_width = OVER_PLAQUE_MAX_WIDTH - 2 * pad_x - font.size(suffix)[0]
        text = ui.ellipsize(font, winner.name, name_width) + suffix
        text_width, text_height = font.size(text)
        plaque = pygame.Rect(0, 0, text_width + 2 * pad_x, text_height + 2 * pad_y)
        plaque.center = OVER_PLAQUE_CENTER
        return plaque, text

    def _draw_game_over(self) -> None:
        """Draw final rankings and lifetime stats.

        Shows "Game Over" with the winner's name on a plaque in their seat
        colour, the "Final Ranking" card (from ``game.ranking``, with tokens
        home and captures per player), the "Lifetime Stats" card (games,
        human and AI wins, average turns per game, and games per board
        size), and the New Game and Quit buttons. If no game exists it falls
        back to the setup screen.
        """

        if self.game is None:
            self.screen = "setup"
            return
        self.buttons = self._buttons_for_screen()
        mouse = self._logical_mouse_pos()
        winner = self.game.players[self.game.winner] if self.game.winner is not None else self.game.players[0]
        ui.draw_text(self.window, self.fonts["huge"], "Game Over", (450, 104), WHITE, center=True)
        plaque, text = self._winner_plaque(winner)
        theme.draw_shadowed_rect(self.window, plaque, winner.color, border=theme.BOARD_EDGE, radius=14)
        plaque_label = theme.readable_on(winner.color)
        ui.draw_text(self.window, self.fonts["title"], text, plaque.center, plaque_label, center=True)

        table = OVER_RANKING_RECT
        theme.draw_shadowed_rect(self.window, table, theme.HUD_DARK, border=winner.color, radius=14)
        ui.draw_text(self.window, self.fonts["header"], "Final Ranking", (table.x + 28, table.y + 24), WHITE)
        for rank, player_index in enumerate(self.game.ranking, start=1):
            player = self.game.players[player_index]
            y = table.y + 70 + (rank - 1) * 48
            ui.draw_text(self.window, self.fonts["body"], f"{rank}. {player.name}", (table.x + 34, y), player.color)
            ui.draw_text(
                self.window,
                self.fonts["small"],
                f"Home {player.finished_count(self.game.layout.finish_steps)}/4  Captures {player.captures}",
                (table.x + 254, y + 3),
                SOFT,
            )

        stats = OVER_STATS_RECT
        # The stats card uses the same floating table-card style as the
        # redesigned setup and play screens.
        theme.draw_shadowed_rect(self.window, stats, theme.HUD_DARK, border=PANEL_EDGE, radius=14)
        title_pos = (stats.x + OVER_CARD_PADDING, stats.y + OVER_CARD_PADDING)
        ui.draw_text(self.window, self.fonts["header"], "Lifetime Stats", title_pos, WHITE)
        # ``max(1, ...)`` avoids dividing by zero when no game is recorded.
        games = max(1, int(self.stats.get("games", 0)))
        average_turns = int(self.stats.get("turn_total", 0)) / games
        by_count = {**{"4": 0, "5": 0, "6": 0}, **self.stats.get("by_player_count", {})}
        lines = [
            f"Games: {self.stats.get('games', 0)}",
            f"Human wins: {self.stats.get('human_wins', 0)}",
            f"AI wins: {self.stats.get('ai_wins', 0)}",
            f"Average turns: {average_turns:.1f}",
            f"4P / 5P / 6P: {by_count['4']} / {by_count['5']} / {by_count['6']}",
        ]
        for offset, line in enumerate(lines):
            y = stats.y + OVER_STATS_FIRST_LINE + offset * OVER_STATS_LINE_STEP
            ui.draw_text(self.window, self.fonts["body"], line, (stats.x + OVER_CARD_PADDING, y), SOFT)
        for button in self.buttons:
            button.draw(self.window, self.fonts, mouse)


def _over_button_rects() -> tuple[pygame.Rect, pygame.Rect]:
    """Return the New Game and Quit rects, centred under the stats card."""

    width, height = OVER_BUTTON_SIZE
    rects = []
    for index in range(2):
        rect = pygame.Rect(0, OVER_BUTTON_TOP + index * OVER_BUTTON_STEP, width, height)
        rect.centerx = OVER_STATS_RECT.centerx
        rects.append(rect)
    return rects[0], rects[1]


def _roster_chip_rect(index: int) -> pygame.Rect:
    """Return the play-screen rectangle of roster chip ``index`` (one per seat)."""

    y = PLAY_ROSTER_Y + index * PLAY_ROSTER_STEP
    return pygame.Rect(PLAY_ROSTER_X, y, PLAY_ROSTER_WIDTH, PLAY_ROSTER_CHIP_HEIGHT)


def _move_button_rect(index: int) -> pygame.Rect:
    """Return the play-screen rectangle for move button ``index`` (0 to 3)."""

    y = PLAY_MOVE_START[1] + index * (PLAY_MOVE_SIZE[1] + PLAY_MOVE_GAP)
    return pygame.Rect(PLAY_MOVE_START[0], y, PLAY_MOVE_SIZE[0], PLAY_MOVE_SIZE[1])


def _name_rect(index: int) -> pygame.Rect:
    """Return the setup-screen rectangle for one human name field."""

    return pygame.Rect(
        SETUP_CONTROL_X,
        SETUP_NAME_START_Y + index * SETUP_NAME_FIELD_STEP,
        SETUP_CONTROL_WIDTH,
        SETUP_NAME_FIELD_HEIGHT,
    )


def _toggle_label(label: str, enabled: bool) -> str:
    """Format an On/Off label for a house-rule or Sound toggle button."""

    return f"{label}: {'On' if enabled else 'Off'}"


def _sound_pill_color(sound_on: bool, hovered: bool) -> tuple[int, int, int]:
    """Return the in-game Sound pill's colour: green while on, grey while off, lighter when hovered."""

    color = PLAY_SOUND_ON_COLOR if sound_on else PLAY_SOUND_OFF_COLOR
    return theme.brighten(color, PLAY_PILL_HOVER_BRIGHTEN) if hovered else color


def _resource_path(name: str) -> str:
    """Path to a bundled resource, working from source or a frozen .exe."""
    base = getattr(sys, "_MEIPASS", None)
    base_dir = base if base else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, name)


def _load_icon() -> pygame.Surface:
    """Return the bundled window icon, or the drawn fallback if it cannot load.

    ``ludo_icon.png`` is the 256px image from inside ``ludo_icon.ico``. The
    .ico itself cannot be loaded here (SDL_image reports "Unsupported ICO
    bitmap format"); PyInstaller still uses it for the .exe's own file and
    taskbar icon (see the spec's ``icon=``).
    """

    try:
        return pygame.image.load(_resource_path(ICON_FILE))
    except (OSError, pygame.error):
        return _make_icon()


def _make_icon() -> pygame.Surface:
    """Draw a simple fallback icon: a cream board with one dot per classic seat."""

    icon = pygame.Surface((ICON_SIZE, ICON_SIZE), pygame.SRCALPHA)
    board = (ICON_BOARD_INSET, ICON_BOARD_INSET, ICON_BOARD_SIZE, ICON_BOARD_SIZE)
    pygame.draw.rect(icon, ICON_BOARD_COLOR, board, border_radius=ICON_BOARD_RADIUS)
    # Seat dots sit in a 2x2 grid, in the classic four-player seat order.
    for index, color in enumerate(seat_colors(MIN_PLAYERS)):
        x = ICON_DOT_ORIGIN + (index % 2) * ICON_DOT_SPACING
        y = ICON_DOT_ORIGIN + (index // 2) * ICON_DOT_SPACING
        pygame.draw.circle(icon, color, (x, y), ICON_DOT_RADIUS)
    return icon


def main() -> None:
    """Initialize pygame, run the app, and always shut pygame down.

    The mixer format is requested before ``pygame.init()`` opens the mixer,
    and the music channel is reserved right after. The ``try``/``finally``
    makes sure ``pygame.quit()`` runs even if the app raises, so the window
    is always closed cleanly.
    """

    audio.init_mixer()
    pygame.init()
    audio.reserve_channels()
    try:
        if os.environ.get("LUDO_AUTOTEST"):
            # Headless self-test: play a seeded all-AI game on the classic
            # four-player board, and never touch the player's saves or stats.
            app = LudoApp(persist=False)
            players = [(f"AI {seat + 1} ({seat_name(MIN_PLAYERS, seat)})", False) for seat in range(MIN_PLAYERS)]
            app.start_game(LudoGame(players, LudoRules(total_players=MIN_PLAYERS), seed=AUTOTEST_SEED))
            app.run(max_frames=AUTOTEST_FRAMES)
        else:
            LudoApp().run()
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
