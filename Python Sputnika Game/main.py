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

# `OrbitalOrchardGame` is the main "controller" object for the whole program.
# It owns the window, the current scene, the list of bodies, and the game loop.
from game import OrbitalOrchardGame


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
    """Create pygame, run the game loop, and clean up on exit."""
    # pygame has a few subsystems that care about initialization order.
    # Audio is the most sensitive one here, so we configure it first.
    # `pre_init` asks pygame to use these audio settings when the mixer starts.
    # Keeping this before `pygame.init()` gives more predictable sound latency.
    #
    # The numbers mean:
    # - 22050: sample rate in Hz,
    # - -16: signed 16-bit audio samples,
    # - 1: mono audio,
    # - 512: small-ish audio buffer for responsive sound playback.
    pygame.mixer.pre_init(22050, -16, 1, 512)

    # Initialize every pygame subsystem we use: display, mixer, fonts, input, etc.
    pygame.init()
    try:
        # Load the generated project icon if it is available.
        # This is optional on purpose: if the icon file is missing for any reason,
        # the game should still open normally instead of crashing at startup.
        icon_path = _resource_path("orbital_orchard_icon.png")
        if icon_path.exists():
            # Icon-loading failures are cosmetic, so we ignore them safely.
            with contextlib.suppress(pygame.error):
                pygame.display.set_icon(pygame.image.load(str(icon_path)))

        # Build the main game object, which owns the window, world state, and loop.
        # From this point on, almost all interesting game behavior lives in that object.
        game = OrbitalOrchardGame()

        # During headless verification we do not want the game to run forever,
        # so an environment variable asks the game to stop after a few frames.
        #
        # In normal play this variable is not set, so `max_frames` becomes `None`
        # and the game loop keeps running until the player closes the window.
        max_frames = 6 if os.environ.get("ORBITAL_ORCHARD_AUTOTEST") else None

        # Hand control over to the game loop.
        # `run()` will keep looping until the player quits or a test frame limit is reached.
        game.run(max_frames=max_frames)
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
