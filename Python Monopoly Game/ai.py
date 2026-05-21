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

import board_data
from settings import JAIL_FINE

# Colour groups roughly ordered by how rewarding they are to develop -- the
# orange and red streets are landed on most often, so the AI builds them first.
GROUP_BUILD_PRIORITY = [
    "orange", "red", "yellow", "light_blue", "pink", "green", "dark_blue", "brown",
]


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


def _profile(game) -> AIProfile:
    """Return the named game-wide AI profile, falling back to standard."""
    return AI_PROFILES.get(getattr(game, "ai_profile", "standard"),
                           AI_PROFILES["standard"])


def _trace(game, player, message: str) -> None:
    """Leave one compact explainable AI decision in the shared event log."""
    game._note(f"{player.name}: {message}")


def property_value(game, player, position, profile: AIProfile | None = None) -> int:
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
        value += space.rent[-1] * 0.08
        if _completes_group(game, player, position):
            value *= 2.35
        elif _owns_some_of_group(game, player, position):
            value *= 1.32
        elif any(_completes_group(game, opponent, position)
                 for opponent in game.other_players(player)):
            value *= 1.0 + profile.blocker_bonus
    elif space.kind == "railroad":
        value *= 1.0 + 0.28 * game.count_railroads(player)
    elif space.kind == "utility":
        value *= 1.12 if game.count_utilities(player) else 0.95

    return max(space.mortgage, int(round(value * profile.value_scale)))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def take_action(game) -> None:
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
def _do_pre_roll(game, player) -> None:
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


def _do_post_roll(game, player) -> None:
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


def _handle_jail(game, player) -> None:
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


def _best_build(game, player):
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


def _best_unmortgage(game, player):
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
        cost = int(round(game.board[pos].mortgage * 1.1))
        if player.cash - cost >= _profile(game).cash_cushion:
            return pos
    return None


# --------------------------------------------------------------------------
# Buying a property you landed on
# --------------------------------------------------------------------------
def _do_buy_decision(game, player) -> None:
    """Decide whether to buy the space just landed on, or send it to auction."""
    position = game.pending_purchase
    if _wants_to_buy(game, player, position):
        _trace(game, player, f"buys {game.board[position].name}; value wins.")
        game.buy_property()
    else:
        _trace(game, player, f"sends {game.board[position].name} to auction.")
        game.decline_property()


def _wants_to_buy(game, player, position) -> bool:
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
def _do_auction(game, player) -> None:
    """Place one bid or pass in the current auction."""
    auction = game.auction
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


def _auction_ceiling(game, player, position) -> int:
    """The most this AI is willing to pay for `position` at auction."""
    profile = _profile(game)
    value = property_value(game, player, position, profile)
    # Never bid into bankruptcy -- always keep a small cushion.
    return min(value, max(0, player.cash - profile.auction_reserve))


# --------------------------------------------------------------------------
# Trading
# --------------------------------------------------------------------------
def propose_trade(game, player):
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


def _missing_one(game, player, group):
    """If `player` owns every space of `group` except one, return that space."""
    members = board_data.COLOR_GROUPS[group]
    owned = [p for p in members if game.owners.get(p) == player.index]
    missing = [p for p in members
               if game.owners.get(p) not in (player.index, None)]
    if len(owned) == len(members) - 1 and len(missing) == 1:
        return missing[0]
    return None


def _make_offer(game, player, partner, wanted):
    """Build an offer to win `wanted` that both `player` and `partner` accept."""
    give = {"props": [], "cash": 0, "jail": 0}
    get = {"props": [wanted], "cash": 0, "jail": 0}
    # The best sweetener is a property that completes a monopoly for the partner.
    swap = _property_completing_for(game, player, partner)
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


def _property_completing_for(game, giver, partner):
    """Return a house-free property `giver` owns that completes a monopoly for
    `partner`, or None. Such a property is safe to give away -- the giver holds
    only that single space of the group."""
    for group, members in board_data.COLOR_GROUPS.items():
        partner_owned = sum(1 for p in members if game.owners.get(p) == partner.index)
        if partner_owned != len(members) - 1:
            continue
        for pos in members:
            if (game.owners.get(pos) == giver.index
                    and game.houses.get(pos, 0) == 0 and pos not in game.mortgaged):
                return pos
    return None


def evaluate_offer(game, player, offer) -> bool:
    """Return True if `player` should accept the trade `offer`."""
    if offer is None or not game.trade_is_legal(offer):
        return False
    if player.index not in (offer["from"], offer["to"]):
        return False
    return _trade_swing(game, player, offer) >= _profile(game).trade_accept_margin


def _trade_swing(game, evaluator, offer) -> int:
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
        if _completes_group_with(game, evaluator, pos, incoming["props"]):
            swing += game.board[pos].price * 2
    for pos in outgoing["props"]:
        if _completes_group_with(game, opponent, pos, outgoing["props"]):
            swing -= game.board[pos].price
    return swing


def _bundle_value(game, bundle) -> int:
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
def _group_of(game, position):
    """The colour group of a street, or None for non-streets."""
    space = game.board[position]
    return space.group if space.kind == "street" else None


def _owns_some_of_group(game, player, position) -> bool:
    """True if `player` already owns at least one space in this street's group."""
    group = _group_of(game, position)
    if not group:
        return False
    return any(game.owners.get(pos) == player.index
               for pos in board_data.COLOR_GROUPS[group])


def _in_monopoly(game, player, position) -> bool:
    """True if `position` is part of a colour group `player` fully owns."""
    group = _group_of(game, position)
    return bool(group) and game.has_monopoly(player, group)


def _completes_group(game, player, position) -> bool:
    """True if buying `position` would complete a colour group for `player`."""
    group = _group_of(game, position)
    if not group:
        return False
    members = board_data.COLOR_GROUPS[group]
    owned = sum(1 for pos in members if game.owners.get(pos) == player.index)
    return owned == len(members) - 1


def _completes_group_with(game, player, position, extra_positions) -> bool:
    """Like `_completes_group`, but counting `extra_positions` as also owned.

    Used when valuing a trade: the properties coming in are not owned yet but
    would be once the trade goes through.
    """
    group = _group_of(game, position)
    if not group:
        return False
    members = board_data.COLOR_GROUPS[group]
    owned = 0
    for pos in members:
        if game.owners.get(pos) == player.index or pos in extra_positions:
            owned += 1
    return owned == len(members)
