"""The computer players' decision-making.

`take_action(game)` is the single entry point. It looks at what the engine is
waiting for, decides what the current AI player should do, and calls exactly
one engine action -- so the caller can step the AI one move at a time (the UI
inserts a short pause between moves so a human can follow along).

The AI is a *heuristic* player: it follows sensible rules of thumb -- grab
property early, complete colour groups, build on them, keep a cash cushion,
bid to a property's worth, and trade to finish monopolies. It is a tough
opponent for casual play, not a perfect solver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import board_data
from settings import JAIL_FINE

if TYPE_CHECKING:
    from game import MonopolyGame
    from player import Player

# Colour groups roughly ordered by how rewarding they are to develop -- the
# orange and red streets are landed on most often, so the AI builds them first.
GROUP_BUILD_PRIORITY = [
    "orange", "red", "yellow", "light_blue", "pink", "green", "dark_blue", "brown",
]

# Valuation multipliers used by `property_value`. They are rules of thumb, not
# derived numbers, tuned by watching AI-vs-AI simulation batches:
# - Completing a monopoly unlocks building, which is where Monopoly money is
#   made, so such a title is worth well over double its list price.
# - A partial group is a step toward that, worth a smaller premium.
# - Each railroad already owned raises the value of the next one because the
#   collection's rent doubles with every member.
# - A second utility mildly beats a first; a lone utility is slightly below
#   list price because its rent rarely pays back the investment.
STREET_TOP_RENT_WEIGHT = 0.08
GROUP_COMPLETION_MULT = 2.35
PARTIAL_GROUP_MULT = 1.32
RAILROAD_OWNED_STEP = 0.28
UTILITY_PAIR_MULT = 1.12
UTILITY_SINGLE_MULT = 0.95


@dataclass(frozen=True)
class AIProfile:
    """Tunable decision knobs for one explainable AI difficulty."""

    key: str
    cash_cushion: int
    build_reserve: int
    trade_accept_margin: int
    value_scale: float
    auction_reserve: int
    blocker_bonus: float


AI_PROFILES = {
    "cautious": AIProfile(
        key="cautious",
        cash_cushion=320,
        build_reserve=360,
        trade_accept_margin=110,
        value_scale=0.88,
        auction_reserve=140,
        blocker_bonus=0.18,
    ),
    "standard": AIProfile(
        key="standard",
        cash_cushion=200,
        build_reserve=250,
        trade_accept_margin=60,
        value_scale=1.0,
        auction_reserve=60,
        blocker_bonus=0.35,
    ),
    "sharp": AIProfile(
        key="sharp",
        cash_cushion=140,
        build_reserve=180,
        trade_accept_margin=30,
        value_scale=1.12,
        auction_reserve=40,
        blocker_bonus=0.55,
    ),
}


def _profile(game: MonopolyGame) -> AIProfile:
    """Return the named game-wide AI profile, falling back to standard."""
    return AI_PROFILES.get(getattr(game, "ai_profile", "standard"),
                           AI_PROFILES["standard"])


def _trace(game: MonopolyGame, player: Player, message: str) -> None:
    """Leave one compact explainable AI decision in the shared event log."""
    game._note(f"{player.name}: {message}")


def property_value(game: MonopolyGame, player: Player, position: int,
                   profile: AIProfile | None = None) -> int:
    """Estimate a title's strategic value to `player`.

    Valuation stays deliberately readable: title price starts the estimate,
    rent potential raises streets with development upside, collections raise
    railroads/utilities, monopoly progress raises titles the player wants, and
    a smaller denial bonus prices blocking an opponent's last title.
    """
    profile = profile or _profile(game)
    space = game.board[position]
    value = float(space.price)

    if space.kind == "street":
        value += space.rent[-1] * STREET_TOP_RENT_WEIGHT
        if _completes_group(game, player, position):
            value *= GROUP_COMPLETION_MULT
        elif _owns_some_of_group(game, player, position):
            value *= PARTIAL_GROUP_MULT
        elif any(_completes_group(game, opponent, position)
                 for opponent in game.other_players(player)):
            value *= 1.0 + profile.blocker_bonus
    elif space.kind == "railroad":
        value *= 1.0 + RAILROAD_OWNED_STEP * game.count_railroads(player)
    elif space.kind == "utility":
        value *= UTILITY_PAIR_MULT if game.count_utilities(player) else UTILITY_SINGLE_MULT

    return max(space.mortgage, round(value * profile.value_scale))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def take_action(game: MonopolyGame) -> None:
    """Make the acting AI player perform one engine action."""
    if game.phase == "game_over":
        return
    player = game.players[game.actor()]
    state = game.awaiting

    if state == "pre_roll":
        _do_pre_roll(game, player)
    elif state == "buy_or_auction":
        _do_buy_decision(game, player)
    elif state == "auction":
        _do_auction(game, player)
    elif state == "post_roll":
        _do_post_roll(game, player)
    elif state == "trade_response":
        accept = evaluate_offer(game, player, game.pending_trade)
        _trace(game, player, "accepts a trade on value." if accept
               else "rejects a weak trade.")
        game.respond_trade(accept)


# --------------------------------------------------------------------------
# Pre-roll and post-roll: building, jail, ending the turn
# --------------------------------------------------------------------------
def _do_pre_roll(game: MonopolyGame, player: Player) -> None:
    """Before rolling: handle jail, build a house if worthwhile, then roll."""
    if player.in_jail:
        _handle_jail(game, player)
        return
    target = _best_build(game, player)
    if target is not None:
        _trace(game, player, f"builds into {game.board[target].group} pressure.")
        game.build_house(target)
        return
    game.roll_dice()


def _do_post_roll(game: MonopolyGame, player: Player) -> None:
    """After moving: build, lift a mortgage if flush, otherwise end the turn."""
    target = _best_build(game, player)
    if target is not None:
        _trace(game, player, f"builds into {game.board[target].group} pressure.")
        game.build_house(target)
        return
    if game._trades_proposed == 0:
        proposal = propose_trade(game, player)
        if proposal is not None:
            _trace(game, player, "offers a trade for group value.")
            game.propose_trade(proposal)
            return
    lift = _best_unmortgage(game, player)
    if lift is not None:
        _trace(game, player, f"lifts {game.board[lift].name} for rent.")
        game.unmortgage(lift)
        return
    game.end_turn()


def _handle_jail(game: MonopolyGame, player: Player) -> None:
    """Choose how to leave jail: a free card, the fine, or rolling for doubles."""
    if player.jail_cards > 0:
        game.use_jail_card()
        return
    # Early in the game getting out fast is worth $50 (there is land to buy).
    properties_claimed = len(game.owners)
    if properties_claimed < 14 and player.cash > JAIL_FINE + 150:
        game.pay_jail_fine()
        return
    # Otherwise just roll and hope for doubles; the engine handles 3 failures.
    game.roll_dice()


def _best_build(game: MonopolyGame, player: Player) -> int | None:
    """Return the best space to build one house/hotel on now, or None.

    The AI only builds when it owns a complete colour group, can do so legally
    (the engine's even-building rule), and still keeps a cash reserve.
    """
    profile = _profile(game)
    for group in GROUP_BUILD_PRIORITY:
        if not game.has_monopoly(player, group):
            continue
        # Least-developed lots first so building stays even within the group.
        members = sorted(board_data.COLOR_GROUPS[group],
                         key=lambda pos: game.houses.get(pos, 0))
        for pos in members:
            if game.can_build(player, pos):
                cost = game.board[pos].house_cost
                if player.cash - cost >= profile.build_reserve:
                    return pos
    return None


def _best_unmortgage(game: MonopolyGame, player: Player) -> int | None:
    """Return a mortgaged property worth lifting now, or None.

    Only done when comfortably rich; properties inside a monopoly come first
    because they are the ones that earn rent.
    """
    if player.cash < 700:
        return None
    mortgaged = [pos for pos in game.properties_of(player) if pos in game.mortgaged]
    if not mortgaged:
        return None
    mortgaged.sort(key=lambda pos: not _in_monopoly(game, player, pos))
    for pos in mortgaged:
        cost = round(game.board[pos].mortgage * 1.1)
        if player.cash - cost >= _profile(game).cash_cushion:
            return pos
    return None


# --------------------------------------------------------------------------
# Buying a property you landed on
# --------------------------------------------------------------------------
def _do_buy_decision(game: MonopolyGame, player: Player) -> None:
    """Decide whether to buy the space just landed on, or send it to auction."""
    position = game.pending_purchase
    assert position is not None, "buy decisions only happen with a pending purchase"
    if _wants_to_buy(game, player, position):
        _trace(game, player, f"buys {game.board[position].name}; value wins.")
        game.buy_property()
    else:
        _trace(game, player, f"sends {game.board[position].name} to auction.")
        game.decline_property()


def _wants_to_buy(game: MonopolyGame, player: Player, position: int) -> bool:
    """True if the AI should buy `position` at its list price."""
    space = game.board[position]
    profile = _profile(game)
    if player.cash < space.price:
        return False
    completes = _completes_group(game, player, position)
    # Spend down to the wire to complete a monopoly -- it is that valuable.
    if completes:
        return True
    # Railroads and utilities are flexible and always worth grabbing if afford.
    if space.kind in ("railroad", "utility"):
        return player.cash - space.price >= 0
    # Streets: buy freely while cash is healthy, or if it extends a group.
    if property_value(game, player, position, profile) >= space.price \
            and player.cash - space.price >= profile.cash_cushion:
        return True
    if _owns_some_of_group(game, player, position):
        return player.cash - space.price >= 0
    return False


# --------------------------------------------------------------------------
# Auctions
# --------------------------------------------------------------------------
def _do_auction(game: MonopolyGame, player: Player) -> None:
    """Place one bid or pass in the current auction."""
    auction = game.auction
    assert auction is not None, "only called while an auction is running"
    position = auction["position"]
    high = auction["high_bid"]
    ceiling = _auction_ceiling(game, player, position)
    step = max(10, game.board[position].price // 20)
    bid = high + step
    if bid <= ceiling and bid <= player.cash:
        _trace(game, player, f"bids ${bid}; ceiling ${ceiling}.")
        game.auction_bid(bid)
    else:
        _trace(game, player, f"passes at ${high}; ceiling ${ceiling}.")
        game.auction_pass()


def _auction_ceiling(game: MonopolyGame, player: Player, position: int) -> int:
    """The most this AI is willing to pay for `position` at auction."""
    profile = _profile(game)
    value = property_value(game, player, position, profile)
    # Never bid into bankruptcy -- always keep a small cushion.
    return min(value, max(0, player.cash - profile.auction_reserve))


# --------------------------------------------------------------------------
# Trading
# --------------------------------------------------------------------------
def propose_trade(game: MonopolyGame, player: Player) -> dict | None:
    """Look for a trade that completes one of this AI's colour groups.

    Returns an offer dict, or None. The AI prefers a swap that *also* completes
    a monopoly for the partner -- a deal both sides love -- and otherwise puts
    in enough cash to make the partner say yes.
    """
    for group in board_data.COLOR_GROUPS:
        wanted = _missing_one(game, player, group)
        if wanted is None:
            continue
        if wanted in game.mortgaged or game.houses.get(wanted, 0) > 0:
            continue
        partner = game.players[game.owners[wanted]]
        if partner.bankrupt:
            continue
        offer = _make_offer(game, player, partner, wanted)
        if offer is not None:
            return offer
    return None


def _missing_one(game: MonopolyGame, player: Player, group: str) -> int | None:
    """If `player` owns every space of `group` except one, return that space."""
    members = board_data.COLOR_GROUPS[group]
    owned = [p for p in members if game.owners.get(p) == player.index]
    missing = [p for p in members
               if game.owners.get(p) not in (player.index, None)]
    if len(owned) == len(members) - 1 and len(missing) == 1:
        return missing[0]
    return None


def _make_offer(game: MonopolyGame, player: Player, partner: Player, wanted: int) -> dict | None:
    """Build an offer to win `wanted` that both `player` and `partner` accept."""
    give: dict = {"props": [], "cash": 0, "jail": 0}
    get: dict = {"props": [wanted], "cash": 0, "jail": 0}
    # The best sweetener is a property that completes a monopoly for the
    # partner -- but never one from the group the AI is itself completing,
    # or the AI would trade away the very tile it is bargaining for.
    swap = _property_completing_for(game, player, partner,
                                    _group_of(game, wanted))
    if swap is not None:
        give["props"].append(swap)
    affordable = max(0, player.cash - _profile(game).cash_cushion)
    # Search upward for the least cash the partner will accept. The smaller
    # this number ends up being, the better the deal is for THIS AI -- so the
    # first cash amount the partner accepts is also the best one we will find
    # (every larger amount would just give the partner more for the same
    # property), which is why we return as soon as the partner says yes.
    for cash in range(0, affordable + 1, 25):
        give["cash"] = cash
        offer = {"from": player.index, "to": partner.index, "give": give, "get": get}
        if not game.trade_is_legal(offer):
            return None
        if evaluate_offer(game, partner, offer):
            # Only actually propose it if it is worthwhile for this AI too.
            if _trade_swing(game, player, offer) >= 0:
                return offer
            return None
    return None


def _property_completing_for(game: MonopolyGame, giver: Player, partner: Player,
                             avoid_group: str | None = None) -> int | None:
    """Return a house-free property `giver` owns that completes a monopoly for
    `partner`, or None. Such a property is safe to give away -- the giver holds
    only that single space of the group.

    `avoid_group` is the colour group the AI is itself trying to complete in
    this trade; a sweetener must never come from it, otherwise the AI gives
    away a tile of the very group it is bargaining for (for a two-property
    group that is a pointless 1-for-1 swap)."""
    for group, members in board_data.COLOR_GROUPS.items():
        if group == avoid_group:
            continue
        partner_owned = sum(1 for p in members if game.owners.get(p) == partner.index)
        if partner_owned != len(members) - 1:
            continue
        for pos in members:
            if (game.owners.get(pos) == giver.index
                    and game.houses.get(pos, 0) == 0 and pos not in game.mortgaged):
                return pos
    return None


def evaluate_offer(game: MonopolyGame, player: Player, offer: dict | None) -> bool:
    """Return True if `player` should accept the trade `offer`."""
    if offer is None or not game.trade_is_legal(offer):
        return False
    if player.index not in (offer["from"], offer["to"]):
        return False
    return _trade_swing(game, player, offer) >= _profile(game).trade_accept_margin


def _trade_swing(game: MonopolyGame, evaluator: Player, offer: dict) -> int:
    """Estimate how much the trade is worth to `evaluator` (may be negative).

    Raw asset values are compared, then big adjustments are applied: gaining a
    completed monopoly is a large plus, and handing the other player one is a
    real cost.
    """
    if offer["to"] == evaluator.index:
        incoming, outgoing = offer["give"], offer["get"]
        opponent = game.players[offer["from"]]
    else:
        incoming, outgoing = offer["get"], offer["give"]
        opponent = game.players[offer["to"]]

    swing = _bundle_value(game, incoming) - _bundle_value(game, outgoing)
    for pos in incoming["props"]:
        # The evaluator gains `incoming` but gives away `outgoing` -- a tile
        # being traded away must not still count toward a monopoly.
        if _completes_group_with(game, evaluator, pos, incoming["props"],
                                 outgoing["props"]):
            swing += game.board[pos].price * 2
    for pos in outgoing["props"]:
        if _completes_group_with(game, opponent, pos, outgoing["props"],
                                 incoming["props"]):
            swing -= game.board[pos].price
    return swing


def _bundle_value(game: MonopolyGame, bundle: dict) -> int:
    """The plain asset value of one side of a trade (cash + property + cards)."""
    total = bundle["cash"] + bundle["jail"] * 50
    for pos in bundle["props"]:
        space = game.board[pos]
        if pos in game.mortgaged:
            # The receiver owes the immediate interest on a mortgaged title.
            total += space.mortgage - space.mortgage // 10
        else:
            total += property_value(game, game.players[game.owners[pos]], pos)
    return total


# --------------------------------------------------------------------------
# Small shared helpers
# --------------------------------------------------------------------------
def _group_of(game: MonopolyGame, position: int) -> str | None:
    """The colour group of a street, or None for non-streets."""
    space = game.board[position]
    return space.group if space.kind == "street" else None


def _owns_some_of_group(game: MonopolyGame, player: Player, position: int) -> bool:
    """True if `player` already owns at least one space in this street's group."""
    group = _group_of(game, position)
    if not group:
        return False
    return any(game.owners.get(pos) == player.index
               for pos in board_data.COLOR_GROUPS[group])


def _in_monopoly(game: MonopolyGame, player: Player, position: int) -> bool:
    """True if `position` is part of a colour group `player` fully owns."""
    group = _group_of(game, position)
    return group is not None and game.has_monopoly(player, group)


def _completes_group(game: MonopolyGame, player: Player, position: int) -> bool:
    """True if buying `position` would complete a colour group for `player`."""
    group = _group_of(game, position)
    if not group:
        return False
    members = board_data.COLOR_GROUPS[group]
    owned = sum(1 for pos in members if game.owners.get(pos) == player.index)
    return owned == len(members) - 1


def _completes_group_with(game: MonopolyGame, player: Player, position: int,
                          extra_positions, removed_positions=()) -> bool:
    """Like `_completes_group`, but for a trade in flight.

    `extra_positions` are titles coming IN to `player` (not owned yet, but
    will be); `removed_positions` are titles going OUT (owned now, but won't
    be after the trade). A member only counts if `player` gains it or keeps
    it -- otherwise valuing a swap would credit a monopoly the player has
    just traded half of away.
    """
    group = _group_of(game, position)
    if not group:
        return False
    members = board_data.COLOR_GROUPS[group]
    owned = 0
    for pos in members:
        gained = pos in extra_positions
        kept = (game.owners.get(pos) == player.index
                and pos not in removed_positions)
        if gained or kept:
            owned += 1
    return owned == len(members)
