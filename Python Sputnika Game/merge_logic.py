"""Rules for detecting and packaging valid merge opportunities.

Physics decides when bodies overlap.
This file decides whether that overlap should count as a merge.

Beginner note:
- Collision detection and merge detection are related, but not the same thing.
- Two bodies can touch physically without necessarily becoming a merge.
- This file is where the "same tier + valid state = evolve" rule lives.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pygame

from settings import MERGE_CONTACT_SLOP, MERGE_VELOCITY_DAMP, TIERS

if TYPE_CHECKING:
    from entities import CelestialBody


@dataclass(slots=True)
class MergeEvent:
    """A lightweight description of one merge to apply after physics.

    Attributes:
        first_id, second_id: `body_id`s of the two bodies being consumed.
        source_tier: Tier of the two consumed bodies.
        target_tier: Tier of the body that replaces them (`source_tier + 1`).
        position: Where the new body appears (mass-weighted centre).
        velocity: Starting velocity of the new body (damped combined velocity).
        score_gain: Base points before the combo multiplier; it is the
            score value of `target_tier`.
    """

    # We store ids instead of whole objects so the event stays simple and easy
    # to sort/apply later.
    #
    # These fields describe:
    # - which two old bodies are being consumed,
    # - what the new upgraded tier should be,
    # - where and how fast the replacement body should spawn,
    # - how many points the player earns.
    first_id: int
    second_id: int
    source_tier: int
    target_tier: int
    position: pygame.Vector2
    velocity: pygame.Vector2
    score_gain: int


def find_merge_events(bodies, now: float) -> list[MergeEvent]:
    """Scan the current bodies and return all non-conflicting merges.

    The function deliberately returns data instead of mutating bodies directly.
    That separation keeps the merge search simple and lets `game.py` decide
    how to replace old bodies with the new merged one.

    A pair qualifies when both bodies share a tier below the top one, both are
    older than `MERGE_ARM_TIME`, and their centres are no further apart than
    the sum of their radii plus `MERGE_CONTACT_SLOP`. When one body could
    merge with several partners, candidates are ranked (highest tier first,
    then the tightest overlap, then the lowest relative speed) and each body
    is used by at most one event.

    Args:
        bodies: The live `CelestialBody` list (read only).
        now: Current game clock time, for the merge arming delay.

    Returns:
        The chosen merges, in ranking order.
    """
    # `candidates` stores extra sort information before we decide which merges
    # actually win this frame. Each tuple contains:
    # - source tier,
    # - center-distance squared,
    # - relative speed squared,
    # - first body,
    # - second body.
    candidates: list[tuple[int, float, float, CelestialBody, CelestialBody]] = []
    total_tiers = len(TIERS)

    for index, first in enumerate(bodies):
        # Highest-tier bodies cannot evolve further, and freshly created bodies
        # wait a short moment before becoming eligible to merge.
        if first.tier >= total_tiers - 1 or not first.can_merge(now):
            continue

        # `bodies[index + 1 :]` avoids checking every pair twice.
        # If we checked both `(A, B)` and `(B, A)`, the work would double.
        for second in bodies[index + 1 :]:
            # Only identical tiers are allowed to combine.
            if second.tier != first.tier or not second.can_merge(now):
                continue

            delta = second.position - first.position
            contact_distance = first.radius + second.radius + MERGE_CONTACT_SLOP

            # If the centers are farther apart than the allowed contact range,
            # this pair is not touching closely enough to merge.
            #
            # We compare squared distances because it is faster than taking a
            # square root for every pair.
            if delta.length_squared() > contact_distance * contact_distance:
                continue

            # We keep some extra sort data:
            # - higher tiers should be resolved first,
            # - tighter overlaps are better candidates,
            # - lower relative speed tends to feel cleaner and less chaotic.
            relative_speed = (second.velocity - first.velocity).length_squared()
            candidates.append((first.tier, delta.length_squared(), relative_speed, first, second))

    # Prefer bigger/higher-value merges first, then better contact quality.
    # Sorting this way helps the results feel more intentional in crowded stacks.
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))

    chosen: set[int] = set()
    events: list[MergeEvent] = []
    for _, _, _, first, second in candidates:
        # A body can only participate in one merge per frame.
        if first.body_id in chosen or second.body_id in chosen:
            continue

        # Once accepted, both bodies are reserved so another candidate cannot reuse them.
        chosen.add(first.body_id)
        chosen.add(second.body_id)

        target_tier = first.tier + 1
        total_mass = first.mass + second.mass

        # Spawn the merged body at the mass-weighted center so larger bodies
        # feel like they contribute more strongly to the final position.
        position = (first.position * first.mass + second.position * second.mass) / total_mass

        # Damp the combined velocity so chain merges stay exciting but readable.
        velocity = (first.velocity + second.velocity) * MERGE_VELOCITY_DAMP

        # `score_gain` is taken from the resulting tier, not the consumed tier.
        # That makes higher evolutions dramatically more rewarding.
        events.append(
            MergeEvent(
                first_id=first.body_id,
                second_id=second.body_id,
                source_tier=first.tier,
                target_tier=target_tier,
                position=pygame.Vector2(position),
                velocity=pygame.Vector2(velocity),
                score_gain=TIERS[target_tier].score,
            )
        )

    return events
