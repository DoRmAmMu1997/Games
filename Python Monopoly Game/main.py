"""Program entry point: the window, the run loop, input, and the AI driver.

`main.py` wires the parts together. It owns the pygame window, decides which
screen to show, turns clicks into engine actions for human players, and steps
the AI on a timer so a person can watch its moves.

A headless self-test runs when the MONOPOLY_AUTOTEST environment variable is
set: a seeded four-AI game is played for up to 4000 frames with no AI delay
(use the SDL dummy video driver to keep the window hidden), which exercises
the engine, the AI and all the drawing code at once. It never writes the
player's save or stats.

Sound: ``audio.py`` synthesises every effect and the music; this shell plays
them for the engine's events (``event_sounds``), token hops and button
clicks, loops the swing tune, and ends each game with a win or lose jingle.
Ctrl+M, or a Sound button, switches all sound off and on; the choice is
saved as ``"sound"`` in options.json.
"""

from __future__ import annotations

import contextlib
import json
import os
import random
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pygame

import ai
import audio
import board_render
import ui
from board_data import THEME_ORDER
from game import MonopolyGame, TradeOffer
from settings import (
    AI_TURN_DELAY_MS,
    BG,
    FPS,
    MUSIC_FADE_IN_MS,
    MUSIC_GAME_OVER_FADE_MS,
    MUSIC_LOOP_SECONDS,
    MUSIC_VOLUME,
    OPTIONS_PATH,
    SAVE_DIR,
    SAVEGAME_PATH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SFX_COOLDOWNS,
    SFX_RECIPES,
    STATS_PATH,
    TOKEN_HOP_SPEED,
    WINDOW_TITLE,
    music_notes,
)


class TradeDraft(TradeOffer, total=False):
    """A human's in-progress trade offer plus the dialog's scroll offsets.

    The engine only reads the `TradeOffer` keys; the two scroll offsets
    remember how far each side's title list is scrolled in the dialog.
    """

    give_scroll: int
    get_scroll: int


# Which effect (a name in settings.SFX_RECIPES) each engine event plays; see
# game.EVENT_KINDS. "game_over" has no entry because the end of a game is
# answered by the game-over jingle.
EVENT_SOUNDS = {
    "roll": "dice",
    "doubles": "doubles",
    "three_doubles_jail": "three_doubles",
    "go_salary": "cha_ching",
    "buy": "buy",
    "rent": "rent",
    "tax": "tax",
    "card_chance": "card_chance",
    "card_chest": "card_chest",
    "go_to_jail": "jail",
    "leave_jail": "leave_jail",
    "build_house": "build_house",
    "build_hotel": "build_hotel",
    "sell_building": "sell",
    "mortgage": "mortgage",
    "unmortgage": "unmortgage",
    "auction_start": "auction_start",
    "auction_bid": "bid",
    "auction_won": "gavel",
    "trade_proposed": "trade_proposed",
    "trade_accepted": "trade_accepted",
    "trade_rejected": "trade_rejected",
    "raise_funds": "raise_funds",
    "bankrupt": "bankrupt",
}


# The action-bar slot (bottom right) of the in-game Sound toggle. No turn
# state uses more than seven slots, so this one is always free.
SOUND_SLOT = 7


def event_sounds(kinds: list[str]) -> list[str]:
    """Return the effect names to play for one frame's engine events, oldest first.

    A few events stay quiet so one moment never sounds twice: a third
    double plays its own groan, which already ends in the jail bars (so
    neither the doubles chime nor the jail clang repeats it), and doubles
    rolled to escape Jail are heard as the release rather than the chime.
    """
    sounds: list[str] = []
    for kind in kinds:
        name = EVENT_SOUNDS.get(kind)
        if (
            name is None
            or (kind == "doubles" and ("three_doubles_jail" in kinds or "leave_jail" in kinds))
            or (kind == "go_to_jail" and "three_doubles_jail" in kinds)
        ):
            continue
        sounds.append(name)
    return sounds


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


def _atomic_write(path: Path, payload: dict) -> None:
    """Write JSON via a temp file + os.replace, so a crash cannot corrupt it."""
    try:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as error:
        _log_error(error)


def load_stats() -> dict:
    """Read lifetime stats, returning zeros if none are saved yet.

    A damaged stats file (not a JSON object, or numbers that are not
    integers) is logged and read as zeros instead of crashing the game.
    """
    try:
        data = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("stats.json is not a JSON object")
        return {"games": int(data.get("games", 0)),
                "human_wins": int(data.get("human_wins", 0))}
    except FileNotFoundError:
        return {"games": 0, "human_wins": 0}
    except (OSError, ValueError, TypeError, AttributeError, OverflowError) as error:
        _log_error(error)
        return {"games": 0, "human_wins": 0}


def load_options() -> dict:
    """Read the player's options, returning the defaults if none are saved yet.

    Returns ``{"sound": bool}``. Sound stays on unless the file holds a
    real JSON ``false``, so a damaged value can never silence the game; a
    damaged file (not JSON, or not a JSON object) is logged and read as
    the defaults instead of crashing the game.
    """
    try:
        data = json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("options.json is not a JSON object")
    except FileNotFoundError:
        return {"sound": True}
    except (OSError, ValueError) as error:
        _log_error(error)
        return {"sound": True}
    return {"sound": data.get("sound", True) is not False}


def save_game(game: MonopolyGame) -> None:
    """Write the current game to disk so it can be resumed later."""
    _atomic_write(SAVEGAME_PATH, game.to_dict())


def load_saved_game() -> MonopolyGame | None:
    """Load the saved game, or return None if there is no valid save.

    A save that cannot be loaded is logged and renamed to
    savegame.bad.json, so the Resume button disappears instead of failing
    on every click (and the file is kept for anyone who wants to inspect it).
    """
    try:
        data = json.loads(SAVEGAME_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("savegame.json is not a JSON object")
        return MonopolyGame.from_dict(data)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        _log_error(error)
        with contextlib.suppress(OSError):
            os.replace(SAVEGAME_PATH, SAVEGAME_PATH.with_name("savegame.bad.json"))
        return None


def has_saved_game() -> bool:
    """True if a saved game file exists on disk."""
    return SAVEGAME_PATH.exists()


def _clear_saved_game() -> None:
    """Delete the saved game (called when a game finishes)."""
    with contextlib.suppress(OSError):
        SAVEGAME_PATH.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# The application
# --------------------------------------------------------------------------
class MonopolyApp:
    """Owns the window and run loop and routes input to the game engine.

    The app is the "thin shell" around `MonopolyGame`: it never applies a
    rule itself. Each frame it reads input, advances animations and the AI,
    rebuilds the buttons from the engine's state, and draws.

    Key attributes:
    - `screen`: which screen is showing ("setup", "playing" or "over").
    - `game` / `renderer`: the engine and board renderer (None on setup).
    - `mode`: the in-game interaction mode ("normal", "build", "sell",
      "mortgage", "assets" or "trade"); the engine's `awaiting` says what
      the rules need, `mode` only says which dialog a human has open.
    - `trade`, `asset_position`, `message`: the open dialog's draft offer,
      the selected title, and the prompt line's last notice.
    - `token_px`, `token_route`, `token_hops`, `dice_show`, ...: animation
      state, which only eases pixels toward what the engine already decided.
    - `sounds`: the `audio.SoundBank` of effects (silent without a mixer).
    - `music`: the `audio.MusicPlayer` looping the swing tune.
    - `persist`: False in the self-test, so nothing is written to disk.
    - `options`: the saved player options (`"sound"` on or off).
    """

    def __init__(self, persist: bool = True) -> None:
        """Open the window and set up the setup screen.

        `persist` False (the headless self-test) means the app never writes
        or deletes the player's saved game or lifetime stats.
        """
        self.persist = persist
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
        # Every effect is synthesised once here from the recipes in settings.
        self.sounds = audio.SoundBank(SFX_RECIPES, SFX_COOLDOWNS)
        # The tune renders in a background thread; it starts playing on the
        # first frame after it is ready (``music.update`` in ``_update``).
        self.music = audio.MusicPlayer(music_notes, MUSIC_LOOP_SECONDS, MUSIC_VOLUME)
        self.music.start(MUSIC_FADE_IN_MS)

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
        self.trade: TradeDraft | None = None
        self.asset_position: int | None = None
        self.ai_timer = 0
        self.fast_forward = False   # spectator: run the AI with no delay
        self.message = ""
        self.stats = load_stats()
        self.options = load_options()
        # A saved "sound": false silences the bank and the music from the first frame.
        self._apply_sound_setting()
        self.buttons: list = []
        self._autosave_current: int | None = None   # last-seen turn marker

        # Visual polish: tokens hop space-by-space after a roll and the dice
        # shuffle before settling on their real value. The AI pauses while
        # either animation is running so a person can follow play.
        self.token_px: dict = {}                 # player index -> (x, y) float pixels
        self.token_pos: dict = {}                # player index -> last-seen board space
        self.token_route: dict = {}              # player index -> pending waypoint pixels
        # Player index -> pitch step of the token's next hop sound, or None
        # while it slides (jail, long card jumps) instead of hopping.
        self.token_hops: dict[int, int | None] = {}
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
        self.fast_forward = False
        self.message = ""
        # Reset the visuals so the next frame places tokens / dice from scratch.
        self.token_px = {}
        self.token_pos = {}
        self.token_route = {}
        self.token_hops = {}
        self.dice_show = (0, 0)
        self.dice_anim_remaining_ms = 0
        self.last_game_dice = (0, 0)
        # Autosave baseline: a save fires when the turn (current player) moves.
        self._autosave_current = game.current

    @property
    def sound_on(self) -> bool:
        """True unless the player has switched sound off (Ctrl+M or a Sound button)."""
        return bool(self.options["sound"])

    def _toggle_sound(self) -> None:
        """Switch all sound off or back on, and remember the choice in options.json.

        Muting stops the music at once and blocks every effect; unmuting
        resumes the music and plays a click so the player hears it worked.
        A non-persisting app (the self-test) only changes it in memory.
        """
        self.options["sound"] = not self.sound_on
        self._apply_sound_setting()
        if self.persist:
            _atomic_write(OPTIONS_PATH, self.options)
        if self.sound_on:
            self.sounds.play("click")

    def _apply_sound_setting(self) -> None:
        """Pass the sound setting to the effects bank and the music player."""
        self.sounds.muted = not self.sound_on
        self.music.set_muted(not self.sound_on)

    def _require_game(self) -> MonopolyGame:
        """Return the active game on code paths that only run mid-game.

        ``self.game`` is Optional because the setup screen has no game yet;
        the playing/over screens always do. Binding through this helper keeps
        that invariant explicit (and visible to the type checker) instead of
        sprinkling ``self.game`` derefs that could hide a real None bug.
        """
        game = self.game
        assert game is not None, "no active game on this screen"
        return game

    def _spectating(self) -> bool:
        """True once no solvent human remains and the AIs play on alone."""
        game = self.game
        return (game is not None and game.phase == "playing"
                and not any(p.is_human and not p.bankrupt for p in game.players))

    def _end_game(self) -> None:
        """Record the result and move to the end screen."""
        game = self._require_game()
        self.screen = "over"
        self.stats["games"] += 1
        if game.winner is not None and game.players[game.winner].is_human:
            self.stats["human_wins"] += 1
        if self.persist:
            _atomic_write(STATS_PATH, self.stats)
            _clear_saved_game()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self, max_frames: int | None = None) -> None:
        """Run the game until the window is closed (or a frame limit is hit).

        `max_frames` is only given by the self-test; it also tells `_update`
        to run the AI without pauses.

        Beginner note:
        - This is the classic game loop. Every pass handles all waiting input
          events, updates the state, draws a whole new frame, and shows it
          with `display.flip()`. `clock.tick(FPS)` sleeps just long enough
          to hold the loop at FPS frames per second.
        """
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
                    self._handle_keydown(event)
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
        """Advance the game: play sounds, animate visuals, then step the AI if it is its turn.

        In order, once per frame: let the music player start the tune once it
        has rendered (on every screen); play the sounds for everything the engine
        reported since the last frame; switch to the end screen when the
        game is over; autosave when the turn passes; move each token along
        its queue of waypoints (tapping a hop sound at each space); run the
        dice shuffle; then, if an AI must act, call `ai.take_action` once
        its delay has passed. `autotest` skips the delay and the wait for
        animations.
        """
        self.music.update()
        if self.screen != "playing" or self.game is None:
            return
        game = self.game
        self._play_event_sounds()
        if game.phase == "game_over":
            self._end_game()
            self._play_game_over_jingle()
            return

        # Autosave once per completed turn: the engine advances `current` to
        # the next player when a turn ends, for both humans and AI. Not while
        # spectating: the humans are out, so there is nothing to resume.
        if game.current != self._autosave_current:
            self._autosave_current = game.current
            if self.persist and not self._spectating():
                save_game(game)

        elapsed = self.clock.get_time()     # milliseconds since the last frame

        # Token hopping: after a roll a token visits every space it passes,
        # like a physical token counting out the dice. Jumps that are not a
        # normal forward roll (jail, some cards) slide directly instead. On
        # the first frame after the game starts, seed each token at its space.
        if not self.token_px:
            for player in game.players:
                self.token_px[player.index] = board_render.token_center(
                    player.position, player.index)
                self.token_pos[player.index] = player.position
                self.token_route[player.index] = []
        animating_tokens = False
        budget = TOKEN_HOP_SPEED * elapsed / 1000.0
        for player in game.players:
            idx = player.index
            if player.position != self.token_pos.get(idx):
                old = self.token_pos.get(idx, player.position)
                # Spaces travelled clockwise; `% 40` handles passing GO.
                forward = (player.position - old) % 40
                if 1 <= forward <= 12:
                    # A dice roll moves at most 12 spaces, so walk them all.
                    self.token_route[idx] = [
                        board_render.token_center((old + step) % 40, idx)
                        for step in range(1, forward + 1)
                    ]
                    self.token_hops[idx] = 0
                else:
                    self.token_route[idx] = [
                        board_render.token_center(player.position, idx)]
                    self.token_hops[idx] = None
                self.token_pos[idx] = player.position
            target = board_render.token_center(player.position, idx)
            current = self.token_px[idx]
            route = self.token_route.setdefault(idx, [])
            remaining = budget
            # Walk the waypoint queue at constant speed; one frame may finish
            # several short hops when the frame rate dips.
            while route and remaining > 0:
                head = route[0]
                dx, dy = head[0] - current[0], head[1] - current[1]
                length = (dx * dx + dy * dy) ** 0.5     # straight-line distance
                if length <= remaining:
                    current = head
                    route.pop(0)
                    remaining -= length
                    self._play_hop(idx)
                else:
                    # Not reached this frame: step `remaining` pixels toward
                    # the waypoint (dx / length is the unit direction).
                    current = (current[0] + dx / length * remaining,
                               current[1] + dy / length * remaining)
                    remaining = 0
            self.token_px[idx] = current
            if route or abs(current[0] - target[0]) > 1.5 \
                    or abs(current[1] - target[1]) > 1.5:
                animating_tokens = True

        # Dice shuffle: when the engine reports a new roll, randomise the
        # displayed dice for a short moment before settling on the real value.
        if game.dice != self.last_game_dice and game.dice != (0, 0):
            self.dice_anim_remaining_ms = 480
            self.last_game_dice = game.dice
        if self.dice_anim_remaining_ms > 0:
            self.dice_anim_remaining_ms -= elapsed
            self.dice_show = (random.randint(1, 6), random.randint(1, 6))
        else:
            self.dice_show = game.dice

        # AI driver: pace it, and pause while an animation is still playing.
        # The self-test and a spectator's fast-forward skip both waits.
        actor = game.players[game.actor()]
        if actor.is_human:
            return                       # wait for the human's clicks
        hurry = autotest or self.fast_forward
        if not hurry and (animating_tokens or self.dice_anim_remaining_ms > 0):
            return
        self.ai_timer += elapsed
        if hurry or self.ai_timer >= AI_TURN_DELAY_MS:
            self.ai_timer = 0
            ai.take_action(game)

    def _play_event_sounds(self) -> None:
        """Drain the engine's event queue and play each event's effect.

        Draining once per frame means every event is heard exactly once,
        whether a human click or an AI step caused it.
        """
        game = self._require_game()
        for name in event_sounds(game.drain_events()):
            self.sounds.play(name)

    def _play_game_over_jingle(self) -> None:
        """Fade the music out and play the win or lose jingle for the finished game.

        The win jingle plays when a human won, and also when no human played
        at all (an all-AI table); a computer beating the humans, or a game
        nobody survived, gets the gentle lose jingle.
        """
        game = self._require_game()
        self.music.stop(MUSIC_GAME_OVER_FADE_MS)
        humans = [player for player in game.players if player.is_human]
        won = not humans or (game.winner is not None and game.players[game.winner].is_human)
        self.sounds.play("win" if won else "lose")

    def _play_hop(self, idx: int) -> None:
        """Tap the hop sound for a token that just reached a space, one step higher each time.

        Slides (to Jail, or a long card jump) are silent here: their events
        have their own sounds.
        """
        step = self.token_hops.get(idx)
        if step is not None:
            self.sounds.play("hop", pitch_step=step)
            self.token_hops[idx] = step + 1

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def _handle_keydown(self, event: pygame.event.Event) -> None:
        """Route one key press: Ctrl+M, F11, turn shortcuts or name typing.

        Ctrl+M switches sound off and on, on every screen (even while a
        name box has focus, so plain M still types there and still means
        Mortgage on a turn).
        """
        if event.key == pygame.K_m and event.mod & pygame.KMOD_CTRL:
            self._toggle_sound()
        elif event.key == pygame.K_F11:
            # F11 toggles fullscreen. The SCALED flag set at startup
            # keeps logical coordinates intact, so we don't need to
            # remap anything ourselves.
            pygame.display.toggle_fullscreen()
        elif self.screen == "playing":
            self._handle_shortcut(event.key)
        elif (self.screen == "setup" and self.active_field is not None
              and not self.confirm_new_game):
            # Typing into a focused human-name box on the setup screen.
            self._type_into_name_field(event)

    def _handle_click(self, pos: tuple[int, int]) -> None:
        """Route a left-click to the right handler for the current screen."""
        if self.screen == "setup":
            self._click_setup(pos)
        elif self.screen == "over":
            self._click_button(pos)
        elif self.screen == "playing":
            game = self._require_game()
            actor = game.players[game.actor()]
            if not actor.is_human and not self._spectating():
                # During AI turns only the Sound toggle is on screen.
                self._click_button(pos)
                return
            if self.mode in ("build", "sell", "mortgage"):
                if not self._click_button(pos):      # the "Done" button
                    self._click_board(pos)
            elif self.mode == "assets":
                self._click_button(pos)
            elif self.mode == "trade":
                self._click_trade(pos)
            else:
                self._click_button(pos)

    def _click_button(self, pos: tuple[int, int]) -> bool:
        """Check the current buttons; act on the first one hit (with a click sound)."""
        for button in self.buttons:
            if button.hit(pos):
                self.sounds.play("click")
                self._on_button(button.key)
                return True
        return False

    def _click_setup(self, pos: tuple[int, int]) -> None:
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

    def _type_into_name_field(self, event: pygame.event.Event) -> None:
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

    def _click_board(self, pos: tuple[int, int]) -> None:
        """In build/sell/mortgage mode, act on the board space clicked.

        A refused click shows the engine's reason in the prompt (until the
        next click or Done), instead of silently doing nothing.
        """
        game = self._require_game()
        for position in range(40):
            if board_render.space_rect(position).collidepoint(pos):
                player = game.players[game.actor()]
                if self.mode == "build":
                    action, done = "build", game.build_house(position)
                elif self.mode == "sell":
                    action, done = "sell", game.sell_house(position)
                elif position in game.mortgaged:
                    action, done = "unmortgage", game.unmortgage(position)
                else:
                    action, done = "mortgage", game.mortgage(position)
                self.message = "" if done else str(
                    game.asset_actions_for(player, position)[action]["reason"])
                return

    def _click_trade(self, pos: tuple[int, int]) -> None:
        """Handle clicks inside the trade-building dialog."""
        if self._click_button(pos):
            return
        trade = self.trade
        if trade is None:
            return
        layout = ui.trade_layout(self._require_game(), trade)
        for key, props in (("give_rows", trade["give"]["props"]), ("get_rows", trade["get"]["props"])):
            for row, position in layout[key]:
                if row.collidepoint(pos):
                    if position in props:
                        props.remove(position)
                    else:
                        props.append(position)
                    return

    def _on_button(self, key: str) -> None:
        """Carry out the action bound to a button `key`.

        The button keys form disjoint families (setup screen, turn actions,
        the asset manager, and the trade dialog), so each family lives in its
        own handler and the first one that recognises the key wins. Quit and
        New Game come first (after the Sound toggle, which works on every
        screen): they also appear with no game in progress (the setup
        screen), where the game-dependent handlers cannot run.
        """
        if key == "toggle_sound":
            self._toggle_sound()
            return
        if key == "new_game":
            self.screen = "setup"
            self.game = None
            self.music.start(MUSIC_FADE_IN_MS)
            return
        if key == "quit":
            self.running = False
            return
        if self._on_setup_button(key):
            return
        if self._on_turn_button(key):
            return
        if self._on_asset_button(key):
            return
        self._on_trade_button(key)

    def _on_setup_button(self, key: str) -> bool:
        """Handle setup-screen controls; True if `key` belonged here.

        The steppers wrap around their option lists (humans are clamped to
        1-4 instead). Start asks for confirmation first when a saved game
        exists, because starting a new game will overwrite it at the next
        autosave. Resume loads the save, if it is still valid.
        """
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
        else:
            return False
        return True

    def _on_turn_button(self, key: str) -> bool:
        """Handle in-turn actions and auctions; True if `key` belonged here.

        Most keys call one engine action directly (roll, buy, bid, pay, ...).
        "build", "sell" and "mortgage" only switch the board-click mode; the
        engine is called when a space is then clicked. The rest leave the
        game: "save_quit" saves and returns to setup, and "concede" (offered
        once every human is bankrupt) records the result and does the same.
        """
        game = self._require_game()
        if key in ("roll", "jail_pay", "jail_card", "buy", "auction_decline", "end_turn",
                   "bid", "pass", "pay_debts", "declare_bankruptcy"):
            # A new engine action starts from a clean prompt.
            self.message = ""
        if key == "roll":
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
            self.message = ""
        elif key == "end_turn":
            game.end_turn()
        elif key == "save_quit":
            if self.persist:
                save_game(game)
            self.screen = "setup"
            self.game = None
        elif key == "bid":
            auction = game.auction
            assert auction is not None, "bid button only exists during an auction"
            # The same step as the AI's bids: 5% of list price, at least $10.
            step = max(10, game.board[auction["position"]].price // 20)
            game.auction_bid(auction["high_bid"] + step)
        elif key == "pass":
            game.auction_pass()
        elif key == "pay_debts":
            game.pay_debts()
        elif key == "declare_bankruptcy":
            game.declare_bankruptcy()
        elif key == "fast_forward":
            self.fast_forward = True
        elif key == "concede":
            # Leaving a game no human can win still counts as a game played
            # (and not a human win); the save is cleared with it.
            self._end_game()
            self.screen = "setup"
            self.game = None
        else:
            return False
        return True

    def _on_asset_button(self, key: str) -> bool:
        """Handle the title/asset manager; True if `key` belonged here."""
        game = self._require_game()
        if key == "assets":
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
        else:
            return False
        return True

    def _on_trade_button(self, key: str) -> bool:
        """Handle the trade dialog; True if `key` belonged here.

        The steppers change the draft offer in `self.trade` ($50 per cash
        step, one card per jail step). Propose hands the draft to the engine
        and shows the engine's reason if it is refused. Accept and Reject
        answer an incoming offer made to a human.
        """
        game = self._require_game()
        if key == "trade":
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
        elif key == "give_jail_up":
            self._adjust_trade_jail("give", 1)
        elif key == "give_jail_down":
            self._adjust_trade_jail("give", -1)
        elif key == "get_jail_up":
            self._adjust_trade_jail("get", 1)
        elif key == "get_jail_down":
            self._adjust_trade_jail("get", -1)
        elif key == "trade_propose":
            trade = self.trade
            assert trade is not None, "propose button only exists inside the dialog"
            if game.propose_trade(trade):
                self.mode = "normal"
            else:
                self.message = game.trade_error(trade) or "That trade is not legal."
        elif key == "trade_cancel":
            self.mode = "normal"
        elif key == "trade_accept":
            self.message = ""
            game.respond_trade(True)
        elif key == "trade_reject":
            self.message = ""
            game.respond_trade(False)
        else:
            return False
        return True

    def _begin_new_game(self) -> None:
        """Create a fresh game from the setup-screen choices."""
        # Give each AI a short name so the log and panels read pleasantly.
        ai_names = ["Iris", "Knox", "Mira", "Quill"]
        specs = []
        for i in range(4):
            human = i < self.human_count
            if human:  # noqa: SIM108 -- the ternary form buries the `or` fallback
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
        game = self._require_game()
        me = game.current
        others = [p.index for p in game.players
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
        """Open the title manager for the acting player, first title selected.

        The actor is the current player, or a debtor raising funds (who may
        not be the current player at all).
        """
        game = self._require_game()
        owned = sorted(game.properties_of(game.players[game.actor()]))
        if not owned:
            self.message = "You do not own any titles yet."
            return
        self.mode = "assets"
        self.asset_position = owned[0]
        self.message = ""

    def _manage_asset(self, action: str, operation: Callable[[int], bool]) -> None:
        """Run one engine asset action or show the engine's blocker reason."""
        if self.asset_position is None:
            self.message = "Choose a title first."
            return
        game = self._require_game()
        player = game.players[game.actor()]
        status = game.asset_actions_for(player, self.asset_position)[action]
        if not status["allowed"]:
            self.message = status["reason"]
            return
        if not operation(self.asset_position):
            self.message = status["reason"] or "That asset action did not resolve."
            return
        self.message = ""

    def _cycle_trade_partner(self, step: int) -> None:
        """Move the trade to another eligible partner; clear chosen items."""
        game = self._require_game()
        trade = self.trade
        if trade is None:
            return
        others = [p.index for p in game.players
                  if p.index != trade["from"] and not p.bankrupt]
        if not others:
            return
        current = others.index(trade["to"]) if trade["to"] in others else 0
        trade["to"] = others[(current + step) % len(others)]
        trade["give"]["props"].clear()
        trade["get"]["props"].clear()
        trade["get"]["jail"] = 0        # the new partner may hold no cards
        # A new partner usually has a different property list -- reset scroll
        # so the next dialog opens at the top of both columns.
        trade["give_scroll"] = 0
        trade["get_scroll"] = 0

    def _adjust_trade_cash(self, side: Literal["give", "get"], delta: int) -> None:
        """Step the cash on one side of the in-progress trade offer."""
        game = self._require_game()
        trade = self.trade
        if trade is None:
            return
        idx = trade["from"] if side == "give" else trade["to"]
        cap = game.players[idx].cash
        trade[side]["cash"] = max(0, min(cap, trade[side]["cash"] + delta))

    def _adjust_trade_jail(self, side: Literal["give", "get"], delta: int) -> None:
        """Step the Get Out of Jail Free cards on one side of the offer.

        The count stays between zero and the cards that side's player holds.
        """
        game = self._require_game()
        trade = self.trade
        if trade is None:
            return
        idx = trade["from"] if side == "give" else trade["to"]
        cap = game.players[idx].jail_cards
        trade[side]["jail"] = max(0, min(cap, trade[side]["jail"] + delta))

    def _scroll_trade(self, mouse_pos: tuple[int, int], wheel_dy: int) -> None:
        """Scroll one side of the trade dialog under the mouse cursor.

        Wheeling up (`wheel_dy > 0`) moves the visible window UP the list
        (decreases the scroll offset). The offset is clamped so the player
        cannot scroll past the last full window.
        """
        trade = self.trade
        if trade is None:
            return
        game = self._require_game()
        panel = ui.trade_layout(game, trade)["panel"]
        on_give_side = mouse_pos[0] < panel.centerx
        owner_idx = trade["from"] if on_give_side else trade["to"]
        owner = game.players[owner_idx]
        max_scroll = max(0, len(game.properties_of(owner))
                         - ui.TRADE_VISIBLE_ROWS)
        key: Literal["give_scroll", "get_scroll"] = "give_scroll" if on_give_side else "get_scroll"
        current = trade.get(key, 0)
        step = -1 if wheel_dy > 0 else 1
        trade[key] = max(0, min(current + step, max_scroll))

    def _handle_shortcut(self, key: int) -> None:
        """Run common human actions from the keyboard when they are available."""
        game = self.game
        if game is None:
            return
        actor = game.players[game.actor()]
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

    def _hovered_board_space(self, pos: tuple[int, int]) -> int | None:
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

    def _draw_playing(self, mouse: tuple[int, int]) -> None:
        """Draw the board, side panel, action bar and any open dialog.

        The order matters, because later drawing covers earlier drawing:
        the board and tokens, then the side panel, the last card, the dice
        and the hover card, then the action bar, and finally at most one
        modal dialog (auction, asset manager, trade builder or incoming
        trade offer) over everything.
        """
        game = self._require_game()
        renderer = self.renderer
        assert renderer is not None, "renderer exists whenever a game does"
        self.window.fill(BG)

        renderer.draw(self.window, game, self.fonts,
                      token_pixels=self.token_px,
                      highlight_positions=self._board_highlights())
        ui.draw_panel(self.window, self.fonts, game, mouse)

        ui.draw_center_card(self.window, self.fonts, game)
        if self.dice_show != (0, 0):
            ui.draw_dice(self.window, self.fonts, self.dice_show)
        hovered = self._hovered_board_space(mouse)
        if hovered is not None:
            ui.draw_property_detail(self.window, self.fonts, game, hovered)

        ui.draw_action_bar(self.window, self.fonts, self.buttons,
                           self._prompt(), mouse)

        # Modal dialogs on top of everything else.
        if game.awaiting == "auction":
            ui.draw_auction(self.window, self.fonts, game, self.buttons, mouse)
        elif self.mode == "assets":
            ui.draw_assets(self.window, self.fonts, game, self.asset_position,
                           self.buttons, mouse)
        elif self.mode == "trade" and self.trade is not None:
            ui.draw_trade(self.window, self.fonts, game, self.trade,
                          self.buttons, mouse)
        elif game.awaiting == "trade_response" and \
                game.players[game.actor()].is_human:
            ui.draw_trade_response(self.window, self.fonts, game,
                                   self.buttons, mouse)

    def _board_highlights(self) -> list[int]:
        """Spaces the human can act on in the current board-click mode.

        These get a yellow ring: buildable streets in build mode, titles
        that can be mortgaged or lifted in mortgage mode, and sellable
        streets in sell mode.
        """
        game = self._require_game()
        human = game.players[game.actor()]
        if self.mode == "build":
            return [pos for pos in range(40) if game.can_build(human, pos)]
        if self.mode == "mortgage":
            return [pos for pos in game.properties_of(human)
                    if game.can_mortgage(human, pos) or game.can_unmortgage(human, pos)]
        if self.mode == "sell":
            return [pos for pos in game.properties_of(human)
                    if game.can_sell_building(human, pos)]
        return []

    def _prompt(self) -> str:
        """A short instruction line for the action bar.

        Keep these short: the strip shows ONE line, so every fixed prompt
        here is worded to fit in full with the longest player name.
        """
        game = self._require_game()
        actor = game.players[game.actor()]
        if self._spectating():
            return "You are out: watch, fast-forward or concede."
        if not actor.is_human:
            # AI player names already carry an "(AI)" suffix -- don't add it
            # again here or the prompt reads "Mira (AI) (AI) is taking...".
            return f"{actor.name} is taking their turn..."
        if self.mode == "build":
            return self.message or "Click a ringed street to build, then Done."
        if self.mode == "mortgage":
            return self.message or "Click a ringed title to mortgage or lift it."
        if self.mode == "sell":
            return self.message or "Click a ringed street to sell a building."
        if self.mode == "assets":
            return self.message or "Pick a title, then choose an action."
        if self.message:
            return self.message
        state = game.awaiting
        if state == "pre_roll":
            if actor.in_jail:
                return f"{actor.name}: in Jail. Pay, use a card or roll."
            return f"{actor.name}: your turn. Roll the dice."
        if state == "buy_or_auction" and game.pending_purchase is not None:
            space = game.board[game.pending_purchase]
            # The title comes last, so a very long name is what gets shortened.
            return f"Buy or auction: {space.name} (${space.price})"
        if state == "auction" and game.auction is not None:
            # The dialog carries the detail; the strip only says what to do.
            bank = game.auction.get("context") == "bankruptcy"
            return "Bank bankruptcy auction: bid or pass." if bank else "Auction: bid or pass."
        if state == "post_roll":
            return f"{actor.name}: build, trade, or end your turn."
        if state == "raise_funds" and game.debts:
            owed = game.debts[0]["amount"]
            payee = game.debts[0]["payee"]
            to = "the Bank" if payee is None else game.players[payee].name
            if actor.cash < owed:
                return f"Raise ${owed - actor.cash} more to pay {to} ${owed}."
            return f"You can now pay {to} ${owed}."
        if state == "trade_response":
            return "You have received a trade offer."
        return ""

    def _build_buttons(self) -> list:
        """Build the buttons appropriate to the current screen and state."""
        if self.screen == "setup":
            if self.confirm_new_game:
                return ui.confirm_buttons()
            return ui.setup_buttons(has_saved_game(), self.sound_on)
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
        """Build the in-game buttons for the current player and state.

        Each dialog owns a small builder; this dispatcher just picks the one
        matching the current mode or engine state. The Sound toggle sits in
        the action bar's last slot whenever the bar shows, AI turns
        included; the trade builder and asset manager cover the panel, so
        they leave it out (Ctrl+M still works there).
        """
        game = self._require_game()
        actor = game.players[game.actor()]
        sound = ui.Button(ui.bar_slot_rect(SOUND_SLOT), ui.sound_label(self.sound_on), "toggle_sound")
        if self._spectating():
            return [
                ui.Button(ui.bar_slot_rect(0), "Fast-forward", "fast_forward",
                          enabled=not self.fast_forward, color=(46, 116, 78)),
                ui.Button(ui.bar_slot_rect(1), "Concede / Main Menu", "concede",
                          color=(150, 60, 60)),
                sound,
            ]
        if not actor.is_human:
            return [sound]
        if self.mode == "trade" and self.trade is not None:
            return self._trade_dialog_buttons()
        if self.mode == "assets":
            return self._asset_dialog_buttons(actor)
        if game.awaiting == "trade_response":
            return [*self._trade_response_buttons(), sound]
        if game.awaiting == "auction":
            return [*self._auction_buttons(actor), sound]
        if self.mode in ("build", "sell", "mortgage"):
            # Board-click modes need only a way back out.
            return [ui.Button(ui.bar_slot_rect(0), "Done", "done", color=(46, 116, 78)), sound]
        return [*self._action_bar_buttons(actor), sound]

    def _trade_dialog_buttons(self) -> list:
        """Buttons for the trade-building dialog.

        Each side has a cash stepper pair and a Get Out of Jail Free card
        stepper pair under its column; their rects come from
        `ui.trade_layout`, which also places the labels beside them.
        """
        game = self._require_game()
        trade = self.trade
        assert trade is not None, "trade buttons only build inside the dialog"
        layout = ui.trade_layout(game, trade)
        panel, steppers = layout["panel"], layout["steppers"]
        buttons = [
            # Arrows are placed symmetrically and well clear of the
            # centred "With: NAME" label, however wide the name is.
            ui.Button((panel.centerx - 200, panel.y + 54, 30, 26), "<",
                      "trade_partner_prev"),
            ui.Button((panel.centerx + 170, panel.y + 54, 30, 26), ">",
                      "trade_partner_next"),
        ]
        for side, chosen, holder in (("give", trade["give"]["jail"], game.players[trade["from"]]),
                                     ("get", trade["get"]["jail"], game.players[trade["to"]])):
            buttons += [
                ui.Button(steppers[f"{side}_cash_down"], "-$50", f"{side}_cash_down"),
                ui.Button(steppers[f"{side}_cash_up"], "+$50", f"{side}_cash_up"),
                # A side can offer no more jail cards than its player holds.
                ui.Button(steppers[f"{side}_jail_down"], "-1", f"{side}_jail_down",
                          enabled=chosen > 0),
                ui.Button(steppers[f"{side}_jail_up"], "+1", f"{side}_jail_up",
                          enabled=chosen < holder.jail_cards),
            ]
        buttons += [
            ui.Button((panel.centerx - 210, panel.bottom - 56, 190, 40),
                      "Propose", "trade_propose", color=(46, 116, 78)),
            ui.Button((panel.centerx + 20, panel.bottom - 56, 190, 40),
                      "Cancel", "trade_cancel"),
        ]
        return buttons

    def _asset_dialog_buttons(self, actor) -> list:
        """Build the asset-manager buttons for `actor`.

        Every owned title gets a row button that selects it (the selected row
        is tinted). The Build, Sell, Mortgage and Lift Mortgage buttons are
        enabled from the engine's `asset_actions_for`, so they always match
        what the rules allow. A Close button sits at the top right.
        """
        game = self._require_game()
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

    def _trade_response_buttons(self) -> list:
        """Accept/Reject buttons for an incoming trade offer."""
        layout = ui.trade_response_layout()
        return [
            ui.Button(layout["accept"], "Accept", "trade_accept", color=(46, 116, 78)),
            ui.Button(layout["reject"], "Reject", "trade_reject", color=(150, 60, 60)),
        ]

    def _auction_buttons(self, actor) -> list:
        """Bid/Pass buttons for the auction dialog."""
        game = self._require_game()
        auction = game.auction
        assert auction is not None, "auction buttons only build during an auction"
        layout = ui.auction_layout()
        step = max(10, game.board[auction["position"]].price // 20)
        can_bid = (auction["high_bid"] + step) <= actor.cash
        return [
            ui.Button(layout["bid"], f"Bid +${step}", "bid", enabled=can_bid,
                      color=(46, 116, 78)),
            ui.Button(layout["pass"], "Pass", "pass", color=(150, 60, 60)),
        ]

    def _action_bar_buttons(self, actor) -> list:
        """The normal action bar for pre-roll, buy-or-auction, post-roll and raising funds.

        The buttons depend on the engine state: rolling (with the jail
        choices instead of building while in Jail), Buy or Auction after
        landing on an unowned title, End Turn plus building and trading
        after the roll, and Pay / Assets / Declare Bankruptcy while a debt
        is open. A button whose action cannot work yet is shown disabled.
        """
        game = self._require_game()
        buttons = []
        state = game.awaiting
        can_sell = any(game.can_sell_building(actor, pos)
                       for pos in game.properties_of(actor))
        if state == "pre_roll":
            if actor.in_jail:
                buttons.append(ui.Button(ui.bar_slot_rect(0), "Roll Dice", "roll",
                                         color=(46, 116, 78)))
                buttons.append(ui.Button(ui.bar_slot_rect(1), "Pay $50", "jail_pay",
                                         enabled=actor.cash >= 50))
                buttons.append(ui.Button(ui.bar_slot_rect(2), "Use Jail Card", "jail_card",
                                         enabled=actor.jail_cards > 0))
                # Jail only stops movement: the engine still allows asset
                # management and trading before the roll.
                buttons.append(ui.Button(ui.bar_slot_rect(3), "Mortgage", "mortgage"))
                buttons.append(ui.Button(ui.bar_slot_rect(4), "Trade", "trade"))
                buttons.append(ui.Button(ui.bar_slot_rect(5), "Assets", "assets"))
            else:
                buttons.append(ui.Button(ui.bar_slot_rect(0), "Roll Dice", "roll",
                                         color=(46, 116, 78)))
                buttons.append(ui.Button(ui.bar_slot_rect(1), "Build Houses", "build"))
                buttons.append(ui.Button(ui.bar_slot_rect(2), "Sell Buildings", "sell",
                                         enabled=can_sell))
                buttons.append(ui.Button(ui.bar_slot_rect(3), "Mortgage", "mortgage"))
                buttons.append(ui.Button(ui.bar_slot_rect(4), "Trade", "trade"))
                buttons.append(ui.Button(ui.bar_slot_rect(5), "Save & Quit", "save_quit"))
                buttons.append(ui.Button(ui.bar_slot_rect(6), "Assets", "assets"))
        elif state == "buy_or_auction" and game.pending_purchase is not None:
            space = game.board[game.pending_purchase]
            buttons.append(ui.Button(ui.bar_slot_rect(0), f"Buy (${space.price})", "buy",
                                     enabled=actor.cash >= space.price,
                                     color=(46, 116, 78)))
            buttons.append(ui.Button(ui.bar_slot_rect(1), "Auction", "auction_decline"))
        elif state == "post_roll":
            buttons.append(ui.Button(ui.bar_slot_rect(0), "End Turn", "end_turn",
                                     color=(46, 116, 78)))
            buttons.append(ui.Button(ui.bar_slot_rect(1), "Build Houses", "build"))
            buttons.append(ui.Button(ui.bar_slot_rect(2), "Sell Buildings", "sell",
                                     enabled=can_sell))
            buttons.append(ui.Button(ui.bar_slot_rect(3), "Mortgage", "mortgage"))
            buttons.append(ui.Button(ui.bar_slot_rect(4), "Trade", "trade"))
            buttons.append(ui.Button(ui.bar_slot_rect(5), "Assets", "assets"))
        elif state == "raise_funds" and game.debts:
            # The debtor sells and mortgages in the asset manager, then pays
            # (once their cash covers the oldest debt) or concedes.
            owed = game.debts[0]["amount"]
            buttons.append(ui.Button(ui.bar_slot_rect(0), f"Pay ${owed}", "pay_debts",
                                     enabled=actor.cash >= owed, color=(46, 116, 78)))
            buttons.append(ui.Button(ui.bar_slot_rect(1), "Assets", "assets"))
            buttons.append(ui.Button(ui.bar_slot_rect(2), "Declare Bankruptcy",
                                     "declare_bankruptcy", color=(150, 60, 60)))
        return buttons


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def main() -> None:
    """Initialise pygame, run the app, and shut down cleanly.

    The mixer format is requested before ``pygame.init()`` opens the mixer,
    and the music channel is reserved right after.
    """
    audio.init_mixer()
    pygame.init()
    audio.reserve_channels()
    try:
        icon_path = _resource_path("monopoly_icon.png")
        if os.path.exists(icon_path):
            with contextlib.suppress(pygame.error):
                pygame.display.set_icon(pygame.image.load(icon_path))

        autotest = os.environ.get("MONOPOLY_AUTOTEST")
        # The self-test must never overwrite or delete a player's save/stats.
        app = MonopolyApp(persist=not autotest)
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
