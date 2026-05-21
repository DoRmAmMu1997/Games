"""Screens, panels, buttons and dialogs -- everything drawn outside the board.

This module is pure presentation plus a small `Button` helper and layout
helpers. It never changes game state; `main.py` reads clicks and calls the
engine. Keeping it that way means the same engine drives both the UI and the
headless AI tests.
"""

from __future__ import annotations

import pygame

import board_data
from cards import format_card_text
from settings import (
    BG, DANGER, GOLD, GROUP_COLORS, HIGHLIGHT, INK, PANEL_BG, PANEL_CARD,
    PANEL_WIDTH, PANEL_X, SCREEN_HEIGHT, SCREEN_WIDTH, SOFT, SUCCESS,
    TOKEN_COLORS, TOKEN_NAMES, WHITE,
)


# --------------------------------------------------------------------------
# Fonts and buttons
# --------------------------------------------------------------------------
def make_fonts() -> dict:
    """Create every font the game uses (called once, after pygame.init)."""
    return {
        "tile": pygame.font.SysFont("arial", 12),
        "tiny": pygame.font.SysFont("arial", 14),
        "small": pygame.font.SysFont("arial", 17),
        "med": pygame.font.SysFont("arial", 21, bold=True),
        "big": pygame.font.SysFont("arial", 30, bold=True),
        "huge": pygame.font.SysFont("arial", 52, bold=True),
        "title": pygame.font.SysFont("arial", 60, bold=True),
    }


class Button:
    """A clickable rectangle with a label and a string `key` identifying it."""

    def __init__(self, rect, label, key, enabled=True, color=None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.key = key            # e.g. "roll", "buy", "end_turn"
        self.enabled = enabled
        self.color = color or (54, 86, 72)

    def draw(self, surface, fonts, mouse) -> None:
        """Draw the button, brightening it slightly while hovered."""
        hovered = self.enabled and self.rect.collidepoint(mouse)
        fill = self.color if self.enabled else (44, 52, 48)
        if hovered:
            fill = tuple(min(255, c + 28) for c in fill)
        pygame.draw.rect(surface, fill, self.rect, border_radius=8)
        pygame.draw.rect(surface, INK, self.rect, 2, border_radius=8)
        ink = WHITE if self.enabled else SOFT
        glyph = fonts["small"].render(self.label, True, ink)
        surface.blit(glyph, glyph.get_rect(center=self.rect.center))

    def hit(self, pos) -> bool:
        """True if `pos` is inside an enabled button."""
        return self.enabled and self.rect.collidepoint(pos)


def _text(surface, fonts, key, text, pos, color=WHITE, center=False):
    """Small helper: render one line of text and blit it."""
    glyph = fonts[key].render(text, True, color)
    rect = glyph.get_rect(center=pos) if center else glyph.get_rect(topleft=pos)
    surface.blit(glyph, rect)
    return rect


# --------------------------------------------------------------------------
# Setup screen
# --------------------------------------------------------------------------
def setup_buttons(has_save: bool) -> list:
    """Build the clickable buttons for the setup screen."""
    buttons = [
        # The right-hand stepper buttons sit far enough out so even the
        # widest theme name ("World Landmarks") fits between them.
        Button((90, 250, 44, 44), "-", "humans_down"),
        Button((380, 250, 44, 44), "+", "humans_up"),
        Button((90, 380, 44, 44), "<", "theme_prev"),
        Button((380, 380, 44, 44), ">", "theme_next"),
        Button((90, 470, 320, 56), "Start Game", "start", color=(46, 116, 78)),
        # A way out of the setup screen without closing the window.
        Button((SCREEN_WIDTH - 160, 30, 130, 40), "Quit", "quit",
               color=(120, 60, 60)),
    ]
    if has_save:
        buttons.append(Button((90, 540, 320, 50), "Resume Saved Game",
                              "resume", color=(58, 92, 140)))
    return buttons


def setup_name_field_rect(i: int) -> pygame.Rect:
    """Screen rect of the i-th human-player name box on the setup screen."""
    return pygame.Rect(620, 393 + i * 50, 330, 38)


def draw_setup(surface, fonts, human_count, theme_key, buttons, mouse,
               stats, name_fields, active_field) -> None:
    """Draw the new-game setup screen."""
    surface.fill(BG)
    _text(surface, fonts, "title", "MONOPOLY", (SCREEN_WIDTH // 2, 110),
          GOLD, center=True)
    _text(surface, fonts, "small",
          "Four players. Choose how many are human -- the rest are AI.",
          (SCREEN_WIDTH // 2, 165), SOFT, center=True)

    _text(surface, fonts, "med", "Human players", (90, 215))
    # Centre the digit and theme name between their stepper buttons so they
    # never overlap the arrows, however long the theme name is.
    _text(surface, fonts, "huge", str(human_count), (257, 272), WHITE, center=True)

    _text(surface, fonts, "med", "Board", (90, 345))
    theme_name = board_data.THEMES[theme_key]["name"]
    _text(surface, fonts, "big", theme_name, (257, 402), GOLD, center=True)

    _draw_setup_info_panel(surface, fonts, stats, human_count,
                           name_fields, active_field)

    for button in buttons:
        button.draw(surface, fonts, mouse)


def _draw_setup_info_panel(surface, fonts, stats, human_count,
                           name_fields, active_field) -> None:
    """Draw the right-hand panel: lifetime stats on top, name boxes below."""
    panel = pygame.Rect(470, 205, 720, 410)
    pygame.draw.rect(surface, PANEL_CARD, panel, border_radius=10)
    pygame.draw.rect(surface, INK, panel, 1, border_radius=10)

    # Lifetime stats -- already loaded from stats.json, just never shown before.
    _text(surface, fonts, "med", "Lifetime Stats",
          (panel.x + 26, panel.y + 16), GOLD)
    games = stats.get("games", 0)
    wins = stats.get("human_wins", 0)
    rate = f"{round(100 * wins / games)}%" if games else "0%"
    for row, label in enumerate((f"Games played:  {games}",
                                 f"Human wins:  {wins}",
                                 f"Win rate:  {rate}")):
        _text(surface, fonts, "small", label,
              (panel.x + 26, panel.y + 52 + row * 26), WHITE)

    # One name box per human player; AI players are auto-named.
    _text(surface, fonts, "med", "Player Names",
          (panel.x + 26, panel.y + 146), GOLD)
    for i in range(human_count):
        box = setup_name_field_rect(i)
        _text(surface, fonts, "small", f"Human {i + 1}",
              (panel.x + 26, box.y + 10), SOFT)
        focused = active_field == i
        pygame.draw.rect(surface, PANEL_BG, box, border_radius=6)
        pygame.draw.rect(surface, GOLD if focused else INK, box,
                         2, border_radius=6)
        text = name_fields[i]
        _text(surface, fonts, "small", text, (box.x + 10, box.y + 10), WHITE)
        if focused:
            caret_x = box.x + 12 + fonts["small"].size(text)[0]
            pygame.draw.line(surface, WHITE, (caret_x, box.y + 9),
                             (caret_x, box.y + 29), 2)


# --------------------------------------------------------------------------
# In-game side panel
# --------------------------------------------------------------------------
def draw_panel(surface, fonts, game, mouse) -> None:
    """Draw the right-hand information panel: player cards and the event log."""
    panel = pygame.Rect(PANEL_X, 0, PANEL_WIDTH + 20, SCREEN_HEIGHT)
    pygame.draw.rect(surface, PANEL_BG, panel)

    card_h = 118
    for i, player in enumerate(game.players):
        rect = pygame.Rect(PANEL_X + 6, 10 + i * (card_h + 6), PANEL_WIDTH + 8, card_h)
        _draw_player_card(surface, fonts, game, player, rect, i == game.current)

    log_top = 10 + 4 * (card_h + 6) + 8
    _draw_log(surface, fonts, game, pygame.Rect(PANEL_X + 6, log_top,
                                                PANEL_WIDTH + 8, 150))


def _draw_player_card(surface, fonts, game, player, rect, is_current) -> None:
    """Draw one player's summary card in the side panel."""
    bg = PANEL_CARD if not is_current else (52, 74, 60)
    pygame.draw.rect(surface, bg, rect, border_radius=8)
    border = HIGHLIGHT if is_current else INK
    pygame.draw.rect(surface, border, rect, 3 if is_current else 1, border_radius=8)

    # Token swatch and name.
    pygame.draw.circle(surface, player.token_color, (rect.x + 24, rect.y + 26), 14)
    pygame.draw.circle(surface, INK, (rect.x + 24, rect.y + 26), 14, 2)
    name_color = SOFT if player.bankrupt else WHITE
    _text(surface, fonts, "med", player.name, (rect.x + 48, rect.y + 12), name_color)

    if player.bankrupt:
        _text(surface, fonts, "small", "BANKRUPT", (rect.x + 48, rect.y + 40), DANGER)
        return

    _text(surface, fonts, "med", f"${player.cash}", (rect.x + 48, rect.y + 38), SUCCESS)
    tag = "AI" if not player.is_human else "You"
    _text(surface, fonts, "tiny", tag, (rect.right - 44, rect.y + 14), SOFT)
    if player.in_jail:
        _text(surface, fonts, "tiny", "IN JAIL", (rect.right - 70, rect.y + 36), DANGER)

    # A row of small swatches, one per property, grouped by colour.
    owned = sorted(game.properties_of(player))
    swatch_x = rect.x + 12
    swatch_y = rect.y + 70
    for pos in owned:
        space = game.board[pos]
        if space.kind == "street":
            color = GROUP_COLORS[space.group]
        elif space.kind == "railroad":
            color = (60, 62, 66)
        else:
            color = (150, 165, 172)
        pygame.draw.rect(surface, color, (swatch_x, swatch_y, 14, 20))
        pygame.draw.rect(surface, INK, (swatch_x, swatch_y, 14, 20), 1)
        if pos in game.mortgaged:
            pygame.draw.line(surface, DANGER, (swatch_x, swatch_y),
                             (swatch_x + 14, swatch_y + 20), 2)
        swatch_x += 17
        if swatch_x > rect.right - 20:
            swatch_x = rect.x + 12
            swatch_y += 24

    monopolies = sum(1 for g in board_data.COLOR_GROUPS
                     if game.has_monopoly(player, g))
    if monopolies:
        _text(surface, fonts, "tiny", f"Monopolies: {monopolies}",
              (rect.right - 116, rect.bottom - 22), GOLD)


def _draw_log(surface, fonts, game, rect) -> None:
    """Draw the most recent game events."""
    pygame.draw.rect(surface, PANEL_CARD, rect, border_radius=8)
    pygame.draw.rect(surface, INK, rect, 1, border_radius=8)
    _text(surface, fonts, "small", "Game Log", (rect.x + 10, rect.y + 6), GOLD)
    visible = game.log[-7:]
    for i, line in enumerate(visible):
        glyph = fonts["tiny"].render(line[:46], True, SOFT)
        surface.blit(glyph, (rect.x + 10, rect.y + 30 + i * 17))


# --------------------------------------------------------------------------
# Board-centre widgets: dice and the current card
# --------------------------------------------------------------------------
def draw_dice(surface, fonts, dice, center) -> None:
    """Draw the two dice at `center` with their pip patterns."""
    size = 52
    gap = 16
    total_w = size * 2 + gap
    x0 = center[0] - total_w // 2
    y0 = center[1] - size // 2
    for d, value in enumerate(dice):
        rect = pygame.Rect(x0 + d * (size + gap), y0, size, size)
        pygame.draw.rect(surface, WHITE, rect, border_radius=10)
        pygame.draw.rect(surface, INK, rect, 2, border_radius=10)
        _draw_pips(surface, rect, value)


def _draw_pips(surface, rect, value) -> None:
    """Draw the 1-6 pip pattern of one die face."""
    cx, cy = rect.center
    ox, oy = rect.width // 4, rect.height // 4
    spots = {
        1: [(0, 0)],
        2: [(-1, -1), (1, 1)],
        3: [(-1, -1), (0, 0), (1, 1)],
        4: [(-1, -1), (1, -1), (-1, 1), (1, 1)],
        5: [(-1, -1), (1, -1), (0, 0), (-1, 1), (1, 1)],
        6: [(-1, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (1, 1)],
    }.get(value, [])
    for sx, sy in spots:
        pygame.draw.circle(surface, INK, (cx + sx * ox, cy + sy * oy), 5)


def draw_center_card(surface, fonts, game) -> None:
    """Draw the most recently drawn Chance / Community Chest card."""
    if game.last_card is None:
        return
    panel = pygame.Rect(0, 0, 320, 120)
    panel.center = (220 + 90, 360 + 90)  # roughly the board centre, upper area
    panel.center = (20 + (SCREEN_HEIGHT - 40) // 2, 20 + (SCREEN_HEIGHT - 40) // 2 - 150)
    deck = game.last_card["deck"]
    bg = (70, 96, 150) if deck == "chance" else (150, 110, 60)
    pygame.draw.rect(surface, bg, panel, border_radius=10)
    pygame.draw.rect(surface, INK, panel, 2, border_radius=10)
    title = "CHANCE" if deck == "chance" else "COMMUNITY CHEST"
    _text(surface, fonts, "small", title, (panel.centerx, panel.y + 16),
          GOLD, center=True)
    words = format_card_text(game.last_card, game.board)
    _blit_wrapped(surface, fonts["tiny"], words, panel.inflate(-24, -44), WHITE)


def _blit_wrapped(surface, font, text, rect, color) -> None:
    """Word-wrap `text` inside `rect` and draw it."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if font.size(trial)[0] <= rect.width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    for i, line in enumerate(lines):
        glyph = font.render(line, True, color)
        surface.blit(glyph, (rect.x, rect.y + i * 18))


# --------------------------------------------------------------------------
# Action bar
# --------------------------------------------------------------------------
def draw_action_bar(surface, fonts, buttons, prompt, mouse) -> None:
    """Draw the bottom action bar: a prompt strip and the button bar.

    The prompt and the buttons sit in two SEPARATE rects so a button can
    never cover the prompt text: a slim prompt strip lives in the gap above
    the bar (between the event log and the button rows), and the button bar
    sits at its original position so every button -- including the final
    "Save & Quit" -- stays inside the visible 880-pixel window even on
    displays that show slightly less than the full screen.
    """
    # Slim prompt strip, just above the bar. One line of text fits; longer
    # prompts get truncated rather than wrapped under a button.
    prompt_strip = pygame.Rect(PANEL_X + 6, SCREEN_HEIGHT - 214,
                               PANEL_WIDTH + 8, 26)
    pygame.draw.rect(surface, PANEL_CARD, prompt_strip, border_radius=8)
    pygame.draw.rect(surface, INK, prompt_strip, 1, border_radius=8)
    _blit_wrapped(surface, fonts["small"], prompt,
                  pygame.Rect(prompt_strip.x + 12, prompt_strip.y + 4,
                              prompt_strip.width - 24, 20), WHITE)

    bar = pygame.Rect(PANEL_X + 6, SCREEN_HEIGHT - 184, PANEL_WIDTH + 8, 178)
    pygame.draw.rect(surface, PANEL_CARD, bar, border_radius=8)
    pygame.draw.rect(surface, INK, bar, 1, border_radius=8)
    for button in buttons:
        button.draw(surface, fonts, mouse)


# --------------------------------------------------------------------------
# Auction overlay
# --------------------------------------------------------------------------
def draw_auction(surface, fonts, game, buttons, mouse) -> None:
    """Draw the auction dialog over the board."""
    _dim(surface)
    panel = pygame.Rect(0, 0, 460, 280)
    panel.center = (SCREEN_HEIGHT // 2, SCREEN_HEIGHT // 2)
    pygame.draw.rect(surface, PANEL_BG, panel, border_radius=12)
    pygame.draw.rect(surface, GOLD, panel, 3, border_radius=12)
    auction = game.auction
    space = game.board[auction["position"]]
    _text(surface, fonts, "big", "AUCTION", (panel.centerx, panel.y + 30),
          GOLD, center=True)
    _text(surface, fonts, "med", space.name, (panel.centerx, panel.y + 72),
          WHITE, center=True)
    _text(surface, fonts, "small", f"List price ${space.price}",
          (panel.centerx, panel.y + 102), SOFT, center=True)
    high = auction["high_bid"]
    bidder = auction["high_bidder"]
    bid_text = (f"High bid ${high} by {game.players[bidder].name}"
                if bidder is not None else "No bids yet")
    _text(surface, fonts, "med", bid_text, (panel.centerx, panel.y + 138),
          SUCCESS, center=True)
    _text(surface, fonts, "small",
          f"{game.players[auction['current']].name} to bid",
          (panel.centerx, panel.y + 170), WHITE, center=True)
    for button in buttons:
        button.draw(surface, fonts, mouse)


# --------------------------------------------------------------------------
# Trade overlay
# --------------------------------------------------------------------------
#: How many property rows are visible per side at once before the user has
#: to scroll. Set so the 15th row's bottom stays well above the cash labels
#: drawn at panel.bottom - 132.
TRADE_VISIBLE_ROWS = 15


def trade_layout(game, trade) -> dict:
    """Compute the clickable rectangles of the trade dialog.

    `trade` is the in-progress offer being built by a human. Returning the
    rectangles here lets both the drawing code and the click handler agree on
    the layout. The two side lists honour the per-side scroll offsets
    (`give_scroll` / `get_scroll`) so the rendered rows match the clickable
    rows even when the player owns more properties than fit on screen.
    """
    panel = pygame.Rect(0, 0, 800, 700)
    panel.center = (SCREEN_HEIGHT // 2, SCREEN_HEIGHT // 2)
    human = game.players[trade["from"]]
    partner = game.players[trade["to"]]
    layout = {
        "panel": panel,
        "give_rows": [],
        "get_rows": [],
        "give_more_above": False,
        "give_more_below": False,
        "get_more_above": False,
        "get_more_below": False,
    }
    for side, key, owner, x in (("give", "give_rows", human, panel.x + 30),
                                ("get", "get_rows", partner, panel.x + 420)):
        props = sorted(game.properties_of(owner))
        # Clamp the stored scroll: properties might have shrunk since the
        # last scroll (e.g. a partner cycle), and an out-of-bounds offset
        # would silently hide rows the player still owns.
        max_scroll = max(0, len(props) - TRADE_VISIBLE_ROWS)
        scroll = max(0, min(trade.get(f"{side}_scroll", 0), max_scroll))
        layout[f"{side}_more_above"] = scroll > 0
        layout[f"{side}_more_below"] = scroll + TRADE_VISIBLE_ROWS < len(props)
        visible_props = props[scroll : scroll + TRADE_VISIBLE_ROWS]
        for i, pos in enumerate(visible_props):
            row = pygame.Rect(x, panel.y + 150 + i * 26, 340, 24)
            layout[key].append((row, pos))
    return layout


def draw_trade(surface, fonts, game, trade, buttons, mouse) -> None:
    """Draw the trade-building dialog."""
    _dim(surface)
    layout = trade_layout(game, trade)
    panel = layout["panel"]
    pygame.draw.rect(surface, PANEL_BG, panel, border_radius=12)
    pygame.draw.rect(surface, GOLD, panel, 3, border_radius=12)
    human = game.players[trade["from"]]
    partner = game.players[trade["to"]]

    _text(surface, fonts, "big", "PROPOSE A TRADE",
          (panel.centerx, panel.y + 26), GOLD, center=True)
    _text(surface, fonts, "med", f"With:  {partner.name}",
          (panel.centerx, panel.y + 67), WHITE, center=True)
    # Showing the partner's cash helps the human size up a fair counter-offer.
    _text(surface, fonts, "small", f"They hold ${partner.cash}",
          (panel.centerx, panel.y + 92), SOFT, center=True)
    _text(surface, fonts, "small", "You give", (panel.x + 30, panel.y + 120), SUCCESS)
    _text(surface, fonts, "small", "You receive", (panel.x + 420, panel.y + 120), SUCCESS)

    # Each row is a checkbox + property name. Unselected rows draw NO fill so
    # they sit invisibly on the panel background -- that, plus an empty box,
    # makes it clear nothing is selected until the player ticks something.
    for key, chosen in (("give_rows", trade["give"]["props"]),
                        ("get_rows", trade["get"]["props"])):
        for row, pos in layout[key]:
            picked = pos in chosen
            if picked:
                pygame.draw.rect(surface, (58, 92, 70), row, border_radius=4)
                pygame.draw.rect(surface, GOLD, row, 1, border_radius=4)
            # A small checkbox at the left makes selection state unambiguous.
            box = pygame.Rect(row.x + 6, row.y + 5, 14, 14)
            pygame.draw.rect(surface, PANEL_BG, box)
            pygame.draw.rect(surface, GOLD if picked else SOFT, box, 2)
            if picked:
                pygame.draw.rect(surface, GOLD, box.inflate(-6, -6))
            _text(surface, fonts, "tiny", game.board[pos].name[:30],
                  (row.x + 28, row.y + 4), WHITE)

    # Scroll indicators -- small gold triangles drawn above/below a column
    # when more rows are hidden in that direction. Mouse wheel scrolls the
    # side under the cursor; the glyph is the only hint the user gets that
    # there is anything off-screen.
    _draw_trade_scroll_glyphs(surface, layout, "give", panel.x + 30 + 170)
    _draw_trade_scroll_glyphs(surface, layout, "get", panel.x + 420 + 170)

    _text(surface, fonts, "small",
          f"Cash you give: ${trade['give']['cash']}",
          (panel.x + 30, panel.bottom - 132), WHITE)
    _text(surface, fonts, "small",
          f"Cash you receive: ${trade['get']['cash']}",
          (panel.x + 420, panel.bottom - 132), WHITE)
    for button in buttons:
        button.draw(surface, fonts, mouse)


def _draw_trade_scroll_glyphs(surface, layout, side: str, cx: int) -> None:
    """Draw small upward/downward triangles when a trade column is scrolled.

    The triangles sit just above the first row and just below the last
    visible row, on the column centred at `cx`. Drawn in `GOLD` so they read
    as 'there is more here' without competing with the row text.
    """
    panel = layout["panel"]
    if layout.get(f"{side}_more_above"):
        top_y = panel.y + 150 - 8
        pygame.draw.polygon(
            surface, GOLD,
            [(cx, top_y - 4), (cx - 6, top_y + 4), (cx + 6, top_y + 4)])
    if layout.get(f"{side}_more_below"):
        last_row_bottom = panel.y + 150 + TRADE_VISIBLE_ROWS * 26
        bot_y = last_row_bottom + 4
        pygame.draw.polygon(
            surface, GOLD,
            [(cx, bot_y + 4), (cx - 6, bot_y - 4), (cx + 6, bot_y - 4)])


# --------------------------------------------------------------------------
# Trade response + game over
# --------------------------------------------------------------------------
def draw_trade_response(surface, fonts, game, buttons, mouse) -> None:
    """Draw the dialog asking a human to accept or reject an offer."""
    _dim(surface)
    panel = pygame.Rect(0, 0, 560, 360)
    panel.center = (SCREEN_HEIGHT // 2, SCREEN_HEIGHT // 2)
    pygame.draw.rect(surface, PANEL_BG, panel, border_radius=12)
    pygame.draw.rect(surface, GOLD, panel, 3, border_radius=12)
    offer = game.pending_trade
    proposer = game.players[offer["from"]]
    _text(surface, fonts, "big", "TRADE OFFER", (panel.centerx, panel.y + 26),
          GOLD, center=True)
    _text(surface, fonts, "small", f"{proposer.name} offers you:",
          (panel.x + 30, panel.y + 70), WHITE)

    you_get = offer["give"]      # what the proposer gives = what you receive
    you_give = offer["get"]
    y = panel.y + 100
    _text(surface, fonts, "small", "You receive:", (panel.x + 30, y), SUCCESS)
    y += 24
    for pos in you_get["props"]:
        _text(surface, fonts, "tiny", "- " + game.board[pos].name, (panel.x + 44, y))
        y += 18
    if you_get["cash"]:
        _text(surface, fonts, "tiny", f"- ${you_get['cash']} cash", (panel.x + 44, y))
        y += 18
    y += 8
    _text(surface, fonts, "small", "You give:", (panel.x + 30, y), DANGER)
    y += 24
    for pos in you_give["props"]:
        _text(surface, fonts, "tiny", "- " + game.board[pos].name, (panel.x + 44, y))
        y += 18
    if you_give["cash"]:
        _text(surface, fonts, "tiny", f"- ${you_give['cash']} cash", (panel.x + 44, y))
    for button in buttons:
        button.draw(surface, fonts, mouse)


def draw_game_over(surface, fonts, game, buttons, mouse) -> None:
    """Draw the end screen announcing the winner."""
    surface.fill(BG)
    _text(surface, fonts, "huge", "GAME OVER", (SCREEN_WIDTH // 2, 150),
          GOLD, center=True)
    if game.winner is not None:
        champ = game.players[game.winner]
        _text(surface, fonts, "big", f"{champ.name} wins!",
              (SCREEN_WIDTH // 2, 240), champ.token_color, center=True)
    # Final standings by net worth.
    ranked = sorted(game.players, key=game.net_worth, reverse=True)
    for i, player in enumerate(ranked):
        line = f"{i + 1}.  {player.name}    net worth ${game.net_worth(player)}"
        color = SOFT if player.bankrupt else WHITE
        _text(surface, fonts, "med", line, (SCREEN_WIDTH // 2, 320 + i * 40),
              color, center=True)
    for button in buttons:
        button.draw(surface, fonts, mouse)


def _dim(surface) -> None:
    """Darken the whole screen behind a modal dialog."""
    veil = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    veil.fill((0, 0, 0, 150))
    surface.blit(veil, (0, 0))


# --------------------------------------------------------------------------
# Confirmation modal (used by the setup screen's overwrite-save guard)
# --------------------------------------------------------------------------
def confirm_panel_rect() -> pygame.Rect:
    """The centred rect of the yes/no confirmation modal."""
    panel = pygame.Rect(0, 0, 520, 220)
    panel.center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
    return panel


def confirm_buttons() -> list:
    """The Yes / Cancel buttons for the confirmation modal."""
    panel = confirm_panel_rect()
    y = panel.bottom - 62
    return [
        Button((panel.centerx - 170, y, 160, 46), "Yes, start",
               "confirm_new_yes", color=(46, 116, 78)),
        Button((panel.centerx + 10, y, 160, 46), "Cancel",
               "confirm_new_no", color=(120, 60, 60)),
    ]


def draw_confirm(surface, fonts, lines, buttons, mouse) -> None:
    """Draw a centred yes/no confirmation modal over the current screen."""
    _dim(surface)
    panel = confirm_panel_rect()
    pygame.draw.rect(surface, PANEL_BG, panel, border_radius=12)
    pygame.draw.rect(surface, GOLD, panel, 3, border_radius=12)
    for i, line in enumerate(lines):
        _text(surface, fonts, "med", line,
              (panel.centerx, panel.y + 48 + i * 32), WHITE, center=True)
    for button in buttons:
        button.draw(surface, fonts, mouse)
