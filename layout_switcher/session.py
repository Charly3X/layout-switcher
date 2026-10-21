"""Whether the user is at an unlocked graphical session, so that typing may be acted on."""

import json
import logging
import os
import subprocess

log = logging.getLogger("layout_switcher")


def _busctl(*args):
    result = subprocess.run(
        ["busctl", "--json=short", *args], capture_output=True, text=True, timeout=2, check=True
    )
    return [json.loads(line)["data"] for line in result.stdout.splitlines() if line.strip()]


class SessionGuard:
    """Asks logind and the KDE screen locker. Anything unclear counts as "locked"."""

    def __init__(self):
        self._warned = False

    def allows_typing(self):
        try:
            allowed = self._our_session_in_front()
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError) as error:
            if not self._warned:
                log.warning("cannot ask logind about the session, staying idle: %s", error)
                self._warned = True
            return False
        self._warned = False
        return allowed and not self._screen_locker_active()

    @staticmethod
    def _our_session_in_front():
        """The session on seat0, which owns the physical keyboard, is ours and unlocked.

        Asking about our own session instead would be wrong when we were started from
        SSH or a TTY, or when the same user also has another session.
        """
        ((_session_id, path),) = _busctl(
            "get-property", "org.freedesktop.login1", "/org/freedesktop/login1/seat/seat0",
            "org.freedesktop.login1.Seat", "ActiveSession",
        )
        if not path or path == "/":
            return False
        (uid, _user_path), locked = _busctl(
            "get-property", "org.freedesktop.login1", path, "org.freedesktop.login1.Session", "User", "LockedHint",
        )
        return uid == os.getuid() and not locked

    @staticmethod
    def _screen_locker_active():
        """KDE's locker; LockedHint alone depends on the compositor reporting it."""
        try:
            (reply,) = _busctl(
                "--user", "call", "org.freedesktop.ScreenSaver", "/ScreenSaver",
                "org.freedesktop.ScreenSaver", "GetActive",
            )
            return bool(reply[0])
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
            return False
