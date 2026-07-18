"""Chance and Community Chest: the card definitions, the deck, and effects.

A card is a plain dict with a `kind` plus kind-specific fields. `apply_card`
is one big dispatch that turns a `kind` into calls on the game engine -- so
the cards know *what* they do and the engine knows *how* money and movement
work.

Beginner note:
- Card destinations are stored as board *positions* (0-39), never as names.
  That is why the same 16 cards work on every themed board: position 5 is the
  first railroad whether it is called "Reading Railroad" or "Heathrow Airport".
"""

from __future__ import annotations

from board_data import RAILROAD_POSITIONS, UTILITY_POSITIONS

# --------------------------------------------------------------------------
# Card definitions -- the standard 16 Chance and 16 Community Chest cards
# --------------------------------------------------------------------------
# `text` may contain "{dest}", which format_card_text() fills with the themed
# name of the destination space.
CHANCE_CARDS = [
    dict(deck="chance", kind="advance", pos=0, text="Advance to {dest}."),
    dict(deck="chance", kind="advance", pos=24, text="Advance to {dest}."),
    dict(deck="chance", kind="advance", pos=11, text="Advance to {dest}."),
    dict(deck="chance", kind="advance", pos=5, text="Take a trip to {dest}."),
    dict(deck="chance", kind="advance", pos=39, text="Advance to {dest}."),
    dict(deck="chance", kind="nearest_rail",
         text="Advance to the nearest Railroad. If owned, pay the owner twice "
              "the rent; otherwise you may buy it."),
    dict(deck="chance", kind="nearest_util",
         text="Advance to the nearest Utility. If owned, throw the dice and "
              "pay the owner ten times the amount; otherwise you may buy it."),
    dict(deck="chance", kind="back", steps=3, text="Go back three spaces."),
    dict(deck="chance", kind="jail", text="Go directly to Jail."),
    dict(deck="chance", kind="jail_card",
         text="Get Out of Jail Free -- keep this card until it is needed."),
    dict(deck="chance", kind="collect", amount=50,
         text="The bank pays you a dividend of $50."),
    dict(deck="chance", kind="collect", amount=150,
         text="Your building loan matures -- collect $150."),
    dict(deck="chance", kind="pay", amount=15, text="Speeding fine -- pay $15."),
    dict(deck="chance", kind="pay_each", amount=50,
         text="You are elected Chairman of the Board -- pay each player $50."),
    dict(deck="chance", kind="repairs", per_house=25, per_hotel=100,
         text="Make general repairs: pay $25 per house and $100 per hotel."),
    dict(deck="chance", kind="advance", pos=0, text="Advance to {dest}."),
]

CHEST_CARDS = [
    dict(deck="chest", kind="advance", pos=0, text="Advance to {dest}."),
    dict(deck="chest", kind="jail", text="Go directly to Jail."),
    dict(deck="chest", kind="jail_card",
         text="Get Out of Jail Free -- keep this card until it is needed."),
    dict(deck="chest", kind="collect", amount=200,
         text="Bank error in your favour -- collect $200."),
    dict(deck="chest", kind="collect", amount=100,
         text="Holiday fund matures -- collect $100."),
    dict(deck="chest", kind="collect", amount=100,
         text="Life insurance matures -- collect $100."),
    dict(deck="chest", kind="collect", amount=100, text="You inherit $100."),
    dict(deck="chest", kind="collect", amount=50,
         text="From the sale of stock you get $50."),
    dict(deck="chest", kind="collect", amount=25,
         text="Receive a $25 consultancy fee."),
    dict(deck="chest", kind="collect", amount=20, text="Income tax refund -- collect $20."),
    dict(deck="chest", kind="collect", amount=10,
         text="Second prize in a beauty contest -- collect $10."),
    dict(deck="chest", kind="collect_each", amount=10,
         text="It is your birthday -- collect $10 from each player."),
    dict(deck="chest", kind="pay", amount=100, text="Hospital fees -- pay $100."),
    dict(deck="chest", kind="pay", amount=50, text="Doctor's fee -- pay $50."),
    dict(deck="chest", kind="pay", amount=50, text="School fees -- pay $50."),
    dict(deck="chest", kind="repairs", per_house=40, per_hotel=115,
         text="Street repairs assessed: pay $40 per house and $115 per hotel."),
]


def format_card_text(card: dict, board) -> str:
    """Return a card's text with "{dest}" replaced by the themed space name."""
    if "{dest}" in card["text"] and "pos" in card:
        return card["text"].format(dest=board[card["pos"]].name)
    return card["text"]


# --------------------------------------------------------------------------
# Deck -- a shuffled pile that draws from the top
# --------------------------------------------------------------------------
class Deck:
    """A Chance or Community Chest pile.

    The deck stores a list of *indices* into its master card list (not the
    cards themselves) so the whole deck state saves to JSON as plain integers.
    A drawn card normally rotates to the bottom; a Get Out of Jail Free card
    instead leaves the deck until its holder uses or sells it.
    """

    def __init__(self, deck_name: str, master: list, rng=None, order=None):
        self.deck_name = deck_name
        self.master = master
        if order is not None:
            # Restoring a saved game: use the exact saved order.
            self.order = list(order)
        else:
            self.order = list(range(len(master)))
            if rng is not None:
                rng.shuffle(self.order)

    def draw(self) -> dict:
        """Take the top card, rotating non-jail cards to the bottom."""
        index = self.order.pop(0)
        card = self.master[index]
        if card["kind"] != "jail_card":
            self.order.append(index)
        return card

    def return_jail_card(self) -> None:
        """Put the Get Out of Jail Free card back on the bottom of the deck."""
        for index, card in enumerate(self.master):
            if card["kind"] == "jail_card" and index not in self.order:
                self.order.append(index)
                return

    def state(self) -> list:
        """Return the deck order as plain integers, for saving."""
        return list(self.order)


def _nearest(position: int, targets: tuple) -> int:
    """Return the first space in `targets` reached going clockwise from here."""
    for step in range(1, 40):
        candidate = (position + step) % 40
        if candidate in targets:
            return candidate
    return targets[0]


# --------------------------------------------------------------------------
# Applying a card's effect
# --------------------------------------------------------------------------
def apply_card(game, player, card: dict) -> None:
    """Carry out one card's effect by calling the game engine.

    Every branch maps a card `kind` to engine actions. The engine handles the
    hard parts (passing GO, rent, who-can-afford-what, bankruptcy).
    """
    kind = card["kind"]

    if kind == "advance":
        game.advance_to(player, card["pos"])
    elif kind == "back":
        game.move_back(player, card["steps"])
    elif kind == "nearest_rail":
        # Advance to the next railroad and pay double rent if it is owned.
        game.advance_to(player, _nearest(player.position, RAILROAD_POSITIONS),
                        rail_rent_multiplier=2)
    elif kind == "nearest_util":
        # Advance to the next utility; rent is 10x a fresh dice throw.
        game.advance_to(player, _nearest(player.position, UTILITY_POSITIONS),
                        utility_card_rent=True)
    elif kind == "jail":
        game.go_to_jail(player)
    elif kind == "jail_card":
        game.grant_jail_card(player, card["deck"])
    elif kind == "collect":
        game.gain(player, card["amount"])
    elif kind == "pay":
        game.charge(player, card["amount"])
    elif kind == "collect_each":
        for other in game.other_players(player):
            game.transfer(other, player, card["amount"])
    elif kind == "pay_each":
        for other in game.other_players(player):
            game.transfer(player, other, card["amount"])
    elif kind == "repairs":
        houses, hotels = game.count_buildings(player)
        game.charge(player, houses * card["per_house"] + hotels * card["per_hotel"])
