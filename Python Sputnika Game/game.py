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

import pygame

from assets import AssetLibrary
from effects import EffectsManager
from entities import CelestialBody
from merge_logic import find_merge_events
from physics import PhysicsWorld
from settings import (
    ANGLE_AIM_SPEED,
    COMBO_WINDOW,
    DROP_COOLDOWN,
    FAIL_AGE_GATE,
    FAIL_DECAY,
    FAIL_GRACE,
    FAIL_LINE_Y,
    FPS,
    KEYBOARD_AIM_SPEED,
    LAUNCH_SPEED,
    MAX_LAUNCH_ANGLE,
    MAX_BODIES,
    MOUSE_WHEEL_ANGLE_STEP,
    SAVE_DATA_DIR,
    SAVE_DATA_PATH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SPAWN_WEIGHTS,
    SPAWN_Y,
    STRESS_PREVIEW_RANGE,
    TIERS,
    WARNING,
    WINDOW_TITLE,
    clamp,
)
from ui import Button, draw_game_over_overlay, draw_hud, draw_menu_overlay, draw_pause_overlay, draw_playfield


def _log_save_error(error: Exception) -> None:
    """Record a failed save to a log file instead of letting it fail silently."""
    try:
        SAVE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with (SAVE_DATA_DIR / "save_error.log").open("a", encoding="utf-8") as log_file:
            log_file.write(f"[{stamp}] could not save progress: {error}\n")
    except OSError:
        # If even the log write fails there is nothing more we can safely do.
        pass


class OrbitalOrchardGame:
    """Top-level game object that keeps all subsystems working together."""

    def __init__(self) -> None:
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
        # `spawn_x` is horizontal position only; vertical spawn height is fixed by `SPAWN_Y`.
        self.spawn_x = self.world.center.x
        self.launch_angle = 0.0
        self.angle_dragging = False

        # Timers and progression values.
        self.drop_timer = 0.0
        self.fail_timer = 0.0
        self.container_stress = 0.0
        self.goal_reached = False
        self.warning_active = False
        self.score = 0
        progress = self._load_progress()
        self.high_score = progress["high_score"]
        self.games_played = progress["games_played"]
        self.lifetime_best_tier = progress["best_tier"]
        self.new_record = False
        self.best_tier_seen = 0

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
        """Run the main loop until the player quits or a test frame limit is reached."""
        frames = 0
        while self.running:
            # `clock.tick(FPS)` waits just enough to target 60 FPS and returns the
            # elapsed milliseconds since the previous frame.
            #
            # `dt` means "delta time": how many seconds passed since the previous frame.
            # Multiplying movement by `dt` keeps motion consistent across frame rates.
            dt = min(0.025, self.clock.tick(FPS) / 1000.0)
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
        """Process every pending pygame event for the current frame."""
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
                self._handle_keydown(event.key)

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

    def _handle_keydown(self, key: int) -> None:
        """Handle one key press based on the current scene."""
        if key in (pygame.K_ESCAPE, pygame.K_p):
            # `Esc` / `P` toggles pause during gameplay.
            if self.scene == "playing":
                self.scene = "paused"
                self.assets.sounds.play("button", 0.4)
            elif self.scene == "paused":
                self.scene = "playing"
                self.assets.sounds.play("button", 0.4)
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
                self.scene = "playing"
            elif self.scene == "game_over":
                self.start_round()

    def _handle_click(self, position: tuple[int, int]) -> bool:
        """Route a logical click position to the correct scene buttons.

        Returns `True` when a button handled the click.
        """
        if self.scene == "menu":
            if self.play_button.contains(position):
                self.start_round()
                return True
            return False

        if self.scene == "playing":
            if self.pause_button.contains(position):
                self.scene = "paused"
                self.assets.sounds.play("button", 0.4)
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
                    self.assets.sounds.play("button", 0.4)
                    if action == "resume":
                        self.scene = "playing"
                    elif action == "restart":
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

    def start_round(self) -> None:
        """Reset gameplay state and begin a new run."""
        self.scene = "playing"
        self.bodies.clear()

        # Reset transient feedback so old particles/shake do not leak into the new run.
        self.effects = EffectsManager()
        self.drop_timer = 0.0
        self.fail_timer = 0.0
        self.container_stress = 0.0
        self.goal_reached = False
        self.warning_active = False
        self.launch_angle = 0.0
        self.angle_dragging = False
        self.score = 0
        self.new_record = False
        self.best_tier_seen = 0
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
        """Launch the current queued body into the container."""
        # Ignore launches when not actively playing or while the cooldown is active.
        if self.scene != "playing" or self.drop_timer > 0.0:
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
            position=pygame.Vector2(self.spawn_x, SPAWN_Y),
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

    def _update(self, dt: float) -> None:
        """Advance one frame of non-drawing game logic."""
        # Mouse-driven background drift adds a small amount of depth.
        logical_mouse = self._current_canvas_mouse()
        drift = pygame.Vector2(logical_mouse) - pygame.Vector2(self.world.center.x, SCREEN_HEIGHT / 2)
        self.background_drift = drift * 0.06

        if self.scene == "playing":
            # Only the active gameplay scene should change simulation state.
            self._update_spawn_aim(dt)
            self.drop_timer = max(0.0, self.drop_timer - dt)

            # Physics runs only while the round is active.
            collisions = self.world.step(self.bodies, dt)

            for collision in collisions:
                # Convert high-energy impacts into particles and pulse animations.
                if collision.body_a.register_impact(self.now, collision.impact_speed):
                    self.effects.impact(collision.point, collision.body_a.info.color, collision.impact_speed)
                if collision.body_b and collision.body_b.register_impact(self.now, collision.impact_speed):
                    self.effects.impact(collision.point, collision.body_b.info.color, collision.impact_speed)

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

    def _update_spawn_aim(self, dt: float) -> None:
        """Update launcher position and angle from mouse/keyboard input."""
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
        """Replace merged body pairs with their upgraded result."""
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
            )
            # We intentionally let the merged body pick a fresh default random
            # seed so its new personality/animation can feel like a distinct orb.
            # `pulse`/`flash`/`birth_pop` together drive the "punchy arrival":
            # the body flashes, pops outward, and scales up from small to full.
            merged_body.pulse = 0.95
            merged_body.flash = 0.95
            merged_body.birth_pop = 1.0
            merged_body.lock_merge(self.now)

            # Ensure the newly spawned result is still safely inside the bubble.
            self.world.keep_inside(merged_body)
            spawned.append(merged_body)
            self._next_body_id += 1

            # Combo scoring: merges chained within `COMBO_WINDOW` seconds of the
            # previous merge build an escalating multiplier. A multi-merge frame
            # shares one timestamp, so cascades naturally chain together.
            if self.now - self._last_merge_time <= COMBO_WINDOW:
                self._combo_count += 1
            else:
                self._combo_count = 1
            self._last_merge_time = self.now
            combo_multiplier = min(3.0, 1.0 + 0.5 * (self._combo_count - 1))
            gained = int(round(event.score_gain * combo_multiplier))

            # Reward the player and fire appropriate celebratory effects.
            self.score += gained
            self.effects.merge(merged_body.position, merged_body.info.color, gained, event.target_tier)
            if self._combo_count >= 2:
                # A chain of quick merges earns its own callout popup.
                self.effects.combo(self._combo_count, merged_body.position)
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
                self.assets.sounds.play("big_merge", 0.42)
            else:
                self.assets.sounds.play("merge", 0.36)

        if consumed:
            # Remove all consumed bodies, then append the newly spawned merged bodies.
            self.bodies = [body for body in self.bodies if body.body_id not in consumed]
            self.bodies.extend(spawned)
            self._refresh_high_score()
            self._save_progress()

    def _update_fail_state(self, dt: float) -> None:
        """Track whether the player is approaching game over."""
        highest_top = min((body.top for body in self.bodies), default=self.world.center.y + self.world.radius)

        # Live stress rises as the tallest point in the stack approaches the fail line.
        # This gives the HUD a continuous response instead of only reacting after
        # the player is already in immediate danger.
        preview_ratio = clamp(
            (FAIL_LINE_Y + STRESS_PREVIEW_RANGE - highest_top) / STRESS_PREVIEW_RANGE,
            0.0,
            1.0,
        )

        # Only older bodies count toward losing. This prevents a just-launched body
        # from instantly causing game over while it is still entering the field.
        warning = any(body.top < FAIL_LINE_Y and body.age(self.now) > FAIL_AGE_GATE for body in self.bodies)
        self.warning_active = warning
        if warning:
            # Fill the fail timer while danger is active.
            self.fail_timer = min(FAIL_GRACE, self.fail_timer + dt)

            # Play an escalating warning beep: the closer to game over, the
            # faster the tone repeats, so danger is felt as well as seen.
            if self.now >= self._next_warning_beep:
                ratio = self.fail_timer / FAIL_GRACE if FAIL_GRACE > 0.0 else 0.0
                self.assets.sounds.play("warning", 0.28 + ratio * 0.3)
                self._next_warning_beep = self.now + max(0.2, 0.66 - ratio * 0.46)
        else:
            # If the player recovers, the fail timer drains back down.
            self.fail_timer = max(0.0, self.fail_timer - dt * FAIL_DECAY)
            # Reset the beep timer so the next danger spell starts fresh.
            self._next_warning_beep = 0.0

        # Split the stress bar into two phases:
        # - up to 78% from live stack height,
        # - final 22% from the true fail countdown once the line is crossed.
        timer_ratio = self.fail_timer / FAIL_GRACE if FAIL_GRACE > 0.0 else 0.0
        preview_stress = preview_ratio * 0.78
        danger_stress = 0.78 + timer_ratio * 0.22 if warning else 0.0
        self.container_stress = max(preview_stress, danger_stress)
        if self.fail_timer >= FAIL_GRACE:
            self._trigger_game_over()

    def _trigger_game_over(self) -> None:
        """End the current run if it is not already over."""
        if self.scene == "game_over":
            # This guard prevents duplicate sounds or repeated state changes.
            return
        self.scene = "game_over"
        self.warning_active = False
        self._refresh_high_score()
        self._save_progress()
        self.assets.sounds.play("game_over", 0.42)

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
        - the exact idle blink rhythm once spawned,
        - the tiny orbital drift flavor used by the trajectory preview.

        Storing both values in the queue means the preview arc can represent the
        actual body that will be launched next, not just a rough generic stand-in.
        """
        return self._roll_spawn_tier(), self.random.random()

    def _load_progress(self) -> dict:
        """Read the saved high score and lifetime stats, falling back safely."""
        try:
            if SAVE_DATA_PATH.exists():
                data = json.loads(SAVE_DATA_PATH.read_text(encoding="utf-8"))
            else:
                data = {}
            return {
                "high_score": max(0, int(data.get("high_score", 0))),
                "games_played": max(0, int(data.get("games_played", 0))),
                "best_tier": max(0, min(len(TIERS) - 1, int(data.get("best_tier", 0)))),
            }
        except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
            # A missing or corrupt file simply means "no progress saved yet".
            return {"high_score": 0, "games_played": 0, "best_tier": 0}

    def _refresh_high_score(self) -> None:
        """Promote the current score to a new high score when it beats the old best."""
        if self.score > self.high_score:
            self.high_score = self.score
            self.new_record = True

    def _save_progress(self) -> None:
        """Persist high score and lifetime stats with a crash-safe atomic write."""
        payload = {
            "high_score": self.high_score,
            "games_played": self.games_played,
            "best_tier": self.lifetime_best_tier,
        }
        try:
            SAVE_DATA_DIR.mkdir(parents=True, exist_ok=True)
            # Write to a temp file first, then atomically swap it into place so a
            # crash mid-write can never leave a half-written save behind.
            tmp_path = SAVE_DATA_PATH.with_name(SAVE_DATA_PATH.name + ".tmp")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp_path, SAVE_DATA_PATH)
        except OSError as error:
            _log_save_error(error)

    def _draw(self) -> None:
        """Render one complete frame to the internal canvas, then present it."""
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
        draw_playfield(self.canvas, self.now, self.fail_timer / FAIL_GRACE if FAIL_GRACE else 0.0, self.warning_active)

        if self.scene in {"playing", "paused", "game_over"}:
            self._draw_spawn_indicator(camera)

        # Draw smaller bodies first so larger ones can overlap them naturally.
        for body in sorted(self.bodies, key=lambda item: item.radius):
            body.draw(self.canvas, self.assets, camera, self.now)

        # Particles/popups sit on top of the bodies.
        self.effects.draw(self.canvas, self.assets, camera)

        if self.scene in {"playing", "paused", "game_over"}:
            # HUD and persistent in-run buttons.
            draw_hud(self.canvas, self, self.assets)
            self.pause_button.draw(self.canvas, self.assets, hover_mouse)
            self.restart_button.draw(self.canvas, self.assets, hover_mouse)

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
        """Draw the launcher preview line, arrow, angle label, and current orb."""
        min_x, max_x = self.world.allowed_spawn_x(TIERS[self.current_tier].radius)
        self.spawn_x = clamp(self.spawn_x, min_x, max_x)

        # The launcher line points in the same direction as the initial launch velocity.
        direction = self._launch_direction()
        start = pygame.Vector2(self.spawn_x, SPAWN_Y) + camera
        back = start - direction * 64.0
        front = start + direction * 166.0
        beam_color = WARNING if self.warning_active else (175, 216, 255)

        # Draw a dotted path preview so the player can read the angled launch
        # more easily than from a single straight line alone.
        preview_points = self.world.preview_trajectory(
            pygame.Vector2(self.spawn_x, SPAWN_Y),
            self._launch_velocity(),
            TIERS[self.current_tier].radius,
            self.current_seed,
        )
        if preview_points:
            trail = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            preview_total = max(1, len(preview_points) - 1)
            for index, point in enumerate(preview_points):
                # Early points are drawn brighter/larger so the most immediate
                # section of the path is easiest to understand.
                progress = index / preview_total
                dot_center = point + camera
                dot_radius = max(2, int(8 - progress * 4.5))
                glow_radius = dot_radius + 4
                dot_alpha = int(125 - progress * 72)
                glow_alpha = int(42 - progress * 22)
                pygame.draw.circle(
                    trail,
                    (*beam_color, max(0, glow_alpha)),
                    (int(dot_center.x), int(dot_center.y)),
                    glow_radius,
                )
                pygame.draw.circle(
                    trail,
                    (*beam_color, max(0, dot_alpha)),
                    (int(dot_center.x), int(dot_center.y)),
                    dot_radius,
                )
            self.canvas.blit(trail, (0, 0))

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
        for guide_length, alpha in ((72.0, 95), (118.0, 70), (162.0, 45)):
            # Draw faded trail segments so the aim line feels more visible and "spacey".
            ghost = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            guide_end = start + direction * guide_length
            pygame.draw.line(ghost, (*beam_color, alpha), start, guide_end, 2)
            self.canvas.blit(ghost, (0, 0))

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
        self.launch_angle = clamp(self.launch_angle + delta, -MAX_LAUNCH_ANGLE, MAX_LAUNCH_ANGLE)

    def _set_launch_angle_from_point(self, point: tuple[int, int]) -> None:
        """Aim the launcher toward a point in internal canvas coordinates."""
        origin = pygame.Vector2(self.spawn_x, SPAWN_Y)
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
        angle = math.degrees(math.atan2(delta.x, delta.y))
        self.launch_angle = clamp(angle, -MAX_LAUNCH_ANGLE, MAX_LAUNCH_ANGLE)

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
        if not self.render_rect.collidepoint(position):
            if not keep_inside:
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
