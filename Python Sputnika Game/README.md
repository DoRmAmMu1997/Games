# Orbital Orchard

Orbital Orchard is a desktop Python puzzle game built with `pygame-ce`. You drop tiny celestial bodies into a glowing orbital bubble, bounce them around under a blended gravity field, and merge matching tiers all the way up to a `Quasar Crown`.

## Project Structure

- `main.py` boots pygame and starts the game loop.
- `game.py` owns scenes, input, score saving, spawning, gameplay flow, and rendering order.
- `settings.py` stores screen layout, physics constants, tier definitions, and helper utilities.
- `physics.py` runs the circle-body simulation and bubble collision solver.
- `entities.py` defines the celestial body objects and their animated face rendering.
- `merge_logic.py` finds valid same-tier merge pairs and computes their results.
- `rules.py` holds the pygame-free scoring and danger rules: combos, the fail timer, the stress meter, and save cleaning.
- `effects.py` handles particles, score popups, ring pulses, and screen shake.
- `ui.py` draws panels, buttons, overlays, and the container HUD.
- `assets.py` generates placeholder art, background stars, and fonts, and builds the sound bank.
- `audio.py` is the procedural synthesizer, sound-effect bank, and music looper (its core is shared word for word with the other games in this repository).
- `tests/` holds the headless test suite: engine rules, physics, the game shell, and rendering/layout checks.
- `requirements.txt` lists the runtime dependency.

## Beginner Reading Notes

- The Python source files now include beginner-friendly comments, docstrings, and inline explanations throughout the code.
- `requirements.txt` supports comments, so it includes a short note directly in the file.
- `save_data.json` does not support real comments because standard JSON would become invalid. That file stays minimal and stores four fields: `high_score`, `games_played`, `best_tier`, and `muted` (the sound setting). It lives in your user profile, not next to the source (see "Run" below).

## Install

1. Create and activate a Python 3.12+ virtual environment if you want one.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

The game saves your high score and lifetime stats to `%APPDATA%\Orbital Orchard\save_data.json`. This per-user location is used whether you run the script or a compiled `.exe`, so progress survives across sessions, even if you move the `.exe` elsewhere.

If saving ever fails (for example, a full or read-only disk), the game keeps running and appends a time-stamped line to `%APPDATA%\Orbital Orchard\error.log` instead. A damaged or hand-edited `save_data.json` simply loads as fresh progress.

## Tests

Everything runs headless (SDL's dummy video and audio drivers), so no window ever opens and the tests never touch your real save file. From this folder:

```bash
python -m unittest discover -s tests
```

CI runs the same suite through pytest with a coverage floor:

```bash
python -m pytest tests -q --cov=merge_logic --cov=physics --cov=rules --cov-fail-under=97
```

What the suite covers:

- **Engine rules** (`test_rules.py`, `test_merge_logic.py`, `test_physics.py`, `test_progression.py`): combos, the fail timer and stress meter, save cleaning, merge detection, the wall and pair solver, and a broad phase that must match an all-pairs solver bit for bit.
- **Game shell** (`test_game.py`): spawning inside the bubble, the paused clock, deterministic merges, corrupt saves, when progress is saved, error logging, and draw order.
- **Sound** (`test_audio.py`, plus sound checks in `test_game.py`): buffer lengths for 1 to 8 speaker channels, the limiter, determinism, click-free edges, cooldowns, mute, the music player's lifecycle and seamless loop, and which sound each game event asks for.
- **Rendering and layout** (`test_ui.py`, `test_effects.py`, `test_assets.py`): panels keep their gloss inside rounded corners, the bubble glow stays round, sidebar and modal text fits with real margins and never overlaps, the danger label stays clear of the launcher, popups stay opaque and stack, orb art has no see-through holes, and content-sized overlays draw the same pixels as full-screen ones. Layout checks use the real fonts with generous margins (never a one-pixel fit), and colour checks compare the chosen colours directly instead of sampling antialiased pixels, so they hold with other fonts and on other platforms.

For a quick full-app smoke test, set `ORBITAL_ORCHARD_AUTOTEST=1` and run `python main.py`: the game plays a short real round (four launches, about 120 frames) in a hidden window and exits. It reads your saved progress but never writes it.

## Build a Standalone .exe

The game can be packaged into a single Windows executable with [PyInstaller](https://pyinstaller.org/).

1. Install PyInstaller (only needed once):

```bash
pip install pyinstaller
```

2. From this folder (`Python Sputnika Game`), build using the bundled spec file:

```bash
pyinstaller "Orbital Orchard Game.spec"
```

3. The finished program is written to `dist\Orbital Orchard Game.exe`. Copy that file anywhere you like and double-click it to play.

The spec file produces a single-file, windowed executable and bundles the window icon. Because save data lives in `%APPDATA%`, the high score and stats persist no matter where the `.exe` is moved.

## Controls

- `Move mouse near the top launcher` or `A / D` or `Left / Right`: move the launcher
- `Right click + drag`, `W / S`, `Up / Down`, or `Mouse wheel`: set the launch angle
- `Left click` or `Space`: launch the current body
- `Esc` or `P`: pause / resume
- `R`: restart the current run
- `M`: return to the main menu
- `Ctrl+M`: sound on / off (also the `Sound` button in the sidebar and under the main menu)

## Sound

Every sound is synthesised in code when the game starts; no audio files ship with it. `audio.py` renders short recipes of notes (sine, soft triangle, soft square, plucked and noise voices, each with a volume envelope and an optional pitch slide) into sample buffers, and `settings.py` holds the recipes, written as musical notes in A minor pentatonic so overlapping sounds stay in harmony.

- **Effects:** launch thump and whoosh, a soft "not yet" when a launch is refused by the cooldown, aim clicks every 5 degrees, impact thuds that get heavier with speed, merges that climb in pitch with each tier, combo chimes that rise with the chain, a sparkle when you pass your high score, danger entered / cleared cues, the escalating danger beep, and pause / resume cues.
- **Music:** an ambient space pad with a slow arpeggio. While the stack is over the danger line it crossfades to a tense version with a faster arpeggio and a soft heartbeat. The music renders in a background thread, so startup stays quick.
- **Game over:** the music fades out under a fanfare for a new high score, or a gentle falling phrase otherwise.
- **Mute:** `Ctrl+M` or the `Sound` button switches all sound off and on. The choice is saved in `save_data.json` and remembered next time.

## Gameplay Notes

- Match two bodies of the same tier to merge them into the next stage.
- The orbital bubble uses downward gravity plus a subtle central pull and curved drift.
- If older bodies stay above the danger line too long, the run ends.
- Reaching the `Quasar Crown` is the top-tier goal.

## Architecture Summary

The game uses one lightweight custom circle-physics world. `PhysicsWorld` advances bodies, applies the blended gravity field, resolves body-body and body-wall collisions, and emits impact events. After physics finishes each frame, `merge_logic.py` checks for valid same-tier contacts and `game.py` replaces those pairs with a higher-tier body, updates score, and fires effects.

Rendering is layered in a predictable order: generated background, bubble/container, spawn preview, bodies, particles/popups, HUD, then scene overlays. Art, sound effects and music are procedural, so the project stays self-contained without any external sprite or audio files.

## Easy Tuning Variables

All of the easiest balancing knobs live in `settings.py`:

- `GRAVITY`: base downward pull
- `CENTER_PULL`: how strongly bodies drift back toward the bubble center
- `ORBITAL_PULL`: the curved “space” drift that bends falls
- `AIR_DRAG`: overall velocity damping
- `RESTITUTION`: body-to-body bounce
- `WALL_BOUNCE`: bubble wall bounce
- `WALL_FRICTION`: how quickly wall contact settles motion
- `DROP_COOLDOWN`: time between drops
- `MERGE_CONTACT_SLOP`: how close matching bodies must get to merge
- `FAIL_GRACE`: how long the danger line can stay occupied before game over
- `SPAWN_WEIGHTS`: relative chance of each low-tier spawn
- `TIERS`: names, radii, colors, accents, icons, and score values for every merge stage

## Notes

- `pygame-ce` is the preferred dependency, but the code sticks to the common `pygame` import path.
- All visuals are generated with pygame drawing primitives at runtime.
- Audio is generated procedurally; if the mixer is unavailable, the game still runs silently.

## License

Part of this repository, released under the MIT License — see [LICENSE](../LICENSE).
