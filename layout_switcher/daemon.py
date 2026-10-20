"""Watches typing; retypes words typed in the wrong layout and expands the user's abbreviations."""

import logging
import os
import selectors
import threading
import time
from collections import deque

from . import keymap
from .autoreplace import split_punctuation
from .devices import InputDevice, VirtualKeyboard, find_input_devices
from .language import word_core
from .paths import CONFIG_DIR

log = logging.getLogger("layout_switcher")

LATIN, CYRILLIC = "us", "ru"
OTHER = {LATIN: CYRILLIC, CYRILLIC: LATIN}

DOUBLE_SHIFT_WINDOW = 0.4
MAX_LEAD_IN_WORDS = 4
RESCAN_INTERVAL = 3.0
POLL_INTERVAL = 0.5
LAYOUT_SETTLE_DELAY = 0.05


class Exceptions:
    """Words the user turned back after an automatic switch; never switched again."""

    def __init__(self, path=CONFIG_DIR / "exceptions.txt"):
        self.path = path
        self.entries = set()
        if path.exists():
            self.entries = {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}

    @staticmethod
    def _entry(layout, text):
        return f"{layout}:{text.lower()}"

    def __contains__(self, item):
        layout, text = item
        return self._entry(layout, text) in self.entries

    def add(self, layout, text):
        entry = self._entry(layout, text)
        if entry in self.entries:
            return
        self.entries.add(entry)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with open(fd, "a", encoding="utf-8") as f:
            f.write(entry + "\n")


class Typist:
    """Keyboard state machine: tracks the current word and decides when to retype it."""

    def __init__(self, judge, layouts, keyboard, exceptions, autoreplace):
        self.judge = judge
        self.layouts = layouts
        self.keyboard = keyboard
        self.exceptions = exceptions
        self.autoreplace = autoreplace
        self.paused = False
        self.on_switch = lambda: None
        # Set by Daemon: True when physical keys were pressed after the word ended.
        self.user_kept_typing = lambda: False
        # Set by Daemon: the keyboard LED, or None when it cannot be read.
        self.read_caps_lock = lambda: None
        self.word = []
        self.last_word = None
        self.last_switch = None
        # (typed keys, layout they were typed in, length of the text that replaced them)
        self.last_replacement = None
        self.phrase = []
        self.shifts_down = set()
        self.combo_modifiers_down = set()
        self.caps_lock = False
        self.shift_alone = False
        self.shift_pressed_at = 0.0
        self.last_shift_tap = 0.0

    def forget(self):
        self.word = []
        self.last_word = None
        self.last_switch = None
        self.last_replacement = None
        self.phrase = []

    def on_pointer_button(self):
        self.forget()

    def release_modifiers(self):
        """A keyboard went away; its held keys will never report a release."""
        self.shifts_down.clear()
        self.combo_modifiers_down.clear()
        self.forget()

    def on_key(self, code, value, now=None):
        now = time.monotonic() if now is None else now
        if code in keymap.SHIFT_KEYS:
            self._on_shift(code, value, now)
            return
        if value == 0:
            if code in keymap.COMBO_MODIFIERS:
                self.combo_modifiers_down.discard(code)
            return
        self.shift_alone = False
        self.last_shift_tap = 0.0
        if code in keymap.COMBO_MODIFIERS:
            self.combo_modifiers_down.add(code)
            self.forget()
            return
        if self.combo_modifiers_down:
            self.forget()
            return
        if code == keymap.KEY_CAPSLOCK:
            if value == 1:
                self.caps_lock = not self.caps_lock
            return
        if code == keymap.KEY_BACKSPACE:
            if self.word:
                self.word.pop()
            else:
                self.forget()
            return
        if code == keymap.KEY_SPACE:
            self._on_word_end()
            return
        if code in keymap.TEXT_KEYS:
            self.word.append((code, bool(self.shifts_down)))
            self.last_word = None
            self.last_switch = None
            self.last_replacement = None
            return
        self.forget()

    def _on_shift(self, code, value, now):
        if value == 1:
            self.shifts_down.add(code)
            self.shift_alone = True
            self.shift_pressed_at = now
        elif value == 0:
            self.shifts_down.discard(code)
            held = now - self.shift_pressed_at
            if not self.shift_alone or self.combo_modifiers_down or held > DOUBLE_SHIFT_WINDOW:
                self.shift_alone = False
                return
            self.shift_alone = False
            if now - self.last_shift_tap <= DOUBLE_SHIFT_WINDOW:
                self.last_shift_tap = 0.0
                self.convert_by_hand()
            else:
                self.last_shift_tap = now

    def _on_word_end(self):
        keys, self.word = self.word, []
        self.last_word, self.last_switch, self.last_replacement = (keys or None), None, None
        if not keys or self.paused or self.shifts_down or self.combo_modifiers_down:
            self.phrase = []
            return
        led = self.read_caps_lock()
        if led is not None:
            self.caps_lock = led
        typed_layout, names = self.layouts.state()
        if self._expand_abbreviation(keys, typed_layout, names):
            self.phrase = []
            return
        switched = (
            typed_layout in OTHER
            and OTHER[typed_layout] in names
            and self._switch_if_wrong(keys, typed_layout, names)
        )
        if switched:
            self.phrase = []
        else:
            self.phrase = (self.phrase + [(keys, typed_layout)])[-MAX_LEAD_IN_WORDS:]

    def _switch_if_wrong(self, keys, typed_layout, names):
        other = OTHER[typed_layout]
        typed_text = keymap.render(keys, typed_layout, self.caps_lock)
        if (typed_layout, typed_text) in self.exceptions:
            return False
        intended_text = keymap.render(keys, other, self.caps_lock)
        if not self.judge.wrong_layout(typed_text, typed_layout, intended_text, other):
            return False
        words = self._lead_in(typed_layout, other) + [keys]
        retyped = _join_words(words)
        if not self._retype(retyped, typed_layout, other, names, trailing_space=True):
            log.debug("not switching %r: typing went on", typed_text)
            return False
        log.debug("switched %d word(s) ending with %r -> %r", len(words), typed_text, intended_text)
        self.last_word = retyped
        self.last_switch = (typed_layout, typed_text)
        self.on_switch()
        return True

    def _lead_in(self, typed_layout, other):
        """Words right before a switched one that also read as words in the other layout ("ye b" + "что")."""
        lead_in = []
        for keys, layout in reversed(self.phrase):
            typed_text = keymap.render(keys, layout, self.caps_lock)
            intended_text = keymap.render(keys, other, self.caps_lock)
            if layout != typed_layout or (layout, typed_text) in self.exceptions:
                break
            if not self.judge.could_be_meant(typed_text, layout, intended_text, other):
                break
            lead_in.insert(0, keys)
        return lead_in

    def _expand_abbreviation(self, keys, typed_layout, names):
        """Replace an abbreviation from the user's list, also when typed in the wrong layout."""
        readings = [typed_layout, OTHER.get(typed_layout)]
        for layout in readings:
            if layout not in keymap.LAYOUTS or layout not in names:
                continue
            text = keymap.render(keys, layout, self.caps_lock)
            # Whole text first, so that "т.е." can be an abbreviation of its own.
            before, word, after = "", text, ""
            replacement = self.autoreplace.lookup(word)
            if replacement is None:
                before, word, after = split_punctuation(text)
                replacement = self.autoreplace.lookup(word)
            if replacement is None:
                continue
            if layout != typed_layout:
                typed = word_core(keymap.render(keys, typed_layout, self.caps_lock), typed_layout)
                if typed is not None and self.judge.checker.is_word(typed, typed_layout):
                    continue
            new_text = f"{before}{replacement}{after} "
            plan = keymap.typing_plan(new_text, layout, self.caps_lock)
            if plan is None:
                log.warning("an autoreplace entry has characters that no layout can type")
                return False
            if plan[-1][0] != layout:
                plan.append((layout, []))
            missing = {run_layout for run_layout, _ in plan} - set(names)
            if missing:
                log.warning("an autoreplace entry needs the %s layout, which KDE does not have", ", ".join(sorted(missing)))
                return False
            if not self._replace(len(keys) + 1, plan, typed_layout, names):
                return False
            log.debug("expanded %r -> %r", word, replacement)
            self.last_word = None
            self.last_replacement = (keys, typed_layout, len(new_text))
            self.on_switch()
            return True
        return False

    def convert_by_hand(self):
        """Double Shift: undo the last expansion, or retype the current or just finished word in the other layout."""
        if not self.word and self.last_replacement is not None:
            keys, typed_layout, length = self.last_replacement
            current, names = self.layouts.state()
            if typed_layout in names and self._replace(
                length, [(typed_layout, keys + [(keymap.KEY_SPACE, False)])], current, names
            ):
                self.last_replacement = None
                self.last_word = keys
            return
        if self.word:
            keys, trailing_space = self.word, False
        elif self.last_word:
            keys, trailing_space = self.last_word, True
        else:
            return
        current, names = self.layouts.state()
        target = OTHER.get(current, LATIN)
        if target not in names or not self._retype(keys, current, target, names, trailing_space):
            return
        if trailing_space and self.last_switch is not None:
            self.exceptions.add(*self.last_switch)
        self.last_switch = None

    def _retype(self, keys, current_layout, target_layout, names, trailing_space):
        typed = keys + [(keymap.KEY_SPACE, False)] if trailing_space else keys
        return self._replace(len(typed), [(target_layout, typed)], current_layout, names)

    def _replace(self, delete_count, plan, current_layout, names):
        """Delete `delete_count` characters, then type the [(layout, keys)] runs of `plan`.

        Gives up if the user typed on. The layout of the last run stays active.
        """
        if self.user_kept_typing():
            return False
        first_layout = plan[0][0]
        if first_layout != current_layout:
            # Switch first: if D-Bus fails, nothing has been deleted yet.
            self.layouts.activate(first_layout, names)
            time.sleep(LAYOUT_SETTLE_DELAY)
            if self.user_kept_typing():
                # Keys pressed meanwhile already came out in the new layout, usually the one the
                # user meant; keep it and leave the text as typed rather than mix our keys with theirs.
                self.forget()
                return False
        for _ in range(delete_count):
            self.keyboard.tap(keymap.KEY_BACKSPACE)
        layout = first_layout
        for run_layout, keys in plan:
            if run_layout != layout:
                # Let the compositor take the last key before the layout changes under it.
                time.sleep(LAYOUT_SETTLE_DELAY)
                self.layouts.activate(run_layout, names)
                time.sleep(LAYOUT_SETTLE_DELAY)
                layout = run_layout
            for code, shifted in keys:
                self.keyboard.tap(code, keymap.KEY_LEFTSHIFT if shifted else None)
        return True


def _join_words(words):
    keys = []
    for word in words:
        if keys:
            keys.append((keymap.KEY_SPACE, False))
        keys.extend(word)
    return keys


class Daemon:
    def __init__(self, typist):
        self.typist = typist
        self.selector = selectors.DefaultSelector()
        self.devices = {}
        self.backlog = deque()
        self.stopping = threading.Event()
        typist.user_kept_typing = self._user_kept_typing
        typist.read_caps_lock = self._caps_lock_led

    def _rescan(self):
        found = find_input_devices()
        for path in set(found) - set(self.devices):
            try:
                device = InputDevice(path, is_keyboard=found[path])
            except OSError as error:
                log.warning("cannot open %s: %s", path, error)
                continue
            self.devices[path] = device
            self.selector.register(device, selectors.EVENT_READ)
            log.info("listening to %s", path)

    def _drop(self, device):
        self.selector.unregister(device)
        device.close()
        del self.devices[device.path]
        if device.is_keyboard:
            self.typist.release_modifiers()
        log.info("lost %s", device.path)

    def _read_ready(self, timeout):
        for key, _ in self.selector.select(timeout=timeout):
            device = key.fileobj
            try:
                self.backlog.extend(device.read_key_events())
            except OSError:
                self._drop(device)

    def _caps_lock_led(self):
        for device in list(self.devices.values()):
            if device.is_keyboard:
                try:
                    return device.caps_lock_led()
                except OSError:
                    continue
        return None

    def _user_kept_typing(self):
        self._read_ready(0)
        return any(value != 0 for _code, value in self.backlog)

    def _dispatch(self, code, value):
        try:
            if code >= keymap.FIRST_BUTTON_CODE:
                if value == 1:
                    self.typist.on_pointer_button()
            else:
                self.typist.on_key(code, value)
        except Exception:
            log.exception("failed to handle a key; dropping the current word")
            self.typist.forget()

    def toggle_pause(self, *_):
        self.typist.paused = not self.typist.paused
        self.typist.forget()
        log.info("paused" if self.typist.paused else "resumed")

    def run(self):
        next_rescan = 0.0
        while not self.stopping.is_set():
            if time.monotonic() >= next_rescan:
                self._rescan()
                next_rescan = time.monotonic() + RESCAN_INTERVAL
            self._read_ready(0 if self.backlog else POLL_INTERVAL)
            while self.backlog:
                self._dispatch(*self.backlog.popleft())


def virtual_keyboard():
    codes = set(keymap.TEXT_KEYS) | {keymap.KEY_BACKSPACE, keymap.KEY_SPACE, keymap.KEY_LEFTSHIFT}
    return VirtualKeyboard(sorted(codes))
