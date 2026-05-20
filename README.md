# Games

Three desktop games written in Python. Each one runs from source and ships
with a PyInstaller spec for building a single Windows `.exe`. Every game
keeps its progress under `%APPDATA%` so saves survive moving the executable.

## What's in this repository

| Folder | Game | Engine |
|---|---|---|
| `Python Sputnika Game/` | **[Orbital Orchard](Python%20Sputnika%20Game/README.md)** — a Suika-style merge puzzle. Drop celestial bodies into a bubble, bounce and merge them up to a Quasar Crown. | pygame |
| `Python Solitaire Game/` | **[Klondike Solitaire](Python%20Solitaire%20Game/README.md)** — the classic single-player card game with hints, auto-solve, undo, and a confetti win celebration. | tkinter |
| `Python Monopoly Game/` | **[Monopoly](Python%20Monopoly%20Game/README.md)** — full standard rules, 1-4 humans + AI to fill out four players, three themed boards, auctions, trading, and save & resume. | pygame |

Click into a folder for the full per-game README with rules, controls,
features and build notes.

## Run from source

Each game has its own `requirements.txt` (Monopoly and Orbital Orchard use
`pygame-ce`; Solitaire uses only the standard library). Install the deps
once and start playing:

```bash
cd "Python Monopoly Game"          # or another game's folder
pip install -r requirements.txt
python main.py                     # python solitaire.py for the Solitaire game
```

Python 3.11 or newer is recommended for all three.

## Build a standalone .exe

Every game ships with a PyInstaller spec, so packaging is a one-liner from
inside the game's folder:

```bash
pip install pyinstaller
pyinstaller "<Game Name>.spec"
```

The finished `.exe` appears under `dist\`. The relevant spec files are:

- `Python Sputnika Game/Orbital Orchard Game.spec`
- `Python Solitaire Game/Solitaire Game.spec`
- `Python Monopoly Game/Monopoly Game.spec`

See each game's README for the exact filename and per-game notes.

## Save data

Every game stores progress in its own per-user folder so nothing is lost
when the `.exe` is moved or rebuilt:

- `%APPDATA%\Orbital Orchard\save_data.json` — high score, games played, best tier.
- `%APPDATA%\Klondike Solitaire\solitaire_high_score.json` — high score, lifetime wins / losses.
- `%APPDATA%\Monopoly\stats.json` — lifetime games / wins.
- `%APPDATA%\Monopoly\savegame.json` — one in-progress saved Monopoly game.

## Repository layout

```
Games/
├── README.md                    -- this file
├── .gitignore
├── Python Sputnika Game/        -- Orbital Orchard (pygame)
├── Python Solitaire Game/       -- Klondike Solitaire (tkinter)
└── Python Monopoly Game/        -- Monopoly (pygame)
```

Generated `.exe` files, save-data JSON, `build/`, `dist/` and `__pycache__/`
directories are kept out of the repository by `.gitignore` — only the
source ships here.

## Notes

All visuals are drawn procedurally (no external image files required).
Comments throughout the code are deliberately beginner-friendly: docstrings
on every method, inline explanations on non-obvious logic, and tuning knobs
grouped together at the top of each `settings.py`-style file.

The games were written collaboratively with Claude Code (Anthropic) and
Codex (OpenAI); the original Codex output supplied the playable base, and
later passes added per-user save persistence, crash-safe atomic writes,
gameplay and graphics improvements, an entire new Monopoly game, and the
EXE-build workflow.
