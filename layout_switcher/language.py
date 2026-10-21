"""Deciding whether a word was typed in the wrong layout."""

import json
import math
import os
import subprocess
from collections import Counter
from functools import lru_cache
from pathlib import Path

ALPHABETS = {
    "us": frozenset("abcdefghijklmnopqrstuvwxyz"),
    "ru": frozenset("абвгдеёжзийклмнопрстуфхцчшщъыьэюя"),
}
_INNER_JOINERS = {"us": frozenset("-'"), "ru": frozenset("-")}
_ASPELL_LANG = {"us": "en", "ru": "ru"}
SINGLE_LETTER_WORDS = {"us": frozenset("ai"), "ru": frozenset("абвжикосуя")}

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "layout_switcher"


def word_core(text, layout):
    """The word without surrounding punctuation, or None if it is not a word in this layout."""
    letters = ALPHABETS[layout]
    chars = list(text)
    while chars and chars[0].lower() not in letters:
        chars.pop(0)
    while chars and chars[-1].lower() not in letters:
        chars.pop()
    if not chars:
        return None
    joiners = _INNER_JOINERS[layout]
    if any(c.lower() not in letters and c not in joiners for c in chars):
        return None
    return "".join(chars)


class AspellChecker:
    """Dictionary lookups through long-running `aspell -a` processes."""

    def __init__(self):
        self._processes = {}

    def _process(self, layout):
        process = self._processes.get(layout)
        if process is None or process.poll() is not None:
            _stop(process)
            process = subprocess.Popen(
                ["aspell", "-a", f"--lang={_ASPELL_LANG[layout]}", "--encoding=utf-8", "--dont-suggest"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            process.stdout.readline()
            self._processes[layout] = process
        return process

    def _ask(self, word, layout):
        process = self._process(layout)
        process.stdin.write(f"^{word}\n")
        process.stdin.flush()
        verdicts = []
        while (line := process.stdout.readline()) != "\n":
            if not line:
                raise EOFError("aspell exited")
            verdicts.append(line)
        return bool(verdicts) and all(v[:1] in ("*", "+", "-") for v in verdicts)

    def _lookup(self, word, layout):
        for _attempt in range(2):
            try:
                return self._ask(word, layout)
            except (OSError, EOFError):
                _stop(self._processes.pop(layout, None))
        raise RuntimeError(f"aspell for {layout} keeps failing")

    def close(self):
        for process in self._processes.values():
            _stop(process)
        self._processes.clear()

    @lru_cache(maxsize=4096)
    def is_word(self, word, layout):
        if "-" in word:
            parts = word.split("-")
            return all(parts) and all(self.is_word(part, layout) for part in parts)
        variants = dict.fromkeys([word, word.lower(), word.capitalize()])
        return any(self._lookup(variant, layout) for variant in variants)


def _stop(process):
    if process is None:
        return
    process.kill()
    process.wait()
    for stream in (process.stdin, process.stdout):
        try:
            stream.close()
        except OSError:
            # A dead pipe fails the final flush; close the descriptor underneath anyway.
            stream.buffer.raw.close()


class TrigramModel:
    """Letter trigram model with interpolated smoothing; scores are mean log-probabilities per letter."""

    _WEIGHTS = (0.6, 0.3, 0.1)

    def __init__(self, counts):
        self.tri, self.bi, self.uni = counts
        self.total = sum(self.uni.values())
        self.alphabet_size = len(self.uni) + 1
        self.tri_context, self.bi_context = Counter(), Counter()
        for gram, n in self.tri.items():
            self.tri_context[gram[:2]] += n
        for gram, n in self.bi.items():
            self.bi_context[gram[0]] += n

    @staticmethod
    def count(words):
        tri, bi, uni = Counter(), Counter(), Counter()
        for word in words:
            padded = f"^^{word.lower()}$"
            for i in range(2, len(padded)):
                tri[padded[i - 2:i + 1]] += 1
                bi[padded[i - 1:i + 1]] += 1
                uni[padded[i]] += 1
        return dict(tri), dict(bi), dict(uni)

    def score(self, word):
        padded = f"^^{word.lower()}$"
        w3, w2, w1 = self._WEIGHTS
        total = 0.0
        for i in range(2, len(padded)):
            tri_ctx = self.tri_context[padded[i - 2:i]]
            bi_ctx = self.bi_context[padded[i - 1]]
            p_tri = self.tri.get(padded[i - 2:i + 1], 0) / tri_ctx if tri_ctx else 0.0
            p_bi = self.bi.get(padded[i - 1:i + 1], 0) / bi_ctx if bi_ctx else 0.0
            p_uni = (self.uni.get(padded[i], 0) + 1) / (self.total + self.alphabet_size)
            total += math.log(w3 * p_tri + w2 * p_bi + w1 * p_uni)
        return total / (len(padded) - 2)

    @classmethod
    def for_layout(cls, layout):
        """Model trained on the aspell dictionary, cached after the first build."""
        cache = CACHE_DIR / f"trigrams-{layout}.json"
        if cache.exists():
            return cls(tuple(json.loads(cache.read_text(encoding="utf-8"))))
        counts = cls.count(dictionary_words(layout))
        cache.parent.mkdir(parents=True, exist_ok=True)
        partial = cache.with_suffix(".tmp")
        partial.write_text(json.dumps(counts, ensure_ascii=False), encoding="utf-8")
        os.replace(partial, cache)
        return cls(counts)


def dictionary_words(layout):
    """Every word form of the aspell dictionary, lowercased, letters only."""
    lang = _ASPELL_LANG[layout]
    dump = subprocess.run(["aspell", "-l", lang, "dump", "master"], capture_output=True, check=True)
    expanded = subprocess.run(
        ["aspell", "-l", lang, "expand"], input=dump.stdout, capture_output=True, check=True
    )
    letters = ALPHABETS[layout]
    words = set()
    for word in expanded.stdout.decode("utf-8").split():
        word = word.lower()
        if all(c in letters for c in word):
            words.add(word)
    return sorted(words)


class Judge:
    """Says whether the text typed in `typed_layout` was meant for `other_layout`."""

    MIN_LETTERS = 2
    MIN_LETTERS_WITHOUT_DICTIONARY = 4
    # Tuned with tools/evaluate.py: no wrong switches on held-out dictionary words.
    SCORE_MARGIN = 1.5
    # Typical words score above this; keyboard mash scores far below.
    PLAUSIBLE_SCORE = -3.0

    def __init__(self, checker, models):
        self.checker = checker
        self.models = models

    def wrong_layout(self, typed_text, typed_layout, intended_text, other_layout):
        intended = word_core(intended_text, other_layout)
        if intended is None or len(intended) < self.MIN_LETTERS:
            return False
        typed = word_core(typed_text, typed_layout)
        if typed is not None and self.checker.is_word(typed, typed_layout):
            return False
        intended_score = self.models[other_layout].score(intended)
        typed_score = self.models[typed_layout].score(typed) if typed is not None else -math.inf
        short = len(intended) < self.MIN_LETTERS_WITHOUT_DICTIONARY
        if self.checker.is_word(intended, other_layout):
            # Dictionaries hold plenty of two- and three-letter abbreviations ("jr" for "ок").
            return not short or intended_score > typed_score
        if short:
            return False
        if typed is None:
            return intended_score > self.PLAUSIBLE_SCORE
        return intended_score - typed_score > self.SCORE_MARGIN

    def could_be_meant(self, typed_text, typed_layout, intended_text, other_layout):
        """Looser test for short words right before a switched one ("ye b" + "что" -> "ну и что")."""
        intended = word_core(intended_text, other_layout)
        if intended is None:
            return False
        if len(intended) == 1:
            return intended.lower() in SINGLE_LETTER_WORDS[other_layout]
        if not self.checker.is_word(intended, other_layout):
            return False
        typed = word_core(typed_text, typed_layout)
        if typed is None or not self.checker.is_word(typed, typed_layout):
            return True
        return self.models[other_layout].score(intended) > self.models[typed_layout].score(typed)
