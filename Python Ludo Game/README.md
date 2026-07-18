# Ludo

A desktop **Ludo** game built in Python with `pygame-ce`. It supports 4 to 6
total players, 1 to 6 local human players, and AI seats for the rest. Four
players get the classic square cross board; five and six players get compact
radial boards with yard triangles between the arms. Tokens travel clockwise,
hopping cell by cell like the popular mobile Ludo apps.

## Project Structure

- `main.py` - Pygame window, setup screen, persistence, input, and AI driver.
- `settings.py` - colors, layout constants, timing, and save paths.
- `models.py` - small dataclasses for players, tokens, legal moves, and results.
- `board.py` - generated 4-, 5-, and 6-player board geometry.
- `game.py` - UI-free Ludo rules engine.
- `ai.py` - heuristic AI profiles and move scoring.
- `board_render.py` - procedural board and token drawing.
- `ui.py` - buttons, labels, panels, wrapped text, and dice drawing.
- `simulation.py` - seeded all-AI runs for tuning.
- `tests/` - engine, AI, board-geometry, save/load, and Pygame smoke coverage.
- `requirements.txt`, `Ludo Game.spec` - dependency and PyInstaller recipe.

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

On the setup screen, choose the total player count, human player count, AI
profile, and optional house-rule toggles. The preview thumbnails show the real
board for each count: 4 players use the classic 15x15 square cross, while 5
and 6 players use compact radial boards whose arms meet at a central hub.
Player 1 always sits at the bottom (blue) and seats continue clockwise, the
same direction the tokens move.

Classic competitive rules are enabled by default:

- Roll a `6` to move a token out of the yard.
- Move exactly into the final home cell; overshooting is not legal.
- Capturing on a non-safe square sends opponent tokens back to their yard.
- Each start square and each segment star square is safe.
- Rolling a `6`, capturing, or reaching home grants a bonus turn.
- Rolling three consecutive sixes forfeits the third roll only.
- The first player to bring all four tokens home wins.

## Controls

- **Setup:** click `+` / `-` for total players and human players.
- **Names:** click a human-name box and type.
- **During play:** click **Roll Die** or press `R`.
- **After rolling:** click a highlighted token, press `1` to `4`, or use the
  move buttons.
- **Esc:** save and return to setup during play, or quit from setup.
- **Save & Quit:** writes the in-progress game to `%APPDATA%\Ludo\savegame.json`.

## AI Profiles

- **Tactical** - balanced capture, safety, and progress scoring.
- **Aggressive** - values captures and forward pressure more heavily.
- **Defensive** - favors safe squares, finishing moves, and danger avoidance.

Run seeded all-AI batches from this folder:

```bash
python simulation.py --games 5 --players 4 --profile tactical --seed 1
```

## Save Data

The game stores data in:

```text
%APPDATA%\Ludo\
    stats.json       lifetime games, wins, player-count mix, average turns
    savegame.json    one in-progress autosave / saved game
```

The path is the same from source and from a packaged `.exe`.

## Test

From the repository root:

```bash
python -m unittest discover -s "Python Ludo Game\tests" -v
python -m compileall "Python Ludo Game"
```

For a headless Pygame smoke test in PowerShell:

```powershell
$env:SDL_VIDEODRIVER='dummy'
$env:LUDO_AUTOTEST='1'
python "Python Ludo Game\main.py"
```

## Build a Standalone .exe

Install PyInstaller if needed, then run from this folder:

```bash
pip install pyinstaller
pyinstaller "Ludo Game.spec"
```

The finished executable is written to `dist\Ludo Game.exe`.

## Notes

All visuals are procedural. Every board keeps the same engine numbers -- 13
track cells per player segment and 6 home-lane cells per player -- so the
rules are identical whichever board shape is on screen. The geometry test
suite locks the visual layout to those rules: track continuity, clockwise
movement, and start/yard/home alignment are all asserted per player count.
