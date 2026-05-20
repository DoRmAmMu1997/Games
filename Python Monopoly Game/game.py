"""The Monopoly rules engine -- all the game logic, and no graphics at all.

This file owns every rule: dice, movement, rent, buying, auctions, building,
mortgages, trades, jail, bankruptcy and the win check. It never imports pygame.

How other code drives it
------------------------
The engine is a turn-based state machine. `game.awaiting` says what input is
needed next ("pre_roll", "buy_or_auction", "auction", "post_roll",
"trade_response" or "game_over"), and `game.actor()` says which player must
provide it. The UI calls action methods when a human clicks; the AI calls the
exact same action methods. Because nothing here touches the screen, a whole
4-player AI game can be played in a loop with no window -- which is how the
engine is tested.

Beginner note:
- "the bank" is not a player. It has unlimited cash; it just hands out or
  collects money. Houses and hotels, though, are limited (see BANK_HOUSES).
"""

from __future__ import annotations

import random

import board_data
import cards as cards_module
from player import Player
from settings import (
    BANK_HOTELS, BANK_HOUSES, GO_SALARY, INCOME_TAX, JAIL_FINE, JAIL_POSITION,
    LUXURY_TAX, MAX_JAIL_TURNS, STARTING_CASH,
)

# Rent a railroad charges for 1/2/3/4 railroads owned by the same player.
RAILROAD_RENT = {1: 25, 2: 50, 3: 100, 4: 200}
# A game that somehow never ends is force-finished after this many turns
# (a safety net for the headless AI test; real games end long before this).
TURN_SAFETY_CAP = 3000


class MonopolyGame:
    """A full game of Monopoly: state plus every action that changes it."""

    # ----------------------------------------------------------------------
    # Construction
    # ----------------------------------------------------------------------
    def __init__(self, player_specs: list[tuple[str, bool]], theme: str = "classic",
                 seed: int | None = None):
        """Start a fresh game.

        `player_specs` is a list of (name, is_human) pairs, one per player.
        `theme` is a board theme key from board_data. `seed` makes the dice
        and shuffles repeatable, which the automated tests rely on.
        """
        self.rng = random.Random(seed)
        self.theme = theme
        self.board = board_data.build_board(theme)

        self.players = [
            Player(index=i, name=name, is_human=is_human)
            for i, (name, is_human) in enumerate(player_specs)
        ]

        # Dynamic property state. `owners` maps a board position to the index
        # of the player who owns it; unowned spaces simply are not in the map.
        self.owners: dict[int, int] = {}
        self.houses: dict[int, int] = {}        # position -> 0-4 houses, 5 = hotel
        self.mortgaged: set[int] = set()

        # The bank's limited supply of buildings.
        self.bank_houses = BANK_HOUSES
        self.bank_hotels = BANK_HOTELS

        # The two card decks.
        self.chance = cards_module.Deck("chance", cards_module.CHANCE_CARDS, rng=self.rng)
        self.chest = cards_module.Deck("chest", cards_module.CHEST_CARDS, rng=self.rng)

        # Turn / state-machine bookkeeping.
        self.current = 0
        self.phase = "playing"          # "playing" or "game_over"
        self.awaiting = "pre_roll"
        self.dice = (0, 0)
        self.doubles_count = 0
        self.turn_count = 0
        self.winner: int | None = None

        # Pending-decision context (only one is active at a time).
        self.pending_purchase: int | None = None
        self.auction: dict | None = None
        self.pending_trade: dict | None = None
        self._awaiting_before_trade = "pre_roll"
        self._trades_proposed = 0       # trade offers made this turn (AI cap)

        # Internal flags used while resolving a single roll.
        self._normal_double = False     # may the current player roll again?
        self.last_card: dict | None = None  # most recent card drawn (for the UI)

        self.log: list[str] = []
        self._note(f"New game on the {board_data.THEMES[theme]['name']} board.")

    # ----------------------------------------------------------------------
    # Small helpers
    # ----------------------------------------------------------------------
    def _note(self, message: str) -> None:
        """Add a short message to the event log the UI shows the player."""
        self.log.append(message)
        if len(self.log) > 60:
            self.log = self.log[-60:]

    @property
    def current_player(self) -> Player:
        """The player whose turn it currently is."""
        return self.players[self.current]

    def actor(self) -> int:
        """Return the index of the player who must act for the current state.

        For most states that is the current player; during an auction it is
        whoever's bid it is; during a trade response it is the trade's target.
        """
        if self.awaiting == "auction" and self.auction is not None:
            return self.auction["current"]
        if self.awaiting == "trade_response" and self.pending_trade is not None:
            return self.pending_trade["to"]
        return self.current

    def active_players(self) -> list[Player]:
        """Every player who has not gone bankrupt."""
        return [p for p in self.players if not p.bankrupt]

    def other_players(self, player: Player) -> list[Player]:
        """Every non-bankrupt player except `player` (used by card effects)."""
        return [p for p in self.players if not p.bankrupt and p is not player]

    def properties_of(self, player: Player) -> list[int]:
        """The board positions owned by `player` (the single source of truth)."""
        return [pos for pos, owner in self.owners.items() if owner == player.index]

    def owner_of(self, position: int) -> Player | None:
        """The Player who owns a space, or None if it is unowned."""
        idx = self.owners.get(position)
        return None if idx is None else self.players[idx]

    def count_in_group(self, player: Player, group: str) -> int:
        """How many spaces of a colour group `player` owns."""
        return sum(1 for pos in board_data.COLOR_GROUPS[group]
                   if self.owners.get(pos) == player.index)

    def has_monopoly(self, player: Player, group: str) -> bool:
        """True if `player` owns every space in a colour group."""
        members = board_data.COLOR_GROUPS[group]
        return all(self.owners.get(pos) == player.index for pos in members)

    def count_railroads(self, player: Player) -> int:
        """How many railroads `player` owns."""
        return sum(1 for pos in board_data.RAILROAD_POSITIONS
                   if self.owners.get(pos) == player.index)

    def count_utilities(self, player: Player) -> int:
        """How many utilities `player` owns."""
        return sum(1 for pos in board_data.UTILITY_POSITIONS
                   if self.owners.get(pos) == player.index)

    def count_buildings(self, player: Player) -> tuple[int, int]:
        """Return (total houses, total hotels) across all of `player`'s land."""
        houses = hotels = 0
        for pos in self.properties_of(player):
            level = self.houses.get(pos, 0)
            if level == 5:
                hotels += 1
            else:
                houses += level
        return houses, hotels

    def net_worth(self, player: Player) -> int:
        """Estimate a player's total value: cash + property + buildings.

        Mortgaged land counts at its mortgage value; buildings count at the
        half-price they would sell back for. This drives AI valuations and the
        end-of-game ranking.
        """
        worth = player.cash
        for pos in self.properties_of(player):
            space = self.board[pos]
            if pos in self.mortgaged:
                worth += space.mortgage
            else:
                worth += space.price
            level = self.houses.get(pos, 0)
            worth += level * space.house_cost // 2
        return worth

    # ----------------------------------------------------------------------
    # Money: gaining, paying the bank, paying another player
    # ----------------------------------------------------------------------
    def gain(self, player: Player, amount: int) -> None:
        """The bank pays `player`. The bank never runs out of cash."""
        if amount <= 0:
            return
        player.cash += amount

    def charge(self, player: Player, amount: int) -> None:
        """`player` must pay the bank `amount` (raising funds if short)."""
        self._settle(player, amount, None)

    def transfer(self, payer: Player, payee: Player, amount: int) -> None:
        """`payer` must pay `payee` `amount` (raising funds if short)."""
        self._settle(payer, amount, payee)

    def _settle(self, payer: Player, amount: int, payee: Player | None) -> None:
        """Pay a debt; if `payer` cannot, raise funds, then maybe go bankrupt.

        `payee` is the player who is owed the money, or None for the bank.
        """
        if amount <= 0:
            return
        if payer.cash < amount:
            # Try to cover the shortfall by selling houses and mortgaging.
            self._raise_funds(payer, amount)
        if payer.cash >= amount:
            payer.cash -= amount
            if payee is not None:
                payee.cash += amount
        else:
            # Even stripped bare the player cannot pay -- they are bankrupt.
            paid = payer.cash
            payer.cash = 0
            if payee is not None:
                payee.cash += paid
            self._bankrupt(payer, payee)

    def _raise_funds(self, player: Player, target: int) -> None:
        """Auto-sell houses and mortgage land until `player` has `target` cash.

        Used as a fallback for any player who owes more than they hold. The
        human UI lets a person do this by hand first; this guarantees the rules
        still resolve if they cannot or do not.
        """
        # Sell houses first -- a property must be house-free before mortgaging.
        # Always sell from the most-built property to respect even-selling.
        while player.cash < target:
            best = None
            for pos in self.properties_of(player):
                if self.houses.get(pos, 0) > 0:
                    if best is None or self.houses[pos] > self.houses[best]:
                        best = pos
            if best is None:
                break
            self.sell_house(best, forced=True)

        # Then mortgage any un-mortgaged land.
        while player.cash < target:
            candidate = None
            for pos in self.properties_of(player):
                if pos not in self.mortgaged and self.houses.get(pos, 0) == 0:
                    candidate = pos
                    break
            if candidate is None:
                break
            self.mortgage(candidate, forced=True)

    def _bankrupt(self, player: Player, creditor: Player | None) -> None:
        """Remove `player` from the game, handing their estate to the creditor."""
        player.bankrupt = True
        self._note(f"{player.name} has gone bankrupt!")

        # Buildings always go back to the bank's supply.
        for pos in self.properties_of(player):
            level = self.houses.get(pos, 0)
            if level == 5:
                self.bank_hotels += 1
            else:
                self.bank_houses += level
            self.houses[pos] = 0

        owned = self.properties_of(player)
        if creditor is not None and not creditor.bankrupt:
            # Estate (cash already moved) and land pass to the creditor.
            creditor.cash += player.cash
            for pos in owned:
                self.owners[pos] = creditor.index
        else:
            # Bankrupt to the bank: the land simply becomes unowned again.
            for pos in owned:
                self.owners.pop(pos, None)
                self.mortgaged.discard(pos)
        player.cash = 0

        # Any held jail cards go back to their decks.
        for deck_name in player.jail_card_decks:
            self._deck(deck_name).return_jail_card()
        player.jail_cards = 0
        player.jail_card_decks = []

        self._check_for_winner()

    def _check_for_winner(self) -> None:
        """End the game if only one solvent player is left standing."""
        survivors = self.active_players()
        if len(survivors) <= 1 and self.phase == "playing":
            self.phase = "game_over"
            self.awaiting = "game_over"
            self.winner = survivors[0].index if survivors else None
            if self.winner is not None:
                self._note(f"{self.players[self.winner].name} wins the game!")

    # ----------------------------------------------------------------------
    # Turn flow
    # ----------------------------------------------------------------------
    def _start_turn(self) -> None:
        """Begin the current player's turn (skipping bankrupt players)."""
        if self.phase == "game_over":
            return
        # Skip over anyone who is out of the game.
        guard = 0
        while self.current_player.bankrupt and guard < len(self.players):
            self.current = (self.current + 1) % len(self.players)
            guard += 1
        self.doubles_count = 0
        self._normal_double = False
        self._trades_proposed = 0
        self.awaiting = "pre_roll"
        self.turn_count += 1
        if self.turn_count > TURN_SAFETY_CAP:
            self._force_finish()

    def _force_finish(self) -> None:
        """End an over-long game by ranking the survivors on net worth."""
        survivors = self.active_players()
        survivors.sort(key=self.net_worth, reverse=True)
        self.phase = "game_over"
        self.awaiting = "game_over"
        self.winner = survivors[0].index if survivors else None
        self._note("Turn limit reached -- the richest player wins.")

    def end_turn(self) -> None:
        """Finish the current player's turn and pass play to the next player."""
        if self.awaiting != "post_roll":
            return
        self.current = (self.current + 1) % len(self.players)
        self._start_turn()

    def roll_dice(self) -> tuple[int, int]:
        """Roll the two dice for the current player and resolve what happens."""
        if self.awaiting != "pre_roll":
            return self.dice
        player = self.current_player
        die_a = self.rng.randint(1, 6)
        die_b = self.rng.randint(1, 6)
        self.dice = (die_a, die_b)
        is_double = die_a == die_b
        total = die_a + die_b
        self._normal_double = False

        if player.in_jail:
            self._roll_in_jail(player, total, is_double)
            return self.dice

        if is_double:
            self.doubles_count += 1
            if self.doubles_count >= 3:
                # Three doubles in a row sends you straight to jail.
                self._note(f"{player.name} rolled three doubles and goes to Jail.")
                self.go_to_jail(player)
                self._continue_after_landing()
                return self.dice

        self._note(f"{player.name} rolled {die_a} + {die_b} = {total}.")
        self._step_forward(player, total)
        self._normal_double = is_double  # an extra roll, unless landing changes it
        self._resolve_landing(player)
        # If the landing opened a buy-or-auction decision, pause there;
        # otherwise work out whether the turn continues or ends.
        if self.awaiting != "buy_or_auction":
            self._continue_after_landing()
        return self.dice

    def _roll_in_jail(self, player: Player, total: int, is_double: bool) -> None:
        """Resolve a dice roll made while the player is sitting in jail."""
        if is_double:
            self._note(f"{player.name} rolled doubles and leaves Jail.")
            player.in_jail = False
            player.jail_turns = 0
            self._step_forward(player, total)
            self._resolve_landing(player)
            # Escaping on doubles does NOT grant an extra roll.
            if self.awaiting != "buy_or_auction":
                self._continue_after_landing()
            return
        player.jail_turns += 1
        if player.jail_turns >= MAX_JAIL_TURNS:
            # Out of attempts: pay the fine and move the rolled amount.
            self._note(f"{player.name} pays the ${JAIL_FINE} fine and leaves Jail.")
            self.charge(player, JAIL_FINE)
            player.in_jail = False
            player.jail_turns = 0
            if self.phase == "playing":
                self._step_forward(player, total)
                self._resolve_landing(player)
            if self.awaiting != "buy_or_auction":
                self._continue_after_landing()
        else:
            self._note(f"{player.name} stays in Jail.")
            self.awaiting = "post_roll"

    def pay_jail_fine(self) -> None:
        """Current player pays the fine to get out of jail before rolling."""
        player = self.current_player
        if self.awaiting != "pre_roll" or not player.in_jail:
            return
        self.charge(player, JAIL_FINE)
        if self.phase == "playing":
            player.in_jail = False
            player.jail_turns = 0
            self._note(f"{player.name} pays the ${JAIL_FINE} fine and is free.")

    def use_jail_card(self) -> None:
        """Current player spends a Get Out of Jail Free card before rolling."""
        player = self.current_player
        if self.awaiting != "pre_roll" or not player.in_jail or player.jail_cards <= 0:
            return
        player.jail_cards -= 1
        deck_name = player.jail_card_decks.pop() if player.jail_card_decks else "chance"
        self._deck(deck_name).return_jail_card()
        player.in_jail = False
        player.jail_turns = 0
        self._note(f"{player.name} uses a Get Out of Jail Free card.")

    def _continue_after_landing(self) -> None:
        """Decide what happens after a landing fully resolves.

        If the landing opened a buy-or-auction decision, the turn pauses there.
        Otherwise the player either rolls again (a normal double) or moves on
        to the post-roll phase where they may build/trade and end the turn.
        """
        if self.phase == "game_over":
            return
        if self.current_player.bankrupt:
            # A player who bankrupted on this landing cannot keep their turn.
            self.awaiting = "post_roll"
            return
        if self._normal_double and self.doubles_count < 3:
            self.awaiting = "pre_roll"      # roll again
        else:
            self.awaiting = "post_roll"

    # ----------------------------------------------------------------------
    # Movement and landing
    # ----------------------------------------------------------------------
    def _step_forward(self, player: Player, steps: int) -> None:
        """Move a player `steps` spaces clockwise, paying $200 for passing GO."""
        new_position = (player.position + steps) % 40
        if new_position < player.position:
            self.gain(player, GO_SALARY)
            self._note(f"{player.name} passes GO and collects ${GO_SALARY}.")
        player.position = new_position

    def advance_to(self, player: Player, position: int,
                   rail_rent_multiplier: int = 1, utility_card_rent: bool = False) -> None:
        """Move a player forward to a specific space (used by Chance cards)."""
        if position != player.position and position <= player.position:
            self.gain(player, GO_SALARY)
            self._note(f"{player.name} passes GO and collects ${GO_SALARY}.")
        player.position = position
        self._resolve_landing(player, rail_rent_multiplier=rail_rent_multiplier,
                              utility_card_rent=utility_card_rent)

    def move_back(self, player: Player, steps: int) -> None:
        """Move a player backward `steps` spaces (no GO money for going back)."""
        player.position = (player.position - steps) % 40
        self._resolve_landing(player)

    def go_to_jail(self, player: Player) -> None:
        """Send a player directly to jail; this also ends their turn."""
        player.position = JAIL_POSITION
        player.in_jail = True
        player.jail_turns = 0
        self._normal_double = False
        self._note(f"{player.name} goes to Jail.")

    def _resolve_landing(self, player: Player, rail_rent_multiplier: int = 1,
                         utility_card_rent: bool = False) -> None:
        """Work out and apply whatever happens on the space a player landed on."""
        if self.phase == "game_over":
            return
        space = self.board[player.position]
        kind = space.kind

        if kind == "go_to_jail":
            self.go_to_jail(player)
            return
        if kind == "tax":
            amount = INCOME_TAX if space.tax >= INCOME_TAX else LUXURY_TAX
            self._note(f"{player.name} pays ${amount} {space.name}.")
            self.charge(player, amount)
            return
        if kind in ("chance", "chest"):
            self._draw_card(player, kind)
            return
        if kind in ("go", "jail", "free_parking"):
            return  # nothing happens on these spaces

        # The space is a street, railroad or utility.
        owner = self.owner_of(player.position)
        if owner is None:
            # Unowned: the player may buy it or send it to auction.
            self.pending_purchase = player.position
            self.awaiting = "buy_or_auction"
            return
        if owner is player or owner.bankrupt:
            return
        if player.position in self.mortgaged:
            self._note(f"{space.name} is mortgaged -- no rent is due.")
            return
        rent = self._rent_for(player.position, owner, sum(self.dice),
                              rail_rent_multiplier, utility_card_rent)
        if rent > 0:
            self._note(f"{player.name} pays ${rent} rent to {owner.name}.")
            self.transfer(player, owner, rent)

    def _rent_for(self, position: int, owner: Player, dice_total: int,
                  rail_rent_multiplier: int = 1, utility_card_rent: bool = False) -> int:
        """Compute the rent owed for landing on an owned space."""
        space = self.board[position]
        if space.kind == "railroad":
            base = RAILROAD_RENT.get(self.count_railroads(owner), 0)
            return base * rail_rent_multiplier
        if space.kind == "utility":
            if utility_card_rent:
                # The Chance card always charges ten times a fresh dice throw.
                dice_total = self.rng.randint(1, 6) + self.rng.randint(1, 6)
                return 10 * dice_total
            multiplier = 4 if self.count_utilities(owner) == 1 else 10
            return multiplier * dice_total
        # A street.
        level = self.houses.get(position, 0)
        if level == 0:
            base = space.rent[0]
            # An undeveloped lot in a complete colour group charges double.
            if self.has_monopoly(owner, space.group):
                return base * 2
            return base
        return space.rent[level]

    def _draw_card(self, player: Player, deck_name: str) -> None:
        """Draw and immediately apply a Chance or Community Chest card."""
        deck = self._deck(deck_name)
        card = deck.draw()
        self.last_card = card
        self._note(f"{player.name} draws: {cards_module.format_card_text(card, self.board)}")
        cards_module.apply_card(self, player, card)

    def _deck(self, deck_name: str):
        """Return the Deck object for "chance" or "chest"."""
        return self.chance if deck_name == "chance" else self.chest

    def grant_jail_card(self, player: Player, deck_name: str) -> None:
        """Give a player a Get Out of Jail Free card from the named deck."""
        player.jail_cards += 1
        player.jail_card_decks.append(deck_name)

    # ----------------------------------------------------------------------
    # Buying and auctions
    # ----------------------------------------------------------------------
    def buy_property(self) -> None:
        """Current player buys the space they just landed on, at list price."""
        if self.awaiting != "buy_or_auction" or self.pending_purchase is None:
            return
        player = self.current_player
        space = self.board[self.pending_purchase]
        if player.cash < space.price:
            # Cannot afford it -- it must go to auction instead.
            self.decline_property()
            return
        player.cash -= space.price
        self.owners[self.pending_purchase] = player.index
        self._note(f"{player.name} buys {space.name} for ${space.price}.")
        self.pending_purchase = None
        self._continue_after_landing()

    def decline_property(self) -> None:
        """Current player declines the space; it goes to a public auction."""
        if self.awaiting != "buy_or_auction" or self.pending_purchase is None:
            return
        position = self.pending_purchase
        self.pending_purchase = None
        self._start_auction(position)

    def _start_auction(self, position: int) -> None:
        """Open an ascending-bid auction for a property among all players."""
        bidders = [p.index for p in self.active_players()]
        self.auction = {
            "position": position,
            "active": bidders,
            "high_bid": 0,
            "high_bidder": None,
            "current": bidders[0],
        }
        self.awaiting = "auction"
        self._note(f"{self.board[position].name} goes up for auction.")

    def auction_bid(self, amount: int) -> None:
        """The current bidder raises the bid to `amount`."""
        if self.awaiting != "auction" or self.auction is None:
            return
        auction = self.auction
        bidder = self.players[auction["current"]]
        if amount <= auction["high_bid"] or amount > bidder.cash:
            return  # an illegal bid is simply ignored
        auction["high_bid"] = amount
        auction["high_bidder"] = auction["current"]
        self._advance_auction()

    def auction_pass(self) -> None:
        """The current bidder drops out of the auction."""
        if self.awaiting != "auction" or self.auction is None:
            return
        auction = self.auction
        auction["active"].remove(auction["current"])
        self._advance_auction()

    def _advance_auction(self) -> None:
        """Move the auction to the next bidder, or finish it if it is settled."""
        auction = self.auction
        high_bidder = auction["high_bidder"]
        # Find the next active bidder who is not already the high bidder.
        contenders = [idx for idx in auction["active"] if idx != high_bidder]
        if not contenders:
            self._finish_auction()
            return
        # Advance clockwise from the bidder who just acted.
        order = auction["active"]
        start = order.index(auction["current"]) if auction["current"] in order else -1
        for offset in range(1, len(order) + 1):
            candidate = order[(start + offset) % len(order)]
            if candidate != high_bidder:
                auction["current"] = candidate
                return
        self._finish_auction()

    def _finish_auction(self) -> None:
        """Award the auctioned property and return play to the current player."""
        auction = self.auction
        position = auction["position"]
        winner_index = auction["high_bidder"]
        if winner_index is not None and auction["high_bid"] > 0:
            winner = self.players[winner_index]
            winner.cash -= auction["high_bid"]
            self.owners[position] = winner_index
            self._note(f"{winner.name} wins {self.board[position].name} "
                       f"at auction for ${auction['high_bid']}.")
        else:
            self._note(f"{self.board[position].name} received no bids.")
        self.auction = None
        self._continue_after_landing()

    # ----------------------------------------------------------------------
    # Building, mortgaging
    # ----------------------------------------------------------------------
    def can_build(self, player: Player, position: int) -> bool:
        """True if `player` may legally build one more house/hotel on a space."""
        space = self.board[position]
        if space.kind != "street" or self.owners.get(position) != player.index:
            return False
        if not self.has_monopoly(player, space.group):
            return False
        if any(pos in self.mortgaged for pos in board_data.COLOR_GROUPS[space.group]):
            return False
        level = self.houses.get(position, 0)
        if level >= 5:
            return False
        # Even-building: you may only build on the least-developed lot.
        group_levels = [self.houses.get(pos, 0) for pos in board_data.COLOR_GROUPS[space.group]]
        if level != min(group_levels):
            return False
        if level == 4:
            if self.bank_hotels <= 0:
                return False
        elif self.bank_houses <= 0:
            return False
        return player.cash >= space.house_cost

    def build_house(self, position: int) -> bool:
        """Build one house (or a hotel) on a street the current player owns."""
        player = self.current_player
        if self.awaiting not in ("pre_roll", "post_roll") or not self.can_build(player, position):
            return False
        space = self.board[position]
        level = self.houses.get(position, 0)
        player.cash -= space.house_cost
        if level == 4:
            # The fifth building is a hotel: four houses go back to the bank.
            self.bank_houses += 4
            self.bank_hotels -= 1
        else:
            self.bank_houses -= 1
        self.houses[position] = level + 1
        what = "a hotel" if level == 4 else "a house"
        self._note(f"{player.name} builds {what} on {space.name}.")
        return True

    def sell_house(self, position: int, forced: bool = False) -> bool:
        """Sell one house/hotel back to the bank for half its build cost."""
        player = self.current_player if not forced else self.owner_of(position)
        if player is None or self.owners.get(position) != player.index:
            return False
        level = self.houses.get(position, 0)
        if level <= 0:
            return False
        if not forced:
            # Even-selling: only the most-developed lot in the group may sell.
            group = self.board[position].group
            group_levels = [self.houses.get(pos, 0) for pos in board_data.COLOR_GROUPS[group]]
            if level != max(group_levels):
                return False
        space = self.board[position]
        if level == 5:
            # Selling a hotel needs four houses available from the bank.
            self.bank_hotels += 1
            self.bank_houses -= 4
        else:
            self.bank_houses += 1
        self.houses[position] = level - 1
        player.cash += space.house_cost // 2
        self._note(f"{player.name} sells a building on {space.name}.")
        return True

    def mortgage(self, position: int, forced: bool = False) -> bool:
        """Mortgage a property: raise its mortgage value, collect no rent on it."""
        player = self.current_player if not forced else self.owner_of(position)
        if player is None or self.owners.get(position) != player.index:
            return False
        if position in self.mortgaged or self.houses.get(position, 0) > 0:
            return False
        space = self.board[position]
        self.mortgaged.add(position)
        player.cash += space.mortgage
        self._note(f"{player.name} mortgages {space.name} for ${space.mortgage}.")
        return True

    def unmortgage(self, position: int) -> bool:
        """Lift a mortgage by repaying its value plus 10% interest."""
        player = self.current_player
        if self.owners.get(position) != player.index or position not in self.mortgaged:
            return False
        cost = int(round(self.board[position].mortgage * 1.1))
        if player.cash < cost:
            return False
        player.cash -= cost
        self.mortgaged.discard(position)
        self._note(f"{player.name} lifts the mortgage on {self.board[position].name}.")
        return True

    # ----------------------------------------------------------------------
    # Trading
    # ----------------------------------------------------------------------
    def trade_is_legal(self, offer: dict) -> bool:
        """Check a trade offer is valid before it is proposed or accepted.

        An `offer` is a dict with `from`, `to`, and the two sides' `props`
        (lists of positions), `cash` and `jail` (jail-card counts).
        """
        giver = self.players[offer["from"]]
        taker = self.players[offer["to"]]
        if giver.bankrupt or taker.bankrupt or giver is taker:
            return False
        for side, owner in ((offer["give"], giver), (offer["get"], taker)):
            if side["cash"] < 0 or side["cash"] > owner.cash:
                return False
            if side["jail"] < 0 or side["jail"] > owner.jail_cards:
                return False
            for pos in side["props"]:
                if self.owners.get(pos) != owner.index:
                    return False
                # Land cannot be traded while its colour group has buildings.
                group = self.board[pos].group
                if group:
                    if any(self.houses.get(p, 0) > 0
                           for p in board_data.COLOR_GROUPS[group]):
                        return False
        return True

    def propose_trade(self, offer: dict) -> bool:
        """The current player offers a trade; the target must then respond."""
        if self.awaiting not in ("pre_roll", "post_roll"):
            return False
        if not self.trade_is_legal(offer):
            return False
        self._awaiting_before_trade = self.awaiting
        self.pending_trade = offer
        self.awaiting = "trade_response"
        self._trades_proposed += 1
        self._note(f"{self.players[offer['from']].name} offers "
                   f"{self.players[offer['to']].name} a trade.")
        return True

    def respond_trade(self, accept: bool) -> None:
        """The trade target accepts or rejects the pending trade offer."""
        if self.awaiting != "trade_response" or self.pending_trade is None:
            return
        offer = self.pending_trade
        if accept and self.trade_is_legal(offer):
            self._execute_trade(offer)
            self._note(f"{self.players[offer['to']].name} accepts the trade.")
        else:
            self._note(f"{self.players[offer['to']].name} rejects the trade.")
        self.pending_trade = None
        self.awaiting = self._awaiting_before_trade

    def _execute_trade(self, offer: dict) -> None:
        """Swap the cash, properties and jail cards described by an offer."""
        giver = self.players[offer["from"]]
        taker = self.players[offer["to"]]
        give, get = offer["give"], offer["get"]
        # Cash.
        giver.cash += get["cash"] - give["cash"]
        taker.cash += give["cash"] - get["cash"]
        # Properties.
        for pos in give["props"]:
            self.owners[pos] = taker.index
        for pos in get["props"]:
            self.owners[pos] = giver.index
        # Jail cards (tracked as simple counts plus their deck of origin).
        for _ in range(give["jail"]):
            giver.jail_cards -= 1
            taker.jail_cards += 1
            taker.jail_card_decks.append(
                giver.jail_card_decks.pop() if giver.jail_card_decks else "chance")
        for _ in range(get["jail"]):
            taker.jail_cards -= 1
            giver.jail_cards += 1
            giver.jail_card_decks.append(
                taker.jail_card_decks.pop() if taker.jail_card_decks else "chance")

    # ----------------------------------------------------------------------
    # Save / load
    # ----------------------------------------------------------------------
    def to_dict(self) -> dict:
        """Snapshot the whole game as plain data for saving to JSON.

        Saving is only offered between turns (pre_roll / post_roll), so no
        half-finished auction or trade ever needs to be stored.
        """
        return {
            "theme": self.theme,
            "players": [p.to_dict() for p in self.players],
            "owners": {str(k): v for k, v in self.owners.items()},
            "houses": {str(k): v for k, v in self.houses.items()},
            "mortgaged": sorted(self.mortgaged),
            "bank_houses": self.bank_houses,
            "bank_hotels": self.bank_hotels,
            "chance": self.chance.state(),
            "chest": self.chest.state(),
            "current": self.current,
            "awaiting": self.awaiting if self.awaiting in ("pre_roll", "post_roll") else "pre_roll",
            "turn_count": self.turn_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MonopolyGame":
        """Rebuild a game from a `to_dict()` snapshot (used to resume a game)."""
        specs = [(p["name"], p["is_human"]) for p in data["players"]]
        game = cls(specs, theme=data.get("theme", "classic"))
        game.players = [Player.from_dict(p) for p in data["players"]]
        game.owners = {int(k): v for k, v in data["owners"].items()}
        game.houses = {int(k): v for k, v in data["houses"].items()}
        game.mortgaged = set(data["mortgaged"])
        game.bank_houses = data["bank_houses"]
        game.bank_hotels = data["bank_hotels"]
        game.chance = cards_module.Deck("chance", cards_module.CHANCE_CARDS,
                                        order=data["chance"])
        game.chest = cards_module.Deck("chest", cards_module.CHEST_CARDS,
                                       order=data["chest"])
        game.current = data["current"]
        game.awaiting = data["awaiting"]
        game.turn_count = data["turn_count"]
        game.phase = "playing"
        game._note("Resumed a saved game.")
        return game
