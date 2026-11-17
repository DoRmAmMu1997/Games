"""Lightweight circle physics for the bubble puzzle.

This file handles:
- gravity and drift,
- moving bodies forward in time,
- solving wall collisions against the circular container,
- solving body-vs-body collisions,
- emitting impact events for juice like particles and shake.

Beginner note:
- The goal here is not "perfect real-world physics."
- The goal is "game-feel physics" that is stable, readable, and fun.
- That is why several values and formulas are intentionally tuned rather than
  strictly physically accurate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pygame

from settings import (
    AIR_DRAG,
    BROAD_PHASE_SLOP,
    CENTER_PULL,
    CONTAINER_RADIUS,
    FRICTION,
    GRAVITY,
    IMPACT_EVENT_SPEED,
    MAX_SPEED,
    ORBITAL_PULL,
    PHYSICS_MAX_SUBSTEP,
    PLAYFIELD_CENTER,
    POSITION_CORRECTION_SOFTNESS,
    RESTITUTION,
    SOLVER_ITERATIONS,
    SPAWN_Y,
    WALL_BOUNCE,
    WALL_FRICTION,
)

if TYPE_CHECKING:
    from entities import CelestialBody


EPSILON = 1e-6
# `EPSILON` is a tiny non-zero number used to avoid division-by-zero problems
# in vector math. It acts like "close enough to zero to treat as zero".


@dataclass(slots=True)
class CollisionEvent:
    """Information about one impactful contact that the rest of the game can react to."""

    # `body_b` is optional because wall hits have only one real body involved.
    body_a: CelestialBody
    body_b: CelestialBody | None
    point: pygame.Vector2
    normal: pygame.Vector2
    impact_speed: float


class PhysicsWorld:
    """Owns world-level physics settings and collision helpers."""

    def __init__(self) -> None:
        # Store the circular container once so every body can measure against it.
        # Converting the center to a `Vector2` makes later vector math simpler.
        self.center = pygame.Vector2(PLAYFIELD_CENTER)
        self.radius = CONTAINER_RADIUS

        # `time` lets gravity/orbit math use smooth oscillation over time.
        self.time = 0.0

    def step(self, bodies: list[CelestialBody], dt: float) -> list[CollisionEvent]:
        """Advance the physics simulation by one frame.

        The order is:
        1. split the frame into small internal substeps if needed,
        2. apply forces and move bodies for each substep,
        3. repeatedly solve overlap/collision issues,
        4. return any loud impacts so the effects layer can respond.

        Why use substeps?
        - A full game frame can be a little large for a simple circle solver.
        - Smaller internal slices reduce overlap penetration and stack jitter.
        - This especially helps angled launches and crowded late-game piles.
        """
        events: list[CollisionEvent] = []
        substeps = max(1, math.ceil(dt / PHYSICS_MAX_SUBSTEP))
        sub_dt = dt / substeps

        # Each substep reuses the same solver logic on a smaller time slice.
        # This is a common trick in games: keep the visible frame rate at 60 FPS,
        # but internally solve tricky motion in smaller chunks when helpful.
        for _ in range(substeps):
            self.time += sub_dt
            events.extend(self._step_once(bodies, sub_dt))

        for body in bodies:
            # Bodies that are almost still get a tiny extra reduction so stacks
            # settle instead of trembling forever.
            #
            # The threshold is intentionally small; we only want to calm bodies
            # that are basically at rest, not visibly moving ones.
            if body.velocity.length_squared() < 4.0:
                body.velocity *= 0.985

        return events

    def _step_once(self, bodies: list[CelestialBody], dt: float) -> list[CollisionEvent]:
        """Run one small slice of the simulation.

        `step()` may call this once or multiple times per visible frame.
        Keeping the per-slice math in its own helper makes the main `step()`
        easier to read and makes the substep idea obvious to beginners.
        """
        events: list[CollisionEvent] = []

        # Exponential damping behaves more consistently across frame rates than
        # subtracting a fixed amount every frame.
        damping = math.exp(-AIR_DRAG * dt)

        for body in bodies:
            # Add acceleration caused by gravity and the custom "space drift".
            body.velocity += self._gravity_for(body) * dt

            # Cap speed so the simple solver stays stable and readable.
            # Without a speed cap, rare collisions or bugs could kick a body so
            # hard that it tunnels or jitters through other objects.
            if body.velocity.length_squared() > MAX_SPEED * MAX_SPEED:
                body.velocity.scale_to_length(MAX_SPEED)

            # Move position from velocity, then damp the velocity a little.
            body.position += body.velocity * dt
            body.velocity *= damping

        # Broad phase: find the pairs that are close enough to possibly touch
        # during this slice, once, instead of testing every pair in every
        # solver iteration. The margin covers the biggest body present, the
        # furthest any body can travel in one slice, and a little slop, so no
        # pair that the solver would have pushed apart is ever left out.
        largest_radius = max((body.radius for body in bodies), default=0.0)
        margin = largest_radius + MAX_SPEED * dt + BROAD_PHASE_SLOP
        pairs = self._broad_phase_pairs(bodies, margin)

        for iteration in range(SOLVER_ITERATIONS):
            # We only emit impact events from the first solver pass.
            # Later passes are just cleanup corrections and would otherwise
            # create duplicate effects for the same collision.
            emit_events = iteration == 0
            events.extend(self._solve_boundaries(bodies, emit_events))
            events.extend(self._solve_pairs(bodies, pairs, emit_events))

        return events

    def keep_inside(self, body: CelestialBody) -> None:
        """Clamp one body back inside the circular container immediately."""
        # This is mainly used after spawning a merged result so it does not end
        # up slightly outside the bubble because of rounding or overlap math.
        offset = body.position - self.center
        distance = offset.length()
        limit = self.radius - body.radius - 3.0
        if distance > limit:
            # `normal` points from the center outward toward the body's position.
            normal = offset.normalize() if distance > EPSILON else pygame.Vector2(0.0, -1.0)
            body.position = self.center + normal * limit

    def spawn_point(self, x: float, radius: float) -> pygame.Vector2:
        """Return the launch point for a body of `radius` aimed from column `x`.

        The launcher sits on the fixed `SPAWN_Y` line, but near the top of a
        circular bubble that line can poke outside the legal circle for larger
        bodies. The point is therefore pulled back inside `R - r - 3`, the same
        legal circle that `keep_inside`, the wall solver, and the trajectory
        preview all use, so a fresh body never "snaps" on its first frame.
        """
        point = pygame.Vector2(x, SPAWN_Y)
        offset = point - self.center
        distance = offset.length()
        limit = self.radius - radius - 3.0
        if distance > limit:
            normal = offset.normalize() if distance > EPSILON else pygame.Vector2(0.0, -1.0)
            point = self.center + normal * limit
        return point

    def allowed_spawn_x(self, radius: float) -> tuple[float, float]:
        """Return the left/right spawn limits for a body at the spawn height.

        Because the playfield is circular, the valid horizontal span depends on
        both the container radius and the body radius.
        """
        # `spawn_offset` is the vertical distance between the container center
        # and the spawn line.
        spawn_offset = self.center.y - SPAWN_Y

        # From the circle equation x^2 + y^2 = r^2, if we know `y` we can solve
        # for the maximum `x` still inside the circle.
        chord_half = math.sqrt(max(0.0, self.radius * self.radius - spawn_offset * spawn_offset))
        horizontal = max(0.0, chord_half - radius - 18.0)
        return self.center.x - horizontal, self.center.x + horizontal

    def preview_trajectory(
        self,
        position: pygame.Vector2,
        velocity: pygame.Vector2,
        radius: float,
        seed: float,
        steps: int = 20,
        step_dt: float = 0.055,
    ) -> list[pygame.Vector2]:
        """Approximate where a newly launched body will travel for a short time.

        This is *not* a perfect prediction, because the real game also has:
        - collisions with other bodies,
        - small solver corrections,
        - a continuously changing stack.

        Even so, this preview is still very useful because it shows the player:
        - the initial launch direction,
        - how gravity bends the shot,
        - roughly where the orb will enter the pile.
        """
        # Work on copies so the preview never mutates real gameplay state.
        preview_position = pygame.Vector2(position)
        preview_velocity = pygame.Vector2(velocity)
        preview_time = self.time
        damping = math.exp(-AIR_DRAG * step_dt)
        points: list[pygame.Vector2] = []

        for _ in range(steps):
            # Reuse the same gravity recipe as the real simulation so the guide
            # feels consistent with the actual shot.
            preview_velocity += self._gravity_at(preview_position, seed, preview_time) * step_dt

            # The same speed cap keeps the preview from shooting off unrealistically.
            if preview_velocity.length_squared() > MAX_SPEED * MAX_SPEED:
                preview_velocity.scale_to_length(MAX_SPEED)

            preview_position += preview_velocity * step_dt
            preview_velocity *= damping
            preview_time += step_dt

            # If the preview reaches the bubble wall, clamp the final point to
            # the inside edge and stop. Aiming past that point is rarely useful.
            offset = preview_position - self.center
            distance = offset.length()
            limit = self.radius - radius - 3.0
            if distance > limit:
                normal = offset.normalize() if distance > EPSILON else pygame.Vector2(0.0, -1.0)
                preview_position = self.center + normal * limit
                points.append(preview_position.copy())
                break

            points.append(preview_position.copy())

        return points

    def _gravity_for(self, body: CelestialBody) -> pygame.Vector2:
        """Build the final acceleration vector applied to one body."""
        return self._gravity_at(body.position, body.seed, self.time)

    def _gravity_at(self, position: pygame.Vector2, seed: float, world_time: float) -> pygame.Vector2:
        """Compute the game's custom gravity field at one position.

        The main simulation calls this for real bodies, and the launcher preview
        also calls it for imaginary future positions. Keeping that shared math
        in one helper reduces drift between "what the guide shows" and
        "what the actual body does after launch."
        """
        # Start with regular downward pull so the game still reads like a
        # falling-object puzzle.
        acceleration = pygame.Vector2(0.0, GRAVITY)
        to_center = self.center - position
        distance = to_center.length()
        if distance > EPSILON:
            # Pull slightly toward the center so stacks stay inside the bubble.
            normal = to_center / distance
            acceleration += normal * CENTER_PULL

            # Add a small sideways/tangential drift to create that "cosmic"
            # curving feel without turning the puzzle into chaos.
            #
            # `tangent` is perpendicular to `normal`, so instead of pulling
            # directly toward the center, it pushes around the center.
            tangent = pygame.Vector2(-normal.y, normal.x)
            orbit_amount = ORBITAL_PULL * min(1.0, distance / (self.radius * 0.9))
            acceleration += tangent * orbit_amount * math.sin(world_time * 0.85 + seed * math.tau)
        return acceleration

    def _solve_boundaries(self, bodies: list[CelestialBody], emit_events: bool) -> list[CollisionEvent]:
        """Resolve collisions between bodies and the circular wall."""
        events: list[CollisionEvent] = []
        for body in bodies:
            offset = body.position - self.center
            distance = offset.length()
            limit = self.radius - body.radius - 2.0
            if distance <= limit:
                # This body is still safely inside the circle.
                continue

            # Push the body back onto the legal circle edge.
            normal = offset.normalize() if distance > EPSILON else pygame.Vector2(0.0, -1.0)
            body.position = self.center + normal * limit

            # Only react if the body is moving outward into the wall.
            outward_speed = body.velocity.dot(normal)
            if outward_speed > 0.0:
                tangent = pygame.Vector2(-normal.y, normal.x)

                # Reflect the outward part of the velocity and damp sideways
                # sliding so bodies settle against the wall more naturally.
                body.velocity -= (1.0 + WALL_BOUNCE) * outward_speed * normal
                body.velocity -= tangent * body.velocity.dot(tangent) * WALL_FRICTION
                if emit_events and outward_speed > IMPACT_EVENT_SPEED:
                    # Wall collisions set `body_b=None` because the wall is not a body.
                    events.append(
                        CollisionEvent(
                            body_a=body,
                            body_b=None,
                            point=body.position + normal * body.radius,
                            normal=normal,
                            impact_speed=outward_speed,
                        )
                    )
        return events

    def _broad_phase_pairs(self, bodies: list[CelestialBody], margin: float) -> list[tuple[int, int]]:
        """Return the index pairs `(i, j)`, `i < j`, whose circles come within `margin`.

        A pair is a candidate when the distance between centres is at most
        `radius_i + radius_j + margin`. The result is sorted, so the solver
        visits contacts in exactly the same order as a plain all-pairs loop.

        Beginner note:
        - Checking every body against every other body costs about n*n/2
          tests, which grows fast as the bubble fills up.
        - A *uniform grid* drops each body into a square cell. Cells are as
          wide as the longest possible candidate distance, so a body only
          needs to look at its own cell and the eight cells around it.
        """
        count = len(bodies)
        if count < 2:
            return []
        largest_radius = max(body.radius for body in bodies)
        cell_size = 2.0 * largest_radius + margin
        cells: dict[tuple[int, int], list[int]] = {}
        keys: list[tuple[int, int]] = []
        for index, body in enumerate(bodies):
            key = (math.floor(body.position.x / cell_size), math.floor(body.position.y / cell_size))
            keys.append(key)
            cells.setdefault(key, []).append(index)

        pairs: list[tuple[int, int]] = []
        for index, body in enumerate(bodies):
            cell_x, cell_y = keys[index]
            for neighbour_x in (cell_x - 1, cell_x, cell_x + 1):
                for neighbour_y in (cell_y - 1, cell_y, cell_y + 1):
                    for other_index in cells.get((neighbour_x, neighbour_y), ()):
                        # Keep each pair once, with the lower index first.
                        if other_index <= index:
                            continue
                        other = bodies[other_index]
                        reach = body.radius + other.radius + margin
                        if (other.position - body.position).length_squared() <= reach * reach:
                            pairs.append((index, other_index))
        pairs.sort()
        return pairs

    def _solve_pairs(
        self,
        bodies: list[CelestialBody],
        pairs: list[tuple[int, int]],
        emit_events: bool,
    ) -> list[CollisionEvent]:
        """Resolve body-vs-body overlaps and collision impulses for the candidate `pairs`."""
        events: list[CollisionEvent] = []
        for index, other_index in pairs:
            # Each candidate pair appears only once, lower index first.
            first = bodies[index]
            second = bodies[other_index]
            delta = second.position - first.position
            distance_sq = delta.length_squared()
            min_distance = first.radius + second.radius

            # Skip pairs that are not overlapping.
            if distance_sq >= min_distance * min_distance:
                continue

            if distance_sq > EPSILON:
                distance = math.sqrt(distance_sq)
                normal = delta / distance
            else:
                # If the centers are identical, pick an arbitrary direction
                # to avoid dividing by zero.
                distance = 0.0
                normal = pygame.Vector2(1.0, 0.0)

            penetration = min_distance - distance
            total_inv_mass = first.inv_mass + second.inv_mass
            if total_inv_mass <= EPSILON:
                continue

            # Move both bodies apart proportionally to their inverse masses.
            # Lighter bodies move more than heavier bodies. The softness
            # factor is explained where it is defined in settings.py.
            correction = normal * (penetration / total_inv_mass) * POSITION_CORRECTION_SOFTNESS
            first.position -= correction * first.inv_mass
            second.position += correction * second.inv_mass

            relative_velocity = second.velocity - first.velocity
            velocity_along_normal = relative_velocity.dot(normal)
            if velocity_along_normal < 0.0:
                # Calculate and apply the bounce impulse along the collision normal.
                # If the value were positive, the bodies would already be separating.
                impulse_strength = -(1.0 + RESTITUTION) * velocity_along_normal
                impulse_strength /= total_inv_mass
                impulse = normal * impulse_strength
                first.velocity -= impulse * first.inv_mass
                second.velocity += impulse * second.inv_mass

                # Tangential friction reduces side-sliding after impact.
                tangent = relative_velocity - normal * velocity_along_normal
                if tangent.length_squared() > EPSILON:
                    # Normalize tangent so friction is based on direction, not length.
                    tangent = tangent.normalize()
                    friction_strength = -relative_velocity.dot(tangent) / total_inv_mass
                    friction_impulse = tangent * friction_strength * FRICTION
                    first.velocity -= friction_impulse * first.inv_mass
                    second.velocity += friction_impulse * second.inv_mass

            impact_speed = abs(velocity_along_normal)
            if emit_events and impact_speed > IMPACT_EVENT_SPEED:
                events.append(
                    CollisionEvent(
                        body_a=first,
                        body_b=second,
                        point=first.position + normal * first.radius,
                        normal=normal,
                        impact_speed=impact_speed,
                    )
                )
        return events
