import unittest
from unittest import mock

from layout_switcher import __main__ as main
from layout_switcher.keymap import typing_plan


class DictionaryLayoutsTest(unittest.TestCase):
    def layouts(self, available):
        with mock.patch.object(main, "aspell_layouts", return_value=set(available)):
            return main._dictionary_layouts()

    def test_english_with_either_cyrillic_dictionary_is_enough(self):
        with self.assertLogs(level="INFO"):
            self.assertEqual(self.layouts({"us", "ua"}), ["ua", "us"])
            self.assertEqual(self.layouts({"us", "ru"}), ["ru", "us"])

    def test_refuses_to_start_without_english_or_any_cyrillic_dictionary(self):
        with self.assertRaises(SystemExit):
            self.layouts({"ru", "ua"})
        with self.assertRaises(SystemExit):
            self.layouts({"us"})


class TypingPlanTest(unittest.TestCase):
    def test_returns_to_the_starting_layout_when_it_can_type_the_rest(self):
        self.assertEqual([layout for layout, _ in typing_plan("x мама", "ua")], ["us", "ua"])
        self.assertEqual([layout for layout, _ in typing_plan("x мама", "ru")], ["us", "ru"])

    def test_picks_the_layout_that_types_the_longest_stretch(self):
        self.assertEqual([layout for layout, _ in typing_plan("привіт ґанок", "us")], ["ua"])


if __name__ == "__main__":
    unittest.main()
