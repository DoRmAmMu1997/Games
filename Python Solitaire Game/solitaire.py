"""
Simple Klondike Solitaire built with tkinter.

Everything lives in this one file so it is easy to run and study.
The code is split into:
1. A game model that knows the rules and scoring.
2. A tkinter app that draws the cards and handles input.
"""

import contextlib
import json
import os
import random
import sys
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox
from typing import Any

# Card size in pixels.
CARD_WIDTH = 88
CARD_HEIGHT = 120

# Vertical spacing between cards in a tableau column.
# Face-down cards overlap more tightly so columns stay compact.
FACE_DOWN_SPACING = 16
FACE_UP_SPACING = 24

# General layout values used to place piles on the canvas.
MARGIN_X = 20
TOP_ROW_Y = 20
TABLEAU_Y = 180
COLUMN_GAP = 18

# Window and canvas sizes.
WINDOW_WIDTH = 860
WINDOW_HEIGHT = 860
CANVAS_HEIGHT = 760

# Derived spacing values that are reused in several layout helpers.
TABLEAU_STEP = CARD_WIDTH + COLUMN_GAP
FOUNDATION_START_X = 430

# Colors used by the simple felt-style interface.
BACKGROUND_COLOR = "#0B6E4F"
TABLE_TOP_COLOR = "#0D7857"
TABLE_ACCENT_DARK = "#09573E"
TABLE_ACCENT_LIGHT = "#128562"
CARD_BACK_COLOR = "#274C77"
CARD_BACK_ACCENT = "#86ADD8"
CARD_OUTLINE = "#1E1E1E"
CARD_FILL = "#FFFDF8"
CARD_SHADOW = "#083725"
PLACEHOLDER_FILL = "#0A6248"
EMPTY_OUTLINE = "#DCECC9"
HIGHLIGHT_COLOR = "#FFD24D"
# A separate colour for hint highlights so a hinted destination is never
# confused with the yellow selection highlight on the card the player lifted.
HINT_COLOR = "#FF8A3D"

# Animation timing. More steps means smoother movement.
ANIMATION_STEPS = 18
ANIMATION_DELAY_MS = 16

# Limit the number of undo snapshots so memory use stays reasonable.
UNDO_HISTORY_LIMIT = 300

# Human-friendly symbols for each suit.
SUIT_SYMBOLS = {
    "hearts": "\u2665",
    "diamonds": "\u2666",
    "clubs": "\u2663",
    "spades": "\u2660",
}

SUIT_COLORS = {
    "hearts": "#C62828",
    "diamonds": "#C62828",
    "clubs": "#1A1A1A",
    "spades": "#1A1A1A",
}

RANK_LABELS = {
    1: "A",
    11: "J",
    12: "Q",
    13: "K",
}

FOUNDATION_SUITS = ["hearts", "diamonds", "clubs", "spades"]

# Board structure for a standard Klondike layout.
TABLEAU_COLUMNS = 7
FOUNDATION_COUNT = 4


def _user_save_dir() -> str:
    """Return a stable per-user folder for save data, creating it if needed.

    This must not be derived from __file__: a PyInstaller --onefile build
    resolves __file__ into a temporary folder that Windows deletes when the
    .exe closes, which is why the high score used to reset every session.
    %APPDATA% persists across runs whether the game runs as a script or a
    frozen .exe.
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    save_dir = os.path.join(base, "Klondike Solitaire")
    os.makedirs(save_dir, exist_ok=True)
    return save_dir


def _resource_path(name: str) -> str:
    """Return the path to a bundled read-only resource file, such as the icon.

    PyInstaller unpacks bundled data into sys._MEIPASS at runtime; running from
    source the file simply sits next to this script.
    """
    base = getattr(sys, "_MEIPASS", None)
    base_dir = base if base else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, name)


def _log_save_error(save_path: str, error: Exception) -> None:
    """Record a failed save to a log file instead of letting it fail silently."""
    try:
        log_path = os.path.join(os.path.dirname(save_path), "save_error.log")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"[{stamp}] could not save high score: {error}\n")
    except OSError:
        # If even the log write fails there is nothing more we can safely do.
        pass


@dataclass
class Card:
    """One playing card, including whether it is face up on the board."""

    suit: str
    rank: int
    face_up: bool = False

    def color(self) -> str:
        """Return the card color used by Solitaire move rules."""
        return "red" if self.suit in ("hearts", "diamonds") else "black"

    def label(self) -> str:
        """Build a short text label like 'Q♥' or '10♣'."""
        rank_text = RANK_LABELS.get(self.rank, str(self.rank))
        return f"{rank_text}{SUIT_SYMBOLS[self.suit]}"


@dataclass
class Selection:
    """A group of currently selected cards and where they came from."""

    source_type: str
    pile_index: int
    card_index: int
    cards: list[Card]


@dataclass
class HintMove:
    """A possible move plus a ready-to-show explanation for the player."""

    source_type: str
    source_index: int
    source_card_index: int
    cards: list[Card]
    destination_type: str
    destination_index: int
    stock_clicks: int
    description: str


@dataclass
class AnimationState:
    """Information needed to draw cards moving between two positions."""

    cards: list[Card]
    start_positions: list[tuple[float, float]]
    end_positions: list[tuple[float, float]]
    destination_type: str
    destination_index: int
    completion_message: str
    frame: int = 0
    steps: int = ANIMATION_STEPS


class KlondikeGame:
    """Game model: stores the board and enforces the Klondike rules."""

    # Score values used by the game.
    FOUNDATION_POINTS = 10
    REVEAL_POINTS = 5
    WIN_BONUS = 100
    TIME_BONUS_CAP = 700

    def __init__(self, high_score_path: str) -> None:
        """Create a new game model and load saved score/statistics data."""
        # Remember where score/statistics JSON should be saved.
        self.high_score_path = high_score_path

        # Load any previously saved high score and win/loss counts.
        saved_data = self.load_saved_data()
        self.high_score = saved_data["high_score"]
        self.wins = saved_data["wins"]
        self.losses = saved_data["losses"]

        # These values are reset for each new deal.
        self.score = 0
        self.stock: list[Card] = []
        self.waste: list[Card] = []
        self.foundations: list[list[Card]] = [[] for _ in range(FOUNDATION_COUNT)]
        self.tableau: list[list[Card]] = [[] for _ in range(TABLEAU_COLUMNS)]
        self.won = False
        self.lost = False

        # Start with a fresh shuffled board.
        self.new_game()

    def new_game(self) -> None:
        """Reset the board and deal a standard Klondike opening layout."""
        # Reset score and all piles for a fresh deal.
        self.score = 0
        self.stock = []
        self.waste = []
        self.foundations = [[] for _ in range(FOUNDATION_COUNT)]
        self.tableau = [[] for _ in range(TABLEAU_COLUMNS)]
        self.won = False
        self.lost = False

        # Build and shuffle a full 52-card deck.
        deck = self.create_shuffled_deck()

        # Deal 1 card to the first column, 2 to the second, and so on.
        for column_index in range(TABLEAU_COLUMNS):
            for row_index in range(column_index + 1):
                # Pop from the end because it is the cheapest list operation.
                card = deck.pop()

                # Only the last dealt card in each column starts face up.
                card.face_up = row_index == column_index
                self.tableau[column_index].append(card)

        # Whatever is left becomes the stock pile.
        self.stock = deck

        # Make sure all stock cards are face down.
        for card in self.stock:
            card.face_up = False

    def create_shuffled_deck(self) -> list[Card]:
        """Create a normal 52-card deck and shuffle it in place."""
        deck = [Card(suit=suit, rank=rank) for suit in FOUNDATION_SUITS for rank in range(1, 14)]
        random.shuffle(deck)
        return deck

    def load_saved_data(self) -> dict:
        """Read saved high score and statistics from JSON, if possible."""
        try:
            with open(self.high_score_path, encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # If the file is missing or broken, silently start from zeros.
            data = {}

        def safe_int(name: str) -> int:
            """Read one numeric field safely and clamp it to 0 or higher."""
            try:
                return max(0, int(data.get(name, 0)))
            except (ValueError, TypeError):
                return 0

        return {
            "high_score": safe_int("high_score"),
            "wins": safe_int("wins"),
            "losses": safe_int("losses"),
        }

    def save_high_score(self) -> None:
        """Write best score and win/loss counts with a crash-safe atomic write."""
        payload = {
            "high_score": self.high_score,
            "wins": self.wins,
            "losses": self.losses,
        }
        try:
            os.makedirs(os.path.dirname(self.high_score_path), exist_ok=True)
            # Write to a temp file first, then atomically replace the real file
            # so a crash mid-write can never leave a half-written save behind.
            tmp_path = self.high_score_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2)
            os.replace(tmp_path, self.high_score_path)
        except OSError as error:
            # Saving should never crash the game; log the failure and move on.
            _log_save_error(self.high_score_path, error)

    def add_score(self, points: int) -> None:
        """Add points to the current score and update the saved high score."""
        self.score += points
        if self.score > self.high_score:
            self.high_score = self.score
        self.save_high_score()

    def record_win(self) -> None:
        """Increase the saved win counter."""
        self.wins += 1
        self.save_high_score()

    def record_loss(self) -> None:
        """Increase the saved loss counter."""
        self.losses += 1
        self.save_high_score()

    def snapshot(self) -> dict:
        """Capture the entire game state so Undo can restore it later."""
        return {
            "score": self.score,
            "high_score": self.high_score,
            "wins": self.wins,
            "losses": self.losses,
            "won": self.won,
            "lost": self.lost,
            "stock": self.serialize_cards(self.stock),
            "waste": self.serialize_cards(self.waste),
            "foundations": [self.serialize_cards(pile) for pile in self.foundations],
            "tableau": [self.serialize_cards(column) for column in self.tableau],
        }

    def restore_snapshot(self, snapshot: dict) -> None:
        """Restore a previously saved game state."""
        # Keep the best score the player has ever reached in this session/file.
        previous_high_score = self.high_score
        self.score = int(snapshot["score"])
        self.high_score = max(previous_high_score, int(snapshot["high_score"]))
        self.wins = int(snapshot["wins"])
        self.losses = int(snapshot["losses"])
        self.won = bool(snapshot["won"])
        self.lost = bool(snapshot["lost"])
        self.stock = self.deserialize_cards(snapshot["stock"])
        self.waste = self.deserialize_cards(snapshot["waste"])
        self.foundations = [self.deserialize_cards(pile) for pile in snapshot["foundations"]]
        self.tableau = [self.deserialize_cards(column) for column in snapshot["tableau"]]
        self.save_high_score()

    def serialize_cards(self, cards: list[Card]) -> list[dict]:
        """Turn Card objects into plain dictionaries that JSON can store."""
        return [
            {
                "suit": card.suit,
                "rank": card.rank,
                "face_up": card.face_up,
            }
            for card in cards
        ]

    def deserialize_cards(self, serialized_cards: list[dict]) -> list[Card]:
        """Rebuild Card objects from saved dictionaries."""
        return [
            Card(
                suit=str(card_data["suit"]),
                rank=int(card_data["rank"]),
                face_up=bool(card_data["face_up"]),
            )
            for card_data in serialized_cards
        ]

    def draw_from_stock(self) -> str:
        """Draw from the stock or recycle waste back into stock."""
        if self.stock:
            # Normal draw: reveal one card and place it on the waste pile.
            card = self.stock.pop()
            card.face_up = True
            self.waste.append(card)
            return "draw"

        if self.waste:
            # When stock is empty, recycle the waste pile back into stock.
            while self.waste:
                card = self.waste.pop()
                card.face_up = False
                self.stock.append(card)
            return "reset"

        # No cards anywhere means no draw action is possible.
        return "empty"

    def selection_from_waste(self) -> Selection | None:
        """Return the selectable top waste card, if one exists."""
        if not self.waste:
            return None
        return Selection("waste", 0, len(self.waste) - 1, [self.waste[-1]])

    def selection_from_foundation(self, foundation_index: int) -> Selection | None:
        """Return the top card of a foundation as a Selection."""
        pile = self.foundations[foundation_index]
        if not pile:
            return None
        return Selection("foundation", foundation_index, len(pile) - 1, [pile[-1]])

    def selection_from_tableau(self, column_index: int, card_index: int) -> Selection | None:
        """Build a selection from the real tableau currently on the board."""
        return self.selection_from_tableau_cards(self.tableau, column_index, card_index)

    def selection_from_tableau_cards(
        self, tableau: list[list[Card]], column_index: int, card_index: int
    ) -> Selection | None:
        """
        Build a movable tableau stack from any supplied tableau-like board.

        This helper is used both on the real board and on simulated boards
        created while the hint system tests future situations.
        """
        column = tableau[column_index]
        if card_index < 0 or card_index >= len(column):
            return None

        # A tableau move can include the clicked card and every card below it.
        stack = column[card_index:]
        if not stack or not stack[0].face_up:
            return None
        if not self.is_valid_tableau_stack(stack):
            return None
        return Selection("tableau", column_index, card_index, list(stack))

    def selection_from_hint(self, move: HintMove) -> Selection | None:
        """Translate a stored hint back into a live selectable stack."""
        if move.source_type == "waste":
            return self.selection_from_waste()
        if move.source_type == "foundation":
            return self.selection_from_foundation(move.source_index)
        if move.source_type == "tableau":
            return self.selection_from_tableau(move.source_index, move.source_card_index)
        return None

    def is_valid_tableau_stack(self, cards: list[Card]) -> bool:
        """Check the red-black descending order required in tableau stacks."""
        if not cards or not all(card.face_up for card in cards):
            return False
        for index in range(len(cards) - 1):
            current_card = cards[index]
            next_card = cards[index + 1]
            if current_card.color() == next_card.color():
                return False
            if current_card.rank != next_card.rank + 1:
                return False
        return True

    def can_move_to_tableau(self, cards: list[Card], column_index: int) -> bool:
        """Convenience wrapper that checks a move against one real tableau column."""
        return self.can_move_to_tableau_cards(cards, self.tableau[column_index])

    def can_move_to_tableau_cards(self, cards: list[Card], destination: list[Card]) -> bool:
        """Check the standard tableau rule for any destination pile."""
        if not cards:
            return False
        moving_card = cards[0]
        if not destination:
            # Only a king can start an empty tableau column.
            return moving_card.rank == 13
        top_card = destination[-1]
        if not top_card.face_up:
            return False
        if top_card.color() == moving_card.color():
            return False
        return top_card.rank == moving_card.rank + 1

    def can_move_to_foundation(self, card: Card, foundation_index: int) -> bool:
        """Convenience wrapper for checking one real foundation pile."""
        return self.can_move_to_foundation_piles(card, foundation_index, self.foundations)

    def can_move_to_foundation_piles(
        self,
        card: Card,
        foundation_index: int,
        foundations: list[list[Card]],
    ) -> bool:
        """Check whether a card can be placed on a given foundation pile."""
        expected_suit = FOUNDATION_SUITS[foundation_index]
        if card.suit != expected_suit:
            return False
        destination = foundations[foundation_index]
        if not destination:
            # Empty foundations must start with an Ace.
            return card.rank == 1
        return card.rank == destination[-1].rank + 1

    def move_selection_to_tableau(self, selection: Selection, column_index: int) -> bool:
        """Move a selected stack to another tableau column if legal."""
        if selection.source_type == "tableau" and selection.pile_index == column_index:
            return False
        if not self.can_move_to_tableau(selection.cards, column_index):
            return False
        moving_cards = self.remove_selection(selection)
        self.tableau[column_index].extend(moving_cards)
        return True

    def move_selection_to_foundation(self, selection: Selection, foundation_index: int) -> bool:
        """Move one selected card to a foundation pile if legal."""
        if len(selection.cards) != 1:
            return False
        if selection.source_type == "foundation" and selection.pile_index == foundation_index:
            return False
        card = selection.cards[0]
        if not self.can_move_to_foundation(card, foundation_index):
            return False
        moving_cards = self.remove_selection(selection)
        self.foundations[foundation_index].extend(moving_cards)
        self.add_score(self.FOUNDATION_POINTS)
        return True

    def remove_selection(self, selection: Selection) -> list[Card]:
        """
        Remove the selected cards from their source pile and return them.

        For tableau columns, this method also flips the newly uncovered top
        card if needed.
        """
        if selection.source_type == "waste":
            return [self.waste.pop()]
        if selection.source_type == "foundation":
            return [self.foundations[selection.pile_index].pop()]
        column = self.tableau[selection.pile_index]
        moving_cards = column[selection.card_index:]
        del column[selection.card_index:]
        self.reveal_top_tableau_card(selection.pile_index)
        return moving_cards

    def reveal_top_tableau_card(self, column_index: int) -> None:
        """Flip the top hidden card in a tableau column and award points."""
        column = self.tableau[column_index]
        if column and not column[-1].face_up:
            column[-1].face_up = True
            self.add_score(self.REVEAL_POINTS)

    def has_won(self) -> bool:
        """The game is won when every foundation contains 13 cards."""
        return all(len(pile) == 13 for pile in self.foundations)

    def all_tableau_cards_face_up(self) -> bool:
        """Auto-solve begins only after no hidden tableau cards remain."""
        return all(card.face_up for column in self.tableau for card in column)

    def next_auto_foundation_move(self) -> tuple[Selection, int] | None:
        """
        Return the next direct move to a foundation for auto-complete mode.

        When every tableau card is already face up, a simple foundation-first
        sweep gives the familiar Solitaire auto-finish behavior.
        """
        if self.waste:
            waste_selection = self.selection_from_waste()
            if waste_selection is not None:
                for foundation_index in range(FOUNDATION_COUNT):
                    if self.can_move_to_foundation(waste_selection.cards[0], foundation_index):
                        return waste_selection, foundation_index

        for column_index, column in enumerate(self.tableau):
            if not column or not column[-1].face_up:
                continue
            selection = self.selection_from_tableau(column_index, len(column) - 1)
            if selection is None:
                continue
            for foundation_index in range(FOUNDATION_COUNT):
                if self.can_move_to_foundation(selection.cards[0], foundation_index):
                    return selection, foundation_index

        return None

    # ------------------------------------------------------------------
    # The hint engine
    # ------------------------------------------------------------------
    # Everything from here to `follow_up_creates_concrete_progress` is one
    # subsystem: the hint engine that also powers loss detection. It is a
    # pipeline of four stages:
    #
    #   1. GENERATE  - `current_legal_moves` lists every legal move on the
    #      board right now; `future_waste_moves` simulates clicking through
    #      the stock to find waste cards that become playable later.
    #   2. FILTER    - `is_meaningful_move` throws away legal-but-pointless
    #      shuffles (ace diversions, king shuffles between empty columns,
    #      redundant transfers, unproductive foundation returns).
    #   3. RANK      - `hint_sort_key` / `hint_priority` order what survived;
    #      the lowest priority number wins.
    #   4. DESCRIBE  - `describe_hint` turns the winning move into the text
    #      the player reads.
    #
    # Naming convention: many checks exist twice, as a thin wrapper that
    # reads the REAL board (`is_redundant_tableau_transfer`) plus an
    # `..._on_board` version that takes tableau/foundations as parameters so
    # the same rule can run against SIMULATED "what if" boards. When editing
    # a rule, edit the `_on_board` version - the wrapper only forwards.
    #
    # If no move survives the pipeline (and the stock look-ahead), the game
    # declares the deal lost - so a filter that is too aggressive can cause
    # false "no more moves" verdicts. The filters deliberately allow any
    # move that reveals a hidden card or unlocks a foundation play.
    def find_best_move(self) -> HintMove | None:
        """
        Find the best move for the hint system and loss detection.

        We first prefer moves that are possible right now. If none exist, we
        also look ahead through future stock draws so the hint button can say
        how many clicks away the next useful waste move is.
        """
        current_moves = self.current_legal_moves()
        if current_moves:
            current_moves.sort(key=self.hint_sort_key)
            return current_moves[0]

        future_moves = self.future_waste_moves()
        if future_moves:
            future_moves.sort(key=self.hint_sort_key)
            return future_moves[0]

        return None

    def current_legal_moves(self) -> list[HintMove]:
        """Collect all useful moves that can be made immediately."""
        moves: list[HintMove] = []

        if self.waste:
            # The player may only move the top waste card.
            moves.extend(
                self.single_card_moves(
                    self.waste[-1],
                    source_type="waste",
                    source_index=0,
                    source_card_index=len(self.waste) - 1,
                    stock_clicks=0,
                )
            )

        for foundation_index, pile in enumerate(self.foundations):
            if not pile:
                continue
            # Foundation returns are allowed, but later filtered heavily so
            # hints do not suggest pointless back-and-forth moves.
            card = pile[-1]
            for column_index in range(TABLEAU_COLUMNS):
                if self.can_move_to_tableau([card], column_index):
                    moves.append(
                        self.build_hint_move(
                            source_type="foundation",
                            source_index=foundation_index,
                            source_card_index=len(pile) - 1,
                            cards=[card],
                            destination_type="tableau",
                            destination_index=column_index,
                            stock_clicks=0,
                        )
                    )

        for column_index, column in enumerate(self.tableau):
            if not column:
                continue

            top_card = column[-1]
            if top_card.face_up:
                # The top face-up card can move by itself to tableau/foundation.
                moves.extend(
                    self.single_card_moves(
                        top_card,
                        source_type="tableau",
                        source_index=column_index,
                        source_card_index=len(column) - 1,
                        stock_clicks=0,
                    )
                )

            for card_index, card in enumerate(column):
                if not card.face_up:
                    continue

                selection = self.selection_from_tableau(column_index, card_index)
                if selection is None:
                    continue

                for destination_index in range(TABLEAU_COLUMNS):
                    if destination_index == column_index:
                        continue
                    # Larger face-up stacks can move between tableau columns.
                    if self.can_move_to_tableau(selection.cards, destination_index):
                        moves.append(
                            self.build_hint_move(
                                source_type="tableau",
                                source_index=column_index,
                                source_card_index=card_index,
                                cards=selection.cards,
                                destination_type="tableau",
                                destination_index=destination_index,
                                stock_clicks=0,
                            )
                        )

        return [move for move in moves if self.is_meaningful_move(move)]

    def future_waste_moves(self) -> list[HintMove]:
        """
        Simulate future stock clicks and collect useful waste-based moves.

        This helps the hint system say things like "click the stock twice,
        then move 5♥ to the Hearts foundation."
        """
        future_moves: list[HintMove] = []
        # Keyed by (suit, rank, destination type, destination index); the
        # value is the cheapest (fewest stock clicks) move for that card.
        best_seen: dict[tuple[str, int, str, int], HintMove] = {}

        # Work on copies so the real game state is not changed.
        simulated_stock = list(self.stock)
        simulated_waste = list(self.waste)
        seen_states = set()
        stock_clicks = 0

        while True:
            # If we reach the same stock/waste arrangement again, we would
            # loop forever, so stop the simulation here.
            state_key = (
                tuple((card.suit, card.rank) for card in simulated_stock),
                tuple((card.suit, card.rank) for card in simulated_waste),
            )
            if state_key in seen_states:
                break
            seen_states.add(state_key)

            if simulated_waste and stock_clicks > 0:
                card = simulated_waste[-1]
                for move in self.single_card_moves(
                    card,
                    source_type="future_waste",
                    source_index=0,
                    source_card_index=0,
                    stock_clicks=stock_clicks,
                ):
                    move_key = (
                        move.cards[0].suit,
                        move.cards[0].rank,
                        move.destination_type,
                        move.destination_index,
                    )
                    # The same card can become reachable on several different
                    # stock cycles; keep only the cheapest (fewest clicks) one.
                    old_move = best_seen.get(move_key)
                    if old_move is None or move.stock_clicks < old_move.stock_clicks:
                        best_seen[move_key] = move

            if simulated_stock:
                simulated_waste.append(simulated_stock.pop())
                stock_clicks += 1
                continue

            if simulated_waste:
                # Recycle waste back into stock the same way the real game does.
                while simulated_waste:
                    simulated_stock.append(simulated_waste.pop())
                stock_clicks += 1
                continue

            break

        future_moves.extend(best_seen.values())
        return [move for move in future_moves if self.is_meaningful_move(move)]

    def single_card_moves(
        self,
        card: Card,
        source_type: str,
        source_index: int,
        source_card_index: int,
        stock_clicks: int,
    ) -> list[HintMove]:
        """Build every one-card move available for a given card."""
        moves: list[HintMove] = []

        if source_type != "foundation":
            # Cards already on a foundation are not suggested back to another foundation.
            for foundation_index in range(FOUNDATION_COUNT):
                if self.can_move_to_foundation(card, foundation_index):
                    moves.append(
                        self.build_hint_move(
                            source_type=source_type,
                            source_index=source_index,
                            source_card_index=source_card_index,
                            cards=[card],
                            destination_type="foundation",
                            destination_index=foundation_index,
                            stock_clicks=stock_clicks,
                        )
                    )

        for column_index in range(TABLEAU_COLUMNS):
            if source_type == "tableau" and source_index == column_index:
                continue
            if self.can_move_to_tableau([card], column_index):
                moves.append(
                    self.build_hint_move(
                        source_type=source_type,
                        source_index=source_index,
                        source_card_index=source_card_index,
                        cards=[card],
                        destination_type="tableau",
                        destination_index=column_index,
                        stock_clicks=stock_clicks,
                    )
                )

        return moves

    def build_hint_move(
        self,
        source_type: str,
        source_index: int,
        source_card_index: int,
        cards: list[Card],
        destination_type: str,
        destination_index: int,
        stock_clicks: int,
    ) -> HintMove:
        """Package move information and its human-readable hint text together."""
        description = self.describe_hint(
            source_type,
            source_index,
            cards,
            destination_type,
            destination_index,
            stock_clicks,
        )
        return HintMove(
            source_type=source_type,
            source_index=source_index,
            source_card_index=source_card_index,
            cards=list(cards),
            destination_type=destination_type,
            destination_index=destination_index,
            stock_clicks=stock_clicks,
            description=description,
        )

    # ------------------------------------------------------------------
    # Hint engine stage 4: player-facing descriptions
    # ------------------------------------------------------------------
    def describe_hint(
        self,
        source_type: str,
        source_index: int,
        cards: list[Card],
        destination_type: str,
        destination_index: int,
        stock_clicks: int,
    ) -> str:
        """Create the text shown when the player asks for a hint."""
        card_text = self.describe_cards(cards)
        target_text = self.describe_destination(destination_type, destination_index)

        if source_type == "future_waste":
            prefix = "Click the stock once" if stock_clicks == 1 else f"Click the stock {stock_clicks} times"
            return f"Hint: {prefix}, then move {card_text} to {target_text}."

        source_text = self.describe_source(source_type, source_index)
        return f"Hint: Move {card_text} from {source_text} to {target_text}."

    def describe_source(self, source_type: str, source_index: int) -> str:
        """Convert an internal source location into player-friendly text."""
        if source_type == "waste":
            return "the waste"
        if source_type == "foundation":
            suit_name = FOUNDATION_SUITS[source_index].capitalize()
            return f"the {suit_name} foundation"
        return f"tableau column {source_index + 1}"

    def describe_destination(self, destination_type: str, destination_index: int) -> str:
        """Convert an internal destination into player-friendly text."""
        if destination_type == "foundation":
            suit_name = FOUNDATION_SUITS[destination_index].capitalize()
            return f"the {suit_name} foundation"
        return f"tableau column {destination_index + 1}"

    def describe_cards(self, cards: list[Card]) -> str:
        """Describe either one card or the front card of a moving stack."""
        if len(cards) == 1:
            return cards[0].label()
        return f"{len(cards)} cards starting with {cards[0].label()}"

    # ------------------------------------------------------------------
    # Hint engine stage 3: ranking
    # ------------------------------------------------------------------
    def hint_sort_key(self, move: HintMove) -> tuple[int, int, int, int]:
        """Build the sort key that decides which hint move is shown.

        Python sorts tuples item by item, so this orders moves by priority
        first; ties are then broken by fewest stock clicks, and finally by
        pile index so the chosen hint stays stable instead of jumping around.
        """
        return (
            self.hint_priority(move),
            move.stock_clicks,
            move.source_index,
            move.destination_index,
        )

    def hint_priority(self, move: HintMove) -> int:
        """Assign a priority score to a move; the lower the number, the better.

        The hint system shows the move with the lowest priority number. The
        tiers below rank moves roughly from "always do this" (0) down to
        "only if nothing else helps" (90). Beginners can read this method as
        the game's built-in opinion on what a good next move looks like.
        """
        reveals_hidden = self.move_reveals_hidden(move)
        moving_card = move.cards[0]

        # Moves that need future stock clicks are weak: they cost extra clicks,
        # so they rank well below anything that can be played right now.
        if move.source_type == "future_waste":
            if move.destination_type == "foundation":
                return 50 + move.stock_clicks
            return 60 + move.stock_clicks

        # Taking a card back off a foundation is almost never useful.
        if move.source_type == "foundation":
            return 90

        # Sending a card up to a foundation is good, and best when it also
        # uncovers a face-down card that was sitting underneath it.
        if move.destination_type == "foundation":
            if reveals_hidden:
                return 5
            if move.source_type == "waste":
                return 10
            return 15

        # The single most valuable tableau move: it flips a face-down card.
        if reveals_hidden:
            return 0

        # Playing the waste card frees the waste for the next draw.
        if move.source_type == "waste":
            return 20

        # Moving a King into an empty column opens that column for later use.
        if not self.tableau[move.destination_index] and moving_card.rank == 13:
            return 25

        # Any other legal tableau-to-tableau shuffle is the lowest useful tier.
        return 30

    def move_reveals_hidden(self, move: HintMove) -> bool:
        """True when moving this stack would expose a face-down tableau card."""
        if move.source_type != "tableau":
            return False
        if move.source_card_index == 0:
            return False
        return not self.tableau[move.source_index][move.source_card_index - 1].face_up

    # ------------------------------------------------------------------
    # Hint engine stage 2: meaningfulness filters
    # ------------------------------------------------------------------
    def is_meaningful_move(self, move: HintMove) -> bool:
        """
        Filter out technically legal moves that are strategically pointless.

        The user asked the hint system and loss detection to ignore several
        "to and fro" moves, so this method applies those custom filters.
        """
        if self.is_tableau_ace_diversion(move):
            return False
        if self.is_empty_king_shuffle(move):
            return False
        if self.is_redundant_tableau_transfer(move):
            return False
        return not self.is_unproductive_foundation_return(move)

    def is_tableau_ace_diversion(self, move: HintMove) -> bool:
        """Never prefer moving a tableau Ace to another tableau."""
        if move.source_type != "tableau" or move.destination_type != "tableau":
            return False
        return len(move.cards) == 1 and move.cards[0].rank == 1

    def is_empty_king_shuffle(self, move: HintMove) -> bool:
        """Ignore moving a full king-starting pile between empty columns."""
        if move.source_type != "tableau" or move.destination_type != "tableau":
            return False
        if move.source_card_index != 0:
            return False
        if move.cards[0].rank != 13:
            return False
        return len(self.tableau[move.destination_index]) == 0

    def is_redundant_tableau_transfer(self, move: HintMove) -> bool:
        """Wrapper for testing whether a tableau-to-tableau move is pointless."""
        if move.source_type != "tableau" or move.destination_type != "tableau":
            return False
        return self.is_redundant_tableau_transfer_on_board(
            move.source_index,
            move.source_card_index,
            move.cards,
            move.destination_index,
            self.tableau,
            self.foundations,
        )

    def is_redundant_tableau_transfer_on_board(
        self,
        source_index: int,
        source_card_index: int,
        cards: list[Card],
        destination_index: int,
        tableau: list[list[Card]],
        foundations: list[list[Card]],
    ) -> bool:
        """
        Detect tableau shuffles that do not create new opportunities.

        Example: moving a red 6 onto one black 7 when another identical black 7
        is available and neither resulting top card can immediately advance to a
        foundation.
        """
        if self.move_reveals_hidden_on_board(source_index, source_card_index, tableau):
            return False

        destination_column = tableau[destination_index]
        if not destination_column:
            return False

        if self.is_equivalent_anchor_loop_on_board(
            source_index, source_card_index, destination_index, tableau, foundations
        ):
            return True

        destination_top = destination_column[-1]
        equivalent_destinations = []

        for column_index, column in enumerate(tableau):
            if column_index == source_index or not column:
                continue
            top_card = column[-1]
            if top_card.rank != destination_top.rank or top_card.color() != destination_top.color():
                continue
            if self.can_move_to_tableau_cards(cards, column):
                equivalent_destinations.append(column_index)

        if len(equivalent_destinations) < 2:
            return False

        return not any(
            self.tableau_top_can_move_to_foundation_on_board(column_index, tableau, foundations)
            for column_index in equivalent_destinations
        )

    def is_equivalent_anchor_loop(self, move: HintMove) -> bool:
        """Wrapper for detecting reversible stack swaps between equal anchors."""
        return self.is_equivalent_anchor_loop_on_board(
            move.source_index,
            move.source_card_index,
            move.destination_index,
            self.tableau,
            self.foundations,
        )

    def is_equivalent_anchor_loop_on_board(
        self,
        source_index: int,
        source_card_index: int,
        destination_index: int,
        tableau: list[list[Card]],
        foundations: list[list[Card]],
    ) -> bool:
        """
        Detect moving a tableau stack from one equivalent anchor to another.

        Example:
        - source column: K black, Q red, J black
        - destination column: K black

        Moving the Q-J stack between the two kings is just a reversible shuffle
        unless exposing the source king creates a foundation move.
        """
        if source_card_index <= 0:
            return False

        source_column = tableau[source_index]
        source_anchor = source_column[source_card_index - 1]
        destination_anchor = tableau[destination_index][-1]

        if not self.cards_are_equivalent_anchors(source_anchor, destination_anchor):
            return False

        if self.card_can_move_to_any_foundation_in_piles(source_anchor, foundations):
            return False

        return not self.card_can_move_to_any_foundation_in_piles(destination_anchor, foundations)

    def cards_are_equivalent_anchors(self, first: Card, second: Card) -> bool:
        """Two anchors are equivalent when rank and color match."""
        return first.rank == second.rank and first.color() == second.color()

    def tableau_top_can_move_to_foundation(self, column_index: int) -> bool:
        """Convenience wrapper for checking one real tableau column."""
        return self.tableau_top_can_move_to_foundation_on_board(
            column_index, self.tableau, self.foundations
        )

    def tableau_top_can_move_to_foundation_on_board(
        self,
        column_index: int,
        tableau: list[list[Card]],
        foundations: list[list[Card]],
    ) -> bool:
        """Check whether the top tableau card can move to any foundation."""
        column = tableau[column_index]
        if not column or not column[-1].face_up:
            return False
        return self.card_can_move_to_any_foundation_in_piles(column[-1], foundations)

    def card_can_move_to_any_foundation(self, card: Card) -> bool:
        """Convenience wrapper for the real foundation piles."""
        return self.card_can_move_to_any_foundation_in_piles(card, self.foundations)

    def card_can_move_to_any_foundation_in_piles(
        self, card: Card, foundations: list[list[Card]]
    ) -> bool:
        """Return True if this card fits on at least one foundation pile."""
        return any(
            self.can_move_to_foundation_piles(card, foundation_index, foundations)
            for foundation_index in range(FOUNDATION_COUNT)
        )

    def move_reveals_hidden_on_board(
        self,
        source_index: int,
        source_card_index: int,
        tableau: list[list[Card]],
    ) -> bool:
        """Version of the reveal check that works on a simulated tableau."""
        if source_card_index == 0:
            return False
        return not tableau[source_index][source_card_index - 1].face_up

    def is_unproductive_foundation_return(self, move: HintMove) -> bool:
        """Ignore foundation-to-tableau moves unless they unlock real progress."""
        if move.source_type != "foundation" or move.destination_type != "tableau":
            return False
        return not self.foundation_return_enables_tableau_follow_up(move)

    def is_meaningful_tableau_transfer_on_board(
        self,
        source_index: int,
        source_card_index: int,
        cards: list[Card],
        destination_index: int,
        tableau: list[list[Card]],
        foundations: list[list[Card]],
    ) -> bool:
        """Check whether a simulated tableau transfer would still be useful."""
        if source_index == destination_index:
            return False
        if not self.can_move_to_tableau_cards(cards, tableau[destination_index]):
            return False
        if source_card_index == 0 and cards[0].rank == 13 and not tableau[destination_index]:
            return False
        return not self.is_redundant_tableau_transfer_on_board(
            source_index, source_card_index, cards, destination_index, tableau, foundations
        )

    def foundation_return_enables_tableau_follow_up(self, move: HintMove) -> bool:
        """
        Allow a foundation return only if it enables a new useful tableau move.

        This prevents hints like "pull J♥ down from foundation" unless doing so
        immediately creates some concrete new opportunity on the tableau.
        """
        # Remember the destination column before the foundation card is added.
        destination_before = list(self.tableau[move.destination_index])

        # Build simulated board states that represent the move after it happens.
        tableau_after = [list(column) for column in self.tableau]
        tableau_after[move.destination_index] = destination_before + list(move.cards)

        foundations_after = [list(pile) for pile in self.foundations]
        foundations_after[move.source_index] = foundations_after[move.source_index][:-1]

        for column_index, column in enumerate(tableau_after):
            if column_index == move.destination_index:
                continue

            for card_index, card in enumerate(column):
                if not card.face_up:
                    continue

                selection = self.selection_from_tableau_cards(tableau_after, column_index, card_index)
                if selection is None:
                    continue

                # We only care about moves that become possible because of the
                # returned foundation card, not moves that were already legal.
                can_move_before = self.can_move_to_tableau_cards(selection.cards, destination_before)
                can_move_after = self.can_move_to_tableau_cards(
                    selection.cards, tableau_after[move.destination_index]
                )
                if can_move_after and not can_move_before and self.is_meaningful_tableau_transfer_on_board(
                    column_index,
                    card_index,
                    selection.cards,
                    move.destination_index,
                    tableau_after,
                    foundations_after,
                ) and self.follow_up_creates_concrete_progress(
                    column_index,
                    card_index,
                    selection.cards,
                    tableau_after,
                    foundations_after,
                ):
                    return True

        return False

    def follow_up_creates_concrete_progress(
        self,
        source_index: int,
        source_card_index: int,
        cards: list[Card],
        tableau: list[list[Card]],
        foundations: list[list[Card]],
    ) -> bool:
        """Check whether a follow-up move creates immediate visible progress."""
        if self.move_reveals_hidden_on_board(source_index, source_card_index, tableau):
            return True

        # If the moved-away source exposes a card that can now go to foundation,
        # that also counts as concrete progress.
        source_after = list(tableau[source_index])
        del source_after[source_card_index:]

        return bool(source_after and self.card_can_move_to_any_foundation_in_piles(source_after[-1], foundations))


class SolitaireApp:
    """tkinter user interface that draws the board and reacts to clicks."""

    def __init__(self, root: tk.Tk) -> None:
        """Create the window, game model, and all UI state."""
        self.root = root
        self.root.title("Klondike Solitaire")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(False, False)
        self.root.configure(bg=BACKGROUND_COLOR)

        # Save data must live in a stable per-user folder. A PyInstaller
        # --onefile build unpacks into a temporary folder that Windows deletes
        # when the .exe closes, so a save written next to __file__ is lost every
        # session. The icon, by contrast, is a bundled read-only resource.
        high_score_path = os.path.join(_user_save_dir(), "solitaire_high_score.json")
        icon_path = _resource_path("solitaire_icon.ico")

        # Load the custom window icon when it is available.
        if os.path.exists(icon_path):
            with contextlib.suppress(tk.TclError):
                self.root.iconbitmap(icon_path)

        # Create the game logic object.
        self.game = KlondikeGame(high_score_path)

        # Selection/hint/animation state belongs to the UI layer.
        self.selection: Selection | None = None
        self.hint_move: HintMove | None = None
        self.animation: AnimationState | None = None
        self.auto_solving = False
        self.auto_solve_seen_states: set = set()
        self.history: list[dict] = []

        # tkinter StringVar objects let labels update automatically.
        self.score_var = tk.StringVar()
        self.high_score_var = tk.StringVar()
        self.time_var = tk.StringVar()
        self.stats_var = tk.StringVar()
        self.status_var = tk.StringVar(
            value="Click a face-up card to select it, then click a destination pile."
        )

        self.started_at = time.time()
        self.elapsed_seconds = 0

        # Build widgets, connect shortcuts, and paint the first board.
        self.build_ui()
        self.root.bind("<Control-z>", self.undo_last_action)
        self.root.bind("<Control-Z>", self.undo_last_action)
        # Ctrl+N starts a new game and Ctrl+H asks for a hint. The lambdas
        # absorb the key-event object, which these methods do not expect.
        self.root.bind("<Control-n>", lambda event: self.start_new_game())
        self.root.bind("<Control-N>", lambda event: self.start_new_game())
        self.root.bind("<Control-h>", lambda event: self.show_hint())
        self.root.bind("<Control-H>", lambda event: self.show_hint())
        self.refresh_header_labels()
        self.redraw()
        self.schedule_clock_update()
        self.check_for_loss()

    def build_ui(self) -> None:
        """Create the labels, buttons, status text, and drawing canvas."""
        top_frame = tk.Frame(self.root, bg=BACKGROUND_COLOR, padx=12, pady=10)
        top_frame.pack(fill="x")

        # `Any` values let the same dict splat into every tk.Label call below
        # without fighting tkinter's very specific per-option stub types.
        label_style: dict[str, Any] = {
            "bg": BACKGROUND_COLOR,
            "fg": "white",
            "font": ("Arial", 12, "bold"),
        }

        tk.Label(top_frame, textvariable=self.score_var, **label_style).pack(side="left", padx=(0, 14))
        tk.Label(top_frame, textvariable=self.high_score_var, **label_style).pack(side="left", padx=(0, 14))
        tk.Label(top_frame, textvariable=self.time_var, **label_style).pack(side="left", padx=(0, 14))
        tk.Label(top_frame, textvariable=self.stats_var, **label_style).pack(side="left")

        button_frame = tk.Frame(top_frame, bg=BACKGROUND_COLOR)
        button_frame.pack(side="right")

        tk.Button(
            button_frame,
            text="Undo",
            command=self.undo_last_action,
            font=("Arial", 11, "bold"),
            padx=12,
            pady=4,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            button_frame,
            text="Hint",
            command=self.show_hint,
            font=("Arial", 11, "bold"),
            padx=12,
            pady=4,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            button_frame,
            text="New Game",
            command=self.start_new_game,
            font=("Arial", 11, "bold"),
            padx=12,
            pady=4,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            button_frame,
            text="Help",
            command=self.show_help,
            font=("Arial", 11, "bold"),
            padx=12,
            pady=4,
        ).pack(side="left")

        tk.Label(
            self.root,
            textvariable=self.status_var,
            bg=BACKGROUND_COLOR,
            fg="white",
            anchor="w",
            padx=14,
            font=("Arial", 10),
        ).pack(fill="x")

        self.canvas = tk.Canvas(
            self.root,
            width=WINDOW_WIDTH,
            height=CANVAS_HEIGHT,
            bg=BACKGROUND_COLOR,
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Double-Button-1>", self.on_canvas_double_click)

    def show_help(self) -> None:
        """Show a dialog explaining the objective, controls, and scoring."""
        messagebox.showinfo(
            "How to Play",
            "Objective\n"
            "Move all 52 cards onto the four foundation piles. Each foundation "
            "builds up in one suit from Ace to King.\n\n"
            "Moving cards\n"
            "Click a face-up card to select it, then click where it should go. "
            "Tableau columns build downward in alternating colors. Only a King, "
            "or a run led by a King, can move onto an empty column.\n\n"
            "Stock and waste\n"
            "Click the stock pile to draw a card onto the waste pile. When the "
            "stock is empty, click it again to recycle the waste back into it.\n\n"
            "Controls\n"
            "Undo button or Ctrl+Z  -  take back the last move\n"
            "Hint button  -  highlight a useful move\n"
            "New Game button  -  deal a fresh game\n\n"
            "Scoring\n"
            "+10 for every card sent to a foundation, +5 for revealing a "
            "face-down card, plus a time bonus and a 100-point win bonus for "
            "finishing the game.",
            parent=self.root,
        )

    def schedule_clock_update(self) -> None:
        """Refresh the visible timer a few times per second."""
        if not self.game.won and not self.game.lost:
            self.elapsed_seconds = int(time.time() - self.started_at)
        self.time_var.set(f"Time: {self.format_time(self.elapsed_seconds)}")

        # Ask tkinter to call this method again later.
        self.root.after(250, self.schedule_clock_update)

    def start_new_game(self) -> None:
        """Deal a fresh game and clear all UI-only state."""
        # Guard an in-progress game: a non-empty history with no win/loss yet
        # means real moves would be discarded. Covers the button and Ctrl+N.
        if self.history and not self.game.won and not self.game.lost and not messagebox.askyesno(
                "New Game",
                "Start a new game? Your current progress will be lost."):
            return
        self.game.new_game()
        self.selection = None
        self.hint_move = None
        self.animation = None
        self.auto_solving = False
        self.auto_solve_seen_states = set()
        self.history = []
        self.started_at = time.time()
        self.elapsed_seconds = 0
        self.status_var.set("Started a new game.")
        self.refresh_header_labels()
        self.redraw()
        self.check_for_loss()

    def refresh_header_labels(self) -> None:
        """Copy the latest score/statistics/timer values into the top labels."""
        self.score_var.set(f"Score: {self.game.score}")
        self.high_score_var.set(f"High Score: {self.game.high_score}")
        self.time_var.set(f"Time: {self.format_time(self.elapsed_seconds)}")
        self.stats_var.set(f"Stats: W {self.game.wins} / L {self.game.losses}")

    def capture_history_state(self) -> dict:
        """Create one Undo snapshot before a state-changing action."""
        return {"game": self.game.snapshot()}

    def remember_history_state(self, history_state: dict) -> None:
        """Push a snapshot onto the Undo stack and trim old entries."""
        self.history.append(history_state)
        if len(self.history) > UNDO_HISTORY_LIMIT:
            self.history = self.history[-UNDO_HISTORY_LIMIT:]

    def undo_last_action(self, event: tk.Event | None = None) -> None:
        """Restore the most recent saved snapshot."""
        if self.animation is not None:
            self.status_var.set("Please wait for the card animation to finish.")
            return

        if not self.history:
            self.status_var.set("There is nothing to undo yet.")
            return

        history_state = self.history.pop()
        self.auto_solving = False
        self.auto_solve_seen_states = set()
        self.selection = None
        self.hint_move = None
        self.animation = None
        self.game.restore_snapshot(history_state["game"])
        if not self.game.won and not self.game.lost:
            # Restart the live timer from the already elapsed number of seconds.
            self.started_at = time.time() - self.elapsed_seconds
        self.refresh_header_labels()
        self.status_var.set("Undid the previous move.")
        self.redraw()
        if not self.game.won and not self.game.lost:
            self.check_for_loss()

    def on_canvas_click(self, event: tk.Event) -> None:
        """Main mouse handler: decide which pile the player clicked."""
        if self.animation is not None:
            self.status_var.set("Please wait for the card animation to finish.")
            return

        if self.auto_solving:
            self.status_var.set("Auto-solve is running.")
            return

        if self.game.won:
            self.status_var.set("You already won. Click New Game to play again.")
            return

        if self.game.lost:
            self.status_var.set("No more productive moves remain. Click New Game to try again.")
            return

        x, y = event.x, event.y

        if self.point_in_rect(x, y, self.stock_rect()):
            # Clicking the stock draws a card or recycles the waste pile.
            self.selection = None
            self.hint_move = None
            history_state = self.capture_history_state()
            action = self.game.draw_from_stock()
            if action in ("draw", "reset"):
                # Only keep an undo snapshot if the click actually changed something.
                self.remember_history_state(history_state)
            if action == "draw":
                self.status_var.set("Drew a card from the stock.")
            elif action == "reset":
                self.status_var.set("Recycled the waste pile back into the stock.")
            else:
                self.status_var.set("There are no cards left to draw.")
            self.refresh_header_labels()
            self.redraw()
            if self.should_auto_solve():
                self.begin_auto_solve()
            else:
                self.check_for_loss()
            return

        if self.point_in_rect(x, y, self.waste_rect()) and self.game.waste:
            self.handle_waste_click()
            return

        # Check each foundation rectangle.
        for foundation_index in range(FOUNDATION_COUNT):
            if self.point_in_rect(x, y, self.foundation_rect(foundation_index)):
                self.handle_foundation_click(foundation_index)
                return

        # If it was not a top-row pile, see whether it hit the tableau.
        column_index, card_index = self.find_tableau_hit(x, y)
        if column_index is not None:
            self.handle_tableau_click(column_index, card_index)
            return

        if self.selection is not None:
            self.selection = None
            self.status_var.set("Selection cleared.")
            self.redraw()

    def on_canvas_double_click(self, event: tk.Event) -> None:
        """Double-click a card to send it straight to a foundation if it fits.

        This is a convenience shortcut: instead of selecting the card and then
        clicking the foundation pile, one double-click does both at once.
        """
        # Ignore double-clicks while the board is busy or the game is finished.
        if self.animation is not None or self.auto_solving:
            return
        if self.game.won or self.game.lost:
            return

        selection = self._selection_under_point(event.x, event.y)
        # Only a single face-up card can ever move onto a foundation.
        if selection is None or len(selection.cards) != 1:
            return

        card = selection.cards[0]
        for foundation_index in range(FOUNDATION_COUNT):
            if self.game.can_move_to_foundation(card, foundation_index):
                suit_name = FOUNDATION_SUITS[foundation_index].capitalize()
                self.selection = None
                self.hint_move = None
                self.animate_move(
                    selection=selection,
                    destination_type="foundation",
                    destination_index=foundation_index,
                    completion_message=f"Moved {card.label()} to the {suit_name} foundation.",
                )
                return

    def _selection_under_point(self, x: int, y: int) -> Selection | None:
        """Return a Selection for the card under a click, or None if there is none.

        Used by the double-click shortcut to find which card was clicked. Only
        the waste pile and the tableau columns are checked, because those are
        the only places a card is ever picked up from to send to a foundation.
        """
        if self.point_in_rect(x, y, self.waste_rect()) and self.game.waste:
            return self.game.selection_from_waste()
        column_index, card_index = self.find_tableau_hit(x, y)
        if column_index is not None and card_index is not None:
            return self.game.selection_from_tableau(column_index, card_index)
        return None

    def handle_waste_click(self) -> None:
        """Select or deselect the top waste card."""
        waste_selection = self.game.selection_from_waste()
        if waste_selection is None:
            return
        if self.is_same_selection(waste_selection):
            self.selection = None
            self.status_var.set("Selection cleared.")
        else:
            self.selection = waste_selection
            self.status_var.set(f"Selected {waste_selection.cards[0].label()} from the waste.")
        self.redraw()

    def handle_foundation_click(self, foundation_index: int) -> None:
        """Either select a foundation card or place the current selection there."""
        if self.selection is not None:
            current_selection = self.selection
            moved_card_label = self.describe_cards(current_selection.cards)
            suit_name = FOUNDATION_SUITS[foundation_index].capitalize()

            if self.can_place_selection_on_foundation(current_selection, foundation_index):
                # Clear selection immediately so the UI does not show stale highlights.
                self.selection = None
                self.hint_move = None
                self.animate_move(
                    selection=current_selection,
                    destination_type="foundation",
                    destination_index=foundation_index,
                    completion_message=f"Moved {moved_card_label} to the {suit_name} foundation.",
                )
                return

            same_foundation = (
                current_selection.source_type == "foundation"
                and current_selection.pile_index == foundation_index
            )
            if same_foundation:
                self.selection = None
                self.status_var.set("Selection cleared.")
            else:
                self.status_var.set("That move does not fit the foundation rules.")
            self.redraw()
            return

        foundation_selection = self.game.selection_from_foundation(foundation_index)
        if foundation_selection is not None:
            self.selection = foundation_selection
            self.status_var.set(
                f"Selected {foundation_selection.cards[0].label()} from the foundation."
            )
            self.redraw()

    def handle_tableau_click(self, column_index: int, card_index: int | None) -> None:
        """Handle selection, deselection, and placement inside the tableau."""
        if self.selection is not None:
            current_selection = self.selection
            moved_label = self.describe_cards(current_selection.cards)
            if self.can_place_selection_on_tableau(current_selection, column_index):
                self.selection = None
                self.hint_move = None
                self.animate_move(
                    selection=current_selection,
                    destination_type="tableau",
                    destination_index=column_index,
                    completion_message=f"Moved {moved_label} to tableau column {column_index + 1}.",
                )
                return

            if (
                current_selection.source_type == "tableau"
                and current_selection.pile_index == column_index
                and current_selection.card_index == card_index
            ):
                self.selection = None
                self.status_var.set("Selection cleared.")
                self.redraw()
                return

            new_selection = None
            if card_index is not None:
                new_selection = self.game.selection_from_tableau(column_index, card_index)

            if new_selection is not None:
                self.selection = new_selection
                self.status_var.set(
                    f"Selected {self.describe_cards(new_selection.cards)} from tableau column {column_index + 1}."
                )
            else:
                self.status_var.set("That move does not fit the tableau rules.")
            self.redraw()
            return

        if card_index is None:
            # Clicking empty space in a tableau column does nothing if nothing is selected.
            return

        new_selection = self.game.selection_from_tableau(column_index, card_index)
        if new_selection is not None:
            self.selection = new_selection
            self.status_var.set(
                f"Selected {self.describe_cards(new_selection.cards)} from tableau column {column_index + 1}."
            )
        else:
            self.status_var.set("Only face-up cards in a valid stack can be selected.")
        self.redraw()

    def show_hint(self) -> None:
        """Ask the model for the best current move and highlight it."""
        if self.animation is not None:
            self.status_var.set("Please wait for the current animation to finish.")
            return

        if self.auto_solving:
            self.status_var.set("Auto-solve is already running.")
            return

        if self.game.won:
            self.status_var.set("You already won. Click New Game to play again.")
            return

        if self.game.lost:
            self.status_var.set("This game is already over. Click New Game to try again.")
            return

        best_move = self.game.find_best_move()
        if best_move is None:
            self.end_game_as_loss()
            return

        self.hint_move = best_move
        self.selection = self.game.selection_from_hint(best_move)
        self.status_var.set(best_move.description)
        self.redraw()

    def can_place_selection_on_tableau(self, selection: Selection, column_index: int) -> bool:
        """UI wrapper around the model's tableau move rule."""
        if selection.source_type == "tableau" and selection.pile_index == column_index:
            return False
        return self.game.can_move_to_tableau(selection.cards, column_index)

    def can_place_selection_on_foundation(
        self, selection: Selection, foundation_index: int
    ) -> bool:
        """UI wrapper around the model's foundation move rule."""
        if len(selection.cards) != 1:
            return False
        if selection.source_type == "foundation" and selection.pile_index == foundation_index:
            return False
        return self.game.can_move_to_foundation(selection.cards[0], foundation_index)

    def animate_move(
        self,
        selection: Selection,
        destination_type: str,
        destination_index: int,
        completion_message: str,
    ) -> None:
        """Move cards in the model, then animate them on screen."""
        start_positions = self.selection_positions(selection)
        end_positions = self.destination_positions(selection.cards, destination_type, destination_index)
        history_state = self.capture_history_state()

        # Update the model immediately, then draw the animation over the new board.
        if destination_type == "foundation":
            moved = self.game.move_selection_to_foundation(selection, destination_index)
        else:
            moved = self.game.move_selection_to_tableau(selection, destination_index)

        if not moved:
            self.status_var.set("That move is not legal.")
            self.redraw()
            return

        self.remember_history_state(history_state)
        self.animation = AnimationState(
            cards=list(selection.cards),
            start_positions=start_positions,
            end_positions=end_positions,
            destination_type=destination_type,
            destination_index=destination_index,
            completion_message=completion_message,
        )
        self.refresh_header_labels()
        self.status_var.set("Moving cards...")
        self.redraw()
        self.root.after(ANIMATION_DELAY_MS, self.advance_animation)

    def advance_animation(self) -> None:
        """Advance one frame of the in-progress card animation."""
        if self.animation is None:
            return

        self.animation.frame += 1
        if self.animation.frame >= self.animation.steps:
            completion_message = self.animation.completion_message
            self.animation = None
            self.status_var.set(completion_message)
            self.refresh_header_labels()
            self.redraw()
            self.finish_turn()
            return

        self.redraw()
        self.root.after(ANIMATION_DELAY_MS, self.advance_animation)

    def finish_turn(self) -> None:
        """Run end-of-turn checks after a move or animation finishes."""
        if self.game.has_won() and not self.game.won:
            self.end_game_as_win()
            return
        if self.auto_solving:
            self.root.after(120, self.advance_auto_solve)
            return
        if self.should_auto_solve():
            self.begin_auto_solve()
            return
        self.check_for_loss()

    def should_auto_solve(self) -> bool:
        """Auto-solve starts only after every tableau card is face up."""
        return (
            not self.auto_solving
            and not self.game.won
            and not self.game.lost
            and self.game.all_tableau_cards_face_up()
        )

    def begin_auto_solve(self) -> None:
        """Switch the UI into auto-solve mode."""
        if self.auto_solving or self.game.won or self.game.lost:
            return
        self.auto_solving = True
        self.auto_solve_seen_states = set()
        self.selection = None
        self.hint_move = None
        self.status_var.set("All tableau cards are face up. Auto-solving...")
        self.redraw()
        self.root.after(140, self.advance_auto_solve)

    def advance_auto_solve(self) -> None:
        """Perform one auto-solve step, then schedule the next one."""
        if not self.auto_solving or self.game.won or self.game.lost:
            return
        if self.animation is not None:
            return

        next_move = self.game.next_auto_foundation_move()
        if next_move is not None:
            # If a direct foundation move exists, animate that before anything else.
            self.auto_solve_seen_states.clear()
            selection, foundation_index = next_move
            suit_name = FOUNDATION_SUITS[foundation_index].capitalize()
            self.animate_move(
                selection=selection,
                destination_type="foundation",
                destination_index=foundation_index,
                completion_message=(
                    f"Auto-solve moved {selection.cards[0].label()} to the {suit_name} foundation."
                ),
            )
            return

        state_key = self.auto_solve_state_key()
        if state_key in self.auto_solve_seen_states:
            # Repeating the same stock/waste cycle means auto-solve is stuck.
            self.auto_solving = False
            self.status_var.set("Auto-solve stopped because it reached a repeated stock cycle.")
            self.check_for_loss()
            return

        self.auto_solve_seen_states.add(state_key)
        history_state = self.capture_history_state()
        stock_action = self.game.draw_from_stock()
        if stock_action in ("draw", "reset"):
            # Auto-solve stock clicks should also be undoable.
            self.remember_history_state(history_state)
            if stock_action == "draw":
                self.status_var.set("Auto-solve is drawing from the stock.")
            else:
                self.status_var.set("Auto-solve is recycling the stock.")
            self.refresh_header_labels()
            self.redraw()
            self.root.after(140, self.advance_auto_solve)
            return

        self.auto_solving = False
        if self.game.has_won():
            self.end_game_as_win()
            return
        self.status_var.set("Auto-solve stopped because no direct foundation move is available.")
        self.check_for_loss()

    def auto_solve_state_key(self) -> tuple:
        """Build a hashable summary of the board for loop detection.

        Auto-solve cycles the stock looking for cards it can send to a
        foundation. If a full stock cycle finishes without making progress,
        every pile is in exactly the situation it was in last time -- which
        means the next cycle will do the same nothing and we should give up.
        Bundling stock, waste, foundations and tableau into one tuple gives a
        single value we can drop in a `set` and check against on each step.
        """
        return (
            tuple((card.suit, card.rank) for card in self.game.stock),
            tuple((card.suit, card.rank) for card in self.game.waste),
            tuple(tuple((card.suit, card.rank) for card in pile) for pile in self.game.foundations),
            tuple(tuple((card.suit, card.rank) for card in column) for column in self.game.tableau),
        )

    def check_for_loss(self) -> None:
        """End the game if no meaningful move remains."""
        if self.game.won or self.game.lost:
            return
        if self.game.find_best_move() is None:
            self.end_game_as_loss()

    def end_game_as_win(self) -> None:
        """Freeze the game, apply bonuses, update stats, and celebrate the win."""
        self.game.won = True
        self.auto_solving = False
        self.auto_solve_seen_states = set()

        # The faster the player finishes, the bigger the bonus.
        time_bonus = self.calculate_time_bonus()
        self.game.add_score(self.game.WIN_BONUS)
        self.game.add_score(time_bonus)
        self.game.record_win()
        self.selection = None
        self.hint_move = None
        self.refresh_header_labels()
        self.status_var.set(
            f"You win! Time: {self.format_time(self.elapsed_seconds)}. Time bonus: {time_bonus}."
        )
        self.redraw()

        # Capture the summary values now, then play a short confetti
        # celebration; the win dialog appears once the animation finishes.
        final_score = self.game.score
        elapsed = self.format_time(self.elapsed_seconds)
        self._play_win_celebration(
            lambda: messagebox.showinfo(
                "You Win!",
                (
                    f"Congratulations! You won with a score of {final_score}.\n"
                    f"Time: {elapsed}\n"
                    f"Time bonus: {time_bonus}"
                ),
            )
        )

    def _play_win_celebration(self, on_finished) -> None:
        """Rain confetti and show a banner, then run `on_finished` (the dialog).

        tkinter has no game loop, so the animation is driven by `root.after`:
        each tick nudges every confetti piece downward and schedules the next
        tick, until the celebration has run for its fixed number of frames.
        """
        confetti_colors = ["#FFD24D", "#FF6B6B", "#4DD0E1", "#A5D6A7", "#CE93D8", "#FFFFFF"]
        pieces = []
        for _ in range(60):
            piece_x = random.randint(0, WINDOW_WIDTH)
            piece_y = random.randint(-CANVAS_HEIGHT, 0)
            size = random.randint(6, 13)
            item = self.canvas.create_rectangle(
                piece_x,
                piece_y,
                piece_x + size,
                piece_y + size,
                fill=random.choice(confetti_colors),
                outline="",
                tags="celebration",
            )
            # Each piece drifts sideways slightly while falling at its own speed.
            pieces.append({
                "item": item,
                "vx": random.uniform(-2.0, 2.0),
                "vy": random.uniform(6.0, 13.0),
            })

        # A bold banner across the upper third of the board.
        self.canvas.create_text(
            WINDOW_WIDTH / 2,
            CANVAS_HEIGHT / 3,
            text="YOU WIN!",
            fill="#FFD24D",
            font=("Arial", 56, "bold"),
            tags="celebration",
        )

        # A one-item list so the nested `step` function can change the counter.
        frames_left = [96]

        def step() -> None:
            for piece in pieces:
                self.canvas.move(piece["item"], piece["vx"], piece["vy"])
            frames_left[0] -= 1
            if frames_left[0] > 0:
                self.root.after(ANIMATION_DELAY_MS, step)
            else:
                # Clear the celebration art, then hand control to the dialog.
                self.canvas.delete("celebration")
                on_finished()

        step()

    def end_game_as_loss(self) -> None:
        """Freeze the game, record the loss, and show the final result."""
        self.game.lost = True
        self.auto_solving = False
        self.auto_solve_seen_states = set()
        self.game.record_loss()
        self.selection = None
        self.hint_move = None
        self.refresh_header_labels()
        self.redraw()
        self.status_var.set("No more productive moves remain. You lost this game.")
        messagebox.showinfo(
            "Game Over",
            (
                "No more productive moves remain.\n"
                f"Final score: {self.game.score}\n"
                f"Time played: {self.format_time(self.elapsed_seconds)}"
            ),
        )

    def calculate_time_bonus(self) -> int:
        """Convert elapsed time into a simple decreasing bonus."""
        return max(0, self.game.TIME_BONUS_CAP - self.elapsed_seconds)

    def redraw(self) -> None:
        """Repaint the entire canvas from scratch."""
        self.canvas.delete("all")
        self.draw_table_surface()
        self.draw_top_labels()
        self.draw_stock()
        self.draw_waste()
        self.draw_foundations()
        self.draw_tableau()
        if self.animation is not None:
            self.draw_animation()

    def draw_table_surface(self) -> None:
        """Paint the green table background and a few simple accents."""
        self.canvas.create_rectangle(
            0,
            0,
            WINDOW_WIDTH,
            CANVAS_HEIGHT,
            fill=BACKGROUND_COLOR,
            outline="",
        )
        self.canvas.create_rectangle(
            0,
            0,
            WINDOW_WIDTH,
            150,
            fill=TABLE_TOP_COLOR,
            outline="",
        )
        self.canvas.create_oval(
            -120,
            220,
            270,
            600,
            fill=TABLE_ACCENT_DARK,
            outline="",
        )
        self.canvas.create_oval(
            500,
            120,
            940,
            520,
            fill=TABLE_ACCENT_LIGHT,
            outline="",
        )
        self.canvas.create_rectangle(
            0,
            150,
            WINDOW_WIDTH,
            154,
            fill="#0A6246",
            outline="",
        )

    def draw_top_labels(self) -> None:
        """Draw the text labels above stock, waste, and foundations."""
        self.canvas.create_text(
            self.stock_rect()[0] + CARD_WIDTH / 2,
            TOP_ROW_Y - 10,
            text="Stock",
            fill="white",
            font=("Arial", 10, "bold"),
        )
        self.canvas.create_text(
            self.waste_rect()[0] + CARD_WIDTH / 2,
            TOP_ROW_Y - 10,
            text="Waste",
            fill="white",
            font=("Arial", 10, "bold"),
        )

        for foundation_index, suit in enumerate(FOUNDATION_SUITS):
            x1, _, _, _ = self.foundation_rect(foundation_index)
            self.canvas.create_text(
                x1 + CARD_WIDTH / 2,
                TOP_ROW_Y - 10,
                text=f"{SUIT_SYMBOLS[suit]} Foundation",
                fill="white",
                font=("Arial", 10, "bold"),
            )

    def draw_stock(self) -> None:
        """Draw either the stock pile or an empty placeholder."""
        rect = self.stock_rect()
        if self.game.stock:
            self.draw_card(rect[0], rect[1], self.game.stock[-1], face_up=False, selected=False)
            self.canvas.create_text(
                rect[0] + CARD_WIDTH / 2,
                rect[3] + 12,
                text=f"{len(self.game.stock)} cards",
                fill="white",
                font=("Arial", 10),
            )
        else:
            self.draw_empty_pile(rect[0], rect[1], "Reset")

    def draw_waste(self) -> None:
        """Draw the top waste card or the empty waste placeholder."""
        rect = self.waste_rect()
        if self.game.waste:
            selected = self.selection is not None and self.selection.source_type == "waste"
            self.draw_card(rect[0], rect[1], self.game.waste[-1], face_up=True, selected=selected)
            self.canvas.create_text(
                rect[0] + CARD_WIDTH / 2,
                rect[3] + 12,
                text=f"{len(self.game.waste)} cards",
                fill="white",
                font=("Arial", 10),
            )
        else:
            self.draw_empty_pile(rect[0], rect[1], "Waste")

    def draw_foundations(self) -> None:
        """Draw all four foundation piles."""
        for foundation_index, suit in enumerate(FOUNDATION_SUITS):
            rect = self.foundation_rect(foundation_index)
            pile = self.visible_foundation_pile(foundation_index)
            hint_target = self.is_hint_destination("foundation", foundation_index)

            if pile:
                # A foundation card can be the yellow "selected" card (the
                # player lifted it) and/or the orange hinted destination.
                selected = (
                    self.selection is not None
                    and self.selection.source_type == "foundation"
                    and self.selection.pile_index == foundation_index
                )
                self.draw_card(
                    rect[0],
                    rect[1],
                    pile[-1],
                    face_up=True,
                    selected=selected,
                    hint=hint_target,
                )
            else:
                self.draw_empty_pile(
                    rect[0],
                    rect[1],
                    SUIT_SYMBOLS[suit],
                    SUIT_COLORS[suit],
                    highlighted=hint_target,
                )

    def draw_tableau(self) -> None:
        """Draw the seven tableau columns from left to right."""
        for column_index in range(TABLEAU_COLUMNS):
            x = self.tableau_x(column_index)
            column = self.visible_tableau_column(column_index)
            positions = self.tableau_positions_for_cards(column)
            hint_target = self.is_hint_destination("tableau", column_index)

            if not column:
                self.draw_empty_pile(x, TABLEAU_Y, "K", highlighted=hint_target)
                continue

            for card_index, card in enumerate(column):
                y = positions[card_index]
                selected = self.is_tableau_card_selected(column_index, card_index)
                # The orange hint highlight marks only the top card of the
                # destination column, kept separate from the yellow selection.
                hint = hint_target and card_index == len(column) - 1
                self.draw_card(
                    x,
                    y,
                    card,
                    face_up=card.face_up,
                    selected=selected,
                    hint=hint,
                )

    def rounded_rect(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        radius: float,
        **options,
    ) -> int:
        """Draw a rectangle with rounded corners and return its canvas id.

        tkinter's Canvas has no rounded-rectangle command, so we fake one with
        a polygon: each corner is listed as three close-together points, and
        asking tkinter to draw a smooth curve through them turns the sharp
        corners into gentle arcs while the straight edges stay straight.
        `**options` forwards styling such as `fill`, `outline`, and `width`.
        """
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1,
            x2, y1 + radius, x2, y2 - radius, x2, y2,
            x2 - radius, y2, x1 + radius, y2, x1, y2,
            x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, **options)

    def draw_empty_pile(
        self,
        x: int,
        y: int,
        text: str = "",
        text_color: str = EMPTY_OUTLINE,
        highlighted: bool = False,
    ) -> None:
        """Draw an outlined placeholder where an empty pile sits."""
        outline_color = HINT_COLOR if highlighted else EMPTY_OUTLINE
        width = 3 if highlighted else 2
        self.rounded_rect(
            x,
            y,
            x + CARD_WIDTH,
            y + CARD_HEIGHT,
            10,
            fill=PLACEHOLDER_FILL,
            outline=outline_color,
            width=width,
            dash=(6, 3),
        )
        if text:
            self.canvas.create_text(
                x + CARD_WIDTH / 2,
                y + CARD_HEIGHT / 2,
                text=text,
                fill=text_color,
                font=("Arial", 20, "bold"),
            )

    def draw_card(
        self,
        x: float,
        y: float,
        card: Card,
        face_up: bool,
        selected: bool,
        hint: bool = False,
    ) -> None:
        """Draw one card face or card back.

        `selected` highlights the card the player has picked up (yellow);
        `hint` highlights a destination the hint system suggests (orange).
        Keeping the two colours separate makes the board easier to read.
        """
        if hint:
            outline_color = HINT_COLOR
            outline_width = 4
        elif selected:
            outline_color = HIGHLIGHT_COLOR
            outline_width = 4
        else:
            outline_color = CARD_OUTLINE
            outline_width = 2

        # Draw the shadow first so the card appears to sit on top of it.
        self.draw_card_shadow(x, y)

        if face_up:
            # Outer white card body with gently rounded corners.
            self.rounded_rect(
                x,
                y,
                x + CARD_WIDTH,
                y + CARD_HEIGHT,
                10,
                fill=CARD_FILL,
                outline=outline_color,
                width=outline_width,
            )

            # Inner border adds a little visual polish (no fill, just an edge).
            self.rounded_rect(
                x + 4,
                y + 4,
                x + CARD_WIDTH - 4,
                y + CARD_HEIGHT - 4,
                7,
                fill="",
                outline="#EFE7D9",
                width=1,
            )

            text_color = SUIT_COLORS[card.suit]
            label = card.label()
            suit_symbol = SUIT_SYMBOLS[card.suit]

            # Top-left corner index: the rank with a small suit pip below it,
            # exactly like the index printed on a real playing card.
            self.canvas.create_text(
                x + 9,
                y + 7,
                text=label,
                anchor="nw",
                fill=text_color,
                font=("Arial", 13, "bold"),
            )
            self.canvas.create_text(
                x + 11,
                y + 25,
                text=suit_symbol,
                anchor="nw",
                fill=text_color,
                font=("Arial", 11, "bold"),
            )

            # Large centered suit symbol.
            self.canvas.create_text(
                x + CARD_WIDTH / 2,
                y + CARD_HEIGHT / 2,
                text=suit_symbol,
                fill=text_color,
                font=("Arial", 28, "bold"),
            )

            # Bottom-right corner index: the same rank + suit pip, mirrored so
            # the card still reads correctly when viewed from the other side.
            self.canvas.create_text(
                x + CARD_WIDTH - 9,
                y + CARD_HEIGHT - 7,
                text=label,
                anchor="se",
                fill=text_color,
                font=("Arial", 13, "bold"),
            )
            self.canvas.create_text(
                x + CARD_WIDTH - 11,
                y + CARD_HEIGHT - 25,
                text=suit_symbol,
                anchor="se",
                fill=text_color,
                font=("Arial", 11, "bold"),
            )
            return

        # Face-down cards use a dark blue rounded back.
        self.rounded_rect(
            x,
            y,
            x + CARD_WIDTH,
            y + CARD_HEIGHT,
            10,
            fill=CARD_BACK_COLOR,
            outline=outline_color,
            width=outline_width,
        )
        self.rounded_rect(
            x + 5,
            y + 5,
            x + CARD_WIDTH - 5,
            y + CARD_HEIGHT - 5,
            7,
            fill="",
            outline=CARD_BACK_ACCENT,
            width=1,
        )

        # Decorative diagonal lines make the card back easier to distinguish.
        self.draw_card_back_pattern(x, y)

        self.canvas.create_text(
            x + CARD_WIDTH / 2,
            y + CARD_HEIGHT / 2,
            text="SOL",
            fill="white",
            font=("Arial", 14, "bold"),
        )

    def draw_card_shadow(self, x: float, y: float) -> None:
        """Draw a simple offset rounded shadow under a card."""
        self.rounded_rect(
            x + 4,
            y + 5,
            x + CARD_WIDTH + 4,
            y + CARD_HEIGHT + 5,
            10,
            fill=CARD_SHADOW,
            outline="",
        )

    def draw_card_back_pattern(self, x: float, y: float) -> None:
        """Draw clipped diagonal stripes inside a face-down card.

        The pattern is a family of parallel 45-degree lines spaced
        `stripe_spacing` pixels apart. Each line starts on either the left
        edge or the top edge of the card and travels down-right until it
        meets either the right edge or the bottom edge, whichever comes
        first -- that is how the lines stay neatly clipped inside the card.
        """
        stripe_spacing = 14
        for offset in range(0, CARD_WIDTH + CARD_HEIGHT, stripe_spacing):
            # Start each stripe on either the left edge or the top edge.
            if offset <= CARD_HEIGHT:
                start_x = x
                start_y = y + offset
            else:
                start_x = x + (offset - CARD_HEIGHT)
                start_y = y

            # Compute how far the stripe can travel before leaving the card.
            distance_to_right = (x + CARD_WIDTH) - start_x
            distance_to_bottom = (y + CARD_HEIGHT) - start_y

            if start_y + distance_to_right <= y + CARD_HEIGHT:
                end_x = x + CARD_WIDTH
                end_y = start_y + distance_to_right
            else:
                end_x = start_x + distance_to_bottom
                end_y = y + CARD_HEIGHT

            self.canvas.create_line(
                start_x,
                start_y,
                end_x,
                end_y,
                fill=CARD_BACK_ACCENT,
                width=2,
            )

    def draw_animation(self) -> None:
        """Draw cards that are currently moving between piles."""
        if self.animation is None:
            return

        # Use smoothstep easing so motion starts and ends gently.
        progress = self.animation.frame / self.animation.steps
        eased_progress = progress * progress * (3 - 2 * progress)
        for card, start, end in zip(
            self.animation.cards,
            self.animation.start_positions,
            self.animation.end_positions,
            strict=True,
        ):
            x = start[0] + (end[0] - start[0]) * eased_progress
            y = start[1] + (end[1] - start[1]) * eased_progress
            y -= (1.0 - eased_progress) * 6
            self.draw_card(x, y, card, face_up=card.face_up, selected=False)

    def visible_foundation_pile(self, foundation_index: int) -> list[Card]:
        """Hide destination cards that are being animated on top of a foundation."""
        pile = self.game.foundations[foundation_index]
        hidden_count = self.animation_hidden_count("foundation", foundation_index)
        if hidden_count == 0:
            return pile
        return pile[:-hidden_count]

    def visible_tableau_column(self, column_index: int) -> list[Card]:
        """Hide destination cards that are being animated on top of a tableau."""
        column = self.game.tableau[column_index]
        hidden_count = self.animation_hidden_count("tableau", column_index)
        if hidden_count == 0:
            return column
        return column[:-hidden_count]

    def animation_hidden_count(self, pile_type: str, pile_index: int) -> int:
        """Return how many cards should be hidden in a destination during animation."""
        if self.animation is None:
            return 0
        if self.animation.destination_type != pile_type:
            return 0
        if self.animation.destination_index != pile_index:
            return 0
        return len(self.animation.cards)

    def is_hint_destination(self, pile_type: str, pile_index: int) -> bool:
        """True when the hint system wants this pile highlighted."""
        if self.hint_move is None:
            return False
        return (
            self.hint_move.destination_type == pile_type
            and self.hint_move.destination_index == pile_index
        )

    def is_tableau_card_selected(self, column_index: int, card_index: int) -> bool:
        """Highlight every card in the currently selected tableau stack."""
        if self.selection is None or self.selection.source_type != "tableau":
            return False
        if self.selection.pile_index != column_index:
            return False
        return card_index >= self.selection.card_index

    def selection_positions(self, selection: Selection) -> list[tuple[float, float]]:
        """Find the on-screen positions of the currently selected cards."""
        if selection.source_type == "waste":
            x1, y1, _, _ = self.waste_rect()
            return [(x1, y1)]

        if selection.source_type == "foundation":
            x1, y1, _, _ = self.foundation_rect(selection.pile_index)
            return [(x1, y1)]

        x = self.tableau_x(selection.pile_index)
        positions = self.tableau_positions(selection.pile_index)
        return [(x, positions[index]) for index in range(selection.card_index, len(positions))]

    def destination_positions(
        self,
        cards: list[Card],
        destination_type: str,
        destination_index: int,
    ) -> list[tuple[float, float]]:
        """Compute where each moving card should end up after a move."""
        if destination_type == "foundation":
            x1, y1, _, _ = self.foundation_rect(destination_index)
            return [(x1, y1)]

        x = self.tableau_x(destination_index)
        destination_column = self.game.tableau[destination_index]
        if not destination_column:
            start_y = TABLEAU_Y
        else:
            # The next card goes just below the current top card.
            positions = self.tableau_positions(destination_index)
            top_card = destination_column[-1]
            spacing = FACE_UP_SPACING if top_card.face_up else FACE_DOWN_SPACING
            start_y = positions[-1] + spacing

        return [(x, start_y + FACE_UP_SPACING * offset) for offset in range(len(cards))]

    def point_in_rect(self, x: int, y: int, rect: tuple[int, int, int, int]) -> bool:
        """Basic hit-test helper for rectangular areas."""
        x1, y1, x2, y2 = rect
        return x1 <= x <= x2 and y1 <= y <= y2

    def stock_rect(self) -> tuple[int, int, int, int]:
        """Return the stock pile rectangle."""
        return (MARGIN_X, TOP_ROW_Y, MARGIN_X + CARD_WIDTH, TOP_ROW_Y + CARD_HEIGHT)

    def waste_rect(self) -> tuple[int, int, int, int]:
        """Return the waste pile rectangle."""
        x = MARGIN_X + TABLEAU_STEP
        return (x, TOP_ROW_Y, x + CARD_WIDTH, TOP_ROW_Y + CARD_HEIGHT)

    def foundation_rect(self, foundation_index: int) -> tuple[int, int, int, int]:
        """Return the rectangle for one foundation pile."""
        x = FOUNDATION_START_X + foundation_index * TABLEAU_STEP
        return (x, TOP_ROW_Y, x + CARD_WIDTH, TOP_ROW_Y + CARD_HEIGHT)

    def tableau_x(self, column_index: int) -> int:
        """Return the left x-position of a tableau column."""
        return MARGIN_X + column_index * TABLEAU_STEP

    def tableau_positions(self, column_index: int) -> list[int]:
        """Return every y-position in one real tableau column."""
        return self.tableau_positions_for_cards(self.game.tableau[column_index])

    def tableau_positions_for_cards(self, cards: list[Card]) -> list[int]:
        """Return stacked y-positions for any supplied list of cards.

        Face-down cards can overlap more tightly because nothing on them needs
        to be readable, while face-up cards step further down so their rank
        and suit still show at the top edge. That is why two different
        spacings (FACE_UP_SPACING and FACE_DOWN_SPACING) are used here.
        """
        y_positions: list[int] = []
        y = TABLEAU_Y
        for card in cards:
            y_positions.append(y)
            y += FACE_UP_SPACING if card.face_up else FACE_DOWN_SPACING
        return y_positions

    def find_tableau_hit(self, x: int, y: int) -> tuple[int | None, int | None]:
        """
        Figure out which tableau column/card a mouse click landed on.

        We scan from the top visible card downward so clicks prefer the card the
        player can actually see.
        """
        for column_index in range(TABLEAU_COLUMNS):
            x1 = self.tableau_x(column_index)
            x2 = x1 + CARD_WIDTH
            if not (x1 <= x <= x2):
                continue

            column = self.game.tableau[column_index]
            if not column:
                if TABLEAU_Y <= y <= TABLEAU_Y + CARD_HEIGHT:
                    return column_index, None
                continue

            positions = self.tableau_positions(column_index)
            last_bottom = positions[-1] + CARD_HEIGHT
            if not (TABLEAU_Y <= y <= last_bottom):
                continue

            # Walk backward so the topmost visible card wins the hit test.
            for card_index in range(len(column) - 1, -1, -1):
                top = positions[card_index]
                bottom = top + CARD_HEIGHT if card_index == len(column) - 1 else positions[card_index + 1]

                if top <= y <= bottom:
                    return column_index, card_index

            return column_index, None

        return None, None

    def is_same_selection(self, other: Selection) -> bool:
        """Check whether the user clicked the exact same selection again."""
        if self.selection is None:
            return False
        return (
            self.selection.source_type == other.source_type
            and self.selection.pile_index == other.pile_index
            and self.selection.card_index == other.card_index
        )

    def describe_cards(self, cards: list[Card]) -> str:
        """Small UI wrapper around the model helper."""
        return self.game.describe_cards(cards)

    def format_time(self, seconds: int) -> str:
        """Format elapsed time as MM:SS."""
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        return f"{minutes:02d}:{remaining_seconds:02d}"


def main() -> None:
    """Start the tkinter application."""
    root = tk.Tk()
    SolitaireApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
