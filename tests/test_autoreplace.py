import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layout_switcher.autoreplace import Autoreplace, parse, split_punctuation


class ParseTest(unittest.TestCase):
    def test_reads_pairs_and_skips_comments_and_broken_lines(self):
        with self.assertLogs("layout_switcher", "WARNING"):
            entries = parse("# comment\n\nСпс = спасибо\nмб=может быть\nno separator\nтwo words = x\n= y\n")

        self.assertEqual(entries, {"спс": "спасибо", "мб": "может быть"})

    def test_splits_surrounding_punctuation(self):
        self.assertEqual(split_punctuation("(спс)!"), ("(", "спс", ")!"))
        self.assertEqual(split_punctuation("спс"), ("", "спс", ""))


class AutoreplaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "conf" / "autoreplace.txt"
        self.autoreplace = Autoreplace(self.path)

    def test_without_a_file_nothing_is_replaced(self):
        self.assertIsNone(self.autoreplace.lookup("спс"))

    def test_template_is_created_private_and_replaces_nothing(self):
        self.autoreplace.ensure_file()

        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertIsNone(self.autoreplace.lookup("спс"))

    def test_follows_the_case_of_the_abbreviation(self):
        self.path.parent.mkdir()
        self.path.write_text("спс = спасибо\n", encoding="utf-8")

        self.assertEqual(self.autoreplace.lookup("спс"), "спасибо")
        self.assertEqual(self.autoreplace.lookup("Спс"), "Спасибо")
        self.assertEqual(self.autoreplace.lookup("СПС"), "СПАСИБО")

    def test_ignores_a_byte_order_mark(self):
        self.path.parent.mkdir()
        self.path.write_text("\ufeffспс = спасибо\n", encoding="utf-8")

        self.assertEqual(self.autoreplace.lookup("спс"), "спасибо")

    def test_keeps_the_previous_list_when_the_file_cannot_be_read(self):
        self.path.parent.mkdir()
        self.path.write_text("спс = спасибо\n", encoding="utf-8")
        self.autoreplace.lookup("спс")
        time.sleep(0.01)
        self.path.write_bytes(b"\xff\xfe broken")

        with self.assertLogs("layout_switcher", "WARNING"):
            self.assertEqual(self.autoreplace.lookup("спс"), "спасибо")

    def test_picks_up_edits_without_restart(self):
        self.path.parent.mkdir()
        self.path.write_text("спс = спасибо\n", encoding="utf-8")
        self.assertEqual(self.autoreplace.lookup("спс"), "спасибо")

        time.sleep(0.01)
        self.path.write_text("спс = спасибо большое\n", encoding="utf-8")

        self.assertEqual(self.autoreplace.lookup("спс"), "спасибо большое")


if __name__ == "__main__":
    unittest.main()
