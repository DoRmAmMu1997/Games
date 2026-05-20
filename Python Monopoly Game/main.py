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
        self.window = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
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

        # In-game interaction state.
        self.mode = "normal"          # "normal", "build", "mortgage", "trade"
        self.trade: dict | None = None
        self.ai_timer = 0
        self.message = ""
        self.stats = load_stats()
        self.buttons: list = []

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
        self.ai_timer = 0
        self.message = ""
        # Reset the visuals so the next frame places tokens / dice from scratch.
        self.token_px = {}
        self.dice_show = (0, 0)
        self.dice_anim_remaining_ms = 0
        self.last_game_dice = (0, 0)

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
            self._click_button(pos)
        elif self.screen == "over":
            self._click_button(pos)
        elif self.screen == "playing":
            actor = self.game.players[self.game.actor()]
            if not actor.is_human:
                return                   # ignore clicks during AI turns
            if self.mode in ("build", "mortgage"):
                if not self._click_button(pos):      # the "Done" button
                    self._click_board(pos)
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

    def _click_board(self, pos) -> None:
        """In build/mortgage mode, act on the board space that was clicked."""
        for position in range(40):
            if board_render.space_rect(position).collidepoint(pos):
                if self.mode == "build":
                    self.game.build_house(position)
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
        elif key == "start":
            self._begin_new_game()
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
                self.message = "That trade is not legal."
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
            name = f"Player {i + 1}" if human else f"{ai_names[i]} (AI)"
            specs.append((name, human))
        theme = THEME_ORDER[self.theme_index]
        self.start_game(MonopolyGame(specs, theme=theme))

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
        }

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

    def _adjust_trade_cash(self, side: str, delta: int) -> None:
        """Step the cash on one side of the in-progress trade offer."""
        idx = self.trade["from"] if side == "give" else self.trade["to"]
        cap = self.game.players[idx].cash
        self.trade[side]["cash"] = max(0, min(cap, self.trade[side]["cash"] + delta))

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
                          self.buttons, mouse)
        elif self.screen == "over":
            ui.draw_game_over(self.window, self.fonts, self.game, self.buttons, mouse)
        elif self.screen == "playing":
            self._draw_playing(mouse)

    def _draw_playing(self, mouse) -> None:
        """Draw the board, side panel, action bar and any open dialog."""
        self.window.fill(BG)

        # Yellow rings on the spaces the human can act on in build/mortgage mode.
        highlights: list = []
        if self.mode == "build":
            human = self.game.current_player
            highlights = [pos for pos in range(40)
                          if self.game.can_build(human, pos)]
        elif self.mode == "mortgage":
            human = self.game.current_player
            highlights = [pos for pos in self.game.properties_of(human)
                          if self.game.houses.get(pos, 0) == 0]

        self.renderer.draw(self.window, self.game, self.fonts,
                           token_pixels=self.token_px,
                           highlight_positions=highlights)
        ui.draw_panel(self.window, self.fonts, self.game, mouse)

        board_centre = (20 + (SCREEN_HEIGHT - 40) // 2, 20 + (SCREEN_HEIGHT - 40) // 2)
        ui.draw_center_card(self.window, self.fonts, self.game)
        if self.dice_show != (0, 0):
            ui.draw_dice(self.window, self.fonts, self.dice_show, board_centre)

        ui.draw_action_bar(self.window, self.fonts, self.buttons,
                           self._prompt(), mouse)

        # Modal dialogs on top of everything else.
        if self.game.awaiting == "auction":
            ui.draw_auction(self.window, self.fonts, self.game, self.buttons, mouse)
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
            return f"{actor.name} (AI) is taking their turn..."
        if self.mode == "build":
            return "Click a property in one of your monopolies to build. Then Done."
        if self.mode == "mortgage":
            return "Click a property to mortgage it, or a mortgaged one to lift it."
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
        if state == "post_roll":
            return f"{actor.name}: build, trade, or end your turn."
        if state == "trade_response":
            return "You have received a trade offer."
        return ""

    def _build_buttons(self) -> list:
        """Build the buttons appropriate to the current screen and state."""
        if self.screen == "setup":
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
                ui.Button((panel.x + 30, panel.bottom - 104, 130, 30), "Give -$50",
                          "give_cash_down"),
                ui.Button((panel.x + 170, panel.bottom - 104, 130, 30), "Give +$50",
                          "give_cash_up"),
                ui.Button((panel.x + 380, panel.bottom - 104, 130, 30), "Get -$50",
                          "get_cash_down"),
                ui.Button((panel.x + 520, panel.bottom - 104, 130, 30), "Get +$50",
                          "get_cash_up"),
                ui.Button((panel.centerx - 210, panel.bottom - 56, 190, 40),
                          "Propose", "trade_propose", color=(46, 116, 78)),
                ui.Button((panel.centerx + 20, panel.bottom - 56, 190, 40),
                          "Cancel", "trade_cancel"),
            ]

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

        # Build / mortgage mode: just a Done button.
        if self.mode in ("build", "mortgage"):
            return [ui.Button(_bar_rect(0), "Done", "done", color=(46, 116, 78))]

        # Normal action bar.
        buttons = []
        state = game.awaiting
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
                buttons.append(ui.Button(_bar_rect(2), "Mortgage", "mortgage"))
                buttons.append(ui.Button(_bar_rect(3), "Trade", "trade"))
                buttons.append(ui.Button(_bar_rect(4), "Save & Quit", "save_quit"))
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
            buttons.append(ui.Button(_bar_rect(2), "Mortgage", "mortgage"))
            buttons.append(ui.Button(_bar_rect(3), "Trade", "trade"))
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
