"""Desktop entries: one in the application menu, one in XDG autostart while autostart is on."""

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))

APPLICATION_ENTRY = _DATA_HOME / "applications" / "layout-switcher.desktop"
AUTOSTART_ENTRY = _CONFIG_HOME / "autostart" / "layout-switcher.desktop"


def desktop_entry():
    return f"""[Desktop Entry]
Type=Application
Name=Layout Switcher
Comment=Fixes words typed in the wrong keyboard layout
Path={PROJECT_DIR}
Exec={sys.executable} -m layout_switcher
Icon=input-keyboard
Terminal=false
Categories=Utility;
X-KDE-autostart-after=panel
"""


def _write(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(desktop_entry(), encoding="utf-8")


def is_enabled():
    return AUTOSTART_ENTRY.exists()


def set_enabled(enabled):
    if enabled:
        _write(AUTOSTART_ENTRY)
    else:
        AUTOSTART_ENTRY.unlink(missing_ok=True)


def install_application_entry():
    _write(APPLICATION_ENTRY)
