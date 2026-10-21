import argparse
import fcntl
import logging
import os
import signal
import sys

from . import __version__
from .autoreplace import Autoreplace
from .daemon import Daemon, Exceptions, Typist, virtual_keyboard
from .kde_layouts import KdeLayouts
from .keymap import keys_for, render
from .language import ALPHABETS, AspellChecker, Judge, TrigramModel
from .paths import CONFIG_DIR
from .session import SessionGuard


def main():
    parser = argparse.ArgumentParser(
        prog="layout-switcher",
        description="Retypes words typed in the wrong keyboard layout (us <-> ru) on KDE Plasma.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--no-tray", action="store_true", help="run without the tray icon")
    parser.add_argument(
        "--debug", action="store_true", help="log every switch, including the typed words"
    )
    parser.add_argument(
        "--check", nargs="+", metavar="TEXT",
        help="only print whether each text would be switched, e.g. --check ghbdtn hello",
    )
    args = parser.parse_args()
    # The pause toggle is wired up later; until then SIGUSR1 must not kill us.
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    judge = Judge(AspellChecker(), {layout: TrigramModel.for_layout(layout) for layout in ("us", "ru")})
    if args.check:
        _check(judge, args.check)
        return

    lock = _single_instance_lock()
    if lock is None:
        sys.exit("layout_switcher is already running")

    keyboard = virtual_keyboard()
    typist = Typist(judge, KdeLayouts(), keyboard, Exceptions(), Autoreplace())
    typist.session_allows = SessionGuard().allows_typing
    daemon = Daemon(typist)
    try:
        if args.no_tray:
            signal.signal(signal.SIGUSR1, daemon.toggle_pause)
            daemon.run()
        else:
            from .tray import run_with_tray

            run_with_tray(daemon)
    except KeyboardInterrupt:
        pass
    finally:
        keyboard.close()


def _single_instance_lock():
    """A held flock on a private file, or None if another copy holds it."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        directory = runtime_dir
    else:
        CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory = CONFIG_DIR
    fd = os.open(os.path.join(directory, "layout_switcher.lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    if os.fstat(fd).st_uid != os.getuid():
        os.close(fd)
        sys.exit("layout_switcher: the lock file belongs to another user")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def _check(judge, texts):
    for text in texts:
        layout = "ru" if any(c.lower() in ALPHABETS["ru"] for c in text) else "us"
        other = "us" if layout == "ru" else "ru"
        keys = keys_for(text, layout)
        intended = render(keys, other)
        verdict = judge.wrong_layout(render(keys, layout), layout, intended, other)
        print(f"{text} -> {intended if verdict else 'keep'}")


if __name__ == "__main__":
    main()
