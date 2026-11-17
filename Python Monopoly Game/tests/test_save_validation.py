"""Save-file validation: corrupt saves are refused, legitimate ones still load.

`MonopolyGame.from_dict` is the only door a save file comes through, so it
coerces stored numbers to int and refuses a payload whose turn state, seats,
titles, buildings or decks could not be resumed safely -- while still
accepting every state a real game can legitimately be saved in.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from test_engine_regressions import rig_rolls
from test_foundation_improvements import make_game

from game import MonopolyGame
from settings import JAIL_POSITION


def saved_payload() -> dict:
    """Return a fresh, valid save payload from a deterministic game."""
    return make_game().to_dict()


class SaveValidationTests(unittest.TestCase):
    """from_dict rejects corrupt saves with ValueError and keeps good ones."""

    def test_corrupt_saves_are_rejected_with_value_error(self) -> None:
        """Every kind of unresumable payload raises ValueError, nothing else."""

        def players(payload: dict, count: int) -> None:
            """Trim or pad the saved seats to `count` players."""
            seats = payload["players"]
            while len(seats) < count:
                extra = copy.deepcopy(seats[-1])
                extra["index"] = len(seats)
                seats.append(extra)
            del seats[count:]

        corruptions = {
            "one player": lambda p: players(p, 1),
            "five players": lambda p: players(p, 5),
            "seat index mismatch": lambda p: p["players"][1].update(index=3),
            "current out of range": lambda p: p.update(current=4),
            "negative current": lambda p: p.update(current=-1),
            "mid-auction state": lambda p: p.update(awaiting="auction"),
            "title off the board": lambda p: p["owners"].update({"40": 0}),
            "unownable space owned": lambda p: p["owners"].update({"0": 0}),
            "owner seat missing": lambda p: p["owners"].update({"1": 7}),
            "building level too high": lambda p: p["houses"].update({"1": 6}),
            "negative building level": lambda p: p["houses"].update({"1": -1}),
            "empty deck": lambda p: p.update(chance=[]),
            "deck index out of range": lambda p: p["chest"].append(99),
        }
        for name, corrupt in corruptions.items():
            with self.subTest(name):
                payload = saved_payload()
                corrupt(payload)
                with self.assertRaises(ValueError):
                    MonopolyGame.from_dict(payload)

    def test_save_numbers_stored_as_text_are_coerced_to_int(self) -> None:
        """Hand-edited saves that store numbers as text load as real ints."""
        payload = saved_payload()
        payload.update(current="1", turn_count="12", bank_houses="30", bank_hotels="11")
        payload["owners"] = {"1": "2", "3": "2"}

        game = MonopolyGame.from_dict(payload)

        self.assertEqual(game.current, 1)
        self.assertEqual(game.turn_count, 12)
        self.assertEqual((game.bank_houses, game.bank_hotels), (30, 11))
        self.assertEqual(game.owners, {1: 2, 3: 2})
        for value in (game.current, game.turn_count, game.bank_houses, *game.owners.values()):
            self.assertIs(type(value), int)

    def test_post_bankruptcy_save_still_loads(self) -> None:
        """States a real game reaches after a bankruptcy are not mistaken for corruption.

        A bankrupt current player, a title still pointing at a bankrupt
        seat, a zero building entry and a deck missing the jail card that a
        player holds are all legitimate.
        """
        game = make_game()
        game.players[1].bankrupt = True
        game.players[1].cash = 0
        game.current = 1
        game.awaiting = "post_roll"
        game.owners = {1: 1, 3: 2}
        game.houses = {1: 0}
        jail_index = next(i for i, card in enumerate(game.chance.master)
                          if card["kind"] == "jail_card")
        if jail_index in game.chance.order:
            game.chance.order.remove(jail_index)
        game.grant_jail_card(game.players[2], "chance")

        restored = MonopolyGame.from_dict(game.to_dict())

        self.assertEqual(restored.current, 1)
        self.assertTrue(restored.players[1].bankrupt)
        self.assertEqual(restored.owners, {1: 1, 3: 2})
        self.assertEqual(restored.houses, {1: 0})
        self.assertEqual(len(restored.chance.order), len(restored.chance.master) - 1)

    def test_version_one_save_without_newer_fields_still_loads(self) -> None:
        """A first-release save has no version, AI profile or doubles count."""
        payload = saved_payload()
        for key in ("save_version", "ai_profile", "doubles_count"):
            payload.pop(key, None)

        game = MonopolyGame.from_dict(payload)

        self.assertEqual(game.ai_profile, "standard")
        self.assertEqual(game.doubles_count, 0)

    def test_resumed_save_keeps_doubles_count_for_three_doubles_rule(self) -> None:
        """Saving between two doubles must not reset the three-doubles count.

        A player who rolled two doubles, saved and resumed is still on
        their third roll: another double sends them straight to Jail.
        """
        game = make_game()
        game.doubles_count = 2
        game.awaiting = "pre_roll"

        restored = MonopolyGame.from_dict(game.to_dict())
        self.assertEqual(restored.doubles_count, 2)

        rig_rolls(restored, 3, 3)
        restored.roll_dice()

        player = restored.current_player
        self.assertTrue(player.in_jail)
        self.assertEqual(player.position, JAIL_POSITION)


if __name__ == "__main__":
    unittest.main()
