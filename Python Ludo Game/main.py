"""Program entry point, Pygame window, persistence, input, and AI driver."""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

import pygame

import ai
import ui
from board_render import BoardRenderer
from game import LudoGame, LudoRules
from settings import (
    AI_TURN_DELAY_MS,
    BG,
    DICE_ANIM_MS,
    FPS,
    PANEL_BG,
    PANEL_CARD,
    PANEL_EDGE,
    PANEL_WIDTH,
    PANEL_X,
    PLAYER_COLORS,
    PLAYER_NAMES,
    SAVE_DIR,
    SAVEGAME_PATH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SOFT,
    STATS_PATH,
    TOKEN_ANIM_SPEED,
    WHITE,
    WINDOW_TITLE,
)


def _log_error(error: Exception) -> None:
    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with (SAVE_DIR / "error.log").open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {error}\n")
    except OSError:
        pass


def _atomic_write(path: Path, payload: dict) -> None:
    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, path)
    except OSError as error:
        _log_error(error)


def load_stats() -> dict:
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
        defaults["by_player_count"] = {**{"4": 0, "5": 0, "6": 0}, **defaults.get("by_player_count", {})}
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return defaults


def save_stats(stats: dict) -> None:
    _atomic_write(STATS_PATH, stats)


def save_game(game: LudoGame) -> None:
    _atomic_write(SAVEGAME_PATH, game.to_dict())


def load_saved_game() -> LudoGame | None:
    try:
        return LudoGame.from_dict(json.loads(SAVEGAME_PATH.read_text(encoding="utf-8")))
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def has_saved_game() -> bool:
    return SAVEGAME_PATH.exists()


def clear_saved_game() -> None:
    try:
        SAVEGAME_PATH.unlink(missing_ok=True)
    except OSError:
        pass


class LudoApp:
    """Owns screens, input routing, the game loop, and the AI timer."""

    def __init__(self) -> None:
        self.window = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption(WINDOW_TITLE)
        pygame.display.set_icon(_make_icon())
        self.clock = pygame.time.Clock()
        self.fonts = ui.make_fonts()
        self.running = True

        self.screen = "setup"
        self.game: LudoGame | None = None
        self.renderer: BoardRenderer | None = None
        self.buttons: list[ui.Button] = []
        self.visible_moves = []

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
        self.token_pixels: dict[tuple[int, int], tuple[float, float]] = {}
        self.message = "Choose a table and start the race."
        self.saved_turns_taken: int | None = None

    def setup_buttons(self) -> list[ui.Button]:
        x = PANEL_X + 24
        return [
            ui.Button(pygame.Rect(x, 164, 46, 38), "-", "total_players_prev"),
            ui.Button(pygame.Rect(x + 200, 164, 46, 38), "+", "total_players_next"),
            ui.Button(pygame.Rect(x, 236, 46, 38), "-", "human_count_prev"),
            ui.Button(pygame.Rect(x + 200, 236, 46, 38), "+", "human_count_next"),
            ui.Button(pygame.Rect(x, 308, 46, 38), "<", "ai_profile_prev"),
            ui.Button(pygame.Rect(x + 200, 308, 46, 38), ">", "ai_profile_next"),
            ui.Button(pygame.Rect(x, 390, 246, 36), _toggle_label("Blockades", self.rule_blockades), "toggle_blockades"),
            ui.Button(pygame.Rect(x, 436, 246, 36), _toggle_label("Capture bonus", self.rule_capture_bonus), "toggle_capture_bonus"),
            ui.Button(pygame.Rect(x, 482, 246, 36), _toggle_label("Home bonus", self.rule_home_bonus), "toggle_home_bonus"),
            ui.Button(pygame.Rect(x, 528, 246, 36), _toggle_label("Three 6s", self.rule_three_sixes), "toggle_three_sixes"),
            ui.Button(pygame.Rect(x, 804, 246, 46), "Start Game", "start"),
            ui.Button(pygame.Rect(x, 748, 246, 42), "Resume Saved Game", "resume", enabled=has_saved_game()),
            ui.Button(pygame.Rect(SCREEN_WIDTH - 132, 24, 100, 36), "Quit", "quit"),
        ]

    def run(self, max_frames: int | None = None) -> None:
        frames = 0
        autotest = max_frames is not None
        while self.running:
            self.clock.tick(FPS)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self._handle_click(event.pos)
                elif event.type == pygame.KEYDOWN:
                    self._handle_key(event)

            self._update(autotest)
            self._draw()
            pygame.display.flip()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                break

    def start_game(self, game: LudoGame) -> None:
        self.game = game
        self.renderer = BoardRenderer(game.layout)
        self.screen = "playing"
        self.active_field = None
        self.stats_recorded = False
        self.ai_timer = 0
        self.dice_anim_remaining = 0
        self.token_pixels = {}
        self.saved_turns_taken = game.turns_taken
        self.message = "Roll a 6 to bring a token out."

    def _handle_click(self, pos: tuple[int, int]) -> None:
        if self.screen == "setup":
            for index in range(self.human_count):
                if _name_rect(index).collidepoint(pos):
                    self.active_field = index
                    return
            self.active_field = None

        if self.screen == "playing" and self.game and self.renderer:
            if self.game.current_player.is_human and self.game.awaiting == "choose_move":
                move = self.renderer.move_at_pos(pos, self.visible_moves)
                if move is not None:
                    self._apply_move(move)
                    return

        for button in self._buttons_for_screen():
            if button.contains(pos):
                self._on_button(button.key)
                return

    def _handle_key(self, event: pygame.event.Event) -> None:
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
            saved = load_saved_game()
            if saved is not None:
                self.start_game(saved)
        elif key == "start":
            self._start_new_game()
        elif key == "quit":
            self.running = False

    def _on_play_button(self, key: str) -> None:
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
                players.append((f"AI {ai_number} ({PLAYER_NAMES[index]})", False))
                ai_number += 1
        self.start_game(LudoGame(players, rules, ai_profile=self.ai_profiles[self.ai_profile_index]))
        save_game(self.game)

    def _roll_for_human(self) -> None:
        if self.game is None or self.game.awaiting != "pre_roll":
            return
        forfeited = self.game.record_roll(self.game.rng.randint(1, 6))
        self.dice_anim_remaining = DICE_ANIM_MS
        if not forfeited and not self.game.legal_moves(self.game.last_roll):
            self.game.note_no_move(self.game.last_roll or 1)
        self._save_if_turn_completed()

    def _apply_move(self, move) -> None:
        if self.game is None:
            return
        result = self.game.apply_move(move)
        self.message = result.message
        self._save_if_turn_completed()

    def _update(self, autotest: bool) -> None:
        elapsed = self.clock.get_time()
        if self.dice_anim_remaining > 0:
            self.dice_anim_remaining = max(0, self.dice_anim_remaining - elapsed)
        self._update_token_pixels(elapsed)

        if self.screen != "playing" or self.game is None:
            return
        if self.game.phase == "game_over":
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

    def _update_token_pixels(self, elapsed_ms: int) -> None:
        if self.game is None:
            return
        amount = min(1.0, elapsed_ms / 1000 * TOKEN_ANIM_SPEED)
        for player_index, player in enumerate(self.game.players):
            for token_index, token in enumerate(player.tokens):
                key = (player_index, token_index)
                target = self.game.layout.position_for(player_index, token.steps, token_index)
                current = self.token_pixels.get(key)
                if current is None:
                    self.token_pixels[key] = target
                    continue
                dx = target[0] - current[0]
                dy = target[1] - current[1]
                if dx * dx + dy * dy < 1.0:
                    self.token_pixels[key] = target
                else:
                    self.token_pixels[key] = (current[0] + dx * amount, current[1] + dy * amount)

    def _save_if_turn_completed(self) -> None:
        if self.game is None or self.game.phase == "game_over":
            return
        if self.saved_turns_taken != self.game.turns_taken:
            self.saved_turns_taken = self.game.turns_taken
            save_game(self.game)

    def _record_finished_game_once(self) -> None:
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
        self.window.fill(BG)
        if self.screen == "setup":
            self._draw_setup()
        elif self.screen == "playing":
            self._draw_playing()
        else:
            self._draw_game_over()

    def _draw_setup(self) -> None:
        self.buttons = self.setup_buttons()
        mouse = pygame.mouse.get_pos()
        ui.draw_text(self.window, self.fonts["huge"], "LUDO", (450, 92), WHITE, center=True)
        ui.draw_wrapped(
            self.window,
            self.fonts["body"],
            "Classic competitive Ludo for 4 to 6 players. Choose how many seats are human; the remaining seats use heuristic AI.",
            pygame.Rect(170, 138, 560, 80),
            SOFT,
        )
        _draw_preview_board(self.window)

        panel = pygame.Rect(PANEL_X, 0, PANEL_WIDTH + 30, SCREEN_HEIGHT)
        pygame.draw.rect(self.window, PANEL_BG, panel)
        ui.draw_text(self.window, self.fonts["title"], "Setup", (PANEL_X + 24, 42), WHITE)
        self._setup_value("Total Players", str(self.total_players), 128)
        self._setup_value("Human Players", str(self.human_count), 200)
        self._setup_value("AI Profile", self.ai_profiles[self.ai_profile_index].title(), 272)

        ui.draw_text(self.window, self.fonts["header"], "Advanced Rules", (PANEL_X + 24, 354), WHITE)
        ui.draw_text(self.window, self.fonts["header"], "Human Names", (PANEL_X + 24, 584), WHITE)
        for index in range(self.human_count):
            rect = _name_rect(index)
            color = PLAYER_COLORS[index]
            pygame.draw.rect(self.window, PANEL_CARD, rect, border_radius=6)
            pygame.draw.rect(self.window, color if self.active_field == index else PANEL_EDGE, rect, 2, border_radius=6)
            ui.draw_text(self.window, self.fonts["body"], self.name_fields[index], (rect.x + 10, rect.y + 8), WHITE)

        for button in self.buttons:
            button.draw(self.window, self.fonts, mouse)

    def _setup_value(self, label: str, value: str, y: int) -> None:
        ui.draw_text(self.window, self.fonts["body"], label, (PANEL_X + 24, y), SOFT)
        ui.draw_text(self.window, self.fonts["header"], value, (PANEL_X + 146, y + 38), WHITE, center=True)

    def _draw_playing(self) -> None:
        if self.game is None or self.renderer is None:
            return
        self.visible_moves = []
        if self.game.current_player.is_human and self.game.awaiting == "choose_move" and self.game.last_roll is not None:
            self.visible_moves = self.game.legal_moves(self.game.last_roll)
        self.renderer.draw(self.window, self.game, self.fonts, self.visible_moves, self.token_pixels)

        panel = pygame.Rect(PANEL_X, 0, PANEL_WIDTH + 30, SCREEN_HEIGHT)
        pygame.draw.rect(self.window, PANEL_BG, panel)
        self._draw_score_panel()
        self._draw_action_panel()
        self.buttons = self._buttons_for_screen()
        mouse = pygame.mouse.get_pos()
        for button in self.buttons:
            button.draw(self.window, self.fonts, mouse)

    def _draw_score_panel(self) -> None:
        if self.game is None:
            return
        y = 22
        for index, player in enumerate(self.game.players):
            rect = pygame.Rect(PANEL_X + 14, y, PANEL_WIDTH + 2, 60)
            border = player.color if index == self.game.current else PANEL_EDGE
            ui.draw_panel(self.window, rect, border=border)
            pygame.draw.circle(self.window, player.color, (rect.x + 26, rect.y + 26), 14)
            ui.draw_text(self.window, self.fonts["body"], player.name[:20], (rect.x + 50, rect.y + 12), WHITE)
            tag = "Human" if player.is_human else self.game.ai_profile.title()
            done = player.finished_count(self.game.layout.finish_steps)
            ui.draw_text(
                self.window,
                self.fonts["tiny"],
                f"{tag}  Home {done}/4  Captures {player.captures}",
                (rect.x + 50, rect.y + 42),
                SOFT,
            )
            y += 66

    def _draw_action_panel(self) -> None:
        if self.game is None:
            return
        action = pygame.Rect(PANEL_X + 14, 610, PANEL_WIDTH + 2, 264)
        ui.draw_panel(self.window, action)
        ui.draw_text(self.window, self.fonts["header"], "Turn", (action.x + 18, action.y + 16), WHITE)
        current = self.game.current_player
        ui.draw_text(self.window, self.fonts["body"], current.name, (action.x + 18, action.y + 50), current.color)
        die_value = self.game.last_roll
        if self.dice_anim_remaining > 0:
            die_value = ((pygame.time.get_ticks() // 70) % 6) + 1
        ui.draw_dice(self.window, self.fonts, die_value, pygame.Rect(action.right - 102, action.y + 24, 72, 72))

        if current.is_human and self.game.awaiting == "choose_move":
            prompt = "Pick a highlighted token or use the move buttons."
        elif current.is_human:
            prompt = "Roll the die."
        else:
            prompt = "AI is thinking..."
        ui.draw_wrapped(self.window, self.fonts["small"], prompt, pygame.Rect(action.x + 18, action.y + 106, action.width - 36, 42), SOFT)

        log_rect = pygame.Rect(action.x + 18, action.y + 150, action.width - 36, 96)
        pygame.draw.rect(self.window, (26, 34, 38), log_rect, border_radius=8)
        pygame.draw.rect(self.window, PANEL_EDGE, log_rect, 1, border_radius=8)
        y = log_rect.y + 10
        for line in self.game.event_log[-6:]:
            ui.draw_text(self.window, self.fonts["tiny"], line[:54], (log_rect.x + 10, y), ui.status_color(line))
            y += 24

    def _buttons_for_screen(self) -> list[ui.Button]:
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
        x = PANEL_X + 32
        if self.game.current_player.is_human and self.game.awaiting == "pre_roll":
            buttons.append(ui.Button(pygame.Rect(x, 454, 238, 42), "Roll Die  (R)", "roll"))
        elif self.game.current_player.is_human and self.game.awaiting == "choose_move":
            for index, move in enumerate(self.visible_moves[:4]):
                label = f"{index + 1}: Token {move.token_index + 1} -> {move.to_steps}"
                buttons.append(ui.Button(pygame.Rect(x, 422 + index * 42, 238, 38), label, f"move_{index}"))
        buttons.append(ui.Button(pygame.Rect(x, 804, 238, 42), "Save & Quit", "save_quit"))
        buttons.append(ui.Button(pygame.Rect(x, 850, 238, 34), "New Game", "new_game"))
        return buttons

    def _draw_game_over(self) -> None:
        if self.game is None:
            self.screen = "setup"
            return
        self.buttons = self._buttons_for_screen()
        mouse = pygame.mouse.get_pos()
        winner = self.game.players[self.game.winner] if self.game.winner is not None else self.game.players[0]
        ui.draw_text(self.window, self.fonts["huge"], "Game Over", (450, 104), WHITE, center=True)
        ui.draw_text(self.window, self.fonts["title"], f"{winner.name} wins!", (450, 174), winner.color, center=True)

        table = pygame.Rect(210, 248, 480, 360)
        ui.draw_panel(self.window, table)
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
        pygame.draw.rect(self.window, PANEL_BG, (PANEL_X, 0, PANEL_WIDTH + 30, SCREEN_HEIGHT))
        ui.draw_panel(self.window, stats)
        ui.draw_text(self.window, self.fonts["header"], "Lifetime Stats", (stats.x + 18, stats.y + 18), WHITE)
        games = max(1, int(self.stats.get("games", 0)))
        average_turns = int(self.stats.get("turn_total", 0)) / games
        lines = [
            f"Games: {self.stats.get('games', 0)}",
            f"Human wins: {self.stats.get('human_wins', 0)}",
            f"AI wins: {self.stats.get('ai_wins', 0)}",
            f"Average turns: {average_turns:.1f}",
            f"4P / 5P / 6P: {self.stats.get('by_player_count', {}).get('4', 0)} / {self.stats.get('by_player_count', {}).get('5', 0)} / {self.stats.get('by_player_count', {}).get('6', 0)}",
        ]
        for offset, line in enumerate(lines):
            ui.draw_text(self.window, self.fonts["body"], line, (stats.x + 18, stats.y + 70 + offset * 42), SOFT)
        ui.draw_wrapped(
            self.window,
            self.fonts["small"],
            "Captures, exact home rolls, bonus turns, and safe squares all used the same engine rules as the live game.",
            pygame.Rect(stats.x + 18, stats.y + 316, stats.width - 36, 88),
            SOFT,
        )
        for button in self.buttons:
            button.draw(self.window, self.fonts, mouse)


def _name_rect(index: int) -> pygame.Rect:
    return pygame.Rect(PANEL_X + 24, 628 + index * 42, 246, 34)


def _toggle_label(label: str, enabled: bool) -> str:
    return f"{label}: {'On' if enabled else 'Off'}"


def _make_icon() -> pygame.Surface:
    icon = pygame.Surface((64, 64), pygame.SRCALPHA)
    pygame.draw.rect(icon, (238, 232, 209), (4, 4, 56, 56), border_radius=12)
    for index, color in enumerate(PLAYER_COLORS[:4]):
        x = 22 + (index % 2) * 20
        y = 22 + (index // 2) * 20
        pygame.draw.circle(icon, color, (x, y), 9)
    return icon


def _draw_preview_board(surface: pygame.Surface) -> None:
    center = (450, 476)
    radius = 210
    for sides, x_offset in ((4, -250), (5, 0), (6, 250)):
        points = []
        cx = center[0] + x_offset
        cy = center[1]
        for index in range(sides):
            angle = -math.pi / 2 + math.tau * index / sides
            points.append((int(cx + math.cos(angle) * radius * 0.42), int(cy + math.sin(angle) * radius * 0.42)))
        pygame.draw.polygon(surface, (238, 232, 209), points)
        pygame.draw.polygon(surface, PLAYER_COLORS[sides - 4], points, 4)
        ui.draw_text(surface, pygame.font.SysFont("arial", 24, bold=True), f"{sides}P", (cx, cy), WHITE, center=True)


def main() -> None:
    pygame.init()
    try:
        app = LudoApp()
        max_frames = 8 if os.environ.get("LUDO_AUTOTEST") else None
        app.run(max_frames=max_frames)
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
