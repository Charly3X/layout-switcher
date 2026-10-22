"""Measure how often the letter model alone would switch wrongly or miss a switch.

Trains on 90% of each dictionary, then looks at the held-out 10%: for every word,
d = score(word in its language) - score(same keys read in the other layout).
Typed right, the model switches wrongly when d < -margin; typed in the wrong
layout, it misses when d < margin.
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from layout_switcher.keymap import keys_for, render  # noqa: E402
from layout_switcher.language import TrigramModel, dictionary_words, word_core  # noqa: E402

PAIRS = [("us", "ru"), ("ru", "us"), ("us", "ua"), ("ua", "us")]


def main():
    rng = random.Random(1)
    words, models = {}, {}
    for layout in ("us", "ru", "ua"):
        all_words = [w for w in dictionary_words(layout) if len(w) >= 4]
        rng.shuffle(all_words)
        cut = len(all_words) // 10
        words[layout] = all_words[:cut][:20000]
        models[layout] = TrigramModel(TrigramModel.count(all_words[cut:]))

    for layout, other in PAIRS:
        diffs, no_core = [], 0
        for word in words[layout]:
            garbled = word_core(render(keys_for(word, layout), other), other)
            if garbled is None:
                no_core += 1
                continue
            diffs.append(models[layout].score(word) - models[other].score(garbled))
        diffs.sort()
        print(f"{layout} typed as {other}: {len(diffs)} words, {no_core} turn into punctuation")
        for margin in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0):
            wrong = sum(d < -margin for d in diffs) / len(diffs)
            missed = sum(d < margin for d in diffs) / len(diffs)
            print(f"  margin {margin:3.1f}: wrong switch {wrong:7.3%}   missed {missed:7.3%}")
        scores = sorted(models[layout].score(w) for w in words[layout])
        print(f"  own score percentiles 1/5/50%: "
              f"{scores[len(scores) // 100]:.2f} {scores[len(scores) // 20]:.2f} {scores[len(scores) // 2]:.2f}")


if __name__ == "__main__":
    main()
