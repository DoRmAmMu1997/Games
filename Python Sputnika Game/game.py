"""Main gameplay coordinator.

This file is the "traffic controller" of the project:
- it owns the window and internal render canvas,
- routes input to the correct gameplay/menu behavior,
- advances physics and merge logic,
- updates score/save state,
- draws the final frame in the correct order.

Beginner note:
- If you only read one file to understand "how the whole game works",
  this is the best one to start with.
- Most helper files do one focused job.
- This file is where those helpers are called in the correct order.
"""

from __future__ import annotations

import json
import math
import os
import random
import time
from functools import partial

import pygame

from assets import AssetLibrary
from audio import MusicPlayer
from effects import EffectsManager
from entities import CelestialBody
from merge_logic import find_merge_events
from physics import PhysicsWorld
from rules import (
    advance_fail_timer,
    aim_tick_crossed,
    combo_points,
    fail_ratio,
    impact_sound,
    next_combo_count,
    sanitize_progress,
    stress_level,
    warning_beep_interval,
)
from settings import (
    ANGLE_AIM_SPEED,
    COMBO_CHIME_TOP,
    DANGER_MOOD_HOLD,
    DROP_COOLDOWN,
    FAIL_AGE_GATE,
    FAIL_GRACE,
    FAIL_LINE_Y,
    FPS,
    KEYBOARD_AIM_SPEED,
    LAUNCH_SPEED,
    MAX_BODIES,
    MAX_LAUNCH_ANGLE,
    MOUSE_WHEEL_ANGLE_STEP,
    MUSIC_CALM_CHANNEL,
    MUSIC_CROSSFADE_MS,
    MUSIC_FADE_IN_MS,
    MUSIC_GAME_OVER_FADE_MS,
    MUSIC_LOOP_SECONDS,
    MUSIC_TENSE_CHANNEL,
    MUSIC_VOLUME,
    OVERLAY_PADDING,
    PREVIEW_GLOW_EXTRA,
    SAVE_DATA_DIR,
    SAVE_DATA_PATH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SFX_VOLUMES,
    SPAWN_WEIGHTS,
    SPAWN_Y,
    TIERS,
    WARNING,
    WINDOW_TITLE,
    clamp,
    music_notes,
)
from ui import (
    SOUND_BUTTON_HUD,
    SOUND_BUTTON_MENU,
    Button,
    danger_label_rect,
    draw_danger_label,
    draw_game_over_overlay,
    draw_hud,
    draw_menu_overlay,
    draw_pause_overlay,
    draw_playfield,
    draw_sound_toggle,
    place_game_over_buttons,
    place_menu_buttons,
    place_pause_buttons,
    sound_label,
)


def _log_error(error: Exception) -> None:
    """Write save/load failures to a small per-user error log.

    Save errors should not crash the game window. If the log itself cannot be
    written, the final ``except`` keeps that secondary failure invisible too.
    """

    try:
        SAVE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with (SAVE_DATA_DIR / "error.log").open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {error}\n")
    except OSError:
        pass


class OrbitalOrchardGame:
    """Top-level game object that keeps all subsystems working together.

    One instance owns everything for the lifetime of the window: the pygame
    window and fixed-size canvas, the `AssetLibrary`, `EffectsManager` and
    `PhysicsWorld`, the list of live bodies, the launcher, scoring, and the
    saved lifetime records. `run()` drives it frame by frame.

    Key attributes:
        scene: The screen state machine, one of `"menu"`, `"playing"`,
            `"paused"` or `"game_over"`. Input, updating and drawing all
            branch on it. Transitions: menu -> playing (Start/Enter);
            playing <-> paused (Esc/P or the Pause button); playing ->
            game_over (fail timer full, or the body cap hit); any in-run
            scene -> menu (M or Main Menu) or -> playing again (R/Restart).
        now: Game clock in seconds. It does not advance while paused.
        bodies: Every `CelestialBody` currently in the bubble.
        spawn_x, launch_angle: Launcher column and aim (degrees from straight
            down, clamped to +/- `MAX_LAUNCH_ANGLE`).
        current_tier/current_seed, next_tier/next_seed: The two-slot drop
            queue shown in the HUD.
        drop_timer: Seconds left on the launch cooldown.
        fail_timer: How long the stack has stayed over the fail line; the
            run ends once it reaches `FAIL_GRACE`.
        container_stress: 0..1 value for the HUD danger meter.
        score, high_score, games_played, lifetime_best_tier: Run score and
            the saved lifetime records.
        random: The game's own `random.Random`. Anything that changes
            gameplay (queue tiers, body seeds) draws from it so seeded runs
            replay exactly; purely cosmetic randomness uses the global
            `random` module.
        persist: When False, progress is loaded but never saved.

    Beginner note:
    - The game always draws onto a fixed 1024x1280 `canvas` and only scales
      it to the real window in `_present()`. Every coordinate in the game
      logic is therefore a canvas coordinate; mouse positions are converted
      with `_window_to_canvas()` before use.
    """

    def __init__(self, persist: bool = True) -> None:
        """Build the window, subsystems, and starting state.

        `persist=False` still reads saved progress (so the HUD shows real
        records) but never writes it. The automated smoke test uses this to
        play a real round without touching the player's save.
        """
        self.persist = persist

        # Set the desktop window title that the player sees in the task bar.
        pygame.display.set_caption(WINDOW_TITLE)

        # Create a desktop window sized to fit the current monitor.
        initial_window_size = self._recommended_window_size()
        self.window = pygame.display.set_mode(initial_window_size, pygame.RESIZABLE)

        # The game always renders into this fixed-size internal canvas.
        # Later we scale this canvas to the actual window size.
        self.canvas = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT)).convert()

        # `render_rect` stores where the scaled canvas should appear inside the window.
        self.render_rect = pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
        self._update_render_rect(initial_window_size)

        # `Clock` gives us frame timing so movement remains frame-rate independent.
        self.clock = pygame.time.Clock()

        # Shared helper objects used throughout the loop.
        self.assets = AssetLibrary()
        self.effects = EffectsManager()
        self.world = PhysicsWorld()
        self.random = random.Random()

        # Background music: a calm loop and a tense one for danger, each
        # rendered in its own background thread (see audio.MusicPlayer).
        # `_music_mood` names the track currently wanted ("calm", "tense",
        # or None for silence); `_sync_music()` keeps it in step with play.
        self.music = {
            mood: MusicPlayer(partial(music_notes, mood == "tense"), MUSIC_LOOP_SECONDS, MUSIC_VOLUME, channel=channel)
            for mood, channel in (("calm", MUSIC_CALM_CHANNEL), ("tense", MUSIC_TENSE_CHANNEL))
        }
        self._music_mood: str | None = None

        # Global scene/state flags.
        # `scene` is a simple state machine:
        # - "menu"
        # - "playing"
        # - "paused"
        # - "game_over"
        self.running = True
        self.scene = "menu"
        self.now = 0.0

        # Launcher state.
        # `spawn_x` is horizontal position only; vertical spawn height is fixed by `SPAWN_Y`
        # (large bodies are nudged inward from it by `PhysicsWorld.spawn_point`).
        self.spawn_x = self.world.center.x
        self.launch_angle = 0.0
        self.angle_dragging = False

        # Timers and progression values.
        self.drop_timer = 0.0
        self.fail_timer = 0.0
        self.container_stress = 0.0
        self.goal_reached = False
        self.warning_active = False
        self.danger_mood = False
        self._danger_mood_timer = 0.0
        self.score = 0
        progress = self._load_progress()
        self.high_score = progress["high_score"]
        self.games_played = progress["games_played"]
        self.lifetime_best_tier = progress["best_tier"]
        # The player's sound on/off choice, saved with the progress.
        self.muted = bool(progress["muted"])
        self.new_record = False
        self.best_tier_seen = 0
        # The high score this run has to beat, and whether passing it has
        # already been cheered (the sparkle plays once per run).
        self._score_to_beat = self.high_score
        self._high_score_cheered = False

        # Combo scoring state: quick back-to-back merges build a score
        # multiplier. `_combo_count` is the current chain length and
        # `_last_merge_time` records when the previous merge happened.
        self._combo_count = 0
        self._last_merge_time = -999.0

        # The escalating danger warning beep uses this to space out its tones.
        self._next_warning_beep = 0.0

        # Body bookkeeping.
        self._next_body_id = 1
        self.bodies: list[CelestialBody] = []

        # Small background offset based on mouse position for subtle parallax.
        self.background_drift = pygame.Vector2()

        # Queue up the first current and next body tiers.
        # This creates the "current" + "next" queue familiar from Suika-style games.
        # Each queued entry also carries a random seed so the preview arc can
        # match the subtle orbital drift flavor of the real launched body.
        self.current_tier, self.current_seed = self._roll_spawn_choice()
        self.next_tier, self.next_seed = self._roll_spawn_choice()

        # Create buttons once and reuse them each frame.
        # Reusing button objects keeps click rectangles and labels in one place.
        self.play_button = Button(pygame.Rect(392, 716, 240, 64), "Start Run")
        self.pause_button = Button(pygame.Rect(790, 968, 188, 58), "Pause")
        self.restart_button = Button(pygame.Rect(790, 1042, 188, 58), "Restart", accent=(255, 170, 110))
        self.resume_button = Button(pygame.Rect(357, 500, 310, 60), "Resume")
        self.pause_restart_button = Button(pygame.Rect(357, 574, 310, 60), "Restart", accent=(255, 170, 110))
        self.pause_menu_button = Button(pygame.Rect(357, 648, 310, 60), "Main Menu", accent=(150, 220, 255))
        self.over_restart_button = Button(pygame.Rect(352, 578, 320, 60), "Play Again", accent=(255, 170, 110))
        self.over_menu_button = Button(pygame.Rect(352, 648, 320, 60), "Main Menu", accent=(150, 220, 255))
        # Overlay buttons are laid out inside their modals by ui.py; placing them
        # now means their click areas are right even before the first frame.
        place_menu_buttons([self.play_button])
        place_pause_buttons([self.resume_button, self.pause_restart_button, self.pause_menu_button])
        place_game_over_buttons([self.over_restart_button, self.over_menu_button])
        # The sound toggle: one in the sidebar during a run, one under the menu.
        self.sound_button = Button(SOUND_BUTTON_HUD.copy(), sound_label(self.muted))
        self.menu_sound_button = Button(SOUND_BUTTON_MENU.copy(), sound_label(self.muted))
        self._apply_mute()

    @property
    def current_body_name(self) -> str:
        """Human-friendly name for the current queued body."""
        return TIERS[self.current_tier].name

    @property
    def next_body_name(self) -> str:
        """Human-friendly name for the next queued body."""
        return TIERS[self.next_tier].name

    @property
    def best_tier_name(self) -> str:
        """Human-friendly name for the best tier reached this run."""
        return TIERS[self.best_tier_seen].name

    @property
    def lifetime_best_tier_name(self) -> str:
        """Human-friendly name for the best tier reached across every run."""
        return TIERS[self.lifetime_best_tier].name

    def run(self, max_frames: int | None = None) -> None:
        """Run the main loop until the player quits or a test frame limit is reached.

        Each pass of the loop is one frame: measure elapsed time, handle
        input, update the game, and draw. `dt` is capped at 0.025 s so a long
        stall (dragging the window, a debugger pause) cannot launch bodies
        through each other with one huge physics step.

        Args:
            max_frames: Stop after this many frames. Tests and the autotest
                smoke run use it; normal play passes `None` (no limit).

        Beginner note:
        - This is the classic *game loop*. Nothing happens "by itself" in a
          game: every animation and physics step advances only because this
          loop calls the update code again, about 60 times a second.
        """
        frames = 0
        while self.running:
            # `clock.tick(FPS)` waits just enough to target 60 FPS and returns the
            # elapsed milliseconds since the previous frame.
            #
            # `dt` means "delta time": how many seconds passed since the previous frame.
            # Multiplying movement by `dt` keeps motion consistent across frame rates.
            dt = min(0.025, self.clock.tick(FPS) / 1000.0)
            # Game time stands still behind the pause menu, so bodies do not
            # "age" past the fail-line grace gate while the player is away.
            if self.scene != "paused":
                self.now += dt

            # Every frame follows the same high-level order:
            # 1. read player/system input,
            # 2. update game state,
            # 3. draw the new frame.
            self._handle_events()
            self._update(dt)
            self._draw()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                break

    def _handle_events(self) -> None:
        """Process every pending pygame event for the current frame.

        Events handled here: window close (stop the loop), window resize
        (recompute the letterbox), key presses (`_handle_keydown`), the mouse
        wheel (fine angle steps while playing), right-button drag (aim by
        pointing), and left clicks (buttons first, otherwise launch). Held
        keys for continuous movement are read separately in
        `_update_spawn_aim()`, because events only report the moment a key
        goes down.

        Beginner note:
        - `pygame.event.get()` empties the event queue. If a game stops
          calling it, the operating system decides the window is frozen.
        - Mouse event positions are in *window* pixels, so they go through
          `_window_to_canvas()` before being compared with anything.
        """
        for event in pygame.event.get():
            # pygame delivers many event types through one queue, so this method
            # acts like a dispatcher that sends each event to the right behavior.
            if event.type == pygame.QUIT:
                # Tell the main loop to stop entirely.
                self.running = False
                return

            if event.type == pygame.VIDEORESIZE:
                # Recreate the window at the requested size and recompute scaling.
                self.window = pygame.display.set_mode(event.size, pygame.RESIZABLE)
                self._update_render_rect(event.size)
                continue

            if event.type == pygame.KEYDOWN:
                # Keyboard actions are grouped in a helper so this loop stays readable.
                self._handle_keydown(event.key, event.mod)

            if event.type == pygame.MOUSEWHEEL and self.scene == "playing":
                # Mouse wheel provides fine angle adjustments.
                # `event.y` is positive for wheel up and negative for wheel down.
                self._nudge_launch_angle(-event.y * MOUSE_WHEEL_ANGLE_STEP)
                continue

            if event.type == pygame.MOUSEMOTION and self.scene == "playing" and self.angle_dragging:
                # While the right mouse button is held, mouse motion continuously
                # updates the current launcher angle.
                logical_pos = self._window_to_canvas(event.pos)
                if logical_pos is not None:
                    self._set_launch_angle_from_point(logical_pos)
                continue

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Convert from actual window pixels into internal canvas coordinates.
                logical_pos = self._window_to_canvas(event.pos)
                if logical_pos is None:
                    # Ignore clicks that happened outside the letterboxed game area.
                    continue

                # UI buttons get first chance to consume the click.
                if self._handle_click(logical_pos):
                    continue

                # Otherwise a left click during gameplay launches the current body.
                if self.scene == "playing":
                    self.drop_current_body()
                continue

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and self.scene == "playing":
                # Right click begins angle-drag aiming.
                logical_pos = self._window_to_canvas(event.pos)
                if logical_pos is not None:
                    self.angle_dragging = True
                    self._set_launch_angle_from_point(logical_pos)
                continue

            if event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                # Releasing the right mouse button ends angle dragging.
                self.angle_dragging = False

    def _handle_keydown(self, key: int, mod: int = 0) -> None:
        """Handle one key press based on the current scene.

        Bindings:
        - Ctrl+M: sound on/off, in every scene.
        - Esc / P: toggle between playing and paused.
        - M: back to the menu from any in-run scene.
        - R: restart a fresh run from any in-run scene.
        - W / Up and S / Down: one fixed angle step while playing (holding
          the key also turns the launcher smoothly in `_update_spawn_aim`).
        - Enter / Space: the scene's main action: start, launch, resume, or
          play again.

        Args:
            key: The pygame key code from a `KEYDOWN` event.
            mod: The modifier keys held down (the event's `mod` bit flags).
        """
        if key == pygame.K_m and mod & pygame.KMOD_CTRL:
            # Ctrl+M toggles sound. Plain M (below) keeps its menu job.
            self._toggle_mute()
            return

        if key in (pygame.K_ESCAPE, pygame.K_p):
            # `Esc` / `P` toggles pause during gameplay.
            if self.scene == "playing":
                self._pause()
            elif self.scene == "paused":
                self._resume()
            return

        if key == pygame.K_m:
            # `M` jumps back to the menu from any in-run scene.
            if self.scene in {"playing", "paused", "game_over"}:
                self.scene = "menu"
                self.assets.sounds.play("button", 0.4)
            return

        if key == pygame.K_r and self.scene in {"playing", "paused", "game_over"}:
            # `R` always restarts a fresh run.
            self.start_round()
            return

        if self.scene == "playing":
            # `W/S` or arrow keys adjust launch angle while playing.
            if key in (pygame.K_w, pygame.K_UP):
                self._nudge_launch_angle(-MOUSE_WHEEL_ANGLE_STEP)
                return
            if key in (pygame.K_s, pygame.K_DOWN):
                self._nudge_launch_angle(MOUSE_WHEEL_ANGLE_STEP)
                return

        if key in (pygame.K_RETURN, pygame.K_SPACE):
            # `Enter` / `Space` do the most likely action for the current scene.
            # This is a small convenience feature so keyboard-only play is possible.
            if self.scene == "menu":
                self.start_round()
            elif self.scene == "playing":
                self.drop_current_body()
            elif self.scene == "paused":
                self._resume()
            elif self.scene == "game_over":
                self.start_round()

    def _handle_click(self, position: tuple[int, int]) -> bool:
        """Route a logical click position to the correct scene buttons.

        Returns `True` when a button handled the click.
        """
        # The sound toggle works on the menu and in every in-run scene (the
        # sidebar stays visible behind the pause and game-over modals).
        toggle = self.menu_sound_button if self.scene == "menu" else self.sound_button
        if toggle.contains(position):
            self._toggle_mute()
            return True

        if self.scene == "menu":
            if self.play_button.contains(position):
                self.start_round()
                return True
            return False

        if self.scene == "playing":
            if self.pause_button.contains(position):
                self._pause()
                return True
            if self.restart_button.contains(position):
                self.start_round()
                return True
            return False

        if self.scene == "paused":
            # Pair each button with the action string it should trigger.
            for button, action in (
                (self.resume_button, "resume"),
                (self.pause_restart_button, "restart"),
                (self.pause_menu_button, "menu"),
            ):
                if button.contains(position):
                    if action == "resume":
                        self._resume()
                        return True
                    self.assets.sounds.play("button", 0.4)
                    if action == "restart":
                        self.start_round()
                    else:
                        self.scene = "menu"
                    return True
            return False

        if self.scene == "game_over":
            for button, action in (
                (self.over_restart_button, "restart"),
                (self.over_menu_button, "menu"),
            ):
                if button.contains(position):
                    self.assets.sounds.play("button", 0.4)
                    if action == "restart":
                        self.start_round()
                    else:
                        self.scene = "menu"
                    return True
            return False

        return False

    def _toggle_mute(self) -> None:
        """Switch all sound off or back on, and remember the choice.

        Turning sound back on plays a click, so the player hears it worked.
        """
        self.muted = not self.muted
        self._apply_mute()
        self._save_progress()
        if not self.muted:
            self.assets.sounds.play("button", 0.4)

    def _apply_mute(self) -> None:
        """Pass the mute setting to the effects bank and both music players."""
        self.assets.sounds.muted = self.muted
        for player in self.music.values():
            player.set_muted(self.muted)

    def _pause(self) -> None:
        """Open the pause menu with its falling two-note cue."""
        self.scene = "paused"
        self.assets.sounds.play("pause", SFX_VOLUMES["pause"])

    def _resume(self) -> None:
        """Close the pause menu with its rising two-note cue."""
        self.scene = "playing"
        self.assets.sounds.play("resume", SFX_VOLUMES["resume"])

    def start_round(self) -> None:
        """Reset gameplay state and begin a new run.

        Clears the bubble, the effects, every timer, the score, the combo
        chain and the launcher aim; rolls a fresh current/next queue; and
        switches the scene to `"playing"`. Lifetime records (high score, best
        tier) are kept. The run counter `games_played` goes up by one and is
        saved straight away, so a run counts even if the game is closed
        mid-run.
        """
        self.scene = "playing"
        self.bodies.clear()

        # Reset transient feedback so old particles/shake do not leak into the new run.
        self.effects = EffectsManager()
        self.drop_timer = 0.0
        self.fail_timer = 0.0
        self.container_stress = 0.0
        self.goal_reached = False
        self.warning_active = False
        self.danger_mood = False
        self._danger_mood_timer = 0.0
        self.launch_angle = 0.0
        self.angle_dragging = False
        self.score = 0
        self.new_record = False
        self.best_tier_seen = 0
        self._score_to_beat = self.high_score
        self._high_score_cheered = False
        self.current_tier, self.current_seed = self._roll_spawn_choice()
        self.next_tier, self.next_seed = self._roll_spawn_choice()
        self.spawn_x = self.world.center.x
        self._next_body_id = 1

        # A new run starts with no combo chain and no pending warning beep.
        self._combo_count = 0
        self._last_merge_time = -999.0
        self._next_warning_beep = 0.0

        # Count this run and persist the updated lifetime stats right away.
        self.games_played += 1
        self._save_progress()
        self.assets.sounds.play("button", 0.45)

    def drop_current_body(self) -> None:
        """Launch the current queued body into the container.

        Does nothing unless the scene is `"playing"` and the launch cooldown
        has run out. If the bubble already holds `MAX_BODIES` bodies the run
        ends instead. Otherwise a new body of `current_tier` is created at the
        legal spawn point, moving along the aim direction at `LAUNCH_SPEED`,
        the queue moves forward one slot, and the cooldown restarts.
        """
        # Ignore launches when not actively playing. While the cooldown is
        # active a launch is refused, with a soft "not yet" so the player
        # knows the click was heard.
        if self.scene != "playing":
            return
        if self.drop_timer > 0.0:
            self.assets.sounds.play("launch_blocked", SFX_VOLUMES["launch_blocked"])
            return

        # A body cap prevents the simulation from becoming too crowded or slow.
        if len(self.bodies) >= MAX_BODIES:
            self._trigger_game_over()
            return

        # Clamp the launcher X so large bodies cannot spawn through the wall.
        min_x, max_x = self.world.allowed_spawn_x(TIERS[self.current_tier].radius)
        self.spawn_x = clamp(self.spawn_x, min_x, max_x)

        # Build and register the new physical body.
        body = CelestialBody(
            body_id=self._next_body_id,
            tier=self.current_tier,
            position=self.world.spawn_point(self.spawn_x, TIERS[self.current_tier].radius),
            velocity=self._launch_velocity(),
            created_at=self.now,
            seed=self.current_seed,
        )
        # Once spawned, the queued values move forward exactly one slot:
        # current launches now, next becomes current, and a fresh next is rolled.
        self._next_body_id += 1
        self.bodies.append(body)
        self.best_tier_seen = max(self.best_tier_seen, body.tier)
        self.lifetime_best_tier = max(self.lifetime_best_tier, body.tier)

        # Advance the queue and start the launch cooldown.
        # What was "next" becomes "current", then a brand-new "next" is rolled.
        self.current_tier = self.next_tier
        self.current_seed = self.next_seed
        self.next_tier, self.next_seed = self._roll_spawn_choice()
        self.drop_timer = DROP_COOLDOWN
        self.assets.sounds.play("drop", 0.35)
        self.assets.sounds.play("whoosh", SFX_VOLUMES["whoosh"])

    def _update(self, dt: float) -> None:
        """Advance one frame of non-drawing game logic.

        While playing, the order is: aim the launcher, tick the cooldown, step
        the physics (turning hard impacts into effects), update body
        animations, apply merges, and finally check the fail line. The order
        matters: merges are found on the positions physics has just produced,
        and the fail check sees the stack after merges have removed bodies.

        Outside of `"playing"` only the background parallax and the effects
        keep moving; the simulation is frozen.

        Args:
            dt: Seconds since the previous frame (already capped by `run()`).
        """
        # Mouse-driven background drift adds a small amount of depth. With
        # clamping on, the helper never actually returns None; the fallback
        # here just repeats its own center default for the type checker.
        logical_mouse = self._current_canvas_mouse() or (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        drift = pygame.Vector2(logical_mouse) - pygame.Vector2(self.world.center.x, SCREEN_HEIGHT / 2)
        self.background_drift = drift * 0.06

        if self.scene == "playing":
            # Only the active gameplay scene should change simulation state.
            self._update_spawn_aim(dt)
            self.drop_timer = max(0.0, self.drop_timer - dt)

            # Physics runs only while the round is active.
            collisions = self.world.step(self.bodies, dt)

            # The hardest impact a body registers this frame gets one thud;
            # a pile of simultaneous thuds would only sound like noise.
            hardest = 0.0
            for collision in collisions:
                # Convert high-energy impacts into particles and pulse animations.
                if collision.body_a.register_impact(self.now, collision.impact_speed):
                    self.effects.impact(collision.point, collision.body_a.info.color, collision.impact_speed)
                    hardest = max(hardest, collision.impact_speed)
                if collision.body_b and collision.body_b.register_impact(self.now, collision.impact_speed):
                    self.effects.impact(collision.point, collision.body_b.info.color, collision.impact_speed)
                    hardest = max(hardest, collision.impact_speed)
            if hardest > 0.0:
                weight, volume = impact_sound(hardest)
                self.assets.sounds.play("impact", volume, pitch_step=weight)

            for body in self.bodies:
                # Bodies also update their own blink/pulse state each frame.
                body.update(dt)

            # Physics overlap is not enough by itself; merge rules decide when
            # those overlaps should become real evolutions.
            merge_events = find_merge_events(self.bodies, self.now)
            if merge_events:
                self._apply_merges(merge_events)

            self._update_fail_state(dt)

        # Effects keep animating independently.
        # In this game the pause scene still redraws the current frame instead of
        # freezing a screenshot, so effect state can still be stepped safely.
        self.effects.update(dt)
        self._sync_music()

    def _music_wanted(self) -> str | None:
        """Return which music track the current moment calls for.

        The tense track plays while a run (playing or paused) is over the
        danger line, the calm one everywhere else, and nothing after a loss
        so the game-over jingle stands alone.
        """
        if self.scene == "game_over":
            return None
        if self.scene in {"playing", "paused"} and self.danger_mood:
            return "tense"
        return "calm"

    def _sync_music(self) -> None:
        """Crossfade to the wanted music track, then let both players update.

        A change between calm and tense fades one out while the other fades
        in; music starting from silence fades in more slowly, and a loss
        fades the music out under the game-over jingle.
        """
        wanted = self._music_wanted()
        if wanted != self._music_mood:
            if self._music_mood is not None:
                self.music[self._music_mood].stop(MUSIC_CROSSFADE_MS if wanted else MUSIC_GAME_OVER_FADE_MS)
            if wanted is not None:
                self.music[wanted].start(MUSIC_CROSSFADE_MS if self._music_mood else MUSIC_FADE_IN_MS)
            self._music_mood = wanted
        for player in self.music.values():
            # Hands a finished background render to the mixer (main thread only).
            player.update()

    def _update_spawn_aim(self, dt: float) -> None:
        """Update launcher position and angle from mouse/keyboard input.

        The launcher column follows the mouse only while the cursor is near
        the top of the canvas (at most 34 px below `SPAWN_Y`) and the player
        is not right-dragging the aim. A/D or Left/Right move it at
        `KEYBOARD_AIM_SPEED`, and W/S or Up/Down turn it at
        `ANGLE_AIM_SPEED`, both scaled by `dt` so held keys move smoothly.
        The column is always clamped to the span where the current body fits.

        Args:
            dt: Seconds since the previous frame.
        """
        radius = TIERS[self.current_tier].radius
        min_x, max_x = self.world.allowed_spawn_x(radius)

        logical_mouse = self._current_canvas_mouse(clamp=False)
        if logical_mouse is not None and not self.angle_dragging and logical_mouse[1] <= SPAWN_Y + 34:
            # Horizontal launcher movement only follows the mouse near the top
            # so regular gameplay mouse movement does not constantly yank it around.
            mouse_x, _ = logical_mouse
            self.spawn_x = clamp(mouse_x, min_x, max_x)

        keys = pygame.key.get_pressed()
        move_direction = 0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            move_direction -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            move_direction += 1
        if move_direction:
            # Keyboard movement is continuous because it uses `dt`.
            self.spawn_x = clamp(self.spawn_x + move_direction * KEYBOARD_AIM_SPEED * dt, min_x, max_x)

        # Angle controls are tracked separately from horizontal movement controls.
        angle_direction = 0
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            angle_direction -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            angle_direction += 1
        if angle_direction:
            self._nudge_launch_angle(angle_direction * ANGLE_AIM_SPEED * dt)

    def _apply_merges(self, merge_events) -> None:
        """Replace merged body pairs with their upgraded result.

        For every merge event (from `merge_logic.find_merge_events`) whose two
        bodies are both still unused this frame, the pair is removed and one
        body of `target_tier` is created at the event's position and velocity.
        Each merge also:

        - advances the combo chain and adds the combo-boosted score;
        - spawns merge effects, plus a combo popup from a chain of two;
        - updates the run's and lifetime's best tier, with a bigger celebration
          and sound for the top tier (once per run) or a new lifetime best
          tier of 5 or above.

        Bodies are removed and added only after the loop, so the list is never
        changed while it is being walked. Progress is saved only if a record
        actually changed.

        Args:
            merge_events: `MergeEvent`s for this frame, in priority order.

        Beginner note:
        - The `consumed` set is what stops one body from merging twice in the
          same frame when it touches two equal partners at once.
        """
        # Remember the records so the save file is only rewritten when a merge
        # actually moves one; ordinary merges happen constantly and would
        # otherwise hit the disk many times a second.
        records_before = (self.high_score, self.lifetime_best_tier)

        # A dictionary makes it fast to turn event IDs back into real body objects.
        by_id = {body.body_id: body for body in self.bodies}
        consumed: set[int] = set()
        spawned: list[CelestialBody] = []

        for event in merge_events:
            # Skip any event if one of its bodies was already used this frame.
            if event.first_id in consumed or event.second_id in consumed:
                continue
            first = by_id.get(event.first_id)
            second = by_id.get(event.second_id)
            if first is None or second is None:
                continue

            consumed.add(first.body_id)
            consumed.add(second.body_id)

            # Spawn the upgraded body described by the merge event.
            merged_body = CelestialBody(
                body_id=self._next_body_id,
                tier=event.target_tier,
                position=pygame.Vector2(event.position),
                velocity=pygame.Vector2(event.velocity),
                created_at=self.now,
                seed=self.random.random(),
            )
            # The merged body gets a fresh seed so its orbital drift and idle
            # personality feel like a distinct orb. The seed comes from the
            # game's own seeded generator (not the global `random`), because it
            # changes the body's gravity drift: seeded runs, tests, and
            # simulations must replay exactly. The global `random` is kept for
            # purely cosmetic things such as hover phase, blinks, and particles.
            # `pulse`/`flash`/`birth_pop` together drive the "punchy arrival":
            # the body flashes, pops outward, and scales up from small to full.
            merged_body.pulse = 0.95
            merged_body.flash = 0.95
            merged_body.birth_pop = 1.0

            # Ensure the newly spawned result is still safely inside the bubble.
            self.world.keep_inside(merged_body)
            spawned.append(merged_body)
            self._next_body_id += 1

            # Combo scoring: merges chained within `COMBO_WINDOW` seconds of the
            # previous merge build an escalating multiplier (see rules.py).
            self._combo_count = next_combo_count(self._combo_count, self._last_merge_time, self.now)
            self._last_merge_time = self.now
            gained = combo_points(event.score_gain, self._combo_count)

            # Reward the player and fire appropriate celebratory effects.
            self.score += gained
            self.effects.merge(merged_body.position, merged_body.info.color, gained, event.target_tier)
            if self._combo_count >= 2:
                # A chain of quick merges earns its own callout popup, and a
                # chime that climbs one step with every link of the chain.
                self.effects.combo(self._combo_count, merged_body.position)
                chime = min(self._combo_count, COMBO_CHIME_TOP)
                self.assets.sounds.play("combo", SFX_VOLUMES["combo"], pitch_step=chime)
            self.best_tier_seen = max(self.best_tier_seen, event.target_tier)

            # A merge that beats the best tier ever reached is a personal record.
            new_personal_best = event.target_tier > self.lifetime_best_tier
            self.lifetime_best_tier = max(self.lifetime_best_tier, event.target_tier)

            if event.target_tier >= len(TIERS) - 1 and not self.goal_reached:
                # Reaching the top tier is a milestone the first time it happens.
                self.goal_reached = True
                self.effects.announce(f"{merged_body.info.name} reached!", merged_body.position)
                self.effects.reward_burst(merged_body.position, merged_body.info.color)
                self.assets.sounds.play("record", 0.45)
            elif new_personal_best and event.target_tier >= 5:
                # First time the player has ever reached this mid/high tier.
                self.effects.reward_burst(merged_body.position, merged_body.info.color)
                self.assets.sounds.play("record", 0.42)
            elif event.target_tier >= len(TIERS) - 3:
                self.assets.sounds.play("big_merge", 0.42, pitch_step=event.target_tier)
            else:
                # Each tier merges one step higher up the scale.
                self.assets.sounds.play("merge", 0.36, pitch_step=event.target_tier)

        if consumed:
            # Remove all consumed bodies, then append the newly spawned merged bodies.
            self.bodies = [body for body in self.bodies if body.body_id not in consumed]
            self.bodies.extend(spawned)
            self._refresh_high_score()
            # Passing the old high score mid-run sparkles once. A first-ever
            # run has no score to beat yet, so it stays quiet.
            if not self._high_score_cheered and 0 < self._score_to_beat < self.score:
                self._high_score_cheered = True
                self.assets.sounds.play("high_score", SFX_VOLUMES["high_score"])
            if (self.high_score, self.lifetime_best_tier) != records_before:
                self._save_progress()

    def _update_fail_state(self, dt: float) -> None:
        """Track whether the player is approaching game over.

        A body counts as "over the line" when its top edge is above
        `FAIL_LINE_Y` and it is older than `FAIL_AGE_GATE` (a body still
        falling in from the launcher is ignored). While any body is over, the
        fail timer fills and a warning beep repeats faster and louder as it
        fills; otherwise the timer drains (see `rules.advance_fail_timer`).
        The HUD stress meter is recomputed from the highest settled body and
        the timer, and the run ends once the timer reaches `FAIL_GRACE`.

        Args:
            dt: Seconds since the previous frame.
        """
        # Only bodies older than the fail-age gate count toward the stress
        # meter, so a body still falling from the launcher does not make the
        # meter jump on every drop.
        highest_top = min(
            (body.top for body in self.bodies if body.age(self.now) > FAIL_AGE_GATE),
            default=self.world.center.y + self.world.radius,
        )

        # Only older bodies count toward losing. This prevents a just-launched body
        # from instantly causing game over while it is still entering the field.
        warning = any(body.top < FAIL_LINE_Y and body.age(self.now) > FAIL_AGE_GATE for body in self.bodies)
        self.warning_active = warning
        # What the player HEARS (the danger cue and the tense music) follows a
        # steadier "danger mood" that only flips after the new state has held
        # for DANGER_MOOD_HOLD seconds.
        # Beginner note: this is called hysteresis. A body resting exactly on
        # the line can cross it on one frame and not the next; acting on every
        # flip would make the cues chatter and restart the music each frame.
        if warning != self.danger_mood:
            self._danger_mood_timer += dt
            if self._danger_mood_timer >= DANGER_MOOD_HOLD:
                self.danger_mood = warning
                self._danger_mood_timer = 0.0
                # Entering and leaving danger each get a short cue of their own.
                cue = "danger_on" if warning else "danger_off"
                self.assets.sounds.play(cue, SFX_VOLUMES[cue])
        else:
            self._danger_mood_timer = 0.0
        # The fail timer fills while danger is active and drains when the
        # player recovers (the exact rates live in rules.py).
        self.fail_timer = advance_fail_timer(self.fail_timer, dt, warning)
        if warning:
            # Play an escalating warning beep: the closer to game over, the
            # faster the tone repeats, so danger is felt as well as seen.
            if self.now >= self._next_warning_beep:
                ratio = fail_ratio(self.fail_timer)
                self.assets.sounds.play("warning", 0.28 + ratio * 0.3)
                self._next_warning_beep = self.now + warning_beep_interval(ratio)
        else:
            # Reset the beep timer so the next danger spell starts fresh.
            self._next_warning_beep = 0.0

        # Live stress rises as the tallest point in the stack approaches the
        # fail line, then the fail countdown fills the rest of the meter once
        # the line is crossed. This gives the HUD a continuous response instead
        # of only reacting after the player is already in immediate danger.
        self.container_stress = stress_level(highest_top, self.fail_timer, warning)
        if self.fail_timer >= FAIL_GRACE:
            self._trigger_game_over()

    def _trigger_game_over(self) -> None:
        """End the current run if it is not already over."""
        if self.scene == "game_over":
            # This guard prevents duplicate sounds or repeated state changes.
            return
        self.scene = "game_over"
        self.warning_active = False
        self.danger_mood = False
        self._danger_mood_timer = 0.0
        self._refresh_high_score()
        self._save_progress()
        # The music fades out and a jingle sums up the run: a fanfare for a
        # new high score, otherwise a gentle falling phrase.
        self._sync_music()
        self.assets.sounds.play("record" if self.new_record else "game_over", 0.42)

    def _roll_spawn_tier(self) -> int:
        """Randomly choose a low-tier body for the queue based on weighted odds."""
        indices = list(range(len(SPAWN_WEIGHTS)))
        # `random.choices(..., k=1)` returns a one-item list, so `[0]` extracts the value.
        return self.random.choices(indices, weights=SPAWN_WEIGHTS, k=1)[0]

    def _roll_spawn_choice(self) -> tuple[int, float]:
        """Create one queued spawn entry: both its tier and its motion seed.

        The tier decides:
        - size,
        - color,
        - score potential.

        The seed decides:
        - the tiny sideways orbital drift in its gravity (which the
          trajectory preview also uses),
        - small face details such as its idle gaze and mouth wiggle.

        Storing both values in the queue means the preview arc can represent the
        actual body that will be launched next, not just a rough generic stand-in.
        """
        return self._roll_spawn_tier(), self.random.random()

    def _load_progress(self) -> dict:
        """Read the saved high score, lifetime stats and sound setting, falling back safely."""
        try:
            data = json.loads(SAVE_DATA_PATH.read_text(encoding="utf-8")) if SAVE_DATA_PATH.exists() else {}
            return sanitize_progress(data)
        except (OSError, ValueError, TypeError, AttributeError, OverflowError, RecursionError):
            # A missing or corrupt file simply means "no progress saved yet".
            # `OverflowError` covers numbers like 1e999 or `Infinity`, which
            # cannot become an int; `RecursionError` covers absurdly deep
            # nesting that exhausts the JSON reader. (`json.JSONDecodeError`
            # is a kind of `ValueError`, so it is already covered.)
            return {"high_score": 0, "games_played": 0, "best_tier": 0, "muted": False}

    def _refresh_high_score(self) -> None:
        """Promote the current score to a new high score when it beats the old best."""
        if self.score > self.high_score:
            self.high_score = self.score
            self.new_record = True

    def _save_progress(self) -> None:
        """Persist high score, lifetime stats and the sound setting with a crash-safe atomic write."""
        if not self.persist:
            return
        payload = {
            "high_score": self.high_score,
            "games_played": self.games_played,
            "best_tier": self.lifetime_best_tier,
            "muted": self.muted,
        }
        try:
            SAVE_DATA_DIR.mkdir(parents=True, exist_ok=True)
            # Write to a temp file first, then atomically swap it into place so a
            # crash mid-write can never leave a half-written save behind.
            tmp_path = SAVE_DATA_PATH.with_name(SAVE_DATA_PATH.name + ".tmp")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp_path, SAVE_DATA_PATH)
        except OSError as error:
            _log_error(error)

    def _draw(self) -> None:
        """Render one complete frame to the internal canvas, then present it.

        Layers, back to front: background, playfield shell and fail line,
        bodies (smallest first), launcher and danger label (in a run only),
        effects, HUD and in-run buttons, then the full-screen overlay for the
        menu, pause or game-over scene. Finally `_present()` scales the canvas
        into the window.

        Beginner note:
        - pygame has no layers or z-order: whatever is drawn last ends up on
          top. Getting the order of calls right *is* the layering.
        - The same camera-shake offset is passed to bodies, launcher and
          effects so they all shake together, while the HUD stays still.
        """
        # IMPORTANT: drawing order matters.
        # Background should be behind everything,
        # bodies should appear inside the playfield,
        # UI should appear on top.

        # Start by clearing the canvas with a fresh background draw each frame.
        # For hover effects, a mouse position outside the canvas should behave
        # like "not hovering anything", so we use an off-screen fallback.
        hover_mouse = self._current_canvas_mouse(clamp=False) or (-9999, -9999)

        # Draw background first.
        self.assets.draw_background(self.canvas, self.now, self.background_drift)

        # Effects manager provides camera shake as a temporary offset.
        camera = self.effects.camera_offset()

        # Draw the playfield shell before bodies go inside it.
        # Danger belongs to a run: behind the main menu the line is calm and
        # unlabelled, even if the player left a run while it was in danger.
        in_run = self.scene in {"playing", "paused", "game_over"}
        danger_ratio = fail_ratio(self.fail_timer) if in_run else 0.0
        draw_playfield(self.canvas, danger_ratio)

        # Draw smaller bodies first so larger ones can overlap them naturally.
        for body in sorted(self.bodies, key=lambda item: item.radius):
            body.draw(self.canvas, self.assets, camera, self.now)

        # The launcher (orb, aim line, and trajectory dots) goes on top of the
        # bodies, so it stays visible even when a tall stack rises behind it.
        if in_run:
            self._draw_spawn_indicator(camera)
            if self.warning_active:
                # The danger label goes on top of the stack so it stays
                # readable, at a spot that keeps clear of the launcher.
                self._draw_danger_label(camera)

        # Particles/popups sit on top of the bodies.
        self.effects.draw(self.canvas, self.assets, camera)

        if self.scene in {"playing", "paused", "game_over"}:
            # HUD and persistent in-run buttons.
            draw_hud(self.canvas, self, self.assets)
            self.pause_button.draw(self.canvas, self.assets, hover_mouse)
            self.restart_button.draw(self.canvas, self.assets, hover_mouse)
            draw_sound_toggle(self.canvas, self.assets, self.sound_button, self.muted, hover_mouse)

        # Finally draw whichever full-screen overlay matches the current scene.
        if self.scene == "menu":
            draw_menu_overlay(
                self.canvas,
                self.assets,
                [self.play_button],
                self.high_score,
                self.games_played,
                self.lifetime_best_tier_name,
                hover_mouse,
            )
            draw_sound_toggle(self.canvas, self.assets, self.menu_sound_button, self.muted, hover_mouse)
        elif self.scene == "paused":
            draw_pause_overlay(
                self.canvas,
                self.assets,
                [self.resume_button, self.pause_restart_button, self.pause_menu_button],
                hover_mouse,
            )
        elif self.scene == "game_over":
            draw_game_over_overlay(
                self.canvas,
                self.assets,
                [self.over_restart_button, self.over_menu_button],
                self.score,
                self.high_score,
                self.new_record,
                self.games_played,
                self.lifetime_best_tier_name,
                hover_mouse,
            )

        # `_present()` is the last step because everything should already be
        # fully drawn onto the internal canvas before scaling to the real window.
        self._present()

    def _draw_spawn_indicator(self, camera: pygame.Vector2) -> None:
        """Draw the launcher preview line, arrow, angle label, and current orb.

        Everything starts from the same legal spawn point the real body will
        use. Back to front: the dotted trajectory preview, a soft halo, the
        cooldown arc (while recharging), the aim line with fading guides and an
        arrow head, the angle readout, and finally the orb that will launch,
        dimmed while the cooldown runs.

        Side effect: `spawn_x` is clamped to the span where the current body
        fits, because the queue may have just switched to a bigger body.

        Args:
            camera: Screen-shake offset added to every drawn point.
        """
        min_x, max_x = self.world.allowed_spawn_x(TIERS[self.current_tier].radius)
        self.spawn_x = clamp(self.spawn_x, min_x, max_x)

        # The launcher line points in the same direction as the initial launch velocity.
        direction = self._launch_direction()
        # The launcher orb, aim line, and preview all start from the same legal
        # spawn point the real body will use (see `PhysicsWorld.spawn_point`).
        spawn = self.world.spawn_point(self.spawn_x, TIERS[self.current_tier].radius)
        start = spawn + camera
        back = start - direction * 64.0
        front = start + direction * 166.0
        beam_color = WARNING if self.warning_active else (175, 216, 255)

        # Draw a dotted path preview so the player can read the angled launch
        # more easily than from a single straight line alone.
        preview_points = self.world.preview_trajectory(
            spawn,
            self._launch_velocity(),
            TIERS[self.current_tier].radius,
            self.current_seed,
        )
        if preview_points:
            self._draw_preview_trail(preview_points, camera, beam_color)

        # A launcher halo helps the origin point read clearly against busy stacks.
        halo = pygame.Surface((88, 88), pygame.SRCALPHA)
        halo_center = pygame.Vector2(halo.get_width() / 2, halo.get_height() / 2)
        pygame.draw.circle(halo, (*beam_color, 28), halo_center, 34)
        pygame.draw.circle(halo, (*beam_color, 70), halo_center, 18, width=3)
        self.canvas.blit(halo, halo.get_rect(center=(round(start.x), round(start.y))))

        # Launch-cooldown feedback: while the launcher is "recharging" after a
        # drop, an arc grows around it (and the preview orb below dims). This
        # explains why a click is briefly ignored instead of feeling like lag.
        cooldown_ratio = clamp(self.drop_timer / DROP_COOLDOWN, 0.0, 1.0) if DROP_COOLDOWN > 0.0 else 0.0
        if cooldown_ratio > 0.0:
            ready_fraction = 1.0 - cooldown_ratio
            arc_rect = pygame.Rect(0, 0, 78, 78)
            arc_rect.center = (round(start.x), round(start.y))
            # The arc sweeps further around the circle as the launcher recharges.
            pygame.draw.arc(self.canvas, (150, 200, 255), arc_rect, 0.0, ready_fraction * math.tau, 4)

        # The guide extends in both directions:
        # - a short tail behind the launcher,
        # - a longer forward direction arrow where the launch will go.
        pygame.draw.line(self.canvas, beam_color, back, front, 3)
        self._draw_aim_guides(start, direction, beam_color)

        # Add a simple arrow head to the end of the launcher guide.
        arrow_left = front - direction * 22.0 + pygame.Vector2(-direction.y, direction.x) * 12.0
        arrow_right = front - direction * 22.0 - pygame.Vector2(-direction.y, direction.x) * 12.0
        pygame.draw.polygon(self.canvas, beam_color, [front, arrow_left, arrow_right])
        pygame.draw.circle(self.canvas, beam_color, back, 6)

        # Show the current angle numerically for players who want precision.
        angle_label = self.assets.small_font.render(f"{self.launch_angle:+.0f} deg", True, beam_color)
        self.canvas.blit(angle_label, angle_label.get_rect(midbottom=(int(back.x), int(back.y - 12))))

        # The preview orb shows exactly what body will launch next. It dims
        # while the launcher is on cooldown and brightens as it becomes ready.
        ready_alpha = 230 if self.scene == "playing" else 180
        if cooldown_ratio > 0.0:
            ready_alpha = int(110 + 120 * (1.0 - cooldown_ratio))
        self.assets.draw_preview_orb(
            self.canvas,
            self.current_tier,
            start,
            self.now,
            alpha=ready_alpha,
        )

    def _draw_preview_trail(
        self,
        preview_points: list[pygame.Vector2],
        camera: pygame.Vector2,
        beam_color: tuple[int, int, int],
    ) -> None:
        """Draw the dotted trajectory preview as soft, fading dots.

        Beginner note:
        - The dots are translucent, so they are drawn on their own alpha
          surface and then blended onto the canvas in one blit.
        - That surface only needs to cover the dots, not the whole screen.
          Clearing and blending a full 1024x1280 surface every frame was the
          most expensive part of the launcher drawing.
        """
        preview_total = max(1, len(preview_points) - 1)
        dots: list[tuple[int, int, int, int, int]] = []
        for index, point in enumerate(preview_points):
            # Early points are drawn brighter/larger so the most immediate
            # section of the path is easiest to understand.
            progress = index / preview_total
            dot_center = point + camera
            dot_radius = max(2, int(8 - progress * 4.5))
            dot_alpha = int(125 - progress * 72)
            glow_alpha = int(42 - progress * 22)
            dots.append((int(dot_center.x), int(dot_center.y), dot_radius, dot_alpha, glow_alpha))

        # Bounding box of every glow circle, padded so antialiasing never clips.
        reach = max(dot[2] for dot in dots) + PREVIEW_GLOW_EXTRA + OVERLAY_PADDING
        left = min(dot[0] for dot in dots) - reach
        top = min(dot[1] for dot in dots) - reach
        width = max(dot[0] for dot in dots) + reach - left + 1
        height = max(dot[1] for dot in dots) + reach - top + 1
        trail = pygame.Surface((width, height), pygame.SRCALPHA)
        for x, y, dot_radius, dot_alpha, glow_alpha in dots:
            local = (x - left, y - top)
            pygame.draw.circle(trail, (*beam_color, max(0, glow_alpha)), local, dot_radius + PREVIEW_GLOW_EXTRA)
            pygame.draw.circle(trail, (*beam_color, max(0, dot_alpha)), local, dot_radius)
        self.canvas.blit(trail, (left, top))

    def _draw_aim_guides(
        self,
        start: pygame.Vector2,
        direction: pygame.Vector2,
        beam_color: tuple[int, int, int],
    ) -> None:
        """Draw faded aim-guide segments so the aim line feels brighter and "spacey".

        Each segment gets its own small alpha surface sized to the segment, so
        the overlapping translucent strokes still build up exactly as before.
        """
        for guide_length, alpha in ((72.0, 95), (118.0, 70), (162.0, 45)):
            guide_end = start + direction * guide_length
            left = math.floor(min(start.x, guide_end.x)) - OVERLAY_PADDING
            top = math.floor(min(start.y, guide_end.y)) - OVERLAY_PADDING
            width = math.ceil(max(start.x, guide_end.x)) + OVERLAY_PADDING - left + 1
            height = math.ceil(max(start.y, guide_end.y)) + OVERLAY_PADDING - top + 1
            ghost = pygame.Surface((width, height), pygame.SRCALPHA)
            offset = pygame.Vector2(left, top)
            pygame.draw.line(ghost, (*beam_color, alpha), start - offset, guide_end - offset, 2)
            self.canvas.blit(ghost, (left, top))

    def _draw_danger_label(self, camera: pygame.Vector2) -> None:
        """Draw the "Danger line" label where it cannot hide the launcher or aim line."""
        radius = TIERS[self.current_tier].radius
        launcher = self.world.spawn_point(self.spawn_x, radius) + camera
        direction = self._launch_direction()
        font = self.assets.small_font
        rect = danger_label_rect(
            font.size("Danger line"),
            launcher,
            radius,
            launcher - direction * 64.0,
            launcher + direction * 166.0,
        )
        draw_danger_label(self.canvas, font, rect.center)

    def _launch_direction(self) -> pygame.Vector2:
        """Convert the current launcher angle into a unit direction vector."""
        radians = math.radians(self.launch_angle)
        # `sin` controls horizontal component, `cos` controls vertical component.
        # Because screen Y increases downward, a positive Y component still points down.
        return pygame.Vector2(math.sin(radians), math.cos(radians))

    def _launch_velocity(self) -> pygame.Vector2:
        """Convert aim direction into the starting velocity for a newly launched body."""
        return self._launch_direction() * LAUNCH_SPEED

    def _nudge_launch_angle(self, delta: float) -> None:
        """Adjust the launcher angle while keeping it inside the allowed range."""
        self._aim_at(self.launch_angle + delta)

    def _aim_at(self, angle: float) -> None:
        """Set the launcher angle (clamped to the legal range), ticking at each detent.

        The aim clicks softly every `AIM_TICK_DEGREES`, like a dial, so fine
        aiming can be felt as well as seen.
        """
        angle = clamp(angle, -MAX_LAUNCH_ANGLE, MAX_LAUNCH_ANGLE)
        if aim_tick_crossed(self.launch_angle, angle):
            self.assets.sounds.play("aim_tick", SFX_VOLUMES["aim_tick"])
        self.launch_angle = angle

    def _set_launch_angle_from_point(self, point: tuple[int, int]) -> None:
        """Aim the launcher toward a point in internal canvas coordinates."""
        origin = self.world.spawn_point(self.spawn_x, TIERS[self.current_tier].radius)
        target = pygame.Vector2(point)
        delta = target - origin
        if delta.length_squared() < 1.0:
            # Ignore tiny jitter if the mouse is basically on top of the launcher origin.
            return

        # Avoid allowing the angle to point backward/upward past a sensible limit.
        if delta.y < 16.0:
            delta.y = 16.0

        # `atan2(x, y)` here turns the 2D direction into an angle in degrees.
        # We use x first and y second because our angle is defined as sideways
        # deviation from "straight down", not the usual math convention.
        self._aim_at(math.degrees(math.atan2(delta.x, delta.y)))

    def _recommended_window_size(self) -> tuple[int, int]:
        """Choose a starting window size that fits on the current monitor."""
        display_info = pygame.display.Info()
        if display_info.current_w <= 0 or display_info.current_h <= 0:
            return SCREEN_WIDTH, SCREEN_HEIGHT

        # Leave a small safety margin around the window so it does not touch screen edges.
        max_width = max(420, display_info.current_w - 64)
        max_height = max(420, display_info.current_h - 96)
        scale = min(max_width / SCREEN_WIDTH, max_height / SCREEN_HEIGHT, 1.0)
        return max(1, int(SCREEN_WIDTH * scale)), max(1, int(SCREEN_HEIGHT * scale))

    def _update_render_rect(self, window_size: tuple[int, int]) -> None:
        """Recompute the letterboxed area where the internal canvas should be drawn."""
        window_width, window_height = window_size
        scale = min(window_width / SCREEN_WIDTH, window_height / SCREEN_HEIGHT)
        width = max(1, int(SCREEN_WIDTH * scale))
        height = max(1, int(SCREEN_HEIGHT * scale))

        # Center the scaled canvas inside the real window.
        self.render_rect = pygame.Rect(
            (window_width - width) // 2,
            (window_height - height) // 2,
            width,
            height,
        )

    def _window_to_canvas(self, position: tuple[int, int], keep_inside: bool = False) -> tuple[int, int] | None:
        """Convert real window coordinates into internal canvas coordinates.

        This is required because the game can be letterboxed inside a resized window.
        """
        if self.render_rect.width <= 0 or self.render_rect.height <= 0:
            return None
        if not self.render_rect.collidepoint(position) and not keep_inside:
            return None

        # Convert to percentages inside the render rectangle, then scale that
        # percentage into internal 1024x1280 coordinates.
        relative_x = (position[0] - self.render_rect.x) / self.render_rect.width
        relative_y = (position[1] - self.render_rect.y) / self.render_rect.height
        relative_x = clamp(relative_x, 0.0, 1.0)
        relative_y = clamp(relative_y, 0.0, 1.0)
        return int(relative_x * SCREEN_WIDTH), int(relative_y * SCREEN_HEIGHT)

    def _current_canvas_mouse(self, clamp: bool = True) -> tuple[int, int] | None:
        """Read the current mouse position in internal canvas space."""
        logical = self._window_to_canvas(pygame.mouse.get_pos(), keep_inside=clamp)
        if logical is not None:
            return logical
        if clamp:
            # Returning the center gives callers a safe fallback position.
            return SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2
        return None

    def _present(self) -> None:
        """Copy the internal canvas to the actual window and show it on screen."""
        # Fill the real window first so any letterboxed margins look intentional.
        self.window.fill((2, 5, 12))
        if self.render_rect.size == self.canvas.get_size():
            self.window.blit(self.canvas, self.render_rect.topleft)
        else:
            # When the window is a different size, scale the internal canvas to fit.
            scaled = pygame.transform.smoothscale(self.canvas, self.render_rect.size)
            self.window.blit(scaled, self.render_rect.topleft)
        pygame.display.flip()
