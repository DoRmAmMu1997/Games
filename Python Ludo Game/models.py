"""Small data models shared by the Ludo engine, AI, and UI."""

from __future__ import annotations

from dataclasses import dataclass, field

from settings import TOKENS_PER_PLAYER


@dataclass
class TokenState:
    """Position of one token.

    ``steps`` is measured from the owning player's start square:
    - ``-1`` means the token is still in the yard,
    - ``0`` through ``finish_steps`` are playable progress values.
    """

    steps: int = -1
    # The board length depends on the player count, so the game stamps the
    # current layout's finish step onto each token (see
    # ``LudoGame._mark_finished_tokens``) before ``finished`` is used. It is
    # not serialized; loading a save re-stamps it.
    _finished_steps: int | None = None

    @property
    def in_yard(self) -> bool:
        """True while the token has not entered the board."""

        return self.steps < 0

    @property
    def finished(self) -> bool:
        """True when the token has reached the final home cell."""

        return self._finished_steps is not None and self._finished_steps == self.steps

    def to_dict(self) -> dict:
        """Serialize just the token fields that belong in save files."""

        return {"steps": self.steps}

    @classmethod
    def from_dict(cls, data: dict) -> TokenState:
        """Rebuild a token from saved JSON data."""

        return cls(steps=int(data.get("steps", -1)))


@dataclass
class PlayerState:
    """One Ludo player, human or AI.

    The player owns four token states plus a few counters used for the final
    ranking and lifetime stats. UI-only details, such as selected buttons, do
    not live here because this object is saved to disk.
    """

    name: str
    is_human: bool
    color: tuple[int, int, int]
    tokens: list[TokenState] = field(
        default_factory=lambda: [TokenState() for _ in range(TOKENS_PER_PLAYER)]
    )
    captures: int = 0
    sixes_rolled: int = 0
    finished_turn: int | None = None

    def finished_count(self, finish_steps: int) -> int:
        """Count how many of this player's tokens are fully home."""

        return sum(1 for token in self.tokens if token.steps == finish_steps)

    def progress_score(self, finish_steps: int) -> int:
        """Return a simple total-progress score for ranking unfinished players."""

        return sum(max(0, min(token.steps, finish_steps)) for token in self.tokens)

    def to_dict(self) -> dict:
        """Serialize the player into JSON-compatible save data."""

        return {
            "name": self.name,
            "is_human": self.is_human,
            "color": list(self.color),
            "tokens": [token.to_dict() for token in self.tokens],
            "captures": self.captures,
            "sixes_rolled": self.sixes_rolled,
            "finished_turn": self.finished_turn,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PlayerState:
        """Rebuild a player and all four tokens from saved JSON data."""

        return cls(
            name=str(data["name"]),
            is_human=bool(data["is_human"]),
            color=tuple(data["color"]),
            tokens=[TokenState.from_dict(item) for item in data["tokens"]],
            captures=int(data.get("captures", 0)),
            sixes_rolled=int(data.get("sixes_rolled", 0)),
            finished_turn=data.get("finished_turn"),
        )


@dataclass(frozen=True)
class Move:
    """A legal token move for a specific die roll.

    ``from_steps`` and ``to_steps`` are relative to the moving player's own
    start square. ``landing_index`` is the shared board index, or ``None`` when
    the move lands in the private home lane.
    """

    player_index: int
    token_index: int
    die: int
    from_steps: int
    to_steps: int
    landing_index: int | None
    enters_board: bool = False
    reaches_home: bool = False


@dataclass
class MoveResult:
    """Outcome returned after applying a move.

    The UI uses this to decide what to announce and whether a player earned a
    bonus turn. Tests also inspect it so rule regressions are easy to spot.
    """

    move: Move
    capture: bool = False
    captured: list[tuple[int, int]] = field(default_factory=list)
    home: bool = False
    extra_turn: bool = False
    message: str = ""
