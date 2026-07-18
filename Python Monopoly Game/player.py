"""The Player model -- one per participant, human or AI.

A `Player` is deliberately a thin data holder: cash, where the token sits,
jail state, and a few flags. It does NOT store which properties it owns -- the
game engine keeps a single owners table (position -> player) so there is one
source of truth and no two lists to keep in sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from settings import STARTING_CASH, TOKEN_COLORS, TOKEN_NAMES


@dataclass
class Player:
    """One Monopoly player.

    `index` is the player's seat number 0-3 and also picks the token colour.
    `is_human` decides whether the UI waits for clicks or the AI plays the
    turn. `jail_cards` counts Get Out of Jail Free cards currently held.
    """

    index: int
    name: str
    is_human: bool
    cash: int = STARTING_CASH
    position: int = 0
    in_jail: bool = False
    jail_turns: int = 0          # turns spent trying to escape jail
    jail_cards: int = 0          # Get Out of Jail Free cards held
    bankrupt: bool = False
    # Decks each held jail card came from, so it can be returned when used.
    jail_card_decks: list = field(default_factory=list)

    @property
    def token_color(self):
        """The RGB colour of this player's token."""
        return TOKEN_COLORS[self.index]

    @property
    def token_name(self) -> str:
        """The human-readable colour name of this player's token."""
        return TOKEN_NAMES[self.index]

    def to_dict(self) -> dict:
        """Return a plain-dict snapshot of this player, ready for JSON saving."""
        return {
            "index": self.index,
            "name": self.name,
            "is_human": self.is_human,
            "cash": self.cash,
            "position": self.position,
            "in_jail": self.in_jail,
            "jail_turns": self.jail_turns,
            "jail_cards": self.jail_cards,
            "bankrupt": self.bankrupt,
            "jail_card_decks": list(self.jail_card_decks),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Player:
        """Rebuild a Player from a `to_dict()` snapshot (used when resuming)."""
        return cls(
            index=int(data["index"]),
            name=str(data["name"]),
            is_human=bool(data["is_human"]),
            cash=int(data["cash"]),
            position=int(data["position"]),
            in_jail=bool(data["in_jail"]),
            jail_turns=int(data["jail_turns"]),
            jail_cards=int(data["jail_cards"]),
            bankrupt=bool(data["bankrupt"]),
            jail_card_decks=list(data.get("jail_card_decks", [])),
        )
