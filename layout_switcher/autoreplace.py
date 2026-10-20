"""The user's own abbreviations, expanded when followed by a space."""

import logging
import os
import re

from .paths import CONFIG_DIR

log = logging.getLogger("layout_switcher")

TEMPLATE = """\
# Autoreplace: one "abbreviation = replacement" per line, expanded when you type a space.
# The case follows the abbreviation: "Thx" -> "Thanks", "THX" -> "THANKS".
# Lines starting with # are ignored. Remove the # below to enable the examples.
#
# thx = thanks
# спс = спасибо
# email = name@example.com
"""

_SURROUNDING = re.compile(r"^([(\"'«]*)(.+?)([.,!?;:)\"'»]*)$")


def split_punctuation(text):
    """("(", "thx", ")!") for "(thx)!"."""
    return _SURROUNDING.match(text).groups()


class Autoreplace:
    def __init__(self, path=CONFIG_DIR / "autoreplace.txt"):
        self.path = path
        self.entries = {}
        self._loaded_mtime = None

    def ensure_file(self):
        if not self.path.exists():
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with open(fd, "w", encoding="utf-8") as f:
                f.write(TEMPLATE)
        return self.path

    def _reload_if_changed(self):
        try:
            mtime = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            self.entries, self._loaded_mtime = {}, None
            return
        if mtime == self._loaded_mtime:
            return
        self._loaded_mtime = mtime
        try:
            text = self.path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as error:
            log.warning("cannot read %s, keeping the previous list: %s", self.path, error)
            return
        self.entries = parse(text)
        log.info("loaded %d autoreplace entries", len(self.entries))

    def lookup(self, word):
        """Replacement for `word`, in the word's case, or None."""
        self._reload_if_changed()
        replacement = self.entries.get(word.lower())
        if replacement is None:
            return None
        if len(word) > 1 and word.isupper():
            return replacement.upper()
        if word[0].isupper():
            return replacement[:1].upper() + replacement[1:]
        return replacement


def parse(text):
    entries = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        abbreviation, sep, replacement = (part.strip() for part in line.partition("="))
        if not sep or not abbreviation or not replacement or " " in abbreviation:
            log.warning("autoreplace line %d ignored: expected 'abbreviation = replacement'", number)
            continue
        entries[abbreviation.lower()] = replacement
    return entries
