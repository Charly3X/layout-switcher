"""Raw evdev input and a uinput virtual keyboard, using only the standard library."""

import fcntl
import os
import struct
import time

EV_SYN = 0x00
EV_KEY = 0x01
SYN_REPORT = 0

_EVENT = struct.Struct("llHHi")

_EVIOCGLED = (2 << 30) | (8 << 16) | (0x45 << 8) | 0x19
_LED_CAPSL = 1

_UI_SET_EVBIT = 0x40045564
_UI_SET_KEYBIT = 0x40045565
_UI_DEV_SETUP = 0x405C5503
_UI_DEV_CREATE = 0x5501
_UI_DEV_DESTROY = 0x5502
_BUS_VIRTUAL = 0x06

VIRTUAL_DEVICE_NAME = "layout-switcher virtual keyboard"

_KEY_A = 30
_KEY_SPACE = 57


def _has_bit(bitmap_words, bit):
    words = list(reversed(bitmap_words))
    index, offset = divmod(bit, 64)
    return index < len(words) and bool(int(words[index], 16) >> offset & 1)


def find_input_devices(proc_path="/proc/bus/input/devices"):
    """{event node path: is_keyboard} of physical keyboards and pointers."""
    with open(proc_path, encoding="utf-8") as f:
        blocks = f.read().strip().split("\n\n")
    devices = {}
    for block in blocks:
        name, handlers, key_bits = "", [], []
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line[len("N: Name="):].strip('"')
            elif line.startswith("H: Handlers="):
                handlers = line[len("H: Handlers="):].split()
            elif line.startswith("B: KEY="):
                key_bits = line[len("B: KEY="):].split()
        if name == VIRTUAL_DEVICE_NAME:
            continue
        event = next((h for h in handlers if h.startswith("event")), None)
        if event is None:
            continue
        is_keyboard = "kbd" in handlers and _has_bit(key_bits, _KEY_A) and _has_bit(key_bits, _KEY_SPACE)
        is_pointer = any(h.startswith("mouse") for h in handlers)
        if is_keyboard or is_pointer:
            devices[f"/dev/input/{event}"] = is_keyboard
    return devices


class InputDevice:
    def __init__(self, path, is_keyboard):
        self.path = path
        self.is_keyboard = is_keyboard
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)

    def fileno(self):
        return self.fd

    def caps_lock_led(self):
        leds = fcntl.ioctl(self.fd, _EVIOCGLED, bytes(8))
        return bool(leds[0] >> _LED_CAPSL & 1)

    def read_key_events(self):
        """(code, value) of pending EV_KEY events; raises OSError once unplugged."""
        events = []
        while True:
            try:
                data = os.read(self.fd, _EVENT.size * 64)
            except BlockingIOError:
                return events
            if not data:
                return events
            for offset in range(0, len(data) - _EVENT.size + 1, _EVENT.size):
                _, _, ev_type, code, value = _EVENT.unpack_from(data, offset)
                if ev_type == EV_KEY:
                    events.append((code, value))

    def close(self):
        os.close(self.fd)


class VirtualKeyboard:
    def __init__(self, key_codes, key_delay=0.004):
        self.key_delay = key_delay
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, _UI_SET_EVBIT, EV_KEY)
        for code in key_codes:
            fcntl.ioctl(self.fd, _UI_SET_KEYBIT, code)
        setup = struct.pack("HHHH80sI", _BUS_VIRTUAL, 0x1, 0x1, 1, VIRTUAL_DEVICE_NAME.encode(), 0)
        fcntl.ioctl(self.fd, _UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, _UI_DEV_CREATE)
        time.sleep(0.3)

    def _emit(self, code, value):
        os.write(self.fd, _EVENT.pack(0, 0, EV_KEY, code, value))
        os.write(self.fd, _EVENT.pack(0, 0, EV_SYN, SYN_REPORT, 0))

    def tap(self, code, shift_code=None):
        if shift_code is not None:
            self._emit(shift_code, 1)
        self._emit(code, 1)
        self._emit(code, 0)
        if shift_code is not None:
            self._emit(shift_code, 0)
        time.sleep(self.key_delay)

    def close(self):
        fcntl.ioctl(self.fd, _UI_DEV_DESTROY)
        os.close(self.fd)
