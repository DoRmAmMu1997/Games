# Monopoly

A full desktop **Monopoly** game built in Python with `pygame-ce`. Four
players, with **1-4 human players** (the rest are AI), standard Monopoly rules,
three themed boards, auctions, trading, and save & resume.

## Project Structure

- `main.py` -- pygame window, run loop, input routing, and the AI driver.
- `settings.py` -- constants: window layout, colours, AI tuning, save paths.
- `board_data.py` -- the canonical 40-space board (one set of rules data) and
  the three theme name lists.
- `cards.py` -- the Chance and Community Chest decks plus card effects.
- `player.py` -- the Player model (cash, position, jail state, ...).
- `game.py` -- the **rules engine**: turn flow, dice, rent, auctions, building,
  trading, bankruptcy, win detection. UI-agnostic by design.
- `ai.py` -- AI decisions: buy, auction bid, build, mortgage, jail strategy,
  and trade proposal + evaluation.
- `board_render.py` -- procedural drawing of the board, tokens, and buildings.
- `ui.py` -- screens, panels, dice, buttons, and dialogs.
- `requirements.txt`, `Monopoly Game.spec` -- runtime dependency and build recipe.

## Requirements

- Python 3.11 or newer.
- `pygame-ce`.

Install dependencies once with:

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## How to Play

On the setup screen, choose **how many human players** there are (1-4 -- the
rest are AI) and which **board theme** to play on, then click **Start Game**.
If a saved game exists, **Resume Saved Game** picks it up where you left off.

Each player begins with **$1500**. Take turns rolling two dice, moving around
the board, buying properties, and trying to bankrupt everyone else.

- **Buy** any unowned property you land on -- or send it to **auction** so
  everyone may bid.
- Collect **rent** when others land on your property; rent on a complete
  colour group is double, and houses make it much more.
- Once you own a **complete colour group**, build **houses** (and finally a
  hotel) to make landing there expensive.
- **Mortgage** properties when short on cash; pay back with 10% interest.
- **Trade** properties, cash, and Get Out of Jail Free cards with any other
  player.
- Land on **Go To Jail** (or roll three doubles, or draw the jail card) and
  you go to jail; pay $50, use a jail card, or roll for doubles to get out.
- Pass **GO** to collect $200.
- Last player not bankrupt **wins**.

## Controls

- **Setup screen:** click `+` / `-` to set the number of humans, `<` / `>` to
  cycle the board theme, then **Start Game**.
- **During play:** the action bar on the right shows the buttons available to
  the current human player -- **Roll Dice**, **Buy**, **Auction**, **Build
  Houses**, **Mortgage**, **Trade**, **End Turn**, etc.
- **Building / mortgaging** opens a click-on-the-board mode: click any
  buildable (or mortgageable) property to act on it, then **Done**.
- **Auctions** open their own dialog with a **Bid +$X** button and **Pass**.
- **Trades** open a dialog where you cycle through partners with `<` / `>`,
  click property rows to add or remove them from each side, step the cash
  with the `+$50` / `-$50` buttons, then **Propose** or **Cancel**.
- AI turns play themselves with a short pause between actions so a human can
  follow along.

## Themes

Three boards ship with the game. They share the standard Monopoly prices and
rents -- only the names change.

- **Classic US** -- the Atlantic City names every Monopoly player knows.
- **London** -- the original British edition.
- **World Landmarks** -- iconic landmarks worldwide, from Hadrian's Wall to
  the Eiffel Tower.

## Features

- **Standard Monopoly rules** -- houses, hotels, mortgages, Chance and
  Community Chest, jail and Go To Jail, taxes, bankruptcy, and the win check.
- **Auctions** when a player declines an unowned property.
- **Player and AI trading** -- properties, cash and Get Out of Jail Free
  cards.
- **Save & resume** -- save an in-progress game and continue later.
- **Challenging heuristic AI** -- the computer players buy aggressively,
  complete colour groups, build on them, manage cash, bid in auctions and
  propose monopoly-completing trades. Tough for casual play.
- **Polished procedural graphics** -- the board, tokens, and dice are all
  drawn from code; no image files are needed.

## Save Data

Lifetime stats and the in-progress save live in:

```
%APPDATA%\Monopoly\
    stats.json       lifetime games played and human wins
    savegame.json    one in-progress saved game (if "Save & Quit" was used)
```

This per-user location is used whether you run the script or a compiled
`.exe`, so progress survives across sessions and moving the `.exe`.

## Build a Standalone .exe

The game can be packaged into a single Windows executable with
[PyInstaller](https://pyinstaller.org/).

1. Install PyInstaller (only needed once):

```bash
pip install pyinstaller
```

2. From this folder (`Python Monopoly Game`), build using the bundled spec
   file:

```bash
pyinstaller "Monopoly Game.spec"
```

3. The finished program is written to `dist\Monopoly Game.exe`. Copy that
   file anywhere you like and double-click it to play.

The spec produces a single-file, windowed executable. Because the save data
lives in `%APPDATA%`, the high score and stats persist no matter where the
`.exe` is moved.

## Notes on the AI

The computer players are **heuristic**, not optimal. They:

- buy almost any property they land on when cash allows, with a small cushion;
- bid up to roughly a property's value at auction (and well above if the
  property completes one of their colour groups);
- once they own a complete group, build houses evenly while keeping cash in
  reserve;
- mortgage low-value land first when forced to raise money;
- pay or use a card to escape jail in the early game when there is still
  land to grab, and stay in jail late;
- propose trades that complete a colour group for them -- preferring swaps
  that *also* complete a group for the partner (mutual monopolies are gold).

They are tough for a casual player; the kind of decisive, monopoly-driven
Monopoly games most house games settle into.
