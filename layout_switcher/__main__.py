import argparse
import fcntl
import logging
import os
import signal
import sys

from .autoreplace import Autoreplace
from .daemon import Daemon, Exceptions, Typist, virtual_keyboard
from .kde_layouts import KdeLayouts
from .keymap import keys_for, render
from .language import ALPHABETS, AspellChecker, Judge, TrigramModel

LOCK_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "layout_switcher.lock")


def main():
    parser = argparse.ArgumentParser(
        prog="layout_switcher",
        description="Retypes words typed in the wrong keyboard layout (us <-> ru) on KDE Plasma.",
    )
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

    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("layout_switcher is already running")

    keyboard = virtual_keyboard()
    daemon = Daemon(Typist(judge, KdeLayouts(), keyboard, Exceptions(), Autoreplace()))
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
