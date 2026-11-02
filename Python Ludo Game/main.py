"""Program entry point, Pygame window, persistence, input, and AI driver."""

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
    PANEL_BG,
    PANEL_CARD,
    PANEL_EDGE,
    PANEL_WIDTH,
    PANEL_X,
    SAVE_DIR,
    SAVEGAME_PATH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SOFT,
    STATS_PATH,
    TOKEN_HOP_SPEED,
    WHITE,
    WINDOW_TITLE,
    seat_colors,
    seat_name,
)

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
WINDOW_FIT_PADDING = 8
PLAY_SAVE_RECT = pygame.Rect(34, 794, 136, 38)
PLAY_NEW_RECT = pygame.Rect(34, 842, 136, 34)
PLAY_DICE_TRAY_RECT = pygame.Rect(214, 790, 430, 86)
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
# Game-over screen: the ranking card on the left, the lifetime-stats card on
# the right, and the New Game / Quit buttons centred beneath the stats card.
OVER_RANKING_RECT = pygame.Rect(210, 248, 480, 360)
OVER_STATS_RECT = pygame.Rect(PANEL_X + 14, 60, PANEL_WIDTH + 2, 540)
OVER_BUTTON_SIZE = (220, 44)
OVER_BUTTON_TOP = 700
OVER_BUTTON_STEP = 58
# The winner's name sits on a plaque in their seat colour under "Game Over",
# so it reads on the blue wallpaper whatever the seat colour. The plaque's
# width is capped so it stays clear of the stats card column.
OVER_PLAQUE_CENTER = (450, 178)
OVER_PLAQUE_PADDING = (28, 8)  # space around the text: horizontal, vertical
OVER_PLAQUE_MAX_WIDTH = 620
PREVIEW_CENTERS = ((200, 470), (450, 470), (700, 470))
PREVIEW_SIZE = 216


@dataclass(frozen=True)
class SetupOptionRow:
    """One setup option row with shared label, value, and button geometry."""

    label_y: int
    control_y: int
    value_center: tuple[int, int]
    left_button: pygame.Rect
    right_button: pygame.Rect


def _setup_option_row(index: int) -> SetupOptionRow:
    """Return aligned geometry for one top setup option row."""

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
    """Map a logical 1280x900 point into the scaled OS window."""

    width, height = max(1, window_size[0]), max(1, window_size[1])
    return (
        int(pos[0] * width / SCREEN_WIDTH),
        int(pos[1] * height / SCREEN_HEIGHT),
    )


def _window_to_logical_point(pos: tuple[int, int], window_size: tuple[int, int]) -> tuple[int, int]:
    """Map a scaled OS-window point back into logical game coordinates."""

    width, height = max(1, window_size[0]), max(1, window_size[1])
    logical_x = int(pos[0] * SCREEN_WIDTH / width)
    logical_y = int(pos[1] * SCREEN_HEIGHT / height)
    return (
        max(0, min(SCREEN_WIDTH - 1, logical_x)),
        max(0, min(SCREEN_HEIGHT - 1, logical_y)),
    )


def _desktop_work_area_size() -> tuple[int, int]:
    """Return usable desktop size, preferring Windows' taskbar-aware value."""

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
    """Estimate non-client window chrome so the outer window stays visible."""

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
    """Read lifetime stats, filling in defaults and repairing malformed fields."""

    defaults: dict[str, Any] = {
        "games": 0,
        "human_wins": 0,
        "ai_wins": 0,
        "turn_total": 0,
        "by_player_count": {"4": 0, "5": 0, "6": 0},
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
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    for field in ("games", "human_wins", "ai_wins", "turn_total"):
        defaults[field] = _stat_count(defaults[field], field)
    buckets = defaults["by_player_count"]
    for key in buckets:
        buckets[key] = _stat_count(buckets[key], f"by_player_count[{key}]")
    return defaults


def save_stats(stats: dict) -> None:
    """Persist lifetime stats under ``%APPDATA%``."""

    _atomic_write(STATS_PATH, stats)


def save_game(game: LudoGame) -> None:
    """Persist the current game so it can be resumed later."""

    _atomic_write(SAVEGAME_PATH, game.to_dict())


def load_saved_game() -> LudoGame | None:
    """Load the saved game, returning ``None`` if there is no usable save."""

    try:
        return LudoGame.from_dict(json.loads(SAVEGAME_PATH.read_text(encoding="utf-8")))
    # AttributeError covers a damaged entry of the wrong JSON type (a list
    # where a token object belongs). OverflowError covers huge numbers: JSON
    # reads 1e400 as float inf, and int(inf) raises OverflowError.
    except (OSError, TypeError, ValueError, KeyError, AttributeError, OverflowError, json.JSONDecodeError):
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
        self.window = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT)).convert()
        self.clock = pygame.time.Clock()
        self.fonts = ui.make_fonts()
        self.running = True

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
        self.stats_recorded = False
        self.ai_timer = 0
        self.dice_anim_remaining = 0
        # Animation state per (player_index, token_index): the drawn pixel,
        # the engine steps it reflects, and the queue of cells still to hop.
        self.token_pixels: dict[tuple[int, int], tuple[float, float]] = {}
        self.token_steps: dict[tuple[int, int], int] = {}
        self.token_waypoints: dict[tuple[int, int], list[tuple[float, float]]] = {}
        self.preview_cache: dict[int, pygame.Surface] = {}
        self.message = "Choose a table and start the race."
        self.saved_turns_taken: int | None = None

    def setup_buttons(self) -> list[ui.Button]:
        """Build fresh button objects for the setup screen."""

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
        ]

    def run(self, max_frames: int | None = None) -> None:
        """Run the event loop until the app quits or a test frame limit hits."""

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
        """Scale the logical canvas onto the actual OS window."""

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
        """Switch from setup into a playable game."""

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
        self.saved_turns_taken = game.turns_taken
        self.message = "Roll a 6 to bring a token out."

    def _handle_click(self, pos: tuple[int, int]) -> None:
        """Route one left-click to name fields, tokens, or buttons."""

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
        """Route keyboard shortcuts for setup typing and human turns."""

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
        """Edit the active setup-screen name field."""

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
        """Dispatch a clicked button key to the active screen."""

        if self.screen == "setup":
            self._on_setup_button(key)
        elif self.screen == "playing":
            self._on_play_button(key)
        elif self.screen == "over":
            if key == "new_game":
                self.screen = "setup"
            elif key == "quit":
                self.running = False

    def _on_setup_button(self, key: str) -> None:
        """Handle all setup-screen controls."""

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
            saved = load_saved_game()
            if saved is not None:
                self.start_game(saved)
        elif key == "start":
            self._start_new_game()
        elif key == "quit":
            self.running = False

    def _on_play_button(self, key: str) -> None:
        """Handle buttons shown during an active game."""

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
        """Create a new rules engine from the setup-screen choices."""

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
        """Roll for the current human player and handle no-move rolls."""

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
        """Apply a selected move and surface the result message."""

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
        """Advance animations, game-over bookkeeping, and AI turns."""

        elapsed = self.clock.get_time()
        if self.dice_anim_remaining > 0:
            self.dice_anim_remaining = max(0, self.dice_anim_remaining - elapsed)
        self._update_token_pixels(elapsed)

        if self.screen != "playing" or self.game is None:
            return
        if self.game.phase == "game_over":
            # Stats are recorded here instead of inside the engine because
            # stats are app persistence, not core Ludo rules.
            self._record_finished_game_once()
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

    def _perform_ai_step(self) -> None:
        """Let the current AI player roll or choose one move."""

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
        """Advance drawn token positions along their pending waypoints."""

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
                    self.token_waypoints[key] = self._token_waypoints(
                        player_index, token_index, self.token_steps.get(key, -1), token.steps
                    )
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
                    else:
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

    def _save_if_turn_completed(self) -> None:
        """Autosave after completed turns, not after every animation frame."""

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
        """Add the finished game to lifetime stats exactly once."""

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
        """Draw the setup screen, including preview boards and controls."""

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
        """Return a cached true-to-life thumbnail of one board shape."""

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
        """Draw compact gameplay controls over the wallpaper, not in a sidebar."""

        if self.game is None:
            return
        current = self.game.current_player
        die_value = self.game.last_roll
        if self.dice_anim_remaining > 0:
            die_value = ((pygame.time.get_ticks() // 70) % 6) + 1

        # A single lower tray carries the current player and die, similar to a
        # physical board-game table where the dice sit beside the board.
        tray = PLAY_DICE_TRAY_RECT
        theme.draw_dice_tray(self.window, tray, die_value, self.fonts, accent=current.color)
        theme.draw_player_banner(self.window, PLAY_TRAY_BANNER_RECT, current.color, current.name[:18], self.fonts)

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
        """Draw compact floating player chips instead of a heavy sidebar."""

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
        """Draw gameplay buttons with the new table-HUD treatment."""

        hovered = button.contains(mouse)
        current_color = self.game.current_player.color if self.game is not None else GOLD
        if button.key in {"save_quit", "new_game"}:
            # These small controls behave like table buttons rather than a
            # rectangular sidebar menu. The key text stays short so it fits
            # after the adaptive window scaling shrinks the game.
            color = GOLD if button.key == "save_quit" else current_color
            if hovered:
                color = theme.brighten(color, 28)
            theme.draw_round_icon_button(self.window, button.rect, color, button.text, self.fonts)
            return

        fill = theme.brighten(current_color, 18) if hovered else theme.HUD_DARK
        border = GOLD if button.key == "roll" else current_color
        theme.draw_shadowed_rect(self.window, button.rect, fill, border=border, radius=12, shadow_offset=(0, 4))
        text_color = INK if hovered else WHITE
        ui.draw_text(self.window, self.fonts["button"], button.text, button.rect.center, text_color, center=True)

    def _buttons_for_screen(self) -> list[ui.Button]:
        """Return the buttons that are valid on the current screen."""

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
        """Draw final rankings and lifetime stats."""

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
        # The stats card keeps the old information but uses the same floating
        # table-card style as the redesigned setup and play screens.
        theme.draw_shadowed_rect(self.window, stats, theme.HUD_DARK, border=PANEL_EDGE, radius=14)
        ui.draw_text(self.window, self.fonts["header"], "Lifetime Stats", (stats.x + 18, stats.y + 18), WHITE)
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
            ui.draw_text(self.window, self.fonts["body"], line, (stats.x + 18, stats.y + 70 + offset * 42), SOFT)
        ui.draw_wrapped(
            self.window,
            self.fonts["small"],
            "Captures, exact home rolls, bonus turns, and safe squares "
            "all used the same engine rules as the live game.",
            pygame.Rect(stats.x + 18, stats.y + 316, stats.width - 36, 88),
            SOFT,
        )
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
    """Format an On/Off label for a house-rule toggle button."""

    return f"{label}: {'On' if enabled else 'Off'}"


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
    """Initialize pygame, run the app, and always shut pygame down."""

    pygame.init()
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
