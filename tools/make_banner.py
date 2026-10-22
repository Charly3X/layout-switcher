"""Render docs/banner.png: the README header and the GitHub social preview (1280x640).

GitHub topic and search cards crop the preview to about 2.6:1, i.e. roughly
y 77..563, so everything that matters stays inside that band.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QLinearGradient, QPainter, QPen,
)

WIDTH, HEIGHT = 1280, 640
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "banner.png"

BACKGROUND_TOP = QColor("#20242c")
BACKGROUND_BOTTOM = QColor("#15181e")
CARD = QColor("#262b34")
CARD_BORDER = QColor("#323844")
ACCENT = QColor("#3daee9")
FLASH = QColor("#f67400")
TEXT = QColor("#eef1f5")
MUTED = QColor("#8a93a3")
WRONG = QColor("#6b7280")

SANS = "Noto Sans"
MONO = "JetBrains Mono"

EXAMPLES = [
    ("ghbdtn", "привет", None),
    ("ye b xnj", "ну и что", None),
    ("cgc", "спасибо", "autoreplace"),
]


def font(family, pixels, weight=QFont.Weight.Normal):
    f = QFont(family)
    f.setPixelSize(pixels)
    f.setWeight(weight)
    return f


def draw_badge(painter, rect):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ACCENT)
    painter.drawRoundedRect(rect, rect.width() * 0.22, rect.width() * 0.22)
    painter.setFont(font(SANS, int(rect.height() * 0.47), QFont.Weight.Bold))
    painter.setPen(QColor("white"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Ая")


def draw_chip(painter, x, y, text):
    f = font(SANS, 20, QFont.Weight.Medium)
    width = QFontMetricsF(f).horizontalAdvance(text) + 32
    rect = QRectF(x, y, width, 38)
    painter.setPen(QPen(CARD_BORDER, 1.5))
    painter.setBrush(CARD)
    painter.drawRoundedRect(rect, 19, 19)
    painter.setFont(f)
    painter.setPen(MUTED)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    return x + width + 12


def draw_example(painter, x, baseline, typed, fixed, note):
    mono = font(MONO, 40, QFont.Weight.Medium)
    metrics = QFontMetricsF(mono)
    painter.setFont(mono)

    painter.setPen(WRONG)
    painter.drawText(QPointF(x, baseline), typed)
    typed_width = metrics.horizontalAdvance(typed)
    painter.setPen(QPen(WRONG, 2.5))
    strike_y = baseline - metrics.xHeight() / 2
    painter.drawLine(QPointF(x, strike_y), QPointF(x + typed_width, strike_y))

    arrow_x = x + 260
    painter.setPen(QPen(FLASH, 3.5, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
    mid = baseline - metrics.xHeight() / 2
    painter.drawLine(QPointF(arrow_x, mid), QPointF(arrow_x + 54, mid))
    painter.drawLine(QPointF(arrow_x + 40, mid - 12), QPointF(arrow_x + 54, mid))
    painter.drawLine(QPointF(arrow_x + 40, mid + 12), QPointF(arrow_x + 54, mid))

    fixed_x = arrow_x + 92
    painter.setPen(TEXT)
    painter.drawText(QPointF(fixed_x, baseline), fixed)
    painter.setPen(QPen(ACCENT, 3))
    underline_y = baseline + 10
    painter.drawLine(QPointF(fixed_x, underline_y), QPointF(fixed_x + metrics.horizontalAdvance(fixed), underline_y))

    if note:
        painter.setFont(font(SANS, 20, QFont.Weight.Medium))
        painter.setPen(MUTED)
        painter.drawText(QPointF(fixed_x + metrics.horizontalAdvance(fixed) + 28, baseline - 4), note)


def example_block_width():
    mono = QFontMetricsF(font(MONO, 40, QFont.Weight.Medium))
    note = QFontMetricsF(font(SANS, 20, QFont.Weight.Medium))
    return max(
        352 + mono.horizontalAdvance(fixed) + (28 + note.horizontalAdvance(text) if text else 0)
        for _typed, fixed, text in EXAMPLES
    )


def render():
    image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    gradient = QLinearGradient(0, 0, 0, HEIGHT)
    gradient.setColorAt(0, BACKGROUND_TOP)
    gradient.setColorAt(1, BACKGROUND_BOTTOM)
    painter.fillRect(image.rect(), gradient)

    margin = 88
    draw_badge(painter, QRectF(margin, 110, 100, 100))

    painter.setPen(TEXT)
    painter.setFont(font(SANS, 62, QFont.Weight.Bold))
    painter.drawText(QPointF(margin + 128, 170), "Layout Switcher")
    painter.setPen(MUTED)
    painter.setFont(font(SANS, 27))
    painter.drawText(QPointF(margin + 130, 208), "Fixes words typed in the wrong keyboard layout")

    card = QRectF(margin, 236, WIDTH - 2 * margin, 226)
    painter.setPen(QPen(CARD_BORDER, 1.5))
    painter.setBrush(CARD)
    painter.drawRoundedRect(card, 22, 22)
    left = card.center().x() - example_block_width() / 2
    for i, (typed, fixed, note) in enumerate(EXAMPLES):
        draw_example(painter, left, card.top() + 66 + i * 64, typed, fixed, note)

    x = margin
    for chip in ("KDE Plasma", "Wayland", "English ↔ Russian", "Punto Switcher for Linux"):
        x = draw_chip(painter, x, 482, chip)

    painter.end()
    OUTPUT.parent.mkdir(exist_ok=True)
    image.save(str(OUTPUT))
    print(OUTPUT)


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    render()
