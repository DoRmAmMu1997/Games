"""Heuristic computer-player decisions for Ludo."""

from __future__ import annotations

from dataclasses import dataclass

from models import Move


@dataclass(frozen=True)
class AIProfile:
    """Numeric weights that describe one AI personality.

    The AI does not search future turns. It simply scores every currently
    legal move, and these weights decide what it cares about most. Larger
    numbers make a profile value that idea more strongly.
    """

    capture: int
    safety: int
    progress: int
    enter: int
    danger: int
    finish: int
    blockade: int


AI_PROFILES: dict[str, AIProfile] = {
    "tactical": AIProfile(capture=75, safety=26, progress=3, enter=18, danger=34, finish=320, blockade=24),
    "aggressive": AIProfile(capture=115, safety=12, progress=3, enter=15, danger=18, finish=300, blockade=14),
    "defensive": AIProfile(capture=55, safety=44, progress=2, enter=22, danger=54, finish=340, blockade=34),
}


def choose_move(game, profile_key: str, die: int) -> Move | None:
    """Return the highest-scoring legal move for the current AI player.

    This function is deliberately tiny: it asks the rules engine for legal
    moves, scores them, and picks the best one. Keeping legality in
    ``game.legal_moves`` prevents the AI from quietly learning its own version
    of Ludo.
    """

    moves = game.legal_moves(die)
    if not moves:
        return None
    profile = AI_PROFILES.get(profile_key, AI_PROFILES["tactical"])
    scored = [
        (score_move(game, move, profile), -move.token_index, move)
        for move in moves
    ]
    scored.sort(reverse=True)
    return scored[0][2]


def score_move(game, move: Move, profile: AIProfile) -> int:
    """Score a move from the current board state.

    Positive numbers are good for the AI and negative numbers are risky. The
    result is only meaningful relative to the other legal moves in the same
    turn; it is not meant to be an absolute "quality" score.
    """

    score = move.to_steps * profile.progress
    # Getting a token out matters because tokens in the yard cannot threaten
    # captures or make progress toward home.
    if move.enters_board:
        score += profile.enter
    # Finishing a token is the biggest single-turn accomplishment.
    if move.reaches_home:
        score += profile.finish
    # Safe squares cannot be captured, so defensive profiles value them more.
    if game.layout.is_safe_index(move.landing_index):
        score += profile.safety

    capture_count = _capture_count(game, move)
    score += capture_count * profile.capture

    if _lands_in_danger(game, move):
        score -= profile.danger

    if game.rules.blockades and _builds_own_blockade(game, move):
        score += profile.blockade

    # A deterministic nudge prefers moving the most advanced token when scores
    # are equal, which makes seeded simulations easier to compare.
    score += move.to_steps - max(move.from_steps, 0)
    return score


def _capture_count(game, move: Move) -> int:
    """Count how many opposing tokens this move would send back to yard."""

    if move.landing_index is None or game.layout.is_safe_index(move.landing_index):
        return 0
    return sum(1 for player_index, _ in game.tokens_at_track(move.landing_index) if player_index != move.player_index)


def _lands_in_danger(game, move: Move) -> bool:
    """Return True when an opponent could capture the landing square soon.

    A full tactical search would simulate future dice rolls. For a readable
    beginner-friendly AI, this uses a simpler warning: if any opponent token
    can reach the landing square with a die value from 1 to 6, the square is
    considered dangerous.
    """

    if move.landing_index is None or game.layout.is_safe_index(move.landing_index):
        return False
    for player_index, player in enumerate(game.players):
        if player_index == move.player_index:
            continue
        for token in player.tokens:
            if token.steps < 0 or token.steps >= game.layout.track_length:
                continue
            for die in range(1, 7):
                target = game.layout.track_index(player_index, token.steps + die)
                if target == move.landing_index:
                    return True
    return False


def _builds_own_blockade(game, move: Move) -> bool:
    """Return True if the move stacks two own tokens on a track square."""

    if move.landing_index is None:
        return False
    same_square = 0
    for token_index, token in enumerate(game.players[move.player_index].tokens):
        if token_index == move.token_index:
            continue
        if game.layout.track_index(move.player_index, token.steps) == move.landing_index:
            same_square += 1
    return same_square >= 1
