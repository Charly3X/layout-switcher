import os
import subprocess
import unittest
from unittest import mock

from layout_switcher import session as session_module
from layout_switcher.session import SessionGuard


def busctl_replies(seat, session, screensaver=None):
    """Fake subprocess.run for the seat0, session and screen locker queries."""
    def run(args, **kwargs):
        if "--user" in args:
            reply = screensaver if screensaver is not None else LOCKER_OFF
        elif "/org/freedesktop/login1/seat/seat0" in args:
            reply = seat
        else:
            reply = session
        if isinstance(reply, Exception):
            raise reply
        return subprocess.CompletedProcess(args, 0, stdout=reply, stderr="")
    return run


OUR_SEAT = '{"type":"(so)","data":["5","/org/freedesktop/login1/session/_35"]}\n'


def session_reply(uid, locked):
    return (f'{{"type":"(uo)","data":[{uid},"/org/freedesktop/login1/user/_{uid}"]}}\n'
            f'{{"type":"b","data":{"true" if locked else "false"}}}\n')


LOCKER_OFF = '{"type":"b","data":[false]}\n'


class SessionGuardTest(unittest.TestCase):
    def allows(self, seat=OUR_SEAT, session=None, screensaver=None):
        session = session if session is not None else session_reply(os.getuid(), False)
        with mock.patch.object(session_module.subprocess, "run", busctl_replies(seat, session, screensaver)):
            return SessionGuard().allows_typing()

    def test_our_unlocked_session_in_front_allows_typing(self):
        self.assertTrue(self.allows())

    def test_locked_session_blocks(self):
        self.assertFalse(self.allows(session=session_reply(os.getuid(), True)))

    def test_another_users_session_in_front_blocks(self):
        self.assertFalse(self.allows(session=session_reply(os.getuid() + 1, False)))

    def test_no_session_in_front_blocks(self):
        self.assertFalse(self.allows(seat='{"type":"(so)","data":["","/"]}\n'))

    def test_kde_locker_blocks_even_without_locked_hint(self):
        self.assertFalse(self.allows(screensaver='{"type":"b","data":[true]}\n'))

    def test_logind_failure_blocks(self):
        with self.assertLogs("layout_switcher", "WARNING"):
            self.assertFalse(self.allows(seat=subprocess.CalledProcessError(1, "busctl")))

    def test_missing_screen_locker_does_not_block(self):
        self.assertTrue(self.allows(screensaver=subprocess.CalledProcessError(1, "busctl")))


if __name__ == "__main__":
    unittest.main()
