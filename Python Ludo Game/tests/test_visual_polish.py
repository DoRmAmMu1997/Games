"""Checkable parts of the Ludo graphics polish: text fits, nothing overlaps.

These tests rasterize shapes into pygame masks where rectangles alone cannot
describe them (the triangular radial yards), so "does not overlap" means no
shared pixel at all.
"""

from __future__ import annotations

import itertools
import os
import sys
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import pygame

import main
import ui
import visual_theme as theme
from board_render import START_CELL_BRIGHTEN, BoardRenderer, _square_home_rects
from game import LudoGame, LudoRules
from settings import GOLD, LABEL_CONTRAST_TARGET, MIN_LABEL_CONTRAST, SCREEN_HEIGHT, SCREEN_WIDTH, WHITE, seat_colors

# Yard parking slots are drawn as rings of this radius (see _draw_yard_slots).
YARD_SLOT_RADIUS = 24
# Name banners cast a drop shadow this far below themselves.
BANNER_SHADOW_DROP = 4
# draw_token_pin wraps each pawn's coloured head in a white ring this wide.
PIN_RING_WIDTH = 4
# Font-dependent layouts must pass with spare room, not by a hair: digit ink
# and line heights shift by a pixel or two between fonts and platforms.
LABEL_CLEARANCE = 2  # least gap between a pawn number and any later pawn's head
LINE_HEIGHT_SLACK = 2  # extra height allowed per text line for taller platform fonts


def make_game(total_players: int) -> LudoGame:
    """Create a deterministic game with seat 0 human and the rest AI."""

    players = [(f"P{i + 1}", i == 0) for i in range(total_players)]
    return LudoGame(players, LudoRules(total_players=total_players), seed=12)


def yard_mask(renderer: BoardRenderer) -> pygame.mask.Mask:
    """Return a full-canvas mask of every yard frame and parking-slot ring."""

    surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
    solid = (255, 255, 255, 255)
    if renderer.display.yard_frames:
        for frame in renderer.display.yard_frames:
            pygame.draw.polygon(surface, solid, [(round(x), round(y)) for x, y in frame])
    else:
        for yard in _square_home_rects():
            pygame.draw.rect(surface, solid, yard)
    for slots in renderer.display.yard_positions:
        for x, y in slots:
            pygame.draw.circle(surface, solid, (round(x), round(y)), YARD_SLOT_RADIUS)
    return pygame.mask.from_surface(surface)


class BannerPlacementTests(unittest.TestCase):
    """Player name banners sit fully outside their yards and on the canvas."""

    def test_banners_clear_every_yard(self) -> None:
        """No banner shares a pixel with any yard frame or parking slot."""

        for count in (4, 5, 6):
            renderer = BoardRenderer(make_game(count).layout)
            yards = yard_mask(renderer)
            for seat, rect in enumerate(renderer.banner_rects()):
                with self.subTest(total_players=count, seat=seat):
                    banner = pygame.mask.Mask(rect.size, fill=True)
                    self.assertEqual(yards.overlap_area(banner, rect.topleft), 0, f"banner {rect} covers a yard")

    def test_banners_stay_on_the_canvas(self) -> None:
        """Every banner, including its drop shadow, is fully inside the window."""

        screen = pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT)
        for count in (4, 5, 6):
            for seat, rect in enumerate(BoardRenderer(make_game(count).layout).banner_rects()):
                with self.subTest(total_players=count, seat=seat):
                    self.assertTrue(screen.contains(rect.inflate(0, 2 * BANNER_SHADOW_DROP)), rect)

    def test_bottom_banner_and_shadow_clear_the_dice_tray(self) -> None:
        """Seat 0's banner, shadow included, stops above the HUD dice tray."""

        for count in (4, 5, 6):
            with self.subTest(total_players=count):
                rect = BoardRenderer(make_game(count).layout).banner_rects()[0]
                shadowed = rect.union(rect.move(0, BANNER_SHADOW_DROP))
                self.assertFalse(shadowed.colliderect(main.PLAY_DICE_TRAY_RECT), f"{shadowed} touches the tray")


class SetupPanelTests(unittest.TestCase):
    """The setup column fits inside its dark panel even with six human names."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once for the setup-panel checks."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the setup-panel checks."""

        pygame.quit()

    def test_six_human_setup_fits_inside_the_panel(self) -> None:
        """Every setup button and name field sits at least 8 px inside the panel."""

        app = main.LudoApp(persist=False)
        self.addCleanup(setattr, app, "running", False)
        app.total_players = 6
        app.human_count = 6
        inner = main.SETUP_PANEL_RECT.inflate(-16, -16)
        rects = [(button.key, button.rect) for button in app.setup_buttons()]
        rects += [(f"name {index + 1}", main._name_rect(index)) for index in range(6)]
        for name, rect in rects:
            with self.subTest(control=name):
                self.assertTrue(inner.contains(rect), f"{name} {rect} leaves the panel {inner}")

    def test_section_headers_leave_a_gap_above_their_controls(self) -> None:
        """Each section header ends at least SETUP_HEADER_GAP px above its first control.

        Beginner note: the same font size renders at different line heights
        on different machines (28 px FreeSans here, about 32 px Arial on
        Windows, 33 px DejaVu Sans on some Linux CI runners). So the layout
        reserves SETUP_HEADER_LINE_ALLOWANCE for the header line, and this
        test checks both this machine's real font and that allowance, so a
        near miss fails everywhere, not only on the tallest-font platform.
        """

        app = main.LudoApp(persist=False)
        self.addCleanup(setattr, app, "running", False)
        header_height = app.fonts["header"].get_height()
        gap = main.SETUP_HEADER_GAP
        self.assertLessEqual(header_height, main.SETUP_HEADER_LINE_ALLOWANCE, "header font outgrew the layout")
        buttons = {button.key: button.rect for button in app.setup_buttons()}
        sections = (
            ("Advanced Rules", main.SETUP_RULES_HEADER_Y, buttons["toggle_blockades"].y),
            ("Human Names", main.SETUP_NAME_HEADER_Y, main._name_rect(0).y),
        )
        for name, header_y, control_y in sections:
            with self.subTest(header=name):
                self.assertLessEqual(header_y + header_height + gap, control_y, "measured header touches its control")
                self.assertLessEqual(
                    header_y + main.SETUP_HEADER_LINE_ALLOWANCE + gap, control_y, "no room for a taller header font"
                )
        self.assertLessEqual(main._setup_option_row(2).left_button.bottom + gap, main.SETUP_RULES_HEADER_Y)
        self.assertLessEqual(buttons["toggle_three_sixes"].bottom + gap, main.SETUP_NAME_HEADER_Y)


class RecordingFont:
    """Wrap a pygame font and remember the colour of every ``render`` call."""

    def __init__(self, font: pygame.font.Font) -> None:
        """Keep the real font and start with no recorded colours."""

        self.font = font
        self.colors: list[tuple[int, int, int]] = []

    def render(self, text: str, antialias: bool, color, *args) -> pygame.Surface:
        """Record ``color`` as an RGB triple, then render with the real font."""

        self.colors.append((color[0], color[1], color[2]))
        return self.font.render(text, antialias, color, *args)


def rgb(color: pygame.Color) -> tuple[int, int, int]:
    """Return a sampled pixel's colour as a plain RGB triple."""

    return (color.r, color.g, color.b)


def luminance(color) -> float:
    """Return perceived brightness of an RGB colour, 0 (black) to 255 (white)."""

    return 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]


class ButtonStateTests(unittest.TestCase):
    """A disabled button reads as switched off: darker and dimmer than an idle one."""

    fonts: dict[str, pygame.font.Font]

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame and fonts once for the button checks."""

        pygame.init()
        cls.fonts = ui.make_fonts()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the button checks."""

        pygame.quit()

    def render(self, enabled: bool) -> tuple[pygame.Surface, pygame.Rect]:
        """Draw one button, not hovered, and return the surface and its rect."""

        surface = pygame.Surface((300, 80))
        rect = pygame.Rect(20, 20, 246, 34)
        ui.Button(rect, "Resume Saved Game", "resume", enabled=enabled).draw(surface, self.fonts, (0, 0))
        return surface, rect

    def test_disabled_fill_is_darker_than_an_enabled_fill(self) -> None:
        """The disabled background is never brighter than an idle enabled background."""

        enabled, rect = self.render(True)
        disabled, _rect = self.render(False)
        sample = (rect.x + 8, rect.centery)
        self.assertLess(luminance(disabled.get_at(sample)), luminance(enabled.get_at(sample)) + 1)

    def test_disabled_label_is_dimmed(self) -> None:
        """A disabled button draws no near-white label pixels."""

        surface, rect = self.render(False)
        brightest = max(
            luminance(surface.get_at((x, y))) for x in range(rect.x, rect.right) for y in range(rect.y, rect.bottom)
        )
        self.assertLess(brightest, 170)


class RosterChipTests(unittest.TestCase):
    """Every line of text on a roster chip stays inside that chip."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once for the roster checks."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the roster checks."""

        pygame.quit()

    def test_roster_text_fits_inside_each_chip(self) -> None:
        """Long names and big counters are fitted to the chip, never drawn past it."""

        app = main.LudoApp(persist=False)
        self.addCleanup(setattr, app, "running", False)
        players = [("W" * 18, True)] + [(f"AI {seat} (Purple)", False) for seat in range(1, 6)]
        game = LudoGame(players, LudoRules(total_players=6), seed=1, ai_profile="aggressive")
        for player in game.players:
            player.captures = 99
            for token in player.tokens:
                token.steps = game.layout.finish_steps
        app.start_game(game)
        chips = [main._roster_chip_rect(index) for index in range(6)]
        drawn: list[pygame.Rect] = []
        real_draw_text = ui.draw_text

        def record(surface, font, text, pos, *args, **kwargs) -> None:
            """Remember the box of every text drawn inside a roster chip, then draw it."""

            box = pygame.Rect((int(pos[0]), int(pos[1])), font.size(text))
            if any(chip.collidepoint(box.topleft) for chip in chips):
                drawn.append(box)
            real_draw_text(surface, font, text, pos, *args, **kwargs)

        with mock.patch.object(ui, "draw_text", side_effect=record):
            app._draw_player_roster()

        self.assertEqual(len(drawn), 18, "expected a name, a seat tag, and a stats line per chip")
        for box in drawn:
            chip = next(chip for chip in chips if chip.collidepoint(box.topleft))
            with self.subTest(box=box):
                # 4 px inset on every side leaves room for a slightly taller font.
                self.assertTrue(chip.inflate(-8, -8).contains(box), f"{box} crowds the edge of {chip}")
                others = [other for other in drawn if other is not box and chip.collidepoint(other.topleft)]
                self.assertEqual(box.collidelistall(others), [], f"{box} overlaps another line on its chip")


class StackReadabilityTests(unittest.TestCase):
    """Every pawn number in a stack stays visible above the pawns drawn after it."""

    fonts: dict[str, pygame.font.Font]

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame and the app fonts once for the stack checks."""

        pygame.init()
        cls.fonts = ui.make_fonts()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the stack checks."""

        pygame.quit()

    def label_ink(self, label: str, centre: tuple[float, float]) -> pygame.Rect:
        """Return the screen rect of a pawn label's actual ink, drawn centred on ``centre``."""

        image = self.fonts["tiny"].render(label, True, (255, 255, 255))
        full = image.get_rect(center=(int(centre[0]), int(centre[1])))
        return image.get_bounding_rect().move(full.topleft)

    def test_stack_numbers_are_not_covered_by_later_pawns(self) -> None:
        """For stacks of 2 to 6 pawns, no later pawn's head covers an earlier number."""

        for count in (4, 5, 6):
            for size in range(2, 7):
                with self.subTest(total_players=count, stack=size):
                    game = make_game(count)
                    safe = game.layout.safe_indices[1]
                    seats = [seat for seat in (0, 2) for _ in range(4)][:size]
                    keys = []
                    for slot, seat in enumerate(seats):
                        token_index = slot % 4
                        game.players[seat].tokens[token_index].steps = game.layout.steps_to_reach(seat, safe)
                        keys.append((seat, token_index))
                    pins = BoardRenderer(game.layout).token_pins(game)
                    order = [key for key in pins if key in keys]
                    for position, key in enumerate(order):
                        ink = self.label_ink(str(key[1] + 1), pins[key][0])
                        for later in order[position + 1:]:
                            (cx, cy), radius = pins[later]
                            nearest_x = min(max(cx, ink.left), ink.right)
                            nearest_y = min(max(cy, ink.top), ink.bottom)
                            head = radius + PIN_RING_WIDTH
                            self.assertGreaterEqual(
                                ((cx - nearest_x) ** 2 + (cy - nearest_y) ** 2) ** 0.5,
                                head + LABEL_CLEARANCE,
                                f"pawn {later} covers (or nearly covers) the number of pawn {key}",
                            )


class SeatMarkingContrastTests(unittest.TestCase):
    """Markings drawn on seat colours (arrows, pawn numbers, names) are readable."""

    fonts: dict[str, pygame.font.Font]

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame and the app fonts once for the contrast checks."""

        pygame.init()
        cls.fonts = ui.make_fonts()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the contrast checks."""

        pygame.quit()

    def all_seat_colors(self) -> set[tuple[int, int, int]]:
        """Return every seat colour used by any supported board."""

        return {color for count in (4, 5, 6) for color in seat_colors(count)}

    def test_contrast_ratio_matches_the_wcag_formula(self) -> None:
        """Black on white is 21:1 and any colour against itself is 1:1."""

        self.assertAlmostEqual(theme.contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0, places=2)
        self.assertAlmostEqual(theme.contrast_ratio((120, 30, 200), (120, 30, 200)), 1.0)

    def test_label_colour_beats_the_design_target_on_every_seat_fill(self) -> None:
        """The label colour picked for each seat colour and start tint reaches 4.5:1.

        This compares plain colours, so it is exact and font-independent. The
        design target (LABEL_CONTRAST_TARGET) sits well above the 3:1 floor
        that rendered, antialiased pixels must clear on any platform.
        """

        seats = self.all_seat_colors()
        fills = seats | {theme.brighten(color, START_CELL_BRIGHTEN) for color in seats}
        for fill in fills:
            with self.subTest(fill=fill):
                label = theme.readable_on(fill)
                self.assertGreaterEqual(theme.contrast_ratio(label, fill), LABEL_CONTRAST_TARGET)
                self.assertGreater(LABEL_CONTRAST_TARGET, MIN_LABEL_CONTRAST)

    def test_start_arrows_use_the_readable_colour_of_their_start_cells(self) -> None:
        """Each start square's arrow is drawn in exactly the readable colour for that square."""

        for count in (4, 5, 6):
            surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
            renderer = BoardRenderer(make_game(count).layout)
            renderer.draw_static(surface)
            for seat, start in enumerate(renderer.layout.start_indices):
                with self.subTest(total_players=count, seat=seat):
                    x, y = renderer.display.track_positions[start]
                    cell = theme.brighten(seat_colors(count)[seat], START_CELL_BRIGHTEN)
                    # The arrow shaft is a plain 3 px line through the square's
                    # centre, so this pixel is the arrow colour exactly.
                    self.assertEqual(rgb(surface.get_at((int(x), int(y)))), theme.readable_on(cell))

    def test_pawn_numbers_use_the_readable_colour_of_the_pawn(self) -> None:
        """draw_token_pin renders each number in readable_on(pawn colour)."""

        for color in self.all_seat_colors():
            with self.subTest(color=color):
                recorder = RecordingFont(self.fonts["tiny"])
                fonts = {"tiny": cast(pygame.font.Font, recorder)}
                theme.draw_token_pin(pygame.Surface((80, 80)), (40, 36), color, radius=15, label="4", fonts=fonts)
                self.assertEqual(recorder.colors, [theme.readable_on(color)])

    def test_rendered_pawn_numbers_clear_the_contrast_floor(self) -> None:
        """Sanity check on real pixels: some ink pixel of each number reaches 3:1.

        Antialiasing thins strokes differently per font, so this only asks for
        the 3:1 floor while the colours themselves target 4.5:1.
        """

        for color in self.all_seat_colors():
            with self.subTest(color=color):
                surface = pygame.Surface((80, 80))
                theme.draw_token_pin(surface, (40, 36), color, radius=15, label="4", fonts=self.fonts)
                image = self.fonts["tiny"].render("4", True, (255, 255, 255))
                ink = image.get_bounding_rect().move(image.get_rect(center=(40, 36)).topleft)
                best = max(
                    theme.contrast_ratio(rgb(surface.get_at((x, y))), color)
                    for x in range(ink.left, ink.right)
                    for y in range(ink.top, ink.bottom)
                )
                self.assertGreaterEqual(best, MIN_LABEL_CONTRAST)


class GameOverLayoutTests(unittest.TestCase):
    """The game-over screen puts the winner on a plaque and centres its buttons."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once for the game-over checks."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the game-over checks."""

        pygame.quit()

    def finished_app(self, winner_name: str = "Player 1") -> main.LudoApp:
        """Return a non-persisting app showing a finished 6P game won by seat 0."""

        app = main.LudoApp(persist=False)
        self.addCleanup(setattr, app, "running", False)
        players = [(winner_name, True)] + [(f"AI {seat}", False) for seat in range(1, 6)]
        game = LudoGame(players, LudoRules(total_players=6), seed=2)
        for token in game.players[0].tokens:
            token.steps = game.layout.finish_steps
        game._finish_game(0)
        app.start_game(game)
        app.screen = "over"
        return app

    def test_winner_name_sits_on_a_plaque_in_the_winner_colour(self) -> None:
        """Behind the winner text is a plaque filled with the winner's colour, not wallpaper."""

        app = self.finished_app()
        app._draw()
        assert app.game is not None
        winner = app.game.players[0]
        plaque, text = app._winner_plaque(winner)
        self.assertEqual(text, "Player 1 wins!")
        self.assertEqual(rgb(app.window.get_at((plaque.x + 8, plaque.centery))), winner.color)
        label = theme.readable_on(winner.color)
        self.assertGreaterEqual(theme.contrast_ratio(label, winner.color), LABEL_CONTRAST_TARGET)

    def test_long_winner_names_still_fit_their_plaque(self) -> None:
        """A wide winner name is ellipsized so the text stays inside a plaque left of the panel."""

        app = self.finished_app("W" * 18)
        assert app.game is not None
        plaque, text = app._winner_plaque(app.game.players[0])
        text_rect = pygame.Rect((0, 0), app.fonts["title"].size(text))
        text_rect.center = plaque.center
        self.assertTrue(plaque.contains(text_rect), f"{text_rect} spills out of {plaque}")
        self.assertTrue(text.endswith("wins!"))
        self.assertLessEqual(plaque.right, main.PANEL_X)
        self.assertGreaterEqual(plaque.left, 0)

    def test_end_buttons_are_centred_under_the_stats_card(self) -> None:
        """New Game and Quit share the stats card's centre line."""

        app = self.finished_app()
        buttons = app._buttons_for_screen()
        self.assertEqual([button.key for button in buttons], ["new_game", "quit"])
        for button in buttons:
            with self.subTest(button=button.key):
                self.assertEqual(button.rect.centerx, main.OVER_STATS_RECT.centerx)


class MoveHighlightTests(unittest.TestCase):
    """Move-highlight rings have a dark edge, so they show up on the cream board."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once for the highlight checks."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the highlight checks."""

        pygame.quit()

    def test_rings_stand_out_on_the_cream_board(self) -> None:
        """Along every direction, each ring shows its colour and a dark edge against cream."""

        game = make_game(4)
        game.players[0].tokens[0].steps = 10
        game.record_roll(2)
        moves = [move for move in game.legal_moves(2) if move.token_index == 0]
        renderer = BoardRenderer(game.layout)
        pins = renderer.token_pins(game)
        start, _radius = pins[(0, 0)]
        landing = renderer.position_for(0, moves[0].to_steps, 0)
        for name, centre, color in (("token ring", start, WHITE), ("landing ring", landing, GOLD)):
            surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
            surface.fill(theme.CREAM)
            renderer._draw_move_highlights(surface, moves, pins)
            for angle in range(0, 360, 45):
                with self.subTest(ring=name, angle=angle):
                    direction = pygame.math.Vector2(1, 0).rotate(angle)
                    samples = [
                        rgb(surface.get_at((int(centre[0] + direction.x * step), int(centre[1] + direction.y * step))))
                        for step in range(20, 46)
                    ]
                    self.assertIn(color, samples, "ring colour missing")
                    edge = max(theme.contrast_ratio(sample, theme.CREAM) for sample in samples)
                    self.assertGreaterEqual(edge, MIN_LABEL_CONTRAST, "ring has no visible edge on cream")


class BlendedShadowTests(unittest.TestCase):
    """Drop shadows darken what is under them instead of painting solid black."""

    BACKGROUND = (200, 200, 200)

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once for the shadow checks."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the shadow checks."""

        pygame.quit()

    def canvas(self) -> pygame.Surface:
        """Return an opaque light-grey surface, like the game's window."""

        surface = pygame.Surface((200, 200))
        surface.fill(self.BACKGROUND)
        return surface

    def assert_blended(self, pixel: pygame.Color) -> None:
        """Fail unless ``pixel`` is darker than the background but clearly not black."""

        value = rgb(pixel)
        self.assertLess(value[0], self.BACKGROUND[0], f"{value} is not shaded")
        self.assertGreater(value[0], self.BACKGROUND[0] // 4, f"{value} is (nearly) solid black")

    def test_rect_shadow_is_blended(self) -> None:
        """The strip below a shadowed rect is a translucent shade."""

        surface = self.canvas()
        theme.draw_shadowed_rect(surface, pygame.Rect(40, 40, 100, 60), (90, 90, 200), radius=8, shadow_offset=(0, 6))
        self.assert_blended(surface.get_at((90, 103)))

    def test_polygon_shadow_is_blended(self) -> None:
        """The strip below a shadowed polygon is a translucent shade."""

        surface = self.canvas()
        theme.draw_shadowed_polygon(surface, [(40, 40), (160, 40), (160, 120), (40, 120)], (90, 90, 200))
        self.assert_blended(surface.get_at((100, 124)))

    def test_pawn_shadow_is_blended(self) -> None:
        """The oval under a pawn, beside its pointer, is a translucent shade."""

        surface = self.canvas()
        theme.draw_token_pin(surface, (100, 80), (200, 60, 60), radius=15)
        self.assert_blended(surface.get_at((87, 95)))

    def test_radial_hub_shadow_is_blended(self) -> None:
        """The shadow under the radial hub is a translucent shade, not black."""

        surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        surface.fill(self.BACKGROUND)
        renderer = BoardRenderer(make_game(6).layout)
        renderer._draw_center_home(surface, None)
        hub = renderer.display.hub_polygon
        lowest = max(hub, key=lambda point: point[1])
        self.assert_blended(surface.get_at((int(lowest[0]), int(lowest[1]) + 4)))


class WallpaperGlowTests(unittest.TestCase):
    """The soft glow behind the board blends over the dice stamps, with no rim."""

    @classmethod
    def setUpClass(cls) -> None:
        """Build the full-size wallpaper once for the glow checks."""

        pygame.init()
        cls.wallpaper = theme._build_wallpaper((SCREEN_WIDTH, SCREEN_HEIGHT))

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the glow checks."""

        pygame.quit()

    wallpaper: pygame.Surface

    def brightness(self, point: tuple[int, int]) -> float:
        """Return the perceived brightness of one wallpaper pixel."""

        return luminance(rgb(self.wallpaper.get_at(point)))

    def test_stamps_stay_visible_inside_the_glow(self) -> None:
        """A stamp's parking dot near the glow's centre is darker than the gap beside it."""

        # The stamp at (540, 440) lies well inside the glow; its first dot is at
        # (+28, +28), and (530, 430) is open wallpaper just outside the stamp.
        self.assertGreater(self.brightness((530, 430)) - self.brightness((568, 468)), 8)

    def test_glow_fades_out_without_a_hard_rim(self) -> None:
        """Walking out through the glow's edge, brightness never jumps between neighbours."""

        centre = pygame.math.Vector2(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)
        radius = min(SCREEN_WIDTH, SCREEN_HEIGHT) // 3
        # At -10 degrees the edge crosses open wallpaper between the stamps.
        direction = pygame.math.Vector2(1, 0).rotate(-10)
        samples = []
        for step in range(radius - 60, radius + 30):
            point = centre + direction * step
            samples.append(self.brightness((int(point.x), int(point.y))))
        jumps = [abs(after - before) for before, after in itertools.pairwise(samples)]
        self.assertLess(max(jumps), 3, "the glow ends in a visible rim")


class SetupIntroTests(unittest.TestCase):
    """The setup screen's intro sits on a dark plate that holds every line."""

    @classmethod
    def setUpClass(cls) -> None:
        """Initialize pygame once for the intro checks."""

        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        """Release pygame after the intro checks."""

        pygame.quit()

    def setUp(self) -> None:
        """Draw one setup frame with a non-persisting app."""

        self.app = main.LudoApp(persist=False)
        self.addCleanup(setattr, self.app, "running", False)
        self.app._draw()

    def test_intro_text_contrasts_with_its_plate(self) -> None:
        """The intro colour reaches the 4.5:1 target against the plate actually drawn."""

        plate, _lines = self.app._setup_intro_layout()
        behind = rgb(self.app.window.get_at((plate.x + 6, plate.centery)))
        self.assertGreaterEqual(theme.contrast_ratio(main.SETUP_INTRO_COLOR, behind), LABEL_CONTRAST_TARGET)

    def test_plate_holds_every_line_and_clears_the_title_and_previews(self) -> None:
        """Every wrapped line fits inside the plate, which sits between the title and previews."""

        plate, lines = self.app._setup_intro_layout()
        font = self.app.fonts["body"]
        self.assertGreaterEqual(len(lines), 2)
        for index, line in enumerate(lines):
            with self.subTest(line=line):
                box = pygame.Rect(0, 0, *font.size(line))
                box.centerx = plate.centerx
                box.y = plate.y + main.SETUP_INTRO_PADDING[1] + index * (font.get_height() + main.SETUP_INTRO_LINE_GAP)
                self.assertTrue(plate.contains(box), f"{box} spills out of {plate}")
        title_bottom = main.SETUP_TITLE_CENTER[1] + self.app.fonts["huge"].get_height() // 2
        self.assertGreater(plate.top, title_bottom)
        preview_top = min(y for _x, y in main.PREVIEW_CENTERS) - main.PREVIEW_SIZE // 2
        self.assertLess(plate.bottom + 2 * LINE_HEIGHT_SLACK * len(lines), preview_top)


if __name__ == "__main__":
    unittest.main()
