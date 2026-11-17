"""Command-line rule flags for the seeded all-AI simulation runner."""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import simulation
from game import LudoGame, LudoRules


class SimulationFlagTests(unittest.TestCase):
    """Each house-rule flag on the command line reaches the rules engine."""

    def rules_built_by(self, argv: list[str]) -> LudoRules:
        """Run the simulation CLI once and return the rules its game was built with."""

        with (
            mock.patch.object(simulation, "LudoGame", wraps=LudoGame) as built,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            simulation.main(["--games", "1", *argv])
        self.assertEqual(built.call_count, 1)
        return built.call_args.args[1]

    def test_defaults_use_the_classic_rules(self) -> None:
        """With no flags the simulated game uses the setup screen's default rules."""

        self.assertEqual(self.rules_built_by([]), LudoRules(total_players=4))

    def test_each_flag_reaches_the_engine(self) -> None:
        """Every rule flag flips exactly its own LudoRules field."""

        cases = {
            "--blockades": {"blockades": True},
            "--no-capture-bonus": {"bonus_on_capture": False},
            "--no-home-bonus": {"bonus_on_home": False},
            "--no-three-sixes": {"three_sixes_penalty": False},
        }
        for flag, changed in cases.items():
            with self.subTest(flag=flag):
                expected = LudoRules(total_players=5, **changed)
                self.assertEqual(self.rules_built_by(["--players", "5", flag]), expected)

    def test_run_ai_game_plays_to_the_end_under_custom_rules(self) -> None:
        """A seeded game with every flag set still finishes."""

        rules = LudoRules(
            total_players=4, blockades=True, bonus_on_capture=False, bonus_on_home=False, three_sixes_penalty=False
        )
        metrics = simulation.run_ai_game(rules=rules, seed=3)
        self.assertTrue(metrics["completed"])


if __name__ == "__main__":
    unittest.main()
