# AGENTS.md — guide for AI coding agents working in this repository

This file is the single source of truth for ANY coding agent (Claude Code,
Codex, Copilot, or anything else) touching this repo. `CLAUDE.md` simply
imports it. If repo conventions change, update THIS file in the same commit.

## 1. What this project is

Four self-contained Python desktop games, each in its own folder, each
shipping as a single Windows `.exe` via PyInstaller:

| Folder | Game | Stack |
|---|---|---|
| `Python Sputnika Game/` | **Orbital Orchard** — Suika-style merge puzzle in a circular bubble | pygame-ce |
| `Python Solitaire Game/` | **Klondike Solitaire** — hints, auto-solve, undo | tkinter (stdlib only) |
| `Python Monopoly Game/` | **Monopoly** — full standard rules, AI seats, trading, auctions | pygame-ce |
| `Python Ludo Game/` | **Ludo** — 4-6 players, clockwise movement, classic 4P cross + radial 5P/6P boards | pygame-ce |

These are hobby games, but they are maintained to production hygiene: typed,
linted, security-scanned, and tested in CI. All art and sound is procedural —
there are no image/audio assets except the window-icon `.ico` files.

## 2. Mandatory workflow skills

Before starting ANY task in this repo, activate (if your environment provides
them) the skills the owner uses everywhere:

| When | Skill |
|---|---|
| First, always | `using-superpowers` (skill-discovery discipline) |
| Writing/reviewing/refactoring code | `karpathy-guidelines` (surgical changes, no speculative complexity) |
| Any feature or bugfix | `test-driven-development` |
| Before claiming something works | `verification-before-completion` (run the gates; evidence before assertions) |

The Karpathy rules matter here specifically: each game deliberately duplicates
small helpers instead of sharing a package (see §5) — do not "helpfully"
deduplicate across game folders.

## 3. Repository map

```
Games/
├── AGENTS.md / CLAUDE.md        -- this guide (CLAUDE.md just imports it)
├── README.md                    -- player-facing overview
├── pyproject.toml               -- ruff + mypy + bandit config (repo-wide)
├── requirements-dev.txt         -- exact-pinned dev/CI toolchain
├── .pre-commit-config.yaml      -- check-only hooks (never rewrite files)
├── .github/workflows/quality-and-security.yml
└── Python <Name> Game/          -- one self-contained game per folder
    ├── main.py                  -- entry point (Solitaire: solitaire.py)
    ├── game.py                  -- UI-free rules engine (pygame games)
    ├── settings.py              -- ALL tuning knobs and constants
    ├── tests/                   -- headless test suite
    ├── requirements.txt         -- runtime deps (pygame-ce or nothing)
    └── <Name>.spec              -- PyInstaller build recipe
```

Per-game module patterns (pygame games): `models.py` (dataclasses),
`ai.py` (heuristics), `board_render.py`/`ui.py`/`visual_theme.py`/`assets.py`
(drawing), `simulation.py` (seeded all-AI batches for tuning). Solitaire is a
single file: `KlondikeGame` (rules) + `SolitaireApp` (tkinter shell).

## 4. Architecture pattern (all four games)

**UI-free engine + thin shell.** The rules engine (`game.py` /
`KlondikeGame`) never imports pygame/tkinter and is driven entirely through
methods; humans (clicks), AI (`ai.py`), tests, and simulations all call the
same engine API. The shell (`main.py`) owns the window, input routing, timers,
animation state, and persistence. Keep it that way:

- New rules go in the engine with tests; the shell only translates input.
- Engine state machines are explicit (`awaiting`/`phase` strings). The UI
  builds buttons from engine state each frame instead of caching decisions.
- Animation is presentation-only: engines update instantly; the shell's
  waypoint queues (token hops) merely ease pixels toward engine truth.
- Ludo specifics: `board.py` owns the authoritative track *indices*;
  `board_render.py`'s `DisplayLayout` owns every on-screen coordinate. The
  ordering of `DisplayLayout.track_positions` alone decides movement
  direction (clockwise). `tests/test_board_geometry.py` locks continuity,
  clockwise winding, and start/yard/home alignment — change geometry only
  with those tests green and a headless PNG render inspected.

## 5. Coding conventions

- Python 3.11+; `from __future__ import annotations`; modern typing
  (`X | None`, pep585 builtins). Line length 120 (ruff enforces).
- **Self-contained games.** Never import across game folders and never
  create a shared package. Small helpers (`_atomic_write`, `_log_error`,
  `_resource_path`, window scaling) are deliberately duplicated per game so
  each folder builds into a standalone exe; keep the copies textually
  consistent when you touch one.
- The folder names contain spaces — always quote paths in commands, specs,
  and CI.
- Flat module layout: game code does `from game import ...`; tests insert
  the game folder into `sys.path` first (the shim at the top of every test
  file). Because all four games share module names (`main`, `game`,
  `settings`, ...), tools that build one module graph (mypy, pytest) must be
  run per game folder — never across the whole repo at once.
- `settings.py` owns every tuning knob, named and commented with the "why".
  No bare magic numbers in logic code.
- Docstring style: every module and def carries a docstring; beginner-facing
  explanations use full-sentence prose, with "Beginner note:" blocks for
  concepts a newcomer would trip on. Match this in new code.
- Persistence: saves live under `%APPDATA%\<Game>\` (never next to the
  source — PyInstaller one-file builds unpack to a temp dir), written via
  the atomic temp-file + `os.replace` pattern, with failures logged to
  `error.log` rather than crashing the game.
- Type-narrowing `assert`s are the house pattern for Optional state whose
  invariant the UI guarantees (e.g. Monopoly's `_require_game()`); bandit's
  B101 is skipped for this reason. Do not use asserts for input validation.
- Randomness always flows through each game's seeded `random.Random` (or
  `random` for cosmetics only) — that is what makes simulations and tests
  reproducible. B311 is skipped: dice are not cryptography.

## 6. Quality gates (run before claiming done)

Install once: `pip install -r requirements-dev.txt` plus
`pip install -r "Python Ludo Game/requirements.txt"` (any one pygame game's
requirements file provides pygame-ce for all three).

From the repo root, all of these must pass — CI runs exactly this set on
Python 3.11 and 3.13:

```powershell
# Headless env for the pygame games (PowerShell syntax)
$env:SDL_VIDEODRIVER = 'dummy'; $env:SDL_AUDIODRIVER = 'dummy'

# Tests with coverage floors, run FROM INSIDE each game folder
cd "Python Ludo Game";     python -m pytest tests -q --cov=game --cov=board --cov=ai --cov=models --cov-fail-under=75; cd ..
cd "Python Monopoly Game"; python -m pytest tests -q --cov=game --cov=ai --cov=cards --cov=board_data --cov=player --cov-fail-under=80; cd ..
cd "Python Sputnika Game"; python -m pytest tests -q --cov=merge_logic --cov=physics --cov-fail-under=90; cd ..
cd "Python Solitaire Game"; python -m pytest tests -q --cov=solitaire --cov-fail-under=32; cd ..

# Static gates (repo root)
python -m compileall -q .
python -m ruff check .
python -m mypy "Python Ludo Game"
python -m mypy "Python Monopoly Game"
python -m mypy "Python Sputnika Game"
python -m mypy "Python Solitaire Game"
python -m bandit -c pyproject.toml -r . -q
```

Hard rules:
- Coverage floors may be raised as coverage grows; **never lower one** to
  make a failing change pass.
- If you change a CI command, change the identical command here in §6 in the
  same commit.
- Tool versions are pinned in `requirements-dev.txt` and mirrored in
  `.pre-commit-config.yaml` (the ruff rev) — bump them together.
- Pre-commit hooks are check-only; never add hooks that rewrite files.

## 7. Windows / PowerShell gotchas

The owner develops on Windows 11 with PowerShell 5.1:

- No `&&` / `||` chaining in PowerShell 5.1 — use `;` or `if ($?) { ... }`.
- `Out-File`/`Set-Content` default to UTF-16; pass `-Encoding utf8` (and
  note PS 5.1 writes a BOM — for files other tools parse, prefer
  `[System.IO.File]::WriteAllText(...)`, which writes BOM-free UTF-8).
  Multi-line commit messages: write to a temp file, then `git commit -F`.
- Always quote the space-containing game folder paths.
- Headless runs need `SDL_VIDEODRIVER=dummy` (and `SDL_AUDIODRIVER=dummy`);
  in CI these are job-level env vars.

## 8. Testing conventions

- Framework: `unittest`-style classes, run via pytest (CI) or
  `python -m unittest discover -s tests` (both work). Every test module,
  class, and test carries a docstring stating the behaviour under test.
- Tests are engine-first and fully headless: pygame under the SDL dummy
  driver; Solitaire tests exercise only the Tk-free `KlondikeGame` (never
  instantiate `Tk()` in a test).
- Full-app smoke tests: `LUDO_AUTOTEST=1`, `MONOPOLY_AUTOTEST=1`, and
  `ORBITAL_ORCHARD_AUTOTEST=1` each play a short hidden-window session of
  `main.py` and exit 0.
- Visual changes to the Ludo board: render each mode headless to a PNG and
  inspect it (create a small scratch script that calls
  `BoardRenderer.draw`/`draw_static` and `pygame.image.save`), in addition
  to keeping `tests/test_board_geometry.py` green.
- Determinism: seed every game/simulation in tests; never sleep or rely on
  wall-clock time.

## 9. Building the executables

From inside a game's folder:

```powershell
pip install pyinstaller
pyinstaller "Ludo Game.spec"   # or the matching spec in that folder
```

Output lands in `dist\`. The specs produce single-file, windowed exes.
Bundled read-only resources (window icons) are declared in the spec's
`datas` and resolved at runtime through that game's `_resource_path()`
(which handles `sys._MEIPASS`). Save data is NOT bundled — it lives in
`%APPDATA%` so it survives rebuilds and moves.

## 10. Git and PR conventions

- Branch names: `claude/<topic>` or `codex/<topic>` by agent, kebab-case.
- Commits: imperative, single-purpose subject; body explains what and why.
  Stage related work into separate commits rather than one mega-commit.
- Never commit generated output: `build/`, `dist/`, `*.exe`, `__pycache__`,
  save-data JSON (all already gitignored).
- PRs target `main`, one topic per PR, imperative title, body summarising
  the change plus how it was verified. All §6 gates must be green locally
  before pushing; the `Quality & Security` workflow must be green before
  merging.
- Do not amend or force-push shared history; add follow-up commits instead.
