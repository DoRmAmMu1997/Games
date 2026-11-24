# Monopoly

A full desktop **Monopoly** game built in Python with `pygame-ce`. Four
players, with **1-4 human players** (the rest are AI), standard Monopoly rules,
thirteen themed boards, auctions, trading, and save & resume, all to a jazzy
soundtrack that is synthesised in code.

## Project Structure

- `main.py` -- pygame window, run loop, input routing, and the AI driver.
- `settings.py` -- constants: window layout, colours, AI timing, save paths,
  and the sound recipes and music score.
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
- `audio.py` -- the procedural synthesizer, sound-effect bank, and music
  looper (its core is shared word for word with the other games in this
  repository).
- `simulation.py` -- seeded all-AI games and summary metrics for AI tuning.
- `requirements.txt`, `Monopoly Game.spec` -- runtime dependency and build recipe.

## Requirements

- Python 3.12 or newer.
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
  you go to jail; pay $50 (with the cash in hand), use a jail card, or roll
  for doubles to get out.
- Pass **GO** to collect $200.
- **Short of cash?** If you owe more than you hold but selling buildings and
  mortgaging titles would cover it, the game pauses so you can raise the
  money yourself and then pay -- or concede and declare bankruptcy, which
  hands your cash, buildings' sale value and titles to whoever you owe. If
  even selling everything could not cover the debt, you go bankrupt at once.
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
- **Raising funds:** when you owe more cash than you hold, the action bar
  shows what you owe with **Pay $X** (enabled once your cash covers it),
  **Assets** (sell buildings and mortgage titles there) and **Declare
  Bankruptcy**.
- **Spectating:** once every human is bankrupt, the AIs play on. Click
  **Fast-forward** to run them without the pause between moves, or
  **Concede / Main Menu** to record the game as played and leave.
- **Auctions** open their own dialog with a **Bid +$X** button and **Pass**.
- **Bankruptcy auctions** say when a released Bank title is being auctioned,
  so a chain of forced auctions has context.
- **Trades** open a dialog where you cycle through partners with `<` / `>`,
  click property rows to add or remove them from each side, step each
  side's cash with `-$50` / `+$50` and its Get Out of Jail Free cards with
  `-1` / `+1` (never more than that player holds), then **Propose** or
  **Cancel**. Mortgaged titles show the immediate transfer-interest
  consequence before acceptance. An incoming offer lists its cash and jail
  cards first, then the titles on each side.
- AI turns play themselves with a short pause and concise log traces for major
  buy, auction, build, mortgage, and trade decisions.
- Common human-turn keyboard shortcuts are `R` roll, `B` build, `S` sell,
  `M` mortgage, `T` trade, and `E` end turn when that action is available.
- **Sound:** `Ctrl+M` switches sound on / off on every screen (plain `M` is
  still Mortgage). The setup screen has a `Sound` button under Quit, and the
  action bar's bottom-right button does the same during play, AI turns
  included. `F11` toggles fullscreen.

## Sound

Every sound is synthesised in code when the game starts; no audio files ship
with it. `audio.py` renders short recipes of notes (sine, soft triangle and
square, bright pluck, and noise voices, each with a volume envelope and an
optional pitch slide) into sample buffers, and `settings.py` holds the
recipes, written as musical notes in F major so overlapping sounds stay in
harmony with the music.

- **Effects:** the dice rattle and land with a double clack (a chime for
  doubles, a muted "wah-wah" and the jail bars for a third double); one soft
  electric-piano chime per space as a token walks, climbing the scale so you
  hear the count; a cash-register "cha-ching" for passing GO and clinking
  coins for rent; a rubber stamp and rising arpeggio for a purchase; a low
  "dum-dum" for tax; two different paper flips for Chance and Community
  Chest; low clashing bars for Jail and a free-and-easy run for leaving it;
  hammer taps for houses and hotels; falling chimes for selling, mortgaging
  and their rising twins for lifting a mortgage; a soft brass "ta-da" when
  an auction opens, a tick for each bid and a gavel when it is sold; trade
  offers that ask, resolve or decline; a gentle alert when you must raise
  funds; a muted sad trombone for bankruptcy; and a click for every button.
  Computer turns sound exactly like human ones.
- **Music:** a lightly swung, 30-second jazz-lounge loop in F major: a
  walking bass, electric-piano chords and melody, and a ride cymbal. It
  renders in a background thread, so startup stays quick.
- **Game over:** the music fades out under a rising fanfare when a human
  wins (or when every seat was a computer), or a gentle falling phrase when
  a computer beats the humans.
- **Mute:** `Ctrl+M` or a `Sound` button switches all sound off and on. The
  choice is saved as `"sound"` in `options.json` and remembered next time.

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
- **Bankrupt estates** -- a player bankrupted by another player hands that
  creditor their cash, titles and Get Out of Jail Free cards (the cards go
  back to their decks if the creditor cannot cover the mortgage interest);
  bankrupt to the Bank, the titles are auctioned and the cards are returned.
- **Decision clarity** -- owned-title asset management shows deed detail,
  legal action reasons, mortgage-transfer consequences, and Bank bankruptcy
  auction context before the player commits.
- **Profiled heuristic AI** -- the computer players value titles from price,
  rent upside, collection progress, monopoly completion, and denial pressure;
  setup profiles make that aggression tunable.
- **Polished procedural graphics and sound** -- the board, tokens, and dice
  are all drawn from code, and every effect and the music are synthesised
  from code; no image or audio files are needed.

## Save Data

Lifetime stats, the in-progress save and your options live in:

```
%APPDATA%\Monopoly\
    stats.json       lifetime games played and human wins
    savegame.json    one in-progress autosave / saved game
    options.json     the sound on/off setting
```

This per-user location is used whether you run the script or a compiled
`.exe`, so progress survives across sessions and moving the `.exe`.

## Test and Tune

Run the focused Monopoly regression suite from the repository root:

```bash
python -m unittest discover -s "Python Monopoly Game\tests" -v
```

The sound tests (`tests/test_audio.py`) never listen to anything: they check
the sample buffers the synthesizer produces and which sounds the game asks
for, under SDL's dummy audio driver. The headless self-test plays a short
all-AI game in a hidden window and never writes your saves or options:

```powershell
$env:SDL_VIDEODRIVER='dummy'
$env:SDL_AUDIODRIVER='dummy'
$env:MONOPOLY_AUTOTEST='1'
python "Python Monopoly Game\main.py"
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
- when forced to raise money, mortgage idle low-value land (undeveloped
  titles outside a monopoly, cheapest first) before selling any houses;
- pay or use a card to escape jail in the early game when there is still
  land to grab, and stay in jail late;
- propose trades that complete a colour group for them -- preferring swaps
  that *also* complete a group for the partner (mutual monopolies are gold),
  and sweetening with spare Get Out of Jail Free cards (valued at the $50
  fine) before cash.

`cautious`, `standard`, and `sharp` setup profiles tune reserves, bidding
aggression, blocking pressure, and trade margins without changing the rules
engine.

## License

Part of this repository, released under the MIT License — see [LICENSE](../LICENSE).

MONOPOLY is a trademark of Hasbro. This is an unofficial fan-made game and is not affiliated
with, endorsed by, or sponsored by Hasbro.
