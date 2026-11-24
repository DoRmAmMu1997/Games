"""Input-handler tests for ``SolitaireApp`` that never open a window.

The app is built with ``object.__new__`` so ``__init__`` (which creates real
tkinter widgets) never runs. The root window, canvas and message boxes are
mocks, and the label variables are tiny stand-ins, so the handlers run
headless against a real ``KlondikeGame``.
"""

from __future__ import annotations

import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

GAME_DIR = Path(__file__).resolve().parents[1]
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

from solitaire import (
    AUDIO_TICK_MS,
    CARD_HEIGHT,
    CARD_WIDTH,
    FOUNDATION_COUNT,
    MUSIC_GAME_OVER_FADE_MS,
    TABLEAU_COLUMNS,
    AnimationState,
    Card,
    KlondikeGame,
    SilentAudio,
    SolitaireApp,
)


class FakeVar:
    """A stand-in for ``tk.StringVar`` that just remembers its value."""

    def __init__(self, value: str = "") -> None:
        """Store the starting value."""

        self.value = value

    def set(self, value: str) -> None:
        """Remember a new value."""

        self.value = value

    def get(self) -> str:
        """Return the current value."""

        return self.value


def make_app(tmp_dir: str, seed: int = 7) -> SolitaireApp:
    """Build a headless SolitaireApp around a seeded game and mock widgets."""

    app = object.__new__(SolitaireApp)
    app.root = mock.Mock()
    app.canvas = mock.Mock()
    app.game = KlondikeGame(str(Path(tmp_dir) / "scores.json"), rng=random.Random(seed))
    app.selection = None
    app.hint_move = None
    app.animation = None
    app.auto_solving = False
    app.auto_solve_seen_states = set()
    app.history = []
    app.score_var = FakeVar()  # type: ignore[assignment]
    app.high_score_var = FakeVar()  # type: ignore[assignment]
    app.time_var = FakeVar()  # type: ignore[assignment]
    app.stats_var = FakeVar()  # type: ignore[assignment]
    app.status_var = FakeVar()  # type: ignore[assignment]
    app.sound_var = FakeVar()  # type: ignore[assignment]
    app.started_at = 0.0
    app.elapsed_seconds = 0
    # A mock sound wrapper records which sounds the handlers ask for.
    app.audio = mock.Mock()
    return app


def click_at(x: float, y: float) -> mock.Mock:
    """Return a fake mouse event at the given canvas point."""

    event = mock.Mock()
    event.x = int(x)
    event.y = int(y)
    return event


class AppHandlerTestCase(unittest.TestCase):
    """Shared setup: a headless app with message boxes patched out."""

    def setUp(self) -> None:
        """Create the app in a temp save folder and patch ``solitaire.messagebox``."""

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch("solitaire.messagebox")
        self.messagebox = patcher.start()
        self.addCleanup(patcher.stop)
        self.app = make_app(self.tmp.name)
        self.game = self.app.game
        # Keep a typed handle on the mock root so tests can inspect `after`.
        self.root = mock.Mock()
        self.app.root = self.root

    def clear_board(self) -> None:
        """Empty every pile so a test can craft an exact board."""

        self.game.stock = []
        self.game.waste = []
        self.game.foundations = [[] for _ in range(FOUNDATION_COUNT)]
        self.game.tableau = [[] for _ in range(TABLEAU_COLUMNS)]

    def stock_click(self) -> mock.Mock:
        """Return an event in the middle of the stock pile."""

        x1, y1, _, _ = self.app.stock_rect()
        return click_at(x1 + CARD_WIDTH / 2, y1 + CARD_HEIGHT / 2)

    def tableau_click(self, column_index: int, card_index: int) -> mock.Mock:
        """Return an event on the visible strip of one tableau card."""

        y = self.app.tableau_positions(column_index)[card_index]
        return click_at(self.app.tableau_x(column_index) + CARD_WIDTH / 2, y + 5)


class DoubleClickTests(AppHandlerTestCase):
    """Double-clicks that do not send a card home act like a normal click (D5)."""

    def test_stock_double_click_draws(self) -> None:
        """The second click of a fast double-click on the stock still draws."""

        waste_before = len(self.game.waste)

        self.app.on_canvas_double_click(self.stock_click())

        self.assertEqual(len(self.game.waste), waste_before + 1)

    def test_won_board_double_click_explains_itself(self) -> None:
        """A double-click on a won board says why nothing happens."""

        self.game.won = True

        self.app.on_canvas_double_click(self.stock_click())

        self.assertEqual(self.app.status_var.get(), "You already won. Click New Game to play again.")

    def test_busy_board_double_click_explains_itself(self) -> None:
        """A double-click during a card animation asks the player to wait."""

        self.app.animation = AnimationState([], [], [], "tableau", 0, "done")

        self.app.on_canvas_double_click(self.stock_click())

        self.assertEqual(self.app.status_var.get(), "Please wait for the card animation to finish.")

    def test_quick_second_click_on_selected_card_deselects_it(self) -> None:
        """Clicking a selected card twice quickly clears the selection."""

        self.clear_board()
        self.game.tableau[0] = [Card("spades", 9, face_up=True)]
        self.game.tableau[1] = [Card("clubs", 13, face_up=True)]
        self.game.stock = [Card("hearts", 13, face_up=False)]
        self.app.on_canvas_click(self.tableau_click(0, 0))
        self.assertIsNotNone(self.app.selection)

        self.app.on_canvas_double_click(self.tableau_click(0, 0))

        self.assertIsNone(self.app.selection)
        self.assertEqual(self.app.status_var.get(), "Selection cleared.")

    def test_double_click_still_sends_a_card_home(self) -> None:
        """A double-click on a card that fits a foundation starts that move."""

        self.clear_board()
        self.game.tableau[0] = [Card("hearts", 1, face_up=True)]
        self.game.stock = [Card("hearts", 13, face_up=False)]

        self.app.on_canvas_double_click(self.tableau_click(0, 0))

        self.assertEqual(len(self.game.foundations[0]), 1)
        self.assertIsNotNone(self.app.animation)


class GameOverTests(AppHandlerTestCase):
    """Undo and the win celebration once a game has ended (D7)."""

    def finish_with_one_move_left(self) -> None:
        """Craft a board one foundation move from winning and play it via the app."""

        self.clear_board()
        suits = ["hearts", "diamonds", "clubs", "spades"]
        for index, suit in enumerate(suits):
            self.game.foundations[index] = [Card(suit, rank, face_up=True) for rank in range(1, 14)]
        king = self.game.foundations[3].pop()
        self.game.tableau[0] = [king]
        self.app.on_canvas_double_click(self.tableau_click(0, 0))
        assert self.app.animation is not None
        self.app.animation.frame = self.app.animation.steps
        self.app.advance_animation()

    def test_undo_is_refused_after_a_win(self) -> None:
        """A won game stays won: Undo explains itself and changes nothing."""

        self.finish_with_one_move_left()
        self.assertTrue(self.game.won)
        wins = self.game.wins
        history_length = len(self.app.history)

        self.app.undo_last_action()

        self.assertTrue(self.game.won)
        self.assertEqual(self.game.wins, wins)
        self.assertEqual(len(self.app.history), history_length)
        self.assertEqual(self.app.status_var.get(), "You already won. Click New Game to play again.")

    def test_undo_is_allowed_after_a_loss(self) -> None:
        """Undo after a loss takes the loss back and reopens the game."""

        self.clear_board()
        self.game.tableau[0] = [Card("spades", 4, face_up=False), Card("hearts", 9, face_up=True)]
        self.game.tableau[1] = [Card("clubs", 10, face_up=True)]
        self.game.tableau[2] = [Card("hearts", 13, face_up=False), Card("diamonds", 2, face_up=True)]
        self.app.on_canvas_click(self.tableau_click(0, 1))
        self.app.on_canvas_click(self.tableau_click(1, 0))
        assert self.app.animation is not None
        self.app.animation.frame = self.app.animation.steps
        self.app.advance_animation()
        self.assertTrue(self.game.lost)
        self.assertEqual(self.game.losses, 1)

        self.app.undo_last_action()

        self.assertFalse(self.game.lost)
        self.assertEqual(self.game.losses, 0)
        self.assertEqual(self.game.tableau[0][-1].label(), "9\u2665")

    def test_new_game_during_confetti_stops_the_celebration(self) -> None:
        """Starting a new game mid-celebration cancels the stale win dialog."""

        on_finished = mock.Mock()
        self.game.won = True
        self.app._play_win_celebration(on_finished)
        step = self.root.after.call_args[0][1]
        self.root.after.reset_mock()

        self.game.won = False
        step()

        on_finished.assert_not_called()
        self.root.after.assert_not_called()

    def test_celebration_finishes_with_the_dialog(self) -> None:
        """Left alone, the celebration runs its frames and then shows the dialog."""

        on_finished = mock.Mock()
        self.game.won = True
        self.app._play_win_celebration(on_finished)
        for _ in range(500):
            if not self.root.after.called:
                break
            step = self.root.after.call_args[0][1]
            self.root.after.reset_mock()
            step()

        on_finished.assert_called_once()


class LossAndAutoSolveTests(AppHandlerTestCase):
    """The shell's loss check and the auto-solve loop (D10)."""

    def run_scheduled_callbacks(self, limit: int = 2000) -> None:
        """Run ``root.after`` callbacks one by one until none are left."""

        for _ in range(limit):
            if not self.root.after.called:
                return
            callback = self.root.after.call_args[0][1]
            self.root.after.reset_mock()
            callback()
        self.fail("scheduled callbacks never settled")

    def test_stuck_board_ends_the_game_as_a_loss(self) -> None:
        """check_for_loss records a loss and tells the player when no move remains."""

        self.clear_board()
        self.game.tableau[0] = [Card("spades", 4, face_up=False), Card("hearts", 9, face_up=True)]

        self.app.check_for_loss()

        self.assertTrue(self.game.lost)
        self.assertEqual(self.game.losses, 1)
        self.messagebox.showinfo.assert_called_once()

    def test_playable_board_is_not_a_loss(self) -> None:
        """check_for_loss leaves a board with a useful move alone."""

        self.clear_board()
        self.game.tableau[0] = [Card("spades", 4, face_up=False), Card("hearts", 9, face_up=True)]
        self.game.tableau[1] = [Card("clubs", 10, face_up=True)]

        self.app.check_for_loss()

        self.assertFalse(self.game.lost)
        self.messagebox.showinfo.assert_not_called()

    def test_auto_solve_finishes_a_face_up_board(self) -> None:
        """Once every card is face up, auto-solve plays the deal out to a win."""

        self.clear_board()
        suits = ["hearts", "diamonds", "clubs", "spades"]
        for index, suit in enumerate(suits):
            self.game.foundations[index] = [Card(suit, rank, face_up=True) for rank in range(1, 12)]
        self.game.tableau[0] = [Card("spades", 13, face_up=True), Card("hearts", 12, face_up=True)]
        self.game.tableau[1] = [Card("hearts", 13, face_up=True), Card("clubs", 12, face_up=True)]
        self.game.stock = [Card("clubs", 13), Card("diamonds", 12), Card("diamonds", 13), Card("spades", 12)]
        self.assertTrue(self.app.should_auto_solve())

        self.app.begin_auto_solve()
        self.run_scheduled_callbacks()

        self.assertTrue(self.game.won)
        self.assertEqual(self.game.wins, 1)
        self.assertFalse(self.app.auto_solving)
        self.messagebox.showinfo.assert_called_once()


class SoundEffectTests(AppHandlerTestCase):
    """Each table action asks the app's sound wrapper for its effect."""

    def setUp(self) -> None:
        """Give the app a fresh mock sound wrapper that the tests can inspect."""

        super().setUp()
        self.audio = mock.Mock()
        self.app.audio = self.audio

    def played(self) -> list[tuple[str, int]]:
        """Return every requested sound as (name, pitch step), in order."""

        return [(call.args[0], call.kwargs.get("pitch_step", 0)) for call in self.audio.play.call_args_list]

    def names(self) -> list[str]:
        """Return the names of every requested sound, in order."""

        return [name for name, _ in self.played()]

    def playable_board(self) -> None:
        """Craft a small board with a hidden card and one legal move (9 of hearts onto the 10 of clubs)."""

        self.clear_board()
        self.game.tableau[0] = [Card("spades", 4, face_up=False), Card("hearts", 9, face_up=True)]
        self.game.tableau[1] = [Card("clubs", 10, face_up=True)]

    def land(self) -> None:
        """Run the card animation that is in flight to its last frame."""

        assert self.app.animation is not None
        self.app.animation.frame = self.app.animation.steps
        self.app.advance_animation()

    def foundation_click(self, foundation_index: int) -> mock.Mock:
        """Return an event in the middle of one foundation pile."""

        x1, y1, _, _ = self.app.foundation_rect(foundation_index)
        return click_at(x1 + CARD_WIDTH / 2, y1 + CARD_HEIGHT / 2)

    def test_picking_up_a_card_plays_select(self) -> None:
        """Selecting a face-up card plays the pick-up tick."""

        self.playable_board()

        self.app.on_canvas_click(self.tableau_click(0, 1))

        self.assertEqual(self.names(), ["select"])

    def test_waste_and_foundation_pick_ups_play_select(self) -> None:
        """Lifting the top waste card or a foundation card also plays the pick-up tick."""

        self.playable_board()
        self.game.waste = [Card("diamonds", 5, face_up=True)]
        self.game.foundations[0] = [Card("hearts", 1, face_up=True)]

        self.app.handle_waste_click()
        self.app.selection = None
        self.app.handle_foundation_click(0)

        self.assertEqual(self.names(), ["select", "select"])

    def test_tableau_move_plays_place_when_the_cards_land(self) -> None:
        """A tableau move is silent in flight and thuds onto the felt as it lands."""

        self.clear_board()
        self.game.tableau[0] = [Card("hearts", 9, face_up=True)]
        self.game.tableau[1] = [Card("clubs", 10, face_up=True)]
        self.game.tableau[2] = [Card("spades", 4, face_up=False), Card("spades", 5, face_up=True)]
        self.game.stock = [Card("diamonds", 13, face_up=False)]
        self.app.on_canvas_click(self.tableau_click(0, 0))
        self.app.on_canvas_click(self.tableau_click(1, 0))
        self.assertEqual(self.names(), ["select"])

        self.land()

        self.assertEqual(self.names(), ["select", "place"])

    def test_foundation_chime_rises_with_the_rank(self) -> None:
        """A card landing on its foundation chimes at its own rank's pitch."""

        self.playable_board()
        self.game.tableau[2] = [Card("hearts", 3, face_up=True)]
        self.game.foundations[0] = [Card("hearts", 1, face_up=True), Card("hearts", 2, face_up=True)]
        self.app.on_canvas_click(self.tableau_click(2, 0))
        self.app.on_canvas_click(self.foundation_click(0))

        self.land()

        self.assertEqual(self.played()[-1], ("foundation", 3))

    def test_revealing_a_hidden_card_plays_flip(self) -> None:
        """Moving the last card off a face-down card flips it with a paper sound."""

        self.playable_board()
        self.game.stock = [Card("diamonds", 13, face_up=False)]
        self.app.on_canvas_click(self.tableau_click(0, 1))

        self.app.on_canvas_click(self.tableau_click(1, 0))

        self.assertEqual(self.names(), ["select", "flip"])

    def test_stock_clicks_draw_recycle_and_knock_when_empty(self) -> None:
        """The stock draws, recycles the waste, and knocks dully once both piles are empty."""

        self.playable_board()
        self.game.stock = [Card("diamonds", 13, face_up=False)]

        self.app.on_canvas_click(self.stock_click())
        self.app.on_canvas_click(self.stock_click())
        self.game.stock = []
        self.app.on_canvas_click(self.stock_click())

        self.assertEqual(self.names(), ["draw", "recycle", "empty"])

    def test_illegal_moves_play_invalid(self) -> None:
        """Moves the rules refuse play the soft "uh-uh"."""

        self.playable_board()
        self.app.on_canvas_click(self.tableau_click(0, 1))
        self.app.on_canvas_click(self.foundation_click(0))
        self.app.handle_tableau_click(2, None)
        self.app.selection = None
        self.app.on_canvas_click(self.tableau_click(0, 0))

        self.assertEqual(self.names(), ["select", "invalid", "invalid", "invalid"])

    def test_refused_animation_move_plays_invalid(self) -> None:
        """A move the model rejects at the last moment is an illegal move too."""

        self.playable_board()
        selection = self.game.selection_from_tableau(0, 1)
        assert selection is not None

        self.app.animate_move(selection, "tableau", 0, "never shown")

        self.assertEqual(self.names(), ["invalid"])

    def test_undo_plays_undo_and_an_empty_history_plays_invalid(self) -> None:
        """A real undo rewinds; with nothing to undo the click is refused audibly."""

        self.playable_board()
        self.game.stock = [Card("diamonds", 13, face_up=False)]
        self.app.undo_last_action()
        self.app.on_canvas_click(self.stock_click())

        self.app.undo_last_action()

        self.assertEqual(self.names(), ["invalid", "draw", "undo"])

    def test_hint_plays_hint(self) -> None:
        """Showing a hint plays the sparkle."""

        self.playable_board()

        self.app.show_hint()

        self.assertEqual(self.names(), ["hint"])

    def test_new_game_plays_the_deal(self) -> None:
        """Dealing a new game plays the cascade of ticks."""

        self.app.start_new_game()

        self.assertIn("deal", self.names())

    def test_help_button_clicks(self) -> None:
        """The Help button plays the button click."""

        self.app.show_help()

        self.assertEqual(self.names(), ["click"])

    def test_auto_solve_plays_quick_chimes(self) -> None:
        """Auto-solve's foundation moves chime the lighter rising set, never the full chime."""

        self.clear_board()
        suits = ["hearts", "diamonds", "clubs", "spades"]
        for index, suit in enumerate(suits):
            self.game.foundations[index] = [Card(suit, rank, face_up=True) for rank in range(1, 12)]
        self.game.tableau[0] = [Card("spades", 13, face_up=True), Card("hearts", 12, face_up=True)]
        self.game.tableau[1] = [Card("hearts", 13, face_up=True), Card("clubs", 12, face_up=True)]
        self.game.stock = [Card("clubs", 13), Card("diamonds", 12), Card("diamonds", 13), Card("spades", 12)]

        self.app.begin_auto_solve()
        for _ in range(2000):
            if not self.root.after.called:
                break
            callback = self.root.after.call_args[0][1]
            self.root.after.reset_mock()
            callback()

        self.assertTrue(self.game.won)
        self.assertIn(("auto_step", 12), self.played())
        self.assertIn(("auto_step", 13), self.played())
        self.assertIn("draw", self.names())
        self.assertNotIn("foundation", self.names())

    def test_missing_sound_wrapper_is_silent(self) -> None:
        """An app built without ``__init__`` and without sound still runs its handlers."""

        self.playable_board()
        del self.app.audio

        self.app.on_canvas_click(self.tableau_click(0, 1))

        self.assertIsInstance(self.app.audio, SilentAudio)
        self.assertIsNotNone(self.app.selection)

    def test_winning_fades_the_music_into_the_win_jingle(self) -> None:
        """The last card home fades the music out and plays the win jingle after its chime."""

        self.clear_board()
        for index, suit in enumerate(["hearts", "diamonds", "clubs", "spades"]):
            self.game.foundations[index] = [Card(suit, rank, face_up=True) for rank in range(1, 14)]
        self.game.tableau[0] = [self.game.foundations[3].pop()]
        self.app.on_canvas_double_click(self.tableau_click(0, 0))

        self.land()

        self.assertEqual(self.played()[-2:], [("foundation", 13), ("win", 0)])
        self.audio.stop_music.assert_called_once_with(MUSIC_GAME_OVER_FADE_MS)

    def test_losing_fades_the_music_into_the_loss_jingle_before_the_dialog(self) -> None:
        """A lost deal fades the music and plays the loss jingle before the dialog opens."""

        self.clear_board()
        self.game.tableau[0] = [Card("spades", 4, face_up=False), Card("hearts", 9, face_up=True)]
        order = mock.Mock()
        order.attach_mock(self.audio.stop_music, "stop_music")
        order.attach_mock(self.audio.play, "play")
        order.attach_mock(self.messagebox.showinfo, "showinfo")

        self.app.check_for_loss()

        self.assertEqual(
            [call[0] for call in order.mock_calls], ["stop_music", "play", "showinfo"]
        )
        self.audio.stop_music.assert_called_once_with(MUSIC_GAME_OVER_FADE_MS)
        self.assertEqual(self.names(), ["lose"])

    def test_new_game_restarts_the_music(self) -> None:
        """A new deal asks for the music again (it fades out at every game over)."""

        self.app.start_new_game()

        self.audio.start_music.assert_called_once_with()

    def test_undoing_a_loss_restarts_the_music(self) -> None:
        """Undo out of a lost game brings the music back; an ordinary undo leaves it alone."""

        self.playable_board()
        self.game.stock = [Card("diamonds", 13, face_up=False)]
        self.app.on_canvas_click(self.stock_click())
        self.app.undo_last_action()
        self.audio.start_music.assert_not_called()

        self.app.on_canvas_click(self.stock_click())
        self.app.end_game_as_loss()
        self.app.undo_last_action()

        self.audio.start_music.assert_called_once_with()

    def test_audio_tick_updates_the_music_and_reschedules(self) -> None:
        """Each tick lets the music player start a finished render, then books the next tick."""

        self.app.schedule_audio_update()

        self.audio.update.assert_called_once_with()
        self.root.after.assert_called_once_with(AUDIO_TICK_MS, self.app.schedule_audio_update)

    def test_toggling_sound_mutes_saves_and_relabels(self) -> None:
        """Ctrl+M / the Sound button mute everything, save the choice and relabel the button."""

        self.app.toggle_sound()

        self.assertTrue(self.game.sound_muted)
        self.audio.set_muted.assert_called_once_with(True)
        self.assertEqual(self.app.sound_var.get(), "Sound: Off")
        self.assertTrue(KlondikeGame(self.game.high_score_path).sound_muted)
        self.assertEqual(self.names(), [])

    def test_toggling_sound_back_on_clicks(self) -> None:
        """Switching sound back on unmutes, relabels, saves and plays a click so the player hears it."""

        self.app.toggle_sound()
        self.app.toggle_sound(mock.Mock())

        self.assertFalse(self.game.sound_muted)
        self.audio.set_muted.assert_called_with(False)
        self.assertEqual(self.app.sound_var.get(), "Sound: On")
        self.assertFalse(KlondikeGame(self.game.high_score_path).sound_muted)
        self.assertEqual(self.names(), ["click"])

    def test_saved_mute_is_applied(self) -> None:
        """At start-up the saved choice reaches the sound wrapper and the button label."""

        self.game.sound_muted = True

        self.app.apply_sound_setting()

        self.audio.set_muted.assert_called_once_with(True)
        self.assertEqual(self.app.sound_var.get(), "Sound: Off")

    def test_toggling_mid_game_keeps_the_board_and_undo(self) -> None:
        """The sound choice is not a move: the board and the Undo history are untouched."""

        self.playable_board()
        self.game.stock = [Card("diamonds", 13, face_up=False)]
        self.app.on_canvas_click(self.stock_click())
        history = list(self.app.history)
        board = self.game.position_key()

        self.app.toggle_sound()
        self.app.undo_last_action()

        self.assertEqual(len(history), 1)
        self.assertEqual(self.app.history, [])
        self.assertNotEqual(self.game.position_key(), board)
        self.assertTrue(self.game.sound_muted)

    def test_closing_the_window_shuts_the_mixer(self) -> None:
        """Closing the window closes the sound first, then destroys the root."""

        order = mock.Mock()
        order.attach_mock(self.audio.close, "close")
        order.attach_mock(self.root.destroy, "destroy")

        self.app.close()

        self.assertEqual(order.mock_calls, [mock.call.close(), mock.call.destroy()])


if __name__ == "__main__":
    unittest.main()
