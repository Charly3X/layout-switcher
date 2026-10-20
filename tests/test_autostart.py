import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from layout_switcher import autostart


class AutostartTest(unittest.TestCase):
    def test_switching_autostart_on_and_off(self):
        with TemporaryDirectory() as tmp:
            entry = Path(tmp) / "autostart" / "layout-switcher.desktop"
            with mock.patch.object(autostart, "AUTOSTART_ENTRY", entry):
                self.assertFalse(autostart.is_enabled())

                autostart.set_enabled(True)
                self.assertTrue(autostart.is_enabled())
                text = entry.read_text(encoding="utf-8")
                self.assertIn(f"Path={autostart.PROJECT_DIR}\n", text)
                self.assertIn("-m layout_switcher\n", text)

                autostart.set_enabled(False)
                self.assertFalse(autostart.is_enabled())
                autostart.set_enabled(False)


if __name__ == "__main__":
    unittest.main()
