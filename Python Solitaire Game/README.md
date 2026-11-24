# Klondike Solitaire

Klondike Solitaire is the classic single-player card game, built as a desktop
Python app with `tkinter`. Deal a shuffled deck, build the four foundations up
from Ace to King by suit, and clear the board to win — with a hint system,
auto-solve, undo, a confetti win celebration, and procedural sound effects
and music along the way.

## Project Structure

- `solitaire.py` is the game. The rules model (`KlondikeGame`), the tkinter
  interface (`SolitaireApp`) and the sound recipes all live in this file.
- `audio.py` is the small synthesizer that turns those recipes into sound
  effects and music (the same shared core every game in this repository
  carries).
- `tests/` holds the headless test suite: the rules, the hint engine, the
  app's click handlers and drawing, and the sound.
- `requirements.txt` lists the one `pip` package, `pygame-ce`.
- `solitaire_icon.ico` is the window and executable icon.
- `Solitaire Game.spec` is the PyInstaller build recipe for the `.exe`.

## Requirements

- Python 3.12 or newer.
- `tkinter`, which ships with the standard Python installer on Windows and
  macOS.
- `pygame-ce`, used **only for its sound mixer** (tkinter still draws the
  window). Install it once with:

```bash
pip install -r requirements.txt
```

Without `pygame-ce`, or on a machine with no audio device, the game still
runs, just silently.

## Run

```bash
python solitaire.py
```

## Tests

The rules model (`KlondikeGame`) is independent of tkinter, and the app tests
use stand-ins for the window, so the test suite runs headless without opening
a window. The sound tests switch SDL to its silent "dummy" audio driver
themselves, so they need no speakers either:

```bash
python -m unittest discover -s tests
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
- **Sound button** (at the right end of the status line) or **Ctrl+M**:
  switch all sound and music off or back on.
- **Help button**: open an in-game rules and controls reference.

## Features

- **Hint system** — suggests the strongest available move, and can look ahead
  through future stock draws (for example, "click the stock twice, then move
  5♥ to the Hearts foundation"). It remembers every position the deal has
  been in and prefers moves that lead somewhere new, so following the hints
  does not shuffle the same cards back and forth forever.
- **Auto-solve** — once every tableau card is face up, the game finishes the
  deal for you automatically.
- **Undo** — moves, stock draws, and waste recycles can all be taken back.
- **Statistics** — a high score plus lifetime wins and losses are kept across
  sessions.
- **Win celebration** — a confetti shower and a banner play when you win.
- **Sound** — soft card sounds and a calm background tune (see below).

## Sound

Every sound is synthesised in code when the game starts; no audio files ship
with it. `audio.py` renders short recipes of notes (sine, soft triangle and
plucked voices plus noise, each with a volume envelope and an optional pitch
slide) into sample buffers, and the recipes at the top of `solitaire.py` are
written as musical notes in C major so overlapping sounds stay in harmony.
Only pygame's mixer is used; tkinter keeps the window.

- **Effects:** a light paper tick when you pick up a card, a soft felt thud
  when cards land on a column, and a piano-like chime when a card reaches its
  foundation, pitched by rank (Ace lowest, King highest), so a suit filling
  up climbs a scale. A paper flip when a hidden card turns over, a slide for
  each stock draw, a riffle for recycling the waste and a dull knock for an
  empty stock. A gentle "uh-uh" for a move the rules refuse, a rewind for
  Undo, a sparkle for a hint, a cascade of ticks for a new deal, quicker
  chimes while auto-solve finishes the game, and a click for the Help and
  Sound buttons.
- **Music:** a calm, lightly swung lo-fi piano loop (about 27 seconds) over a
  soft bass and brushed drums. It renders in a background thread, so startup
  stays quick.
- **Game over:** the music fades out under a rising C major arpeggio that
  plays with the confetti when you win, or a gentle falling phrase when the
  deal is lost. A new game, or undoing out of a loss, brings the music back.
- **Mute:** `Ctrl+M` or the `Sound` button switches all sound off and on. The
  choice is saved as `"muted"` with your statistics and remembered next time;
  Undo never changes it.

## Scoring

- **+10** for every card moved onto a foundation.
- **-10** for taking a card back off a foundation, so moving the same card
  down and up again never farms points.
- **+5** for every face-down tableau card that gets revealed.
- **+100** win bonus for completing the game.
- **Time bonus** — a decreasing bonus (up to 700 points) for finishing quickly.

## Save Data

The high score, lifetime win/loss counts and the sound on/off choice are
saved to:

```
%APPDATA%\Klondike Solitaire\solitaire_high_score.json
```

This per-user location is used whether you run the script or a compiled
`.exe`, so your stats persist across sessions and survive moving the `.exe`.

## Build a Standalone .exe

The game can be packaged into a single Windows executable with
[PyInstaller](https://pyinstaller.org/).

1. Install PyInstaller and the game's requirements (only needed once):

```bash
pip install pyinstaller
pip install -r requirements.txt
```

2. From this folder (`Python Solitaire Game`), build using the bundled spec
   file:

```bash
pyinstaller "Solitaire Game.spec"
```

3. The finished program is written to `dist\Solitaire Game.exe`. Copy that
   file anywhere you like and double-click it to play.

The build still uses the same `Solitaire Game.spec`: PyInstaller finds
`audio.py` and `pygame-ce` through the game's imports and bundles them, so the
spec needs no changes. It produces a single-file, windowed executable and
bundles the window icon. Because the save data lives in `%APPDATA%`, the high score and
stats persist no matter where the `.exe` is moved.

## License

Part of this repository, released under the MIT License — see [LICENSE](../LICENSE).
