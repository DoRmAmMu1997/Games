# Ludo

A desktop **Ludo** game built in Python with `pygame-ce`. It supports 4 to 6
total players, 1 to 6 local human players, and AI seats for the rest. Four
players get the classic square cross board; five and six players get compact
radial boards with yard triangles between the arms. Tokens travel clockwise,
hopping cell by cell like the popular mobile Ludo apps, to a marimba soundtrack
that is synthesised in code.

## Project Structure

- `main.py` - Pygame window, setup screen, persistence, input, and AI driver.
- `settings.py` - colors, layout constants, timing, save paths, and the sound
  recipes and music score.
- `models.py` - small dataclasses for players, tokens, legal moves, and results.
- `board.py` - generated 4-, 5-, and 6-player board geometry.
- `game.py` - UI-free Ludo rules engine.
- `ai.py` - heuristic AI profiles and move scoring.
- `board_render.py` - procedural board and token drawing.
- `ui.py` - buttons, labels, panels, wrapped text, and dice drawing.
- `audio.py` - the procedural synthesizer, sound-effect bank, and music looper
  (its core is shared word for word with the other games in this repository).
- `simulation.py` - seeded all-AI runs for tuning.
- `tests/` - engine, AI, board-geometry, save/load, sound, and Pygame smoke
  coverage.
- `requirements.txt`, `Ludo Game.spec` - dependency and PyInstaller recipe.
- `ludo_icon.ico`, `ludo_icon.png` - the `.exe` icon, and the window icon
  (the 256px image from inside the `.ico`, which pygame cannot decode).

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

On the setup screen, choose the total player count, human player count, AI
profile, and optional house-rule toggles. The preview thumbnails show the real
board for each count: 4 players use the classic 15x15 square cross, while 5
and 6 players use compact radial boards whose arms meet at a central hub.
Player 1 always sits at the bottom (blue) and seats continue clockwise, the
same direction the tokens move.

Classic competitive rules are enabled by default:

- Roll a `6` to move a token out of the yard.
- A lap is 51 squares on the four-player board (64 on five players, 77 on
  six): a token never lands on the square just behind its own start, and
  turns straight into its home column from the square before it.
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
- **Ctrl+M:** sound on / off, on every screen (also the `Sound` button under
  Quit on the setup screen, and the `Sound` pill beside the dice tray).
- **Save & Quit:** writes the in-progress game to `%APPDATA%\Ludo\savegame.json`.

## Sound

Every sound is synthesised in code when the game starts; no audio files ship
with it. `audio.py` renders short recipes of notes (marimba-like plucks, sine,
soft triangle and square voices, and noise, each with a volume envelope and an
optional pitch slide) into sample buffers, and `settings.py` holds the recipes,
written as musical notes in G major so overlapping sounds stay in harmony.

- **Effects:** the dice rattle and land on a note for each face, a sparkle for
  a 6 and a deflating groan for a forfeited third 6, a pop when a token leaves
  its yard, one marimba tap per cell as a token hops (climbing the scale, so
  you hear the count), two falling bonks for a capture, a ringing chord for a
  token home, a chime for a bonus roll, a soft "nope" when there is no move, a
  knock when the turn passes to a human, and a click for every button.
- **Music:** an upbeat 30-second folk loop in G major: a marimba melody over
  an "oom-pah" bass and chords with a light shaker. It renders in a background
  thread, so startup stays quick.
- **Game over:** the music fades out under a rising fanfare when a human wins
  (or when every seat was a computer), or a gentle falling phrase when a
  computer beats the humans.
- **Mute:** `Ctrl+M` or a `Sound` button switches all sound off and on. The
  choice is saved as `"sound"` in `stats.json` and remembered next time.

## AI Profiles

- **Tactical** - balanced capture, safety, and progress scoring.
- **Aggressive** - values captures and forward pressure more heavily.
- **Defensive** - favors safe squares, finishing moves, and danger avoidance.

Run seeded all-AI batches from this folder:

```bash
python simulation.py --games 5 --players 4 --profile tactical --seed 1
```

Add `--blockades`, `--no-capture-bonus`, `--no-home-bonus`, or
`--no-three-sixes` to simulate the same house rules the setup screen offers.

## Save Data

The game stores data in:

```text
%APPDATA%\Ludo\
    stats.json       lifetime games, wins, player-count mix, average turns,
                     and the sound on/off setting
    savegame.json    one in-progress autosave / saved game
```

The path is the same from source and from a packaged `.exe`.

Saves written before the 51-square lap still load. They counted one extra
shared square (the corner just behind each start), so loading shifts them
onto the shorter lap:

- Tokens in the home column or at home keep their cell and their distance.
- A token on the old corner steps back one cell to its column entrance and
  keeps its distance.
- Tokens on the shared track keep their cell and end up one cell closer to
  home, because the lap is one cell shorter.

## Test

From the repository root:

```bash
python -m unittest discover -s "Python Ludo Game\tests" -v
python -m compileall "Python Ludo Game"
```

For a headless Pygame smoke test in PowerShell (it plays a short seeded
all-AI game in a hidden window and never writes or deletes your saves):

```powershell
$env:SDL_VIDEODRIVER='dummy'
$env:SDL_AUDIODRIVER='dummy'
$env:LUDO_AUTOTEST='1'
python "Python Ludo Game\main.py"
```

The sound tests (`tests/test_audio.py`) never listen to anything: they check
the sample buffers the synthesizer produces and which sounds the game asks
for, under SDL's dummy audio driver.

## Build a Standalone .exe

Install PyInstaller if needed, then run from this folder:

```bash
pip install pyinstaller
pyinstaller "Ludo Game.spec"
```

The finished executable is written to `dist\Ludo Game.exe`.

## Notes

All visuals, sound effects, and music are procedural. Every board keeps the same engine numbers -- 13
track cells per player segment and 6 home-lane cells per player -- so the
rules are identical whichever board shape is on screen. The geometry test
suite locks the visual layout to those rules: track continuity, clockwise
movement, and start/yard/home alignment are all asserted per player count.

## License

Part of this repository, released under the MIT License — see [LICENSE](../LICENSE).
