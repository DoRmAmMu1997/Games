"""Seeded all-AI Ludo simulations for tuning heuristic profiles."""

from __future__ import annotations

import argparse
from collections import Counter

import ai
from game import LudoGame, LudoRules


def run_ai_game(
    *,
    total_players: int = 4,
    profile_key: str = "tactical",
    seed: int = 1,
    max_actions: int = 6000,
) -> dict:
    """Run one headless AI game and return summary metrics."""

    players = [(f"AI {index + 1}", False) for index in range(total_players)]
    game = LudoGame(players, LudoRules(total_players=total_players), seed=seed, ai_profile=profile_key)
    actions = 0
    while game.phase != "game_over" and actions < max_actions:
        actions += 1
        if game.awaiting == "pre_roll":
            forfeited = game.record_roll(game.rng.randint(1, 6))
            if forfeited:
                continue
        if game.awaiting == "choose_move" and game.last_roll is not None:
            move = ai.choose_move(game, profile_key, game.last_roll)
            if move is None:
                game.note_no_move(game.last_roll)
            else:
                game.apply_move(move)

    return {
        "completed": game.phase == "game_over",
        "actions": actions,
        "turns": game.turns_taken,
        "rolls": game.total_rolls,
        "winner": game.winner,
        "captures": sum(player.captures for player in game.players),
        "ranking": list(game.ranking),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run seeded Ludo AI simulations.")
    parser.add_argument("--games", type=int, default=5)
    parser.add_argument("--players", type=int, choices=(4, 5, 6), default=4)
    parser.add_argument("--profile", choices=tuple(ai.AI_PROFILES), default="tactical")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    winners: Counter[int] = Counter()
    completed = 0
    total_turns = 0
    total_captures = 0
    for offset in range(args.games):
        metrics = run_ai_game(
            total_players=args.players,
            profile_key=args.profile,
            seed=args.seed + offset,
        )
        print(f"game {offset + 1}: {metrics}")
        if metrics["completed"]:
            completed += 1
            winners[metrics["winner"]] += 1
        total_turns += metrics["turns"]
        total_captures += metrics["captures"]

    print()
    print(f"completed: {completed}/{args.games}")
    print(f"average turns: {total_turns / max(1, args.games):.1f}")
    print(f"average captures: {total_captures / max(1, args.games):.1f}")
    print(f"winner counts: {dict(winners)}")


if __name__ == "__main__":
    main()
