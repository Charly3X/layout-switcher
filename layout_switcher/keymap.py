"""Linux key codes and what they produce in the supported layouts."""

KEY_ESC = 1
KEY_BACKSPACE = 14
KEY_TAB = 15
KEY_ENTER = 28
KEY_LEFTCTRL = 29
KEY_LEFTSHIFT = 42
KEY_RIGHTSHIFT = 54
KEY_LEFTALT = 56
KEY_SPACE = 57
KEY_CAPSLOCK = 58
KEY_RIGHTCTRL = 97
KEY_RIGHTALT = 100
KEY_LEFTMETA = 125
KEY_RIGHTMETA = 126

SHIFT_KEYS = frozenset({KEY_LEFTSHIFT, KEY_RIGHTSHIFT})
COMBO_MODIFIERS = frozenset(
    {KEY_LEFTCTRL, KEY_RIGHTCTRL, KEY_LEFTALT, KEY_RIGHTALT, KEY_LEFTMETA, KEY_RIGHTMETA}
)

# Mouse/touch buttons live at 0x100 and above; anything there moves the caret.
FIRST_BUTTON_CODE = 0x100

_ROWS = {
    "us": {
        2: "1!", 3: "2@", 4: "3#", 5: "4$", 6: "5%", 7: "6^", 8: "7&", 9: "8*", 10: "9(", 11: "0)",
        12: "-_", 13: "=+",
        16: "qQ", 17: "wW", 18: "eE", 19: "rR", 20: "tT", 21: "yY", 22: "uU", 23: "iI", 24: "oO",
        25: "pP", 26: "[{", 27: "]}",
        30: "aA", 31: "sS", 32: "dD", 33: "fF", 34: "gG", 35: "hH", 36: "jJ", 37: "kK", 38: "lL",
        39: ";:", 40: "'\"", 41: "`~", 43: "\\|",
        44: "zZ", 45: "xX", 46: "cC", 47: "vV", 48: "bB", 49: "nN", 50: "mM", 51: ",<", 52: ".>",
        53: "/?",
    },
    "ru": {
        2: "1!", 3: "2\"", 4: "3№", 5: "4;", 6: "5%", 7: "6:", 8: "7?", 9: "8*", 10: "9(", 11: "0)",
        12: "-_", 13: "=+",
        16: "йЙ", 17: "цЦ", 18: "уУ", 19: "кК", 20: "еЕ", 21: "нН", 22: "гГ", 23: "шШ", 24: "щЩ",
        25: "зЗ", 26: "хХ", 27: "ъЪ",
        30: "фФ", 31: "ыЫ", 32: "вВ", 33: "аА", 34: "пП", 35: "рР", 36: "оО", 37: "лЛ", 38: "дД",
        39: "жЖ", 40: "эЭ", 41: "ёЁ", 43: "\\/",
        44: "яЯ", 45: "чЧ", 46: "сС", 47: "мМ", 48: "иИ", 49: "тТ", 50: "ьЬ", 51: "бБ", 52: "юЮ",
        53: ".,",
    },
}
# KDE's default Ukrainian layout (xkb "ua", variant "unicode") differs from Russian in five keys.
_ROWS["ua"] = {
    **_ROWS["ru"],
    27: "їЇ", 31: "іІ", 40: "єЄ", 41: "'ʼ", 43: "ґҐ",
}

LAYOUTS = tuple(_ROWS)
TEXT_KEYS = frozenset(_ROWS["us"])


def render(keys, layout, caps_lock=False):
    """Text produced by (code, shifted) presses in the given layout."""
    row = _ROWS[layout]
    chars = []
    for code, shifted in keys:
        lower, upper = row[code]
        upper_case = shifted
        if caps_lock and lower.isalpha():
            upper_case = not upper_case
        chars.append(upper if upper_case else lower)
    return "".join(chars)


def keys_for(text, layout):
    """(code, shifted) presses that type `text` in the given layout; other characters are skipped."""
    return [_LOOKUPS[layout][c] for c in text if c in _LOOKUPS[layout]]


def _lookup(layout):
    table = {" ": (KEY_SPACE, False)}
    for code, (lower, upper) in _ROWS[layout].items():
        table.setdefault(lower, (code, False))
        table.setdefault(upper, (code, True))
    return table


_LOOKUPS = {layout: _lookup(layout) for layout in LAYOUTS}


def _reach(text, start, layout):
    count = 0
    for char in text[start:]:
        if char not in _LOOKUPS[layout]:
            break
        count += 1
    return count


def typing_plan(text, start_layout, caps_lock=False):
    """[(layout, keys)] runs that type `text`, switching layout only when a character needs it.

    Returns None if some character exists in no supported layout.
    """
    layout = start_layout if start_layout in _ROWS else LAYOUTS[0]
    runs = []
    for i, char in enumerate(text):
        if char not in _LOOKUPS[layout]:
            able = [name for name in LAYOUTS if char in _LOOKUPS[name]]
            if not able:
                return None
            # Switch to the layout that types the longest stretch from here.
            layout = max(able, key=lambda name: (_reach(text, i, name), name == start_layout))
        code, shifted = _LOOKUPS[layout][char]
        if caps_lock and char.isalpha():
            shifted = not shifted
        if not runs or runs[-1][0] != layout:
            runs.append((layout, []))
        runs[-1][1].append((code, shifted))
    return runs
