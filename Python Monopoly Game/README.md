# Monopoly

A full desktop **Monopoly** game built in Python with `pygame-ce`. Four
players, with **1-4 human players** (the rest are AI), standard Monopoly rules,
thirteen themed boards, auctions, trading, and save & resume.

## Project Structure

- `main.py` -- pygame window, run loop, input routing, and the AI driver.
- `settings.py` -- constants: window layout, colours, AI timing, save paths.
- `board_data.py` -- the canonical 40-space board (one set of rules data) and
  the theme name lists.
- `cards.py` -- the Chance and Community Chest decks plus card effects.
- `player.py` -- the Player model (cash, position, jail state, ...).
- `game.py` -- the **rules engine**: turn flow, dice, rent, auctions, building,
  trading, bankruptcy, win detection. UI-agnostic by design.
- `ai.py` -- AI decisions: buy, auction bid, build, mortgage, jail strategy,
  and trade proposal + evaluation.
- `board_render.py` -- procedural drawing of the board, tokens, and buildings.
- `ui.py` -- screens, panels, dice, buttons, and dialogs.
- `simulation.py` -- seeded all-AI games and summary metrics for AI tuning.
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
rest are AI), which **board theme** to play on, and an AI difficulty profile,
then click **Start Game**. If a saved game exists, **Resume Saved Game** picks
it up where you left off.

Each player begins with **$1500**. Take turns rolling two dice, moving around
the board, buying properties, and trying to bankrupt everyone else.

- **Buy** any unowned property you land on -- or send it to **auction** so
  everyone may bid.
- Collect **rent** when others land on your property; rent on a complete
  colour group is double, and houses make it much more.
- Once you own a **complete colour group**, build **houses** (and finally a
  hotel) to make landing there expensive.
- Use the **Asset Manager** to inspect your titles and manage legal building,
  selling, mortgage, and unmortgage choices with the engine's reason text.
  The fast board-click build, sell, and mortgage modes are still there.
- **Trade** properties, cash, and Get Out of Jail Free cards with any other
  player.
- Land on **Go To Jail** (or roll three doubles, or draw the jail card) and
  you go to jail; pay $50, use a jail card, or roll for doubles to get out.
- Pass **GO** to collect $200.
- Last player not bankrupt **wins**.

## Controls

- **Setup screen:** click `+` / `-` to set the number of humans, use the
  theme and AI difficulty `<` / `>` steppers, then **Start Game**.
- **During play:** the action bar on the right shows the buttons available to
  the current human player -- **Roll Dice**, **Buy**, **Auction**, **Build
  Houses**, **Sell Buildings**, **Mortgage**, **Assets**, **Trade**, **End
  Turn**, etc.
- **Asset Manager:** click **Assets** to browse owned titles, read deed detail,
  see why an action is available or blocked, and build, sell, mortgage, or
  lift a mortgage from the overlay.
- **Building / selling / mortgaging** opens a click-on-the-board mode: click
  any highlighted property to act on it, then **Done**.
- **Property inspection:** hover any board space to see a deed-style summary
  in the board centre with ownership, rent, mortgage, and development detail.
- **Auctions** open their own dialog with a **Bid +$X** button and **Pass**.
- **Bankruptcy auctions** say when a released Bank title is being auctioned,
  so a chain of forced auctions has context.
- **Trades** open a dialog where you cycle through partners with `<` / `>`,
  click property rows to add or remove them from each side, step the cash
  with the `+$50` / `-$50` buttons, then **Propose** or **Cancel**. Mortgaged
  titles show the immediate transfer-interest consequence before acceptance.
- AI turns play themselves with a short pause and concise log traces for major
  buy, auction, build, mortgage, and trade decisions.
- Common human-turn keyboard shortcuts are `R` roll, `B` build, `S` sell,
  `M` mortgage, `T` trade, and `E` end turn when that action is available.

## Themes

Thirteen boards ship with the game. They share the standard Monopoly prices
and rents -- only the names change.

- **Classic US** -- the Atlantic City names every Monopoly player knows.
- **London** -- the original British edition.
- **World Landmarks** -- iconic landmarks worldwide, from Hadrian's Wall to
  the Eiffel Tower.
- **Indian city boards** -- Delhi-NCR, Mumbai, Chennai, Kolkata, Chandigarh
  Tricity, Bengaluru, Hyderabad, Pune, Lucknow, and Goa.

## Features

- **Standard Monopoly rules** -- houses, hotels, mortgages, Chance and
  Community Chest, jail and Go To Jail, taxes, bankruptcy, and the win check.
- **Auctions** when a player declines an unowned property.
- **Player and AI trading** -- properties, cash and Get Out of Jail Free
  cards.
- **Autosave plus save & resume** -- completed turns are autosaved, and
  **Save & Quit** preserves an in-progress game for later.
- **Classic-rule fixes** -- Bank bankruptcies auction released titles, sold
  buildings obey even-selling rules, and transferred mortgaged titles charge
  the new owner immediate mortgage interest.
- **Decision clarity** -- owned-title asset management shows deed detail,
  legal action reasons, mortgage-transfer consequences, and Bank bankruptcy
  auction context before the player commits.
- **Profiled heuristic AI** -- the computer players value titles from price,
  rent upside, collection progress, monopoly completion, and denial pressure;
  setup profiles make that aggression tunable.
- **Polished procedural graphics** -- the board, tokens, and dice are all
  drawn from code; no image files are needed.

## Save Data

Lifetime stats and the in-progress save live in:

```
%APPDATA%\Monopoly\
    stats.json       lifetime games played and human wins
    savegame.json    one in-progress autosave / saved game
```

This per-user location is used whether you run the script or a compiled
`.exe`, so progress survives across sessions and moving the `.exe`.

## Test and Tune

Run the focused Monopoly regression suite from the repository root:

```bash
python -m unittest discover -s "Python Monopoly Game\tests" -v
```

Run a small seeded AI batch from this folder when tuning difficulty:

```bash
python simulation.py --games 5 --profile standard --seed 1
```

The simulation summary reports completion, turns, actions, auctions, trades,
winner counts, and per-game outcomes so strategy changes can be compared.

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
- bid from a readable property valuation that prices rent upside, collection
  progress, group completion, and strategic blocking;
- once they own a complete group, build houses evenly while keeping cash in
  reserve;
- mortgage low-value land first when forced to raise money;
- pay or use a card to escape jail in the early game when there is still
  land to grab, and stay in jail late;
- propose trades that complete a colour group for them -- preferring swaps
  that *also* complete a group for the partner (mutual monopolies are gold).

`cautious`, `standard`, and `sharp` setup profiles tune reserves, bidding
aggression, blocking pressure, and trade margins without changing the rules
engine.
