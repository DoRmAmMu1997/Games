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
    DICE_ANIM_MS,
    FPS,
    GOLD,
    INK,
    MAX_PLAYERS,
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
SETUP_NAME_HEADER_Y = 570
SETUP_NAME_START_Y = 608
SETUP_NAME_FIELD_HEIGHT = 30
SETUP_NAME_FIELD_STEP = 35
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
PLAY_MOVE_START = (690, 566)
PLAY_MOVE_SIZE = (188, 38)
PLAY_MOVE_GAP = 8
PLAY_LOG_RECT = pygame.Rect(674, 742, 206, 132)
PLAY_ROSTER_X = 932
PLAY_ROSTER_Y = 90
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


def load_stats() -> dict:
    """Read lifetime stats, filling in defaults for missing fields."""

    defaults = {
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
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
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

    def __init__(self) -> None:
        """Create the pygame window and initialize screen-level state."""

        self.window_size = _fit_window_size(_desktop_work_area_size(), _window_chrome_size())
        self.screen_surface = pygame.display.set_mode(self.window_size)
        pygame.display.set_caption(WINDOW_TITLE)
        pygame.display.set_icon(_make_icon())
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
        return [
            ui.Button(total_row.left_button, "-", "total_players_prev"),
            ui.Button(total_row.right_button, "+", "total_players_next"),
            ui.Button(human_row.left_button, "-", "human_count_prev"),
            ui.Button(human_row.right_button, "+", "human_count_next"),
            ui.Button(ai_row.left_button, "<", "ai_profile_prev"),
            ui.Button(ai_row.right_button, ">", "ai_profile_next"),
            ui.Button(
                pygame.Rect(x, 390, SETUP_CONTROL_WIDTH, 36),
                _toggle_label("Blockades", self.rule_blockades),
                "toggle_blockades",
            ),
            ui.Button(
                pygame.Rect(x, 436, SETUP_CONTROL_WIDTH, 36),
                _toggle_label("Capture bonus", self.rule_capture_bonus),
                "toggle_capture_bonus",
            ),
            ui.Button(
                pygame.Rect(x, 482, SETUP_CONTROL_WIDTH, 36),
                _toggle_label("Home bonus", self.rule_home_bonus),
                "toggle_home_bonus",
            ),
            ui.Button(
                pygame.Rect(x, 528, SETUP_CONTROL_WIDTH, 36),
                _toggle_label("Three 6s", self.rule_three_sixes),
                "toggle_three_sixes",
            ),
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

        if (
            self.screen == "playing"
            and self.game
            and self.renderer
            and self.game.current_player.is_human
            and self.game.awaiting == "choose_move"
        ):
            # Human token clicks are only accepted when the engine is
            # waiting for a move after a roll.
            move = self.renderer.move_at_pos(pos, self.visible_moves)
            if move is not None:
                self._apply_move(move)
                return

        for button in self._buttons_for_screen():
            if button.contains(pos):
                self._on_button(button.key)
                return

    def _handle_key(self, event: pygame.event.Event) -> None:
        """Route keyboard shortcuts for setup typing and human turns."""

        if event.key == pygame.K_ESCAPE:
            if self.screen == "playing" and self.game:
                save_game(self.game)
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
        elif event.unicode and event.unicode.isprintable() and len(self.name_fields[index]) < 18:
            self.name_fields[index] += event.unicode

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
            self.total_players = max(4, self.total_players - 1)
            self.human_count = min(self.human_count, self.total_players)
        elif key == "total_players_next":
            self.total_players = min(6, self.total_players + 1)
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
            save_game(self.game)
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
        save_game(game)

    def _roll_for_human(self) -> None:
        """Roll for the current human player and handle no-move rolls."""

        if self.game is None or self.game.awaiting != "pre_roll":
            return
        die = self.game.rng.randint(1, 6)
        forfeited = self.game.record_roll(die)
        self.dice_anim_remaining = DICE_ANIM_MS
        if not forfeited and not self.game.legal_moves(die):
            self.game.note_no_move(die)
        self._save_if_turn_completed()

    def _apply_move(self, move) -> None:
        """Apply a selected move and surface the result message."""

        if self.game is None:
            return
        result = self.game.apply_move(move)
        self.message = result.message
        self._save_if_turn_completed()

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
        self._save_if_turn_completed()

    def _perform_ai_step(self) -> None:
        """Let the current AI player roll or choose one move."""

        if self.game is None:
            return
        if self.game.awaiting == "pre_roll":
            die = self.game.rng.randint(1, 6)
            forfeited = self.game.record_roll(die)
            self.dice_anim_remaining = DICE_ANIM_MS
            if forfeited:
                return
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
        ui.draw_text(self.window, self.fonts["huge"], "LUDO", (450, 92), WHITE, center=True)
        ui.draw_wrapped(
            self.window,
            self.fonts["body"],
            "Classic competitive Ludo for 4 to 6 players. "
            "Choose how many seats are human; the remaining seats use heuristic AI.",
            pygame.Rect(170, 138, 560, 80),
            SOFT,
        )
        self._draw_board_previews()

        panel = pygame.Rect(PANEL_X, 0, PANEL_WIDTH + 30, SCREEN_HEIGHT)
        theme.draw_shadowed_rect(self.window, panel.inflate(-14, -18), PANEL_BG, border=PANEL_EDGE, radius=16)
        ui.draw_text(self.window, self.fonts["title"], "Setup", (PANEL_X + 24, 42), WHITE)
        self._setup_value("Total Players", str(self.total_players), 0)
        self._setup_value("Human Players", str(self.human_count), 1)
        self._setup_value("AI Profile", self.ai_profiles[self.ai_profile_index].title(), 2)

        ui.draw_text(self.window, self.fonts["header"], "Advanced Rules", (PANEL_X + 24, 354), WHITE)
        ui.draw_text(self.window, self.fonts["header"], "Human Names", (SETUP_CONTROL_X, SETUP_NAME_HEADER_Y), WHITE)
        for index in range(self.human_count):
            # Name fields are lightweight hand-drawn rectangles. The active
            # one gets a colored border so typing focus is visible.
            rect = _name_rect(index)
            color = seat_colors(self.total_players)[index]
            pygame.draw.rect(self.window, PANEL_CARD, rect, border_radius=6)
            pygame.draw.rect(self.window, color if self.active_field == index else PANEL_EDGE, rect, 2, border_radius=6)
            ui.draw_text(self.window, self.fonts["body"], self.name_fields[index], (rect.x + 10, rect.y + 4), WHITE)

        for button in self.buttons:
            button.draw(self.window, self.fonts, mouse)

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
        self.visible_moves = []
        choosing = self.game.current_player.is_human and self.game.awaiting == "choose_move"
        if choosing and self.game.last_roll is not None:
            # Recompute visible moves before drawing so the highlights and
            # click targets always match the latest engine state.
            self.visible_moves = self.game.legal_moves(self.game.last_roll)
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
        banner = pygame.Rect(tray.x + 104, tray.y + 12, 180, 28)
        theme.draw_player_banner(self.window, banner, current.color, current.name[:18], self.fonts)

        if current.is_human and self.game.awaiting == "choose_move":
            prompt = "Pick a highlighted token or use a move button."
        elif current.is_human:
            prompt = "Roll the die."
        else:
            prompt = "AI is thinking..."
        ui.draw_wrapped(
            self.window,
            self.fonts["small"],
            prompt,
            pygame.Rect(tray.x + 104, tray.y + 46, 300, 34),
            WHITE,
        )

        self._draw_player_roster()
        log_panel = PLAY_LOG_RECT
        theme.draw_shadowed_rect(self.window, log_panel, theme.HUD_DARK, border=PANEL_EDGE, radius=12)
        ui.draw_text(self.window, self.fonts["small"], "Table Log", (log_panel.x + 12, log_panel.y + 10), WHITE)
        y = log_panel.y + 38
        for line in self.game.event_log[-4:]:
            ui.draw_text(self.window, self.fonts["tiny"], line[:36], (log_panel.x + 12, y), ui.status_color(line))
            y += 22

    def _draw_player_roster(self) -> None:
        """Draw compact floating player chips instead of a heavy sidebar."""

        if self.game is None:
            return
        ui.draw_text(self.window, self.fonts["header"], "Players", (PLAY_ROSTER_X, PLAY_ROSTER_Y - 42), WHITE)
        for index, player in enumerate(self.game.players):
            rect = pygame.Rect(PLAY_ROSTER_X, PLAY_ROSTER_Y + index * 52, 254, 40)
            border = player.color if index == self.game.current else PANEL_EDGE
            theme.draw_shadowed_rect(self.window, rect, theme.HUD_DARK, border=border, radius=12, shadow_offset=(0, 4))
            pygame.draw.circle(self.window, player.color, (rect.x + 22, rect.centery), 12)
            ui.draw_text(self.window, self.fonts["small"], player.name[:18], (rect.x + 44, rect.y + 7), WHITE)
            tag = "Human" if player.is_human else self.game.ai_profile.title()
            done = player.finished_count(self.game.layout.finish_steps)
            ui.draw_text(
                self.window,
                self.fonts["tiny"],
                f"{tag}  Home {done}/4  Captures {player.captures}",
                (rect.x + 44, rect.y + 25),
                SOFT,
            )

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
            return [
                ui.Button(pygame.Rect(PANEL_X + 42, 700, 220, 44), "New Game", "new_game"),
                ui.Button(pygame.Rect(PANEL_X + 42, 758, 220, 44), "Quit", "quit"),
            ]
        if self.game is None:
            return []
        buttons: list[ui.Button] = []
        if self.game.current_player.is_human and self.game.awaiting == "pre_roll":
            buttons.append(ui.Button(PLAY_ROLL_RECT, "Roll", "roll"))
        elif self.game.current_player.is_human and self.game.awaiting == "choose_move":
            for index, move in enumerate(self.visible_moves[:4]):
                label = f"{index + 1}: Token {move.token_index + 1} -> {move.to_steps}"
                y = PLAY_MOVE_START[1] + index * (PLAY_MOVE_SIZE[1] + PLAY_MOVE_GAP)
                buttons.append(
                    ui.Button(
                        pygame.Rect(PLAY_MOVE_START[0], y, PLAY_MOVE_SIZE[0], PLAY_MOVE_SIZE[1]),
                        label,
                        f"move_{index}",
                    )
                )
        buttons.append(ui.Button(PLAY_SAVE_RECT, "Save", "save_quit"))
        buttons.append(ui.Button(PLAY_NEW_RECT, "New", "new_game"))
        return buttons

    def _draw_game_over(self) -> None:
        """Draw final rankings and lifetime stats."""

        if self.game is None:
            self.screen = "setup"
            return
        self.buttons = self._buttons_for_screen()
        mouse = self._logical_mouse_pos()
        winner = self.game.players[self.game.winner] if self.game.winner is not None else self.game.players[0]
        ui.draw_text(self.window, self.fonts["huge"], "Game Over", (450, 104), WHITE, center=True)
        ui.draw_text(self.window, self.fonts["title"], f"{winner.name} wins!", (450, 174), winner.color, center=True)

        table = pygame.Rect(210, 248, 480, 360)
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

        stats = pygame.Rect(PANEL_X + 14, 60, PANEL_WIDTH + 2, 540)
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


def _make_icon() -> pygame.Surface:
    """Create the in-window icon by drawing it.

    ``ludo_icon.ico`` is NOT loaded here: SDL_image cannot decode this file
    ("Unsupported ICO bitmap format"), so a runtime load would always fail
    into this function anyway. The .ico is still used, by PyInstaller, for
    the executable's own file and taskbar icon (see the spec's ``icon=``).
    """

    icon = pygame.Surface((64, 64), pygame.SRCALPHA)
    pygame.draw.rect(icon, (238, 232, 209), (4, 4, 56, 56), border_radius=12)
    for index, color in enumerate(seat_colors(4)):
        x = 22 + (index % 2) * 20
        y = 22 + (index // 2) * 20
        pygame.draw.circle(icon, color, (x, y), 9)
    return icon


def main() -> None:
    """Initialize pygame, run the app, and always shut pygame down."""

    pygame.init()
    try:
        app = LudoApp()
        max_frames = 8 if os.environ.get("LUDO_AUTOTEST") else None
        app.run(max_frames=max_frames)
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
