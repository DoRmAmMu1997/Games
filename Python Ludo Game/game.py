"""UI-free Ludo rules engine."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from board import BoardLayout
from models import Move, MoveResult, PlayerState
from settings import TOKENS_PER_PLAYER, seat_colors


@dataclass(frozen=True)
class LudoRules:
    """Configurable rules for one game.

    These values are captured in save files so a resumed game keeps the same
    house-rule choices it started with. The defaults match the classic
    competitive rule set used by the setup screen.
    """

    total_players: int
    blockades: bool = False
    bonus_on_capture: bool = True
    bonus_on_home: bool = True
    three_sixes_penalty: bool = True

    def __post_init__(self) -> None:
        """Validate the player count as soon as rules are created."""

        if self.total_players not in (4, 5, 6):
            raise ValueError("total_players must be 4, 5, or 6")


class LudoGame:
    """Turn-based state machine for classic competitive Ludo.

    This class intentionally imports no Pygame. Humans, AI, tests, and future
    interfaces all use the same methods, which keeps the official rules in one
    place instead of duplicating them across UI click handlers.
    """

    def __init__(
        self,
        players: Sequence[tuple[str, bool] | PlayerState],
        rules: LudoRules,
        seed: int | None = None,
        ai_profile: str = "tactical",
    ) -> None:
        """Create a game from player names or already restored player states."""

        if len(players) != rules.total_players:
            raise ValueError("players length must match rules.total_players")
        self.rules = rules
        self.layout = BoardLayout.for_player_count(rules.total_players)
        self.rng = random.Random(seed)
        self.seed = seed
        self.ai_profile = ai_profile

        colors = seat_colors(rules.total_players)
        self.players: list[PlayerState] = []
        for index, player in enumerate(players):
            if isinstance(player, PlayerState):
                # Restored games already have token positions and counters, so
                # keep those objects instead of creating new ones.
                self.players.append(player)
            else:
                name, is_human = player
                self.players.append(
                    PlayerState(
                        name=name,
                        is_human=is_human,
                        color=colors[index],
                    )
                )
        for index, player_state in enumerate(self.players):
            # Seat colours are authoritative: they always match the painted
            # board, even for saves written before a palette change.
            player_state.color = colors[index]

        self.current = 0
        # ``awaiting`` is the small state machine the UI and AI both follow:
        # pre_roll -> choose_move -> either pre_roll again for a bonus or the
        # next player's pre_roll.
        self.phase = "playing"
        self.awaiting = "pre_roll"
        self.last_roll: int | None = None
        self.consecutive_sixes = 0
        self.turns_taken = 0
        self.total_rolls = 0
        self.winner: int | None = None
        self.ranking: list[int] = []
        self.event_log: list[str] = ["Choose players and start rolling."]
        self._mark_finished_tokens()

    @property
    def current_player(self) -> PlayerState:
        """Convenience accessor for the player whose turn is active."""

        return self.players[self.current]

    def roll_die(self) -> int:
        """Roll the single Ludo die and record turn-state side effects."""

        die = self.rng.randint(1, 6)
        self.record_roll(die)
        return die

    def record_roll(self, die: int) -> bool:
        """Record a die roll.

        Returns ``True`` when a three-sixes penalty immediately forfeits this
        roll and advances to the next player.
        """

        if self.phase == "game_over":
            return False
        if not 1 <= die <= 6:
            raise ValueError("die must be between 1 and 6")

        self.last_roll = die
        self.total_rolls += 1
        if die == 6:
            self.current_player.sixes_rolled += 1
            self.consecutive_sixes += 1
        else:
            self.consecutive_sixes = 0

        if (
            die == 6
            and self.rules.three_sixes_penalty
            and self.consecutive_sixes >= 3
        ):
            self._note(f"{self.current_player.name} rolled a third 6 and loses the roll.")
            self.consecutive_sixes = 0
            self._advance_turn()
            return True

        self.awaiting = "choose_move"
        return False

    def legal_moves(self, die: int, player_index: int | None = None) -> list[Move]:
        """Return every legal move for ``die``.

        The returned list is the contract between the rules engine and all
        callers. If a move is not present here, the UI cannot offer it and the
        AI cannot choose it.
        """

        if self.phase == "game_over":
            return []
        index = self.current if player_index is None else player_index
        moves: list[Move] = []
        for token_index, token in enumerate(self.players[index].tokens):
            if token.steps == self.layout.finish_steps:
                continue
            if token.steps < 0:
                # Yard tokens need a 6 before they can enter the start square.
                if die != 6:
                    continue
                to_steps = 0
                enters = True
            else:
                to_steps = token.steps + die
                enters = False
            if to_steps > self.layout.finish_steps:
                # Ludo requires an exact roll to finish.
                continue
            landing_index = self.layout.track_index(index, to_steps)
            if self._blocked_by_blockade(index, token.steps, to_steps):
                continue
            moves.append(
                Move(
                    player_index=index,
                    token_index=token_index,
                    die=die,
                    from_steps=token.steps,
                    to_steps=to_steps,
                    landing_index=landing_index,
                    enters_board=enters,
                    reaches_home=to_steps == self.layout.finish_steps,
                )
            )
        return moves

    def apply_move(self, move: Move) -> MoveResult:
        """Apply a legal move and advance turn state.

        The method validates the move against the current legal-move list
        before mutating anything. That keeps tests and UI clicks honest: they
        must pass a move the engine itself already approved.
        """

        if self.phase == "game_over":
            raise ValueError("game is already over")
        if move.player_index != self.current:
            raise ValueError("move does not belong to the current player")
        legal = self.legal_moves(move.die, move.player_index)
        if move not in legal:
            raise ValueError("move is not legal for the current state")

        player = self.players[move.player_index]
        token = player.tokens[move.token_index]
        token.steps = move.to_steps

        captured = self._capture_at(move)
        if captured:
            player.captures += len(captured)

        home = move.reaches_home
        if home:
            self._note(f"{player.name} brought token {move.token_index + 1} home.")
        elif captured:
            targets = ", ".join(self.players[p].name for p, _ in captured)
            self._note(f"{player.name} captured {targets}.")
        else:
            self._note(f"{player.name} moved token {move.token_index + 1}.")

        self._mark_finished_tokens()
        if player.finished_count(self.layout.finish_steps) == TOKENS_PER_PLAYER:
            self._finish_game(move.player_index)
            return MoveResult(
                move=move,
                capture=bool(captured),
                captured=captured,
                home=home,
                extra_turn=False,
                message=f"{player.name} wins!",
            )

        extra_turn = (
            move.die == 6
            or (captured and self.rules.bonus_on_capture)
            or (home and self.rules.bonus_on_home)
        )
        result = MoveResult(
            move=move,
            capture=bool(captured),
            captured=captured,
            home=home,
            extra_turn=extra_turn,
            message=self.event_log[-1],
        )
        if extra_turn:
            self.awaiting = "pre_roll"
        else:
            self.consecutive_sixes = 0
            self._advance_turn()
        return result

    def note_no_move(self, die: int) -> None:
        """Handle a roll with no legal moves."""

        self._note(f"{self.current_player.name} rolled {die} and has no legal move.")
        if die == 6 and self.consecutive_sixes < 3:
            self.awaiting = "pre_roll"
        else:
            self.consecutive_sixes = 0
            self._advance_turn()

    def end_turn(self) -> None:
        """Manually advance to the next player."""

        if self.phase != "game_over":
            self.consecutive_sixes = 0
            self._advance_turn()

    def token_track_index(self, player_index: int, token_index: int) -> int | None:
        """Return where a token sits on the shared track, if anywhere."""

        steps = self.players[player_index].tokens[token_index].steps
        return self.layout.track_index(player_index, steps)

    def tokens_at_track(self, absolute_track_index: int) -> list[tuple[int, int]]:
        """Return ``(player_index, token_index)`` pairs on a track cell."""

        matches: list[tuple[int, int]] = []
        for player_index, player in enumerate(self.players):
            for token_index, token in enumerate(player.tokens):
                if self.layout.track_index(player_index, token.steps) == absolute_track_index:
                    matches.append((player_index, token_index))
        return matches

    def to_dict(self) -> dict:
        """Serialize the current game to plain JSON-compatible data."""

        return {
            "rules": asdict(self.rules),
            "players": [player.to_dict() for player in self.players],
            "current": self.current,
            "phase": self.phase,
            "awaiting": self.awaiting,
            "last_roll": self.last_roll,
            "consecutive_sixes": self.consecutive_sixes,
            "turns_taken": self.turns_taken,
            "total_rolls": self.total_rolls,
            "winner": self.winner,
            "ranking": list(self.ranking),
            "event_log": self.event_log[-12:],
            "seed": self.seed,
            "ai_profile": self.ai_profile,
        }

    @classmethod
    def from_dict(cls, data: dict) -> LudoGame:
        """Rebuild a game from save-file data."""

        rules = LudoRules(**data["rules"])
        players = [PlayerState.from_dict(item) for item in data["players"]]
        game = cls(players, rules, seed=data.get("seed"), ai_profile=data.get("ai_profile", "tactical"))
        game.current = int(data.get("current", 0))
        game.phase = str(data.get("phase", "playing"))
        game.awaiting = str(data.get("awaiting", "pre_roll"))
        game.last_roll = data.get("last_roll")
        game.consecutive_sixes = int(data.get("consecutive_sixes", 0))
        game.turns_taken = int(data.get("turns_taken", 0))
        game.total_rolls = int(data.get("total_rolls", 0))
        game.winner = data.get("winner")
        game.ranking = [int(item) for item in data.get("ranking", [])]
        game.event_log = [str(item) for item in data.get("event_log", [])] or ["Game resumed."]
        game._mark_finished_tokens()
        return game

    def _capture_at(self, move: Move) -> list[tuple[int, int]]:
        """Send opponent tokens on the landing cell back to their yards."""

        if move.landing_index is None or self.layout.is_safe_index(move.landing_index):
            return []
        captured: list[tuple[int, int]] = []
        for player_index, token_index in self.tokens_at_track(move.landing_index):
            if player_index == move.player_index:
                continue
            self.players[player_index].tokens[token_index].steps = -1
            captured.append((player_index, token_index))
        return captured

    def _blocked_by_blockade(self, player_index: int, from_steps: int, to_steps: int) -> bool:
        """Return True if optional blockade rules stop this path."""

        if not self.rules.blockades or from_steps < 0:
            return False
        blocked_indices = self._opponent_blockades(player_index)
        if not blocked_indices:
            return False
        for step in range(from_steps + 1, min(to_steps, self.layout.track_length - 1) + 1):
            if self.layout.track_index(player_index, step) in blocked_indices:
                return True
        return False

    def _opponent_blockades(self, player_index: int) -> set[int]:
        """Find every opponent square occupied by at least two same-player tokens."""

        blockades: set[int] = set()
        for index in range(len(self.players)):
            if index == player_index:
                continue
            counts: dict[int, int] = {}
            for token in self.players[index].tokens:
                track_index = self.layout.track_index(index, token.steps)
                if track_index is not None:
                    counts[track_index] = counts.get(track_index, 0) + 1
            blockades.update(track for track, count in counts.items() if count >= 2)
        return blockades

    def _advance_turn(self) -> None:
        """Move turn control to the next player who has not finished."""

        self.turns_taken += 1
        for offset in range(1, len(self.players) + 1):
            candidate = (self.current + offset) % len(self.players)
            if self.players[candidate].finished_count(self.layout.finish_steps) < TOKENS_PER_PLAYER:
                self.current = candidate
                self.awaiting = "pre_roll"
                return
        self._finish_game(self.current)

    def _finish_game(self, winner_index: int) -> None:
        """Mark the game over and compute a final ranking."""

        self.phase = "game_over"
        self.awaiting = "game_over"
        self.winner = winner_index
        if winner_index not in self.ranking:
            self.ranking.append(winner_index)
        ordered = sorted(
            range(len(self.players)),
            key=lambda index: (
                self.players[index].finished_count(self.layout.finish_steps),
                self.players[index].progress_score(self.layout.finish_steps),
                self.players[index].captures,
            ),
            reverse=True,
        )
        self.ranking = []
        for index in ordered:
            if index not in self.ranking:
                self.ranking.append(index)
        self._note(f"{self.players[winner_index].name} wins the game!")

    def _mark_finished_tokens(self) -> None:
        """Teach token helper properties what this layout's finish step is."""

        for player_state in self.players:
            for token in player_state.tokens:
                token._finished_steps = self.layout.finish_steps

    def _note(self, message: str) -> None:
        """Append a short message to the on-screen event log."""

        self.event_log.append(message)
        del self.event_log[:-12]
