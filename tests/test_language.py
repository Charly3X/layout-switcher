import unittest

from layout_switcher.keymap import keys_for, render
from layout_switcher.language import AspellChecker, Judge, TrigramModel, word_core


class FakeChecker:
    def __init__(self, words):
        self.words = set(words)

    def is_word(self, word, layout):
        return word.lower() in self.words


MODELS = {
    "us": TrigramModel(TrigramModel.count(["hello", "help", "world", "word", "kernel", "grep", "github"])),
    "ru": TrigramModel(TrigramModel.count(["привет", "приветик", "мир", "дела", "москва", "обед", "обеда"])),
}


def judge_typing(judge, text, layout, other):
    keys = keys_for(text, layout)
    return judge.wrong_layout(render(keys, layout), layout, render(keys, other), other)


class WordCoreTest(unittest.TestCase):
    def test_strips_surrounding_punctuation(self):
        self.assertEqual(word_core("«Привет,»", "ru"), "Привет")
        self.assertEqual(word_core("(hello).", "us"), "hello")

    def test_rejects_text_broken_by_punctuation_or_other_alphabet(self):
        self.assertIsNone(word_core("j,tl", "us"))
        self.assertIsNone(word_core("hello", "ru"))
        self.assertIsNone(word_core("123", "us"))

    def test_keeps_inner_hyphen_and_english_apostrophe(self):
        self.assertEqual(word_core("кто-то", "ru"), "кто-то")
        self.assertEqual(word_core("don't", "us"), "don't")


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.judge = Judge(FakeChecker({"привет", "hello", "не", "jr", "ок", "then", "берут", "руб", "hen"}), MODELS)

    def test_switches_when_the_other_layout_gives_a_dictionary_word(self):
        self.assertTrue(judge_typing(self.judge, "ghbdtn", "us", "ru"))

    def test_a_word_hidden_behind_a_leading_letter_key_is_switched(self):
        self.assertTrue(judge_typing(self.judge, ",then", "us", "ru"))

    def test_trailing_punctuation_does_not_count(self):
        self.assertFalse(judge_typing(self.judge, "hen,", "us", "ru"))  # "руб" would be a word
        self.assertFalse(judge_typing(self.judge, "then", "us", "ru"))

    def test_keeps_colloquial_words_the_dictionaries_lack(self):
        self.judge.checker.words.add("of")
        self.assertFalse(judge_typing(self.judge, "ща", "ru", "us"))
        self.assertTrue(judge_typing(self.judge, "xt", "us", "ru"))  # "че"

    def test_keeps_a_dictionary_word(self):
        self.assertFalse(judge_typing(self.judge, "hello", "us", "ru"))

    def test_keeps_short_words_whose_twin_is_an_abbreviation(self):
        self.assertFalse(judge_typing(self.judge, "ок", "ru", "us"))

    def test_switches_short_words_that_read_better_in_the_other_layout(self):
        self.assertTrue(judge_typing(self.judge, "yt", "us", "ru"))

    def test_uses_letter_statistics_for_unknown_words(self):
        self.assertTrue(judge_typing(self.judge, "ghbdtnbr", "us", "ru"))
        self.assertFalse(judge_typing(self.judge, "kernel", "us", "ru"))

    def test_could_be_meant_accepts_dictionary_words_and_one_letter_words(self):
        self.assertTrue(self.judge.could_be_meant("yt", "us", "не", "ru"))
        self.assertTrue(self.judge.could_be_meant("b", "us", "и", "ru"))
        self.assertFalse(self.judge.could_be_meant("s", "us", "ы", "ru"))
        self.assertFalse(self.judge.could_be_meant("hello", "us", "руддщ", "ru"))

    def test_could_be_meant_prefers_the_typed_word_when_both_are_words_and_it_reads_better(self):
        self.assertFalse(self.judge.could_be_meant("ок", "ru", "jr", "us"))

    def test_switches_words_broken_by_punctuation_only_if_the_other_reading_is_plausible(self):
        self.assertTrue(judge_typing(self.judge, "j,tlf", "us", "ru"))
        self.assertFalse(judge_typing(self.judge, "foo,bar", "us", "ru"))


class AspellCheckerTest(unittest.TestCase):
    def setUp(self):
        self.checker = AspellChecker()
        self.addCleanup(self.checker.close)

    def test_checks_both_halves_of_a_hyphenated_word(self):
        self.assertTrue(self.checker.is_word("кто-то", "ru"))
        self.assertFalse(self.checker.is_word("кто-ghbdtn", "ru"))

    def test_survives_a_dead_aspell_process(self):
        self.assertTrue(self.checker.is_word("привет", "ru"))
        self.checker._processes["ru"].kill()
        self.checker._processes["ru"].wait()

        self.assertTrue(self.checker.is_word("мир", "ru"))
        self.assertFalse(self.checker.is_word("ghbdtn", "ru"))


if __name__ == "__main__":
    unittest.main()
