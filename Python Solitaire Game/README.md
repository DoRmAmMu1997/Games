# Klondike Solitaire

Klondike Solitaire is the classic single-player card game, built as a desktop
Python app with `tkinter`. Deal a shuffled deck, build the four foundations up
from Ace to King by suit, and clear the board to win — with a hint system,
auto-solve, undo, and a confetti win celebration along the way.

## Project Structure

- `solitaire.py` is the whole game. The rules model (`KlondikeGame`) and the
  tkinter interface (`SolitaireApp`) both live in this single file.
- `solitaire_icon.ico` is the window and executable icon.
- `Solitaire Game.spec` is the PyInstaller build recipe for the `.exe`.

## Requirements

- Python 3.11 or newer.
- `tkinter`, which ships with the standard Python installer on Windows and
  macOS. **No `pip` packages are required** — the game uses only the Python
  standard library.

## Run

```bash
python solitaire.py
```

## How to Play

The goal is to move all 52 cards onto the four **foundation** piles. Each
foundation is built up in a single suit, from Ace to King.

- **Tableau** (the seven columns): build downward in alternating colours — for
  example, a red 6 onto a black 7. A face-down card flips face up once the
  cards above it are moved away.
- **Empty columns**: only a King, or a run of cards led by a King, may move
  onto an empty tableau column.
- **Stock and waste**: click the stock pile (top-left) to deal a card onto the
  waste pile. When the stock is empty, click it again to recycle the waste
  back into the stock — there is no limit on the number of passes.
- **Winning**: the game is won the moment all four foundations reach King.

## Controls

- **Click** a face-up card to select it, then **click** a destination pile to
  move it. Click the selected card again to deselect it.
- **Double-click** a card to send it straight to a foundation, when that move
  is legal — a shortcut that skips picking the destination.
- **Undo button** or **Ctrl+Z**: take back moves, draws, and recycles (a deep
  history is kept).
- **Hint button** or **Ctrl+H**: highlight a useful move. The card to move is
  outlined in yellow; the suggested destination is outlined in orange.
- **New Game button** or **Ctrl+N**: deal a fresh game.
- **Help button**: open an in-game rules and controls reference.

## Features

- **Hint system** — suggests the strongest available move, and can look ahead
  through future stock draws (for example, "click the stock twice, then move
  5♥ to the Hearts foundation").
- **Auto-solve** — once every tableau card is face up, the game finishes the
  deal for you automatically.
- **Undo** — moves, stock draws, and waste recycles can all be taken back.
- **Statistics** — a high score plus lifetime wins and losses are kept across
  sessions.
- **Win celebration** — a confetti shower and a banner play when you win.

## Scoring

- **+10** for every card moved onto a foundation.
- **+5** for every face-down tableau card that gets revealed.
- **+100** win bonus for completing the game.
- **Time bonus** — a decreasing bonus (up to 700 points) for finishing quickly.

## Save Data

The high score and lifetime win/loss counts are saved to:

```
%APPDATA%\Klondike Solitaire\solitaire_high_score.json
```

This per-user location is used whether you run the script or a compiled
`.exe`, so your stats persist across sessions and survive moving the `.exe`.

## Build a Standalone .exe

The game can be packaged into a single Windows executable with
[PyInstaller](https://pyinstaller.org/).

1. Install PyInstaller (only needed once):

```bash
pip install pyinstaller
```

2. From this folder (`Python Solitaire Game`), build using the bundled spec
   file:

```bash
pyinstaller "Solitaire Game.spec"
```

3. The finished program is written to `dist\Solitaire Game.exe`. Copy that
   file anywhere you like and double-click it to play.

The spec file produces a single-file, windowed executable and bundles the
window icon. Because the save data lives in `%APPDATA%`, the high score and
stats persist no matter where the `.exe` is moved.
