"""Keyboard layout state of KDE Plasma (KWin) over the session D-Bus."""

import json
import subprocess

_TARGET = ["org.kde.keyboard", "/Layouts", "org.kde.KeyboardLayouts"]


def _call(method, *args):
    result = subprocess.run(
        ["busctl", "--user", "--json=short", "call", *_TARGET, method, *args],
        capture_output=True,
        text=True,
        timeout=2,
        check=True,
    )
    return json.loads(result.stdout)["data"] if result.stdout.strip() else None


class KdeLayouts:
    """Asks KWin every time: layouts can be added or reordered while we run."""

    def state(self):
        """(active layout short name or None, all short names in KDE order, e.g. ["us", "ru", "ua"])."""
        names = [short for short, _variant, _title in _call("getLayoutsList")[0]]
        index = _call("getLayout")[0]
        return (names[index] if index < len(names) else None), names

    def activate(self, name, names):
        _call("setLayout", "u", str(names.index(name)))
