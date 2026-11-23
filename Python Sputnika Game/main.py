"""Program entry point.

This file stays intentionally small:
- configure pygame before the rest of the game starts,
- create the main game object,
- optionally run only a few frames during automated smoke tests,
- always shut pygame down cleanly at the end.

Beginner note:
- Think of this file as the front door of the program.
- It does not contain gameplay rules itself.
- Its only real job is to start the app safely and then hand control to `game.py`.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

import pygame

from audio import init_mixer, reserve_channels

# `OrbitalOrchardGame` is the main "controller" object for the whole program.
# It owns the window, the current scene, the list of bodies, and the game loop.
from game import OrbitalOrchardGame
from settings import MUSIC_CHANNEL_COUNT


def _resource_path(name: str) -> Path:
    """Return the path to a bundled resource file.

    PyInstaller unpacks bundled data into `sys._MEIPASS` at runtime; from source
    the file simply sits next to this script. Checking both keeps the icon
    working whether the game runs as a .py or as a frozen .exe.
    """
    base = getattr(sys, "_MEIPASS", None)
    base_dir = Path(base) if base else Path(__file__).resolve().parent
    return base_dir / name


def main() -> None:
    """Create pygame, run the game loop, and clean up on exit.

    Steps: configure the audio mixer, start pygame, set the window icon if the
    bundled PNG is present, then either run the normal game loop or, when the
    `ORBITAL_ORCHARD_AUTOTEST` environment variable is set, play a short
    hidden smoke-test round and return. `pygame.quit()` runs in a `finally`
    block so pygame is shut down on every exit path, errors included.

    Beginner note:
    - `try` / `finally` guarantees the `finally` part runs whether the `try`
      part finishes normally, returns early (as the autotest does), or
      raises an exception.
    """
    # pygame has a few subsystems that care about initialization order.
    # Audio is the most sensitive one here, so we configure it first:
    # `init_mixer()` asks for the shared mixer format (22050 Hz, 16-bit,
    # stereo, a small 512-sample buffer for responsive sound) BEFORE
    # `pygame.init()` opens the mixer. See audio.py for the details.
    init_mixer()

    # Initialize every pygame subsystem we use: display, mixer, fonts, input, etc.
    pygame.init()
    # Now that the mixer is open, keep the music channels (calm and tense)
    # away from effects.
    reserve_channels(MUSIC_CHANNEL_COUNT)
    try:
        # Load the generated project icon if it is available.
        # This is optional on purpose: if the icon file is missing for any reason,
        # the game should still open normally instead of crashing at startup.
        icon_path = _resource_path("orbital_orchard_icon.png")
        if icon_path.exists():
            # Icon-loading failures are cosmetic, so we ignore them safely.
            with contextlib.suppress(pygame.error):
                pygame.display.set_icon(pygame.image.load(str(icon_path)))

        if os.environ.get("ORBITAL_ORCHARD_AUTOTEST"):
            # Headless smoke test: play a short real round (four launches, about
            # 120 frames) and exit. `persist=False` reads the saved progress but
            # never writes it, so the test leaves the player's save untouched.
            game = OrbitalOrchardGame(persist=False)
            game.start_round()
            for _ in range(4):
                game.drop_current_body()
                game.run(max_frames=30)
            return

        # Build the main game object, which owns the window, world state, and loop.
        # From this point on, almost all interesting game behavior lives in that object.
        game = OrbitalOrchardGame()

        # Hand control over to the game loop.
        # `run()` will keep looping until the player closes the window.
        game.run()
    finally:
        # Shut pygame down even if the loop exits because of an error.
        # This helps avoid "stuck" audio/display resources after crashes.
        pygame.quit()


if __name__ == "__main__":
    # Only run the game automatically when this file is launched directly.
    #
    # If another file imports `main.py`, this block does not run, which is useful
    # for tests or tools that want to call `main()` manually.
    main()
