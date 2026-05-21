"""Headless Monopoly simulations for AI tuning and regression checks."""

from __future__ import annotations

import argparse
import json
from collections import Counter

import ai
from game import MonopolyGame


def run_ai_game(seed: int, max_actions: int = 20000,
                profile_key: str = "standard") -> dict:
    """Run one seeded all-AI game and return compact strategy metrics."""
    profile_key = profile_key if profile_key in ai.AI_PROFILES else "standard"
    specs = [(f"AI {index + 1}", False) for index in range(4)]
    game = MonopolyGame(specs, seed=seed, ai_profile=profile_key)
    auction_count = 0
    trade_count = 0
    actions = 0

    while game.phase == "playing" and actions < max_actions:
        had_auction = game.auction is not None
        had_trade = game.pending_trade is not None
        ai.take_action(game)
        actions += 1
        if not had_auction and game.auction is not None:
            auction_count += 1
        if not had_trade and game.pending_trade is not None:
            trade_count += 1

    winner = None if game.winner is None else game.players[game.winner].name
    bankruptcies = [player.name for player in game.players if player.bankrupt]
    return {
        "seed": seed,
        "profile": profile_key,
        "completed": game.phase == "game_over",
        "winner": winner,
        "turns": game.turn_count,
        "actions": actions,
        "auction_count": auction_count,
        "trade_count": trade_count,
        "bankruptcies": bankruptcies,
    }


def run_batch(games: int, profile_key: str, start_seed: int = 1) -> dict:
    """Run a group of seeded games and summarize outcomes for tuning."""
    results = [run_ai_game(start_seed + offset, profile_key=profile_key)
               for offset in range(games)]
    winners = Counter(result["winner"] for result in results)
    return {
        "games": games,
        "profile": profile_key,
        "completed": sum(1 for result in results if result["completed"]),
        "average_turns": round(sum(result["turns"] for result in results) / games, 1),
        "average_actions": round(sum(result["actions"] for result in results) / games, 1),
        "average_auctions": round(sum(result["auction_count"] for result in results) / games, 1),
        "average_trades": round(sum(result["trade_count"] for result in results) / games, 1),
        "winner_counts": dict(winners),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run seeded Monopoly AI simulations.")
    parser.add_argument("--games", type=int, default=5)
    parser.add_argument("--profile", choices=sorted(ai.AI_PROFILES), default="standard")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    print(json.dumps(run_batch(args.games, args.profile, args.seed), indent=2))


if __name__ == "__main__":
    main()
