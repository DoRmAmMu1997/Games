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
    rules: LudoRules | None = None,
) -> dict:
    """Run one headless AI game and return summary metrics.

    ``rules`` overrides the classic defaults (and then decides the player
    count); without it the game uses ``LudoRules(total_players)``.
    """

    if rules is None:
        rules = LudoRules(total_players=total_players)
    players = [(f"AI {index + 1}", False) for index in range(rules.total_players)]
    game = LudoGame(players, rules, seed=seed, ai_profile=profile_key)
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


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser, including the house-rule flags."""

    parser = argparse.ArgumentParser(description="Run seeded Ludo AI simulations.")
    parser.add_argument("--games", type=int, default=5)
    parser.add_argument("--players", type=int, choices=(4, 5, 6), default=4)
    parser.add_argument("--profile", choices=tuple(ai.AI_PROFILES), default="tactical")
    parser.add_argument("--seed", type=int, default=1)
    # The four house rules mirror the setup screen's toggles. Each flag
    # flips its rule away from the classic default.
    parser.add_argument("--blockades", action="store_true", help="two same-colour tokens block a square")
    parser.add_argument("--no-capture-bonus", action="store_true", help="captures do not earn a bonus roll")
    parser.add_argument("--no-home-bonus", action="store_true", help="reaching home does not earn a bonus roll")
    parser.add_argument("--no-three-sixes", action="store_true", help="a third consecutive 6 is not forfeited")
    return parser


def rules_from_args(args: argparse.Namespace) -> LudoRules:
    """Build the LudoRules a batch should use from parsed command-line flags."""

    return LudoRules(
        total_players=args.players,
        blockades=args.blockades,
        bonus_on_capture=not args.no_capture_bonus,
        bonus_on_home=not args.no_home_bonus,
        three_sixes_penalty=not args.no_three_sixes,
    )


def main(argv: list[str] | None = None) -> None:
    """Parse command-line options and print aggregate AI results."""

    args = build_parser().parse_args(argv)
    rules = rules_from_args(args)

    winners: Counter[int] = Counter()
    completed = 0
    total_turns = 0
    total_captures = 0
    for offset in range(args.games):
        # Incrementing the seed gives reproducible but different games within
        # one batch, which is useful when comparing AI profile tweaks.
        metrics = run_ai_game(
            profile_key=args.profile,
            seed=args.seed + offset,
            rules=rules,
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
