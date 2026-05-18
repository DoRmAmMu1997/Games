# Orbital Orchard

Orbital Orchard is a desktop Python puzzle game built with `pygame-ce`. You drop tiny celestial bodies into a glowing orbital bubble, bounce them around under a blended gravity field, and merge matching tiers all the way up to a `Quasar Crown`.

## Project Structure

- `main.py` boots pygame and starts the game loop.
- `game.py` owns scenes, input, score saving, spawning, gameplay flow, and rendering order.
- `settings.py` stores screen layout, physics constants, tier definitions, and helper utilities.
- `physics.py` runs the circle-body simulation and bubble collision solver.
- `entities.py` defines the celestial body objects and their animated face rendering.
- `merge_logic.py` finds valid same-tier merge pairs and computes their results.
- `effects.py` handles particles, score popups, ring pulses, and screen shake.
- `ui.py` draws panels, buttons, overlays, and the container HUD.
- `assets.py` generates placeholder art, background stars, fonts, and simple procedural sounds.
- `requirements.txt` lists the runtime dependency.

## Beginner Reading Notes

- The Python source files now include beginner-friendly comments, docstrings, and inline explanations throughout the code.
- `requirements.txt` supports comments, so it includes a short note directly in the file.
- `save_data.json` does not support real comments because standard JSON would become invalid. That file stays minimal and stores three fields: `high_score`, `games_played`, and `best_tier`. It lives in your user profile, not next to the source (see "Run" below).

## Install

1. Create and activate a Python 3.11+ virtual environment if you want one.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

The game saves your high score and lifetime stats to `%APPDATA%\Orbital Orchard\save_data.json`. This per-user location is used whether you run the script or a compiled `.exe`, so progress survives across sessions, even if you move the `.exe` elsewhere.

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

## Gameplay Notes

- Match two bodies of the same tier to merge them into the next stage.
- The orbital bubble uses downward gravity plus a subtle central pull and curved drift.
- If older bodies stay above the danger line too long, the run ends.
- Reaching the `Quasar Crown` is the top-tier goal.

## Architecture Summary

The game uses one lightweight custom circle-physics world. `PhysicsWorld` advances bodies, applies the blended gravity field, resolves body-body and body-wall collisions, and emits impact events. After physics finishes each frame, `merge_logic.py` checks for valid same-tier contacts and `game.py` replaces those pairs with a higher-tier body, updates score, and fires effects.

Rendering is layered in a predictable order: generated background, bubble/container, spawn preview, bodies, particles/popups, HUD, then scene overlays. Art and sound are procedural, so the project stays self-contained without any external sprite or audio files.

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
