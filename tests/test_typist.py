import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from layout_switcher import keymap
from layout_switcher.autoreplace import Autoreplace
from layout_switcher.daemon import Daemon, Exceptions, Typist
from layout_switcher.keymap import keys_for

PRESS, RELEASE = 1, 0


class FakeLayouts:
    def __init__(self, current, names=("us", "ru", "ua")):
        self._current = current
        self._names = list(names)

    def state(self):
        return self._current, self._names

    def current(self):
        return self._current

    def activate(self, name, names=None):
        self._current = name


class FakeKeyboard:
    def __init__(self, layouts):
        self.layouts = layouts
        self.taps = []

    def tap(self, code, shift_code=None):
        self.taps.append((code, shift_code is not None, self.layouts.current()))

    def typed(self):
        """What the taps produce on screen, applied to an empty line."""
        text = []
        for code, shifted, layout in self.taps:
            if code == keymap.KEY_BACKSPACE:
                text.append("\b")
            elif code == keymap.KEY_SPACE:
                text.append(" ")
            else:
                text.append(keymap.render([(code, shifted)], layout))
        return "".join(text)


class FakeChecker:
    def __init__(self, words=()):
        self.words = set(words)

    def is_word(self, word, layout):
        return word.lower() in self.words


class FakeJudge:
    def __init__(self, switch, meant=()):
        self.switch = set(switch)
        self.meant = set(meant)
        self.asked = []
        self.checker = FakeChecker()
        self.layouts = {"us", "ru"}
        self.targets = {"us", "ru"}

    def supports(self, layout):
        return layout in self.layouts

    def is_word(self, word, layout):
        return self.checker.is_word(word, layout)

    def best_target(self, typed_text, typed_layout, readings):
        """Switch to the first reading whose layout the test allows, if the typed text is listed."""
        self.asked.append(typed_text)
        if typed_text not in self.switch:
            return None
        return next(((layout, text) for layout, text in readings if layout in self.targets), None)

    def could_be_meant(self, typed_text, typed_layout, intended_text, other_layout):
        return intended_text in self.meant


class TypistTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.layouts = FakeLayouts("us")
        self.keyboard = FakeKeyboard(self.layouts)
        self.judge = FakeJudge({"ghbdtn", "Ghbdtn"})
        self.exceptions = Exceptions(Path(self.tmp.name) / "exceptions.txt")
        self.autoreplace = Autoreplace(Path(self.tmp.name) / "autoreplace.txt")
        self.typist = Typist(self.judge, self.layouts, self.keyboard, self.exceptions, self.autoreplace)
        self.clock = 100.0
        patcher = mock.patch("layout_switcher.daemon.time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def key(self, code, value=PRESS, after=0.05):
        self.clock += after
        self.typist.on_key(code, value, now=self.clock)

    def tap(self, code):
        self.key(code, PRESS)
        self.key(code, RELEASE)

    def type_text(self, text, layout="us"):
        for i, word in enumerate(text.split(" ")):
            if i:
                self.tap(keymap.KEY_SPACE)
            for code, shifted in keys_for(word, layout):
                if shifted:
                    self.key(keymap.KEY_LEFTSHIFT, PRESS)
                self.tap(code)
                if shifted:
                    self.key(keymap.KEY_LEFTSHIFT, RELEASE)

    def double_shift(self):
        self.tap(keymap.KEY_LEFTSHIFT)
        self.tap(keymap.KEY_LEFTSHIFT)

    def test_retypes_a_word_typed_in_the_wrong_layout(self):
        self.type_text("ghbdtn")
        self.tap(keymap.KEY_SPACE)

        self.assertEqual(self.keyboard.typed(), "\b" * 7 + "привет ")
        self.assertEqual(self.layouts.current(), "ru")

    def test_retypes_short_words_right_before_a_switched_one(self):
        self.judge.switch = {"xnj"}
        self.judge.meant = {"ну", "и"}
        self.type_text("hello ye b xnj ")

        self.assertEqual(self.keyboard.typed(), "\b" * 9 + "ну и что ")

    def test_lead_in_stops_at_a_word_that_means_nothing_in_the_other_layout(self):
        self.judge.switch = {"xnj"}
        self.judge.meant = {"и"}
        self.type_text("ye b xnj ")

        self.assertEqual(self.keyboard.typed(), "\b" * 6 + "и что ")

    def test_lead_in_does_not_reach_past_a_click(self):
        self.judge.switch = {"xnj"}
        self.judge.meant = {"ну"}
        self.type_text("ye ")
        self.typist.on_pointer_button()
        self.type_text("xnj ")

        self.assertEqual(self.keyboard.typed(), "\b" * 4 + "что ")

    def test_reports_automatic_switches_only(self):
        switches = []
        self.typist.on_switch = lambda: switches.append(1)
        self.type_text("ghbdtn hello ")
        self.double_shift()

        self.assertEqual(switches, [1])

    def test_gives_up_without_touching_anything_if_typing_went_on(self):
        self.typist.user_kept_typing = lambda: True
        self.type_text("ghbdtn ")

        self.assertEqual(self.keyboard.taps, [])
        self.assertEqual(self.layouts.current(), "us")

    def test_keeps_the_new_layout_but_leaves_the_word_if_typing_starts_during_the_switch(self):
        answers = iter([False, True])
        self.typist.user_kept_typing = lambda: next(answers)
        self.type_text("ghbdtn ")

        self.assertEqual(self.keyboard.taps, [])
        self.assertEqual(self.layouts.current(), "ru")
        self.assertIsNone(self.typist.last_word)

    def test_no_exception_is_remembered_when_the_undo_did_not_happen(self):
        self.type_text("ghbdtn ")
        self.typist.user_kept_typing = lambda: True
        self.double_shift()

        self.assertNotIn(("us", "ghbdtn"), self.exceptions)

    def test_deletes_nothing_when_the_layout_switch_fails(self):
        def broken(name, names):
            raise RuntimeError("D-Bus is gone")
        self.layouts.activate = broken
        with self.assertRaises(RuntimeError):
            self.type_text("ghbdtn ")

        self.assertEqual(self.keyboard.taps, [])

    def test_does_not_switch_to_a_layout_kde_does_not_have(self):
        self.layouts._names = ["us", "de"]
        self.type_text("ghbdtn ")

        self.assertEqual(self.keyboard.taps, [])

    def test_double_shift_undoes_the_whole_retyped_phrase(self):
        self.judge.switch = {"xnj"}
        self.judge.meant = {"ну", "и"}
        self.type_text("ye b xnj ")
        self.keyboard.taps.clear()
        self.double_shift()

        self.assertEqual(self.keyboard.typed(), "\b" * 9 + "ye b xnj ")
        self.assertEqual(self.layouts.current(), "us")

    def test_lost_keyboard_releases_held_modifiers(self):
        self.key(keymap.KEY_LEFTCTRL, PRESS)
        self.typist.release_modifiers()
        self.type_text("ghbdtn ")

        self.assertEqual(self.layouts.current(), "ru")

    def write_autoreplace(self, text):
        self.autoreplace.path.write_text(text, encoding="utf-8")

    def test_expands_an_abbreviation_keeping_punctuation_and_case(self):
        self.layouts.activate("ru")
        self.write_autoreplace("спс = спасибо\n")
        self.type_text("Спс! ", "ru")

        self.assertEqual(self.keyboard.typed(), "\b" * 5 + "Спасибо! ")
        self.assertEqual(self.layouts.current(), "ru")

    def test_expands_in_capitals_when_typed_in_capitals(self):
        self.layouts.activate("ru")
        self.write_autoreplace("спс = спасибо\n")
        self.type_text("СПС ", "ru")

        self.assertEqual(self.keyboard.typed(), "\b" * 4 + "СПАСИБО ")

    def test_expands_an_abbreviation_typed_in_the_wrong_layout(self):
        self.write_autoreplace("спс = спасибо\n")
        self.type_text("cgc ")

        self.assertEqual(self.keyboard.typed(), "\b" * 4 + "спасибо ")
        self.assertEqual(self.layouts.current(), "ru")

    def test_wrong_layout_reading_does_not_override_a_real_word(self):
        self.write_autoreplace("щл = окей\n")
        self.judge.checker.words = {"ok"}
        self.type_text("ok ")

        self.assertEqual(self.keyboard.taps, [])

    def test_switches_layouts_inside_a_mixed_replacement_and_comes_back(self):
        self.layouts.activate("ru")
        self.write_autoreplace("почта = name@example.com, тел. 5\n")
        self.type_text("почта ", "ru")

        self.assertEqual(self.keyboard.typed(), "\b" * 6 + "name@example.com, тел. 5 ")
        self.assertEqual(self.layouts.current(), "ru")

    def test_double_shift_undoes_an_expansion(self):
        self.layouts.activate("ru")
        self.write_autoreplace("спс = спасибо\n")
        self.type_text("спс ", "ru")
        self.keyboard.taps.clear()
        self.double_shift()

        self.assertEqual(self.keyboard.typed(), "\b" * 8 + "спс ")
        self.assertEqual(self.layouts.current(), "ru")

    def test_skips_a_replacement_that_needs_a_layout_kde_does_not_have(self):
        self.layouts = FakeLayouts("ru", names=("ru", "de"))
        self.typist.layouts = self.layouts
        self.write_autoreplace("почта = name@example.com\n")
        with self.assertLogs("layout_switcher", "WARNING"):
            self.type_text("почта ", "ru")

        self.assertEqual(self.keyboard.taps, [])

    def test_matches_an_abbreviation_that_ends_in_punctuation(self):
        self.layouts.activate("ru")
        self.write_autoreplace("т.е. = то есть\n")
        self.type_text("т.е. ", "ru")

        self.assertEqual(self.keyboard.typed(), "\b" * 5 + "то есть ")

    def test_uses_the_real_caps_lock_state_for_the_replacement(self):
        self.layouts.activate("ru")
        self.write_autoreplace("спс = спасибо\n")
        self.typist.read_caps_lock = lambda: True
        self.type_text("спс ", "ru")  # unshifted keys: the screen shows "СПС"

        typed = [(code, shifted) for code, shifted, _ in self.keyboard.taps if code != keymap.KEY_BACKSPACE]
        # "СПАСИБО" with CapsLock on is typed without Shift.
        self.assertEqual(typed, keys_for("спасибо ", "ru"))

    def test_skips_a_replacement_no_layout_can_type(self):
        self.write_autoreplace("wr = Wrocław\n")
        with self.assertLogs("layout_switcher", "WARNING"):
            self.type_text("wr ")

        self.assertEqual(self.keyboard.taps, [])

    def test_ignores_typing_on_a_locked_screen(self):
        self.typist.session_allows = lambda: False
        self.type_text("ghbdtn ")
        self.double_shift()

        self.assertEqual(self.keyboard.taps, [])
        self.assertEqual(self.judge.asked, [])
        self.assertEqual(self.typist.word, [])

    def test_a_lock_in_the_middle_of_a_word_stops_the_switch(self):
        self.type_text("ghb")
        self.typist.session_allows = lambda: False
        self.type_text("dtn ")

        self.assertEqual(self.keyboard.taps, [])

    def test_works_again_after_unlocking(self):
        self.typist.session_allows = lambda: False
        self.type_text("ghbdtn ")
        self.typist.session_allows = lambda: True
        self.clock += 2
        self.type_text("ghbdtn ")

        self.assertEqual(self.keyboard.typed(), "\b" * 7 + "привет ")

    def test_asks_about_the_session_once_a_second_while_typing_and_before_acting(self):
        calls = []
        self.typist.session_allows = lambda: calls.append(self.clock) or True
        self.type_text("hello ")  # 12 key events, 0.05 s apart: one check at the start, one before acting
        self.assertEqual(len(calls), 2)

        self.clock += 2
        self.type_text("x ")  # the check made at "x" is fresh enough to act on at the space
        self.assertEqual(len(calls), 3)

    def test_a_word_begun_on_the_lock_screen_is_left_alone_after_unlocking(self):
        self.typist.session_allows = lambda: False
        self.type_text("ghb")
        self.typist.session_allows = lambda: True
        self.clock += 2
        self.type_text("dtn ")

        self.assertEqual(self.keyboard.taps, [])
        self.assertEqual(self.judge.asked, [])

        self.type_text("ghbdtn ")
        self.assertEqual(self.keyboard.typed(), "\b" * 7 + "привет ")

    def test_forgets_a_word_left_alone_for_long(self):
        self.type_text("ghb")
        self.clock += 31
        self.type_text("dtn ")

        self.assertEqual(self.judge.asked, ["dtn"])

    def test_switches_to_ukrainian_when_that_reading_is_chosen(self):
        self.layouts._names = ["us", "ru", "ua"]
        self.judge.layouts.add("ua")
        self.judge.targets = {"ua"}
        self.judge.switch = {"ghbdsn"}
        self.type_text("ghbdsn ")

        self.assertEqual(self.keyboard.typed(), "\b" * 7 + "привіт ")
        self.assertEqual(self.layouts.current(), "ua")

    def test_the_cyrillic_layout_typed_in_last_comes_first(self):
        self.layouts._names = ["us", "ru", "ua"]
        self.judge.layouts.add("ua")
        self.judge.targets = {"ru", "ua"}
        self.type_text("ghbdtn ")
        self.assertEqual(self.layouts.current(), "ru")

        self.layouts.activate("ua")
        self.type_text("так ", "ua")
        self.layouts.activate("us")
        self.keyboard.taps.clear()
        self.type_text("ghbdtn ")
        self.assertEqual(self.layouts.current(), "ua")

    def test_double_shift_from_english_goes_to_the_preferred_cyrillic_layout(self):
        self.layouts._names = ["us", "ru", "ua"]
        self.typist.preferred_cyrillic = "ua"
        self.type_text("ghbdsn")
        self.double_shift()

        self.assertEqual(self.keyboard.typed(), "\b" * 6 + "привіт")

    def test_a_ukrainian_layout_without_a_dictionary_is_left_alone(self):
        self.layouts._names = ["us", "ua"]
        self.layouts.activate("ua")
        self.type_text("руддщ ", "ua")

        self.assertEqual(self.keyboard.taps, [])
        self.assertEqual(self.judge.asked, [])

    def test_keeps_capital_letters_and_trailing_punctuation(self):
        self.judge.switch = {"Ghbdtn?"}
        self.type_text("Ghbdtn?")
        self.tap(keymap.KEY_SPACE)

        self.assertEqual(self.keyboard.typed(), "\b" * 8 + "Привет, ")

    def test_leaves_a_correct_word_alone(self):
        self.type_text("hello")
        self.tap(keymap.KEY_SPACE)

        self.assertEqual(self.keyboard.taps, [])
        self.assertEqual(self.judge.asked, ["hello"])

    def test_backspace_edits_the_word(self):
        self.type_text("ghbdtnx")
        self.tap(keymap.KEY_BACKSPACE)
        self.tap(keymap.KEY_SPACE)

        self.assertEqual(self.judge.asked, ["ghbdtn"])

    def test_mouse_click_drops_the_word(self):
        self.type_text("ghb")
        self.typist.on_pointer_button()
        self.type_text("dtn")
        self.tap(keymap.KEY_SPACE)

        self.assertEqual(self.judge.asked, ["dtn"])

    def test_shortcuts_and_navigation_drop_the_word(self):
        self.type_text("ghb")
        self.key(keymap.KEY_LEFTCTRL, PRESS)
        self.tap(keymap.KEY_SPACE)
        self.key(keymap.KEY_LEFTCTRL, RELEASE)
        self.type_text("dtn")
        self.tap(105)  # KEY_LEFT
        self.tap(keymap.KEY_SPACE)

        self.assertEqual(self.judge.asked, [])

    def test_does_nothing_in_other_layouts(self):
        self.layouts.activate("ua")
        self.type_text("ghbdtn")
        self.tap(keymap.KEY_SPACE)

        self.assertEqual(self.keyboard.taps, [])

    def test_does_nothing_while_paused(self):
        self.typist.paused = True
        self.type_text("ghbdtn")
        self.tap(keymap.KEY_SPACE)

        self.assertEqual(self.keyboard.taps, [])

    def test_double_shift_converts_the_word_being_typed(self):
        self.type_text("hello")
        self.double_shift()

        self.assertEqual(self.keyboard.typed(), "\b" * 5 + "руддщ")
        self.assertEqual(self.layouts.current(), "ru")

    def test_double_shift_after_a_switch_undoes_it_and_remembers_the_word(self):
        self.type_text("ghbdtn")
        self.tap(keymap.KEY_SPACE)
        self.double_shift()

        self.assertEqual(self.keyboard.typed(), "\b" * 7 + "привет " + "\b" * 7 + "ghbdtn ")
        self.assertEqual(self.layouts.current(), "us")

        self.keyboard.taps.clear()
        self.type_text("ghbdtn")
        self.tap(keymap.KEY_SPACE)
        self.assertEqual(self.keyboard.taps, [])
        self.assertIn(("us", "ghbdtn"), self.exceptions)

    def test_pressing_again_after_an_undo_is_not_an_exception(self):
        self.type_text("ghbdtn ")
        self.double_shift()
        self.double_shift()
        self.type_text("vbh ")

        self.assertEqual(self.keyboard.typed(), "\b" * 7 + "привет " + "\b" * 7 + "ghbdtn " + "\b" * 7 + "привет ")
        self.assertNotIn(("us", "ghbdtn"), self.exceptions)

    def test_double_shift_offers_the_other_cyrillic_spelling_after_an_undo(self):
        self.judge.layouts.add("ua")
        self.judge.switch = {"'nj"}
        self.type_text("'nj ")  # "это"
        self.double_shift()     # back to "'nj"
        self.double_shift()     # "єто": Ukrainian spells it differently
        self.double_shift()     # back again
        self.double_shift()     # "это" once both were shown

        self.assertEqual(
            self.keyboard.typed(),
            "\b" * 4 + "это " + "\b" * 4 + "'nj " + "\b" * 4 + "єто " + "\b" * 4 + "'nj " + "\b" * 4 + "это ",
        )

    def test_one_press_undoes_a_switch_from_cyrillic_to_english(self):
        self.judge.layouts.add("ua")
        self.judge.switch = {"ыдууз"}
        self.layouts.activate("ru")
        self.type_text("ыдууз ", "ru")  # "sleep"; the s key is ы in ru and і in ua
        self.double_shift()

        self.assertEqual(self.keyboard.typed(), "\b" * 6 + "sleep " + "\b" * 6 + "ыдууз ")
        self.assertEqual(self.layouts.current(), "ru")

        self.type_text("x")
        self.assertIn(("ru", "ыдууз"), self.exceptions)

    def test_an_unsaved_exception_does_not_stop_the_typist(self):
        self.type_text("ghbdtn ")
        self.double_shift()
        self.exceptions.add = mock.Mock(side_effect=OSError("disk full"))
        with self.assertLogs("layout_switcher", "WARNING"):
            self.type_text("x")

        self.assertEqual(self.typist.word, [(45, False)])

    def test_an_undo_is_remembered_on_exit(self):
        self.type_text("ghbdtn ")
        self.double_shift()
        self.typist.flush()

        self.assertIn(("us", "ghbdtn"), self.exceptions)

    def test_one_press_undoes_even_with_two_cyrillic_layouts(self):
        self.type_text("ghbdtn ")  # "привет" reads the same in ua
        self.double_shift()
        self.double_shift()

        self.assertEqual(self.keyboard.typed(), "\b" * 7 + "привет " + "\b" * 7 + "ghbdtn " + "\b" * 7 + "привет ")
        self.assertEqual(self.layouts.current(), "ru")

    def test_slow_shift_presses_are_not_a_double_shift(self):
        self.type_text("hello")
        self.tap(keymap.KEY_LEFTSHIFT)
        self.key(keymap.KEY_LEFTSHIFT, PRESS, after=1.0)
        self.key(keymap.KEY_LEFTSHIFT, RELEASE)

        self.assertEqual(self.keyboard.taps, [])

    def test_shift_used_for_a_capital_is_not_a_tap(self):
        self.type_text("A")
        self.type_text("B")

        self.assertEqual(self.keyboard.taps, [])


class DaemonTest(unittest.TestCase):
    def test_a_failing_key_drops_the_word_and_keeps_running(self):
        class Exploding:
            word = ["x"]
            user_kept_typing = None

            def on_key(self, code, value):
                raise RuntimeError("boom")

            def forget(self):
                self.word = []

        typist = Exploding()
        with self.assertLogs("layout_switcher", "ERROR"):
            Daemon(typist)._dispatch(keymap.KEY_SPACE, PRESS)
        self.assertEqual(typist.word, [])


class ExceptionsTest(unittest.TestCase):
    def test_file_is_private(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "conf" / "exceptions.txt"
            Exceptions(path).add("us", "ghbdtn")

            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertIn(("us", "Ghbdtn"), Exceptions(path))


if __name__ == "__main__":
    unittest.main()
