"""Program entry point: the window, the run loop, input, and the AI driver.

`main.py` wires the parts together. It owns the pygame window, decides which
screen to show, turns clicks into engine actions for human players, and steps
the AI on a timer so a person can watch its moves.

A headless self-test runs when the MONOPOLY_AUTOTEST environment variable is
set: a full four-AI game is played in a hidden window for a few hundred
frames, which exercises the engine, the AI and all the drawing code at once.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time

import pygame

import ai
import board_data
import board_render
import ui
from game import MonopolyGame
from board_data import THEME_ORDER
from settings import (
    AI_TURN_DELAY_MS, BG, FPS, SAVE_DIR, SAVEGAME_PATH, SCREEN_HEIGHT,
    SCREEN_WIDTH, STATS_PATH, WINDOW_TITLE,
)

# Action-bar button slots: two columns by four rows inside the bottom panel.
# The prompt text now sits in its own strip ABOVE the bar (drawn by
# `ui.draw_action_bar`), so the first row of buttons can start at the very
# top of the bar without ever covering the prompt.
_BAR_COLS = (892, 1086)
_BAR_ROWS = (700, 748, 796, 844)
_BTN_W, _BTN_H = 182, 40


def _bar_rect(slot: int):
    """Return the rectangle for action-bar button number `slot` (0-7)."""
    col = _BAR_COLS[slot % 2]
    row = _BAR_ROWS[slot // 2]
    return pygame.Rect(col, row, _BTN_W, _BTN_H)


def _resource_path(name: str) -> str:
    """Path to a bundled resource, working from source or a frozen .exe."""
    base = getattr(sys, "_MEIPASS", None)
    base_dir = base if base else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, name)


# --------------------------------------------------------------------------
# Persistence: lifetime stats and the single saved game
# --------------------------------------------------------------------------
def _log_error(error: Exception) -> None:
    """Record a save/load failure to a log file instead of failing silently."""
    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with (SAVE_DIR / "error.log").open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {error}\n")
    except OSError:
        pass


def _atomic_write(path, payload: dict) -> None:
    """Write JSON via a temp file + os.replace, so a crash cannot corrupt it."""
    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as error:
        _log_error(error)


def load_stats() -> dict:
    """Read lifetime stats, returning zeros if none are saved yet."""
    try:
        data = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        return {"games": int(data.get("games", 0)),
                "human_wins": int(data.get("human_wins", 0))}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"games": 0, "human_wins": 0}


def save_game(game: MonopolyGame) -> None:
    """Write the current game to disk so it can be resumed later."""
    _atomic_write(SAVEGAME_PATH, game.to_dict())


def load_saved_game() -> MonopolyGame | None:
    """Load the saved game, or return None if there is no valid save."""
    try:
        data = json.loads(SAVEGAME_PATH.read_text(encoding="utf-8"))
        return MonopolyGame.from_dict(data)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def has_saved_game() -> bool:
    """True if a saved game file exists on disk."""
    return SAVEGAME_PATH.exists()


def _clear_saved_game() -> None:
    """Delete the saved game (called when a game finishes)."""
    try:
        SAVEGAME_PATH.unlink(missing_ok=True)
    except OSError:
        pass


# --------------------------------------------------------------------------
# The application
# --------------------------------------------------------------------------
class MonopolyApp:
    """Owns the window and run loop and routes input to the game engine."""

    def __init__(self):
        # `SCALED` lets pygame stretch our logical 1280x880 surface to fit the
        # physical screen when we toggle into fullscreen (with letterboxing
        # for aspect-ratio mismatch). It also makes `event.pos` and
        # `pygame.mouse.get_pos()` keep reporting logical 1280x880
        # coordinates in BOTH windowed and fullscreen modes, so the existing
        # hit-detection just works on either.
        self.window = pygame.display.set_mode(
            (SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SCALED)
        pygame.display.set_caption(WINDOW_TITLE)
        self.clock = pygame.time.Clock()
        self.fonts = ui.make_fonts()
        self.running = True

        # Screen state: "setup", "playing" or "over".
        self.screen = "setup"
        self.game: MonopolyGame | None = None
        self.renderer: board_render.BoardRenderer | None = None

        # Setup-screen choices.
        self.human_count = 1
        self.theme_index = 0
        self.ai_profile_keys = tuple(ai.AI_PROFILES)
        self.ai_profile_index = self.ai_profile_keys.index("standard")
        # Editable human-player names. The list is kept at length 4 so
        # toggling the human count down then back up restores prior entries.
        self.name_fields = ["Player 1", "Player 2", "Player 3", "Player 4"]
        self.active_field: int | None = None    # focused name box, or None
        self.confirm_new_game = False           # is the overwrite modal open?

        # In-game interaction state.
        self.mode = "normal"   # "normal", "build", "sell", "mortgage", "assets", "trade"
        self.trade: dict | None = None
        self.asset_position: int | None = None
        self.ai_timer = 0
        self.message = ""
        self.stats = load_stats()
        self.buttons: list = []
        self._autosave_current: int | None = None   # last-seen turn marker

        # Visual polish: tokens slide between spaces and the dice shuffle on
        # a roll instead of snapping to their final value. The AI pauses
        # while either animation is running so a person can follow play.
        self.token_px: dict = {}                 # player index -> (x, y) float pixels
        self.dice_show = (0, 0)                  # what the UI is currently drawing
        self.dice_anim_remaining_ms = 0          # >0 while the dice shuffle
        self.last_game_dice = (0, 0)             # used to spot a fresh roll

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------
    def start_game(self, game: MonopolyGame) -> None:
        """Switch to the playing screen with `game`."""
        self.game = game
        self.renderer = board_render.BoardRenderer(game.board)
        self.renderer.build_base(self.fonts)
        self.screen = "playing"
        self.mode = "normal"
        self.asset_position = None
        self.ai_timer = 0
        self.message = ""
        # Reset the visuals so the next frame places tokens / dice from scratch.
        self.token_px = {}
        self.dice_show = (0, 0)
        self.dice_anim_remaining_ms = 0
        self.last_game_dice = (0, 0)
        # Autosave baseline: a save fires when the turn (current player) moves.
        self._autosave_current = game.current

    def _end_game(self) -> None:
        """Record the result and move to the end screen."""
        self.screen = "over"
        self.stats["games"] += 1
        if self.game.winner is not None and self.game.players[self.game.winner].is_human:
            self.stats["human_wins"] += 1
        _atomic_write(STATS_PATH, self.stats)
        _clear_saved_game()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self, max_frames: int | None = None) -> None:
        """Run the game until the window is closed (or a frame limit is hit)."""
        frames = 0
        autotest = max_frames is not None
        while self.running:
            self.clock.tick(FPS)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self._handle_click(event.pos)
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    # F11 toggles fullscreen. The SCALED flag set at startup
                    # keeps logical coordinates intact, so we don't need to
                    # remap anything ourselves.
                    pygame.display.toggle_fullscreen()
                elif event.type == pygame.KEYDOWN and self.screen == "playing":
                    self._handle_shortcut(event.key)
                elif (event.type == pygame.KEYDOWN and self.screen == "setup"
                      and self.active_field is not None
                      and not self.confirm_new_game):
                    # Typing into a focused human-name box on the setup screen.
                    self._type_into_name_field(event)
                elif (event.type == pygame.MOUSEWHEEL
                      and self.mode == "trade" and self.trade is not None):
                    # Scroll whichever side of the trade dialog the cursor
                    # is over. event.y > 0 means the wheel rolled up.
                    self._scroll_trade(pygame.mouse.get_pos(), event.y)
            self._update(autotest)
            self._draw()
            pygame.display.flip()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                break

    def _update(self, autotest: bool) -> None:
        """Advance the game: animate visuals, then step the AI if it is its turn."""
        if self.screen != "playing" or self.game is None:
            return
        if self.game.phase == "game_over":
            self._end_game()
            return

        # Autosave once per completed turn: the engine advances `current` to
        # the next player when a turn ends, for both humans and AI.
        if self.game.current != self._autosave_current:
            self._autosave_current = self.game.current
            save_game(self.game)

        elapsed = self.clock.get_time()

        # Token sliding: each token's drawn pixel position eases toward the
        # centre of its actual board space. On the first frame after the game
        # starts the table is empty, so seed each token at its target.
        if not self.token_px:
            for player in self.game.players:
                self.token_px[player.index] = board_render.token_center(
                    player.position, player.index)
        animating_tokens = False
        for player in self.game.players:
            target = board_render.token_center(player.position, player.index)
            cx, cy = self.token_px[player.index]
            nx = cx + (target[0] - cx) * 0.22
            ny = cy + (target[1] - cy) * 0.22
            self.token_px[player.index] = (nx, ny)
            if abs(nx - target[0]) > 1.5 or abs(ny - target[1]) > 1.5:
                animating_tokens = True

        # Dice shuffle: when the engine reports a new roll, randomise the
        # displayed dice for a short moment before settling on the real value.
        if self.game.dice != self.last_game_dice and self.game.dice != (0, 0):
            self.dice_anim_remaining_ms = 480
            self.last_game_dice = self.game.dice
        if self.dice_anim_remaining_ms > 0:
            self.dice_anim_remaining_ms -= elapsed
            self.dice_show = (random.randint(1, 6), random.randint(1, 6))
        else:
            self.dice_show = self.game.dice

        # AI driver: pace it, and pause while an animation is still playing.
        actor = self.game.players[self.game.actor()]
        if actor.is_human:
            return                       # wait for the human's clicks
        if not autotest and (animating_tokens or self.dice_anim_remaining_ms > 0):
            return
        self.ai_timer += elapsed
        if autotest or self.ai_timer >= AI_TURN_DELAY_MS:
            self.ai_timer = 0
            ai.take_action(self.game)

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def _handle_click(self, pos) -> None:
        """Route a left-click to the right handler for the current screen."""
        if self.screen == "setup":
            self._click_setup(pos)
        elif self.screen == "over":
            self._click_button(pos)
        elif self.screen == "playing":
            actor = self.game.players[self.game.actor()]
            if not actor.is_human:
                return                   # ignore clicks during AI turns
            if self.mode in ("build", "sell", "mortgage"):
                if not self._click_button(pos):      # the "Done" button
                    self._click_board(pos)
            elif self.mode == "assets":
                self._click_button(pos)
            elif self.mode == "trade":
                self._click_trade(pos)
            else:
                self._click_button(pos)

    def _click_button(self, pos) -> bool:
        """Check the current buttons; act on the first one hit."""
        for button in self.buttons:
            if button.hit(pos):
                self._on_button(button.key)
                return True
        return False

    def _click_setup(self, pos) -> None:
        """Route a setup-screen click: modal buttons, buttons, or a name box."""
        if self.confirm_new_game:
            self._click_button(pos)          # only the modal Yes/Cancel react
            return
        if self._click_button(pos):
            return
        # A click that missed every button may be focusing a name box.
        self.active_field = None
        for i in range(self.human_count):
            if ui.setup_name_field_rect(i).collidepoint(pos):
                self.active_field = i
                return

    def _type_into_name_field(self, event) -> None:
        """Apply one keystroke to the focused setup-screen name box."""
        i = self.active_field
        if i is None:
            return
        if event.key == pygame.K_BACKSPACE:
            self.name_fields[i] = self.name_fields[i][:-1]
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER,
                           pygame.K_ESCAPE, pygame.K_TAB):
            self.active_field = None
        elif event.unicode and event.unicode.isprintable() \
                and len(self.name_fields[i]) < 14:
            self.name_fields[i] += event.unicode

    def _click_board(self, pos) -> None:
        """In build/sell/mortgage mode, act on the board space clicked."""
        for position in range(40):
            if board_render.space_rect(position).collidepoint(pos):
                if self.mode == "build":
                    self.game.build_house(position)
                elif self.mode == "sell":
                    self.game.sell_house(position)
                elif self.mode == "mortgage":
                    if position in self.game.mortgaged:
                        self.game.unmortgage(position)
                    else:
                        self.game.mortgage(position)
                return

    def _click_trade(self, pos) -> None:
        """Handle clicks inside the trade-building dialog."""
        if self._click_button(pos):
            return
        layout = ui.trade_layout(self.game, self.trade)
        for key, side in (("give_rows", "give"), ("get_rows", "get")):
            for row, position in layout[key]:
                if row.collidepoint(pos):
                    props = self.trade[side]["props"]
                    if position in props:
                        props.remove(position)
                    else:
                        props.append(position)
                    return

    def _on_button(self, key: str) -> None:
        """Carry out the action bound to a button `key`."""
        game = self.game
        if key == "humans_down":
            self.human_count = max(1, self.human_count - 1)
        elif key == "humans_up":
            self.human_count = min(4, self.human_count + 1)
        elif key == "theme_prev":
            self.theme_index = (self.theme_index - 1) % len(THEME_ORDER)
        elif key == "theme_next":
            self.theme_index = (self.theme_index + 1) % len(THEME_ORDER)
        elif key == "ai_profile_prev":
            self.ai_profile_index = (self.ai_profile_index - 1) % len(self.ai_profile_keys)
        elif key == "ai_profile_next":
            self.ai_profile_index = (self.ai_profile_index + 1) % len(self.ai_profile_keys)
        elif key == "start":
            # Guard the player's saved game: confirm before overwriting it.
            if has_saved_game():
                self.confirm_new_game = True
            else:
                self._begin_new_game()
        elif key == "confirm_new_yes":
            self.confirm_new_game = False
            self._begin_new_game()
        elif key == "confirm_new_no":
            self.confirm_new_game = False
        elif key == "resume":
            saved = load_saved_game()
            if saved is not None:
                self.start_game(saved)
        elif key == "roll":
            game.roll_dice()
        elif key == "jail_pay":
            game.pay_jail_fine()
        elif key == "jail_card":
            game.use_jail_card()
        elif key == "buy":
            game.buy_property()
        elif key == "auction_decline":
            game.decline_property()
        elif key == "build":
            self.mode = "build"
        elif key == "sell":
            self.mode = "sell"
        elif key == "mortgage":
            self.mode = "mortgage"
        elif key == "done":
            self.mode = "normal"
        elif key == "end_turn":
            game.end_turn()
        elif key == "save_quit":
            save_game(game)
            self.screen = "setup"
            self.game = None
        elif key == "bid":
            step = max(10, game.board[game.auction["position"]].price // 20)
            game.auction_bid(game.auction["high_bid"] + step)
        elif key == "pass":
            game.auction_pass()
        elif key == "trade":
            self._open_trade()
        elif key == "assets":
            self._open_assets()
        elif key.startswith("asset_title_"):
            self.asset_position = int(key.rsplit("_", 1)[1])
            self.message = ""
        elif key == "asset_build":
            self._manage_asset("build", game.build_house)
        elif key == "asset_sell":
            self._manage_asset("sell", game.sell_house)
        elif key == "asset_mortgage":
            self._manage_asset("mortgage", game.mortgage)
        elif key == "asset_unmortgage":
            self._manage_asset("unmortgage", game.unmortgage)
        elif key == "asset_close":
            self.mode = "normal"
            self.message = ""
        elif key == "trade_partner_prev":
            self._cycle_trade_partner(-1)
        elif key == "trade_partner_next":
            self._cycle_trade_partner(1)
        elif key == "give_cash_up":
            self._adjust_trade_cash("give", 50)
        elif key == "give_cash_down":
            self._adjust_trade_cash("give", -50)
        elif key == "get_cash_up":
            self._adjust_trade_cash("get", 50)
        elif key == "get_cash_down":
            self._adjust_trade_cash("get", -50)
        elif key == "trade_propose":
            if game.propose_trade(self.trade):
                self.mode = "normal"
            else:
                self.message = game.trade_error(self.trade) or "That trade is not legal."
        elif key == "trade_cancel":
            self.mode = "normal"
        elif key == "trade_accept":
            game.respond_trade(True)
        elif key == "trade_reject":
            game.respond_trade(False)
        elif key == "new_game":
            self.screen = "setup"
            self.game = None
        elif key == "quit":
            self.running = False

    def _begin_new_game(self) -> None:
        """Create a fresh game from the setup-screen choices."""
        # Give each AI a short name so the log and panels read pleasantly.
        ai_names = ["Iris", "Knox", "Mira", "Quill"]
        specs = []
        for i in range(4):
            human = i < self.human_count
            if human:
                # Fall back to "Player N" if the name box was left blank.
                name = self.name_fields[i].strip() or f"Player {i + 1}"
            else:
                name = f"{ai_names[i]} (AI)"
            specs.append((name, human))
        theme = THEME_ORDER[self.theme_index]
        profile = self.ai_profile_keys[self.ai_profile_index]
        self.start_game(MonopolyGame(specs, theme=theme, ai_profile=profile))

    def _open_trade(self) -> None:
        """Start building a trade offer from the current human player."""
        me = self.game.current
        others = [p.index for p in self.game.players
                  if p.index != me and not p.bankrupt]
        if not others:
            self.message = "There is no one to trade with."
            return
        self.mode = "trade"
        self.trade = {
            "from": me, "to": others[0],
            "give": {"props": [], "cash": 0, "jail": 0},
            "get": {"props": [], "cash": 0, "jail": 0},
            # Per-side scroll offsets for the property row lists. Used when
            # the player owns more properties than fit in the visible window.
            "give_scroll": 0,
            "get_scroll": 0,
        }

    def _open_assets(self) -> None:
        """Open the title manager with the first owned title selected."""
        owned = sorted(self.game.properties_of(self.game.current_player))
        if not owned:
            self.message = "You do not own any titles yet."
            return
        self.mode = "assets"
        self.asset_position = owned[0]
        self.message = ""

    def _manage_asset(self, action: str, operation) -> None:
        """Run one engine asset action or show the engine's blocker reason."""
        if self.asset_position is None:
            self.message = "Choose a title first."
            return
        player = self.game.current_player
        status = self.game.asset_actions_for(player, self.asset_position)[action]
        if not status["allowed"]:
            self.message = status["reason"]
            return
        if not operation(self.asset_position):
            self.message = status["reason"] or "That asset action did not resolve."
            return
        self.message = ""

    def _cycle_trade_partner(self, step: int) -> None:
        """Move the trade to another eligible partner; clear chosen items."""
        others = [p.index for p in self.game.players
                  if p.index != self.trade["from"] and not p.bankrupt]
        if not others:
            return
        current = others.index(self.trade["to"]) if self.trade["to"] in others else 0
        self.trade["to"] = others[(current + step) % len(others)]
        self.trade["give"]["props"].clear()
        self.trade["get"]["props"].clear()
        # A new partner usually has a different property list -- reset scroll
        # so the next dialog opens at the top of both columns.
        self.trade["give_scroll"] = 0
        self.trade["get_scroll"] = 0

    def _adjust_trade_cash(self, side: str, delta: int) -> None:
        """Step the cash on one side of the in-progress trade offer."""
        idx = self.trade["from"] if side == "give" else self.trade["to"]
        cap = self.game.players[idx].cash
        self.trade[side]["cash"] = max(0, min(cap, self.trade[side]["cash"] + delta))

    def _scroll_trade(self, mouse_pos, wheel_dy: int) -> None:
        """Scroll one side of the trade dialog under the mouse cursor.

        Wheeling up (`wheel_dy > 0`) moves the visible window UP the list
        (decreases the scroll offset). The offset is clamped so the player
        cannot scroll past the last full window.
        """
        if self.trade is None:
            return
        panel = ui.trade_layout(self.game, self.trade)["panel"]
        side = "give" if mouse_pos[0] < panel.centerx else "get"
        owner_idx = self.trade["from"] if side == "give" else self.trade["to"]
        owner = self.game.players[owner_idx]
        max_scroll = max(0, len(self.game.properties_of(owner))
                         - ui.TRADE_VISIBLE_ROWS)
        key = f"{side}_scroll"
        current = self.trade.get(key, 0)
        step = -1 if wheel_dy > 0 else 1
        self.trade[key] = max(0, min(current + step, max_scroll))

    def _handle_shortcut(self, key: int) -> None:
        """Run common human actions from the keyboard when they are available."""
        if self.game is None:
            return
        actor = self.game.players[self.game.actor()]
        if not actor.is_human or self.mode in ("assets", "trade"):
            return
        key_to_action = {
            pygame.K_r: "roll",
            pygame.K_b: "build",
            pygame.K_s: "sell",
            pygame.K_m: "mortgage",
            pygame.K_t: "trade",
            pygame.K_e: "end_turn",
        }
        action = key_to_action.get(key)
        if action is None:
            return
        available = {button.key for button in self._build_buttons() if button.enabled}
        if action in available:
            self._on_button(action)

    def _hovered_board_space(self, pos) -> int | None:
        """Return the board space under `pos`, if the mouse is on the board."""
        for position in range(40):
            if board_render.space_rect(position).collidepoint(pos):
                return position
        return None

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def _draw(self) -> None:
        """Draw the current screen."""
        mouse = pygame.mouse.get_pos()
        self.buttons = self._build_buttons()
        if self.screen == "setup":
            theme = THEME_ORDER[self.theme_index]
            ui.draw_setup(self.window, self.fonts, self.human_count, theme,
                          self.buttons, mouse, self.stats, self.name_fields,
                          self.active_field,
                          self.ai_profile_keys[self.ai_profile_index])
            if self.confirm_new_game:
                ui.draw_confirm(
                    self.window, self.fonts,
                    ["A saved game will be overwritten.", "Start a new game?"],
                    self.buttons, mouse)
        elif self.screen == "over":
            ui.draw_game_over(self.window, self.fonts, self.game, self.buttons, mouse)
        elif self.screen == "playing":
            self._draw_playing(mouse)

    def _draw_playing(self, mouse) -> None:
        """Draw the board, side panel, action bar and any open dialog."""
        self.window.fill(BG)

        # Yellow rings on the spaces the human can act on in board-click modes.
        highlights: list = []
        if self.mode == "build":
            human = self.game.current_player
            highlights = [pos for pos in range(40)
                          if self.game.can_build(human, pos)]
        elif self.mode == "mortgage":
            human = self.game.current_player
            highlights = [pos for pos in self.game.properties_of(human)
                          if self.game.houses.get(pos, 0) == 0]
        elif self.mode == "sell":
            human = self.game.current_player
            highlights = [pos for pos in self.game.properties_of(human)
                          if self.game.can_sell_building(human, pos)]

        self.renderer.draw(self.window, self.game, self.fonts,
                           token_pixels=self.token_px,
                           highlight_positions=highlights)
        ui.draw_panel(self.window, self.fonts, self.game, mouse)

        board_centre = (20 + (SCREEN_HEIGHT - 40) // 2, 20 + (SCREEN_HEIGHT - 40) // 2)
        ui.draw_center_card(self.window, self.fonts, self.game)
        if self.dice_show != (0, 0):
            ui.draw_dice(self.window, self.fonts, self.dice_show, board_centre)
        hovered = self._hovered_board_space(mouse)
        if hovered is not None:
            ui.draw_property_detail(self.window, self.fonts, self.game, hovered)

        ui.draw_action_bar(self.window, self.fonts, self.buttons,
                           self._prompt(), mouse)

        # Modal dialogs on top of everything else.
        if self.game.awaiting == "auction":
            ui.draw_auction(self.window, self.fonts, self.game, self.buttons, mouse)
        elif self.mode == "assets":
            ui.draw_assets(self.window, self.fonts, self.game, self.asset_position,
                           self.buttons, mouse)
        elif self.mode == "trade" and self.trade is not None:
            ui.draw_trade(self.window, self.fonts, self.game, self.trade,
                          self.buttons, mouse)
        elif self.game.awaiting == "trade_response" and \
                self.game.players[self.game.actor()].is_human:
            ui.draw_trade_response(self.window, self.fonts, self.game,
                                   self.buttons, mouse)

    def _prompt(self) -> str:
        """A short instruction line for the action bar."""
        game = self.game
        actor = game.players[game.actor()]
        if not actor.is_human:
            # AI player names already carry an "(AI)" suffix -- don't add it
            # again here or the prompt reads "Mira (AI) (AI) is taking...".
            return f"{actor.name} is taking their turn..."
        if self.mode == "build":
            return "Click a property in one of your monopolies to build. Then Done."
        if self.mode == "mortgage":
            return "Click a property to mortgage it, or a mortgaged one to lift it."
        if self.mode == "sell":
            return "Click a developed street to sell one building back. Then Done."
        if self.mode == "assets":
            return self.message or "Manage one title with deed detail and legal actions."
        if self.message:
            return self.message
        state = game.awaiting
        if state == "pre_roll":
            if actor.in_jail:
                return f"{actor.name}: you are in Jail. Pay, use a card, or roll."
            return f"{actor.name}: your turn. Roll the dice."
        if state == "buy_or_auction":
            space = game.board[game.pending_purchase]
            return f"You landed on {space.name} (${space.price}). Buy it or auction it."
        if state == "auction":
            return game.auction_context_message()
        if state == "post_roll":
            return f"{actor.name}: build, trade, or end your turn."
        if state == "trade_response":
            return "You have received a trade offer."
        return ""

    def _build_buttons(self) -> list:
        """Build the buttons appropriate to the current screen and state."""
        if self.screen == "setup":
            if self.confirm_new_game:
                return ui.confirm_buttons()
            return ui.setup_buttons(has_saved_game())
        if self.screen == "over":
            return [
                ui.Button((SCREEN_WIDTH // 2 - 220, 540, 200, 52), "New Game",
                          "new_game", color=(46, 116, 78)),
                ui.Button((SCREEN_WIDTH // 2 + 20, 540, 200, 52), "Quit", "quit"),
            ]
        if self.screen != "playing" or self.game is None:
            return []
        return self._playing_buttons()

    def _playing_buttons(self) -> list:
        """Build the in-game buttons for the current player and state."""
        game = self.game
        actor = game.players[game.actor()]
        if not actor.is_human:
            return []

        # Trade dialog buttons.
        if self.mode == "trade" and self.trade is not None:
            panel = ui.trade_layout(game, self.trade)["panel"]
            return [
                # Arrows are placed symmetrically and well clear of the
                # centred "With: NAME" label, however wide the name is.
                ui.Button((panel.centerx - 200, panel.y + 54, 30, 26), "<",
                          "trade_partner_prev"),
                ui.Button((panel.centerx + 170, panel.y + 54, 30, 26), ">",
                          "trade_partner_next"),
                # Cash buttons sit directly under each column so the "Give"
                # pair aligns with the give-side row list (x = panel.x + 30)
                # and the "Get" pair aligns with the get-side rows
                # (x = panel.x + 420 in the widened panel).
                ui.Button((panel.x + 30, panel.bottom - 104, 130, 30), "Give -$50",
                          "give_cash_down"),
                ui.Button((panel.x + 170, panel.bottom - 104, 130, 30), "Give +$50",
                          "give_cash_up"),
                ui.Button((panel.x + 420, panel.bottom - 104, 130, 30), "Get -$50",
                          "get_cash_down"),
                ui.Button((panel.x + 560, panel.bottom - 104, 130, 30), "Get +$50",
                          "get_cash_up"),
                ui.Button((panel.centerx - 210, panel.bottom - 56, 190, 40),
                          "Propose", "trade_propose", color=(46, 116, 78)),
                ui.Button((panel.centerx + 20, panel.bottom - 56, 190, 40),
                          "Cancel", "trade_cancel"),
            ]

        # Asset manager buttons: every title row selects a deed; the action
        # buttons below use engine-provided availability and blocker reasons.
        if self.mode == "assets":
            layout = ui.asset_layout(game, actor)
            buttons = []
            for row, position in layout["title_rows"]:
                color = (70, 96, 64) if position == self.asset_position else None
                buttons.append(ui.Button(
                    row, game.board[position].name[:24], f"asset_title_{position}",
                    color=color))
            panel = layout["panel"]
            actions = (game.asset_actions_for(actor, self.asset_position)
                       if self.asset_position is not None else {})
            action_specs = (
                ("Build", "asset_build", "build", (panel.x + 492, panel.bottom - 154)),
                ("Sell", "asset_sell", "sell", (panel.x + 654, panel.bottom - 154)),
                ("Mortgage", "asset_mortgage", "mortgage",
                 (panel.x + 492, panel.bottom - 104)),
                ("Lift Mortgage", "asset_unmortgage", "unmortgage",
                 (panel.x + 654, panel.bottom - 104)),
            )
            for label, key, action, (x, y) in action_specs:
                status = actions.get(action, {"allowed": False})
                buttons.append(ui.Button((x, y, 148, 38), label, key,
                                         enabled=bool(status["allowed"])))
            buttons.append(ui.Button((panel.right - 116, panel.y + 18, 84, 32),
                                     "Close", "asset_close"))
            return buttons

        # Trade-response dialog buttons.
        if game.awaiting == "trade_response":
            panel = pygame.Rect(0, 0, 560, 360)
            panel.center = (SCREEN_HEIGHT // 2, SCREEN_HEIGHT // 2)
            return [
                ui.Button((panel.centerx - 210, panel.bottom - 56, 190, 40),
                          "Accept", "trade_accept", color=(46, 116, 78)),
                ui.Button((panel.centerx + 20, panel.bottom - 56, 190, 40),
                          "Reject", "trade_reject", color=(150, 60, 60)),
            ]

        # Auction dialog buttons.
        if game.awaiting == "auction":
            panel = pygame.Rect(0, 0, 460, 280)
            panel.center = (SCREEN_HEIGHT // 2, SCREEN_HEIGHT // 2)
            step = max(10, game.board[game.auction["position"]].price // 20)
            can_bid = (game.auction["high_bid"] + step) <= actor.cash
            return [
                ui.Button((panel.centerx - 200, panel.bottom - 52, 190, 40),
                          f"Bid +${step}", "bid", enabled=can_bid,
                          color=(46, 116, 78)),
                ui.Button((panel.centerx + 10, panel.bottom - 52, 190, 40),
                          "Pass", "pass", color=(150, 60, 60)),
            ]

        # Build / sell / mortgage mode: just a Done button.
        if self.mode in ("build", "sell", "mortgage"):
            return [ui.Button(_bar_rect(0), "Done", "done", color=(46, 116, 78))]

        # Normal action bar.
        buttons = []
        state = game.awaiting
        can_sell = any(game.can_sell_building(actor, pos)
                       for pos in game.properties_of(actor))
        if state == "pre_roll":
            if actor.in_jail:
                buttons.append(ui.Button(_bar_rect(0), "Roll Dice", "roll",
                                         color=(46, 116, 78)))
                buttons.append(ui.Button(_bar_rect(1), "Pay $50", "jail_pay",
                                         enabled=actor.cash >= 50))
                buttons.append(ui.Button(_bar_rect(2), "Use Jail Card", "jail_card",
                                         enabled=actor.jail_cards > 0))
            else:
                buttons.append(ui.Button(_bar_rect(0), "Roll Dice", "roll",
                                         color=(46, 116, 78)))
                buttons.append(ui.Button(_bar_rect(1), "Build Houses", "build"))
                buttons.append(ui.Button(_bar_rect(2), "Sell Buildings", "sell",
                                         enabled=can_sell))
                buttons.append(ui.Button(_bar_rect(3), "Mortgage", "mortgage"))
                buttons.append(ui.Button(_bar_rect(4), "Trade", "trade"))
                buttons.append(ui.Button(_bar_rect(5), "Save & Quit", "save_quit"))
                buttons.append(ui.Button(_bar_rect(6), "Assets", "assets"))
        elif state == "buy_or_auction":
            space = game.board[game.pending_purchase]
            buttons.append(ui.Button(_bar_rect(0), f"Buy (${space.price})", "buy",
                                     enabled=actor.cash >= space.price,
                                     color=(46, 116, 78)))
            buttons.append(ui.Button(_bar_rect(1), "Auction", "auction_decline"))
        elif state == "post_roll":
            buttons.append(ui.Button(_bar_rect(0), "End Turn", "end_turn",
                                     color=(46, 116, 78)))
            buttons.append(ui.Button(_bar_rect(1), "Build Houses", "build"))
            buttons.append(ui.Button(_bar_rect(2), "Sell Buildings", "sell",
                                     enabled=can_sell))
            buttons.append(ui.Button(_bar_rect(3), "Mortgage", "mortgage"))
            buttons.append(ui.Button(_bar_rect(4), "Trade", "trade"))
            buttons.append(ui.Button(_bar_rect(5), "Assets", "assets"))
        return buttons


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main() -> None:
    """Initialise pygame, run the app, and shut down cleanly."""
    pygame.init()
    try:
        icon_path = _resource_path("monopoly_icon.png")
        if os.path.exists(icon_path):
            try:
                pygame.display.set_icon(pygame.image.load(icon_path))
            except pygame.error:
                pass

        app = MonopolyApp()
        autotest = os.environ.get("MONOPOLY_AUTOTEST")
        if autotest:
            # Headless self-test: jump straight into an all-AI game.
            specs = [(f"AI {i + 1}", False) for i in range(4)]
            app.start_game(MonopolyGame(specs, theme="classic", seed=7))
            app.run(max_frames=4000)
        else:
            app.run()
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
