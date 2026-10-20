#!/bin/sh
# Adds Layout Switcher to the application menu and starts it in the tray.
# Autostart is switched on and off from the tray menu.
set -eu

project_dir=$(cd "$(dirname "$0")" && pwd)

if ! id -nG | tr ' ' '\n' | grep -qx input; then
    echo "Add yourself to the 'input' group first: sudo usermod -aG input $USER (then log out and back in)" >&2
    exit 1
fi

cd "$project_dir"
python3 -c "from layout_switcher import autostart; autostart.install_application_entry()"
setsid -f python3 -m layout_switcher >/dev/null 2>&1
echo "Layout Switcher is running in the system tray."
