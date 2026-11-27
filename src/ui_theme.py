"""
The app's look (Apple-style, light or dark — ⚙ Settings → Appearance), applied at startup.

The app's styles are written with its original warm-grey colours. Every style sheet and
rich-text label goes through restyle(), which swaps each of those for Apple's — system
neutrals (#F5F5F7 window, white cards, hairline separators), system blue as the accent —
in light or dark: text colours (after "color:") one way, backgrounds and borders another.
Data colours (statuses, categories) stay as they are: they were picked to stay apart for
colour-blind eyes. Charts get matching neutrals (charts.set_theme). Exports keep their
own design.
"""

import re, subprocess, sys

# ── colours ───────────────────────────────────────────────────────────────────
# original → Apple light, text colours (after "color:")
LIGHT_TEXT = {"#1A1A18": "#1D1D1F", "#52514E": "#424245", "#666663": "#6E6E73", "#888885": "#86868B",
              "#8A8984": "#86868B", "#999996": "#8E8E93", "#AAAAA6": "#AEAEB2", "#444441": "#3A3A3C",
              "#0F6E56": "#0066CC", "#2F5E9E": "#0066CC", "#0B7A0B": "#248A3D", "#A32D2D": "#D70015",
              "#854F0B": "#B25000", "#3B6D11": "#248A3D", "#B26B00": "#B25000", "#1D9E75": "#007AFF"}
# original → Apple light, backgrounds and borders
LIGHT_FILL = {"#F5F5F2": "#F5F5F7", "#FAFAF8": "#FAFAFC", "#EEECEA": "#EDEDF0", "#E0DDD8": "#E5E5EA",
              "#E6E4E0": "#E8E8ED", "#CCCCC8": "#D2D2D7", "#F0EEE9": "#F0F0F3", "#F0EFEB": "#F2F2F5",
              "#F1EFE8": "#EEEEF2", "#F3F2EF": "#F2F2F7", "#ECEAE6": "#E8E8ED", "#F7F7F5": "#F5F5F7",
              "#E1F5EE": "#E5F0FF", "#FFF6E5": "#FFF4E5", "#F3D9A4": "#FFD9A8", "#E3F4E1": "#E3F5E8",
              "#E8F1FC": "#E5F0FF", "#B4B2A9": "#C7C7CC", "#BDBBB6": "#C7C7CC", "#8CCDB8": "#99C7FF",
              "#F4F3EF": "#F5F5F7", "#1D9E75": "#007AFF", "#17896A": "#0071EB", "#0F6E56": "#0062CC"}
# original → Apple dark
DARK_TEXT = {"#1A1A18": "#F5F5F7", "#52514E": "#D1D1D6", "#666663": "#AEAEB2", "#888885": "#98989D",
             "#8A8984": "#98989D", "#999996": "#8E8E93", "#AAAAA6": "#636366", "#444441": "#E5E5EA",
             "#0F6E56": "#409CFF", "#2F5E9E": "#409CFF", "#993556": "#FF6482", "#0B7A0B": "#30D158",
             "#A32D2D": "#FF6961", "#854F0B": "#FFB340", "#3B6D11": "#30D158", "#B26B00": "#FFB340",
             "#1D9E75": "#0A84FF", "#FFFFFF": "#FFFFFF"}
DARK_FILL = {"#FFFFFF": "#1C1C1E", "#F5F5F2": "#111113", "#FAFAF8": "#232325", "#EEECEA": "#2C2C2E",
             "#E0DDD8": "#38383A", "#E6E4E0": "#2C2C2E", "#CCCCC8": "#48484A", "#F0EEE9": "#2C2C2E",
             "#F0EFEB": "#232325", "#F1EFE8": "#2C2C2E", "#F3F2EF": "#2C2C2E", "#ECEAE6": "#38383A",
             "#F7F7F5": "#232325", "#E1F5EE": "#0A2A4D", "#FFF6E5": "#3A2A12", "#F3D9A4": "#6B4A14",
             "#FCEFF4": "#3A1F2A", "#F4C0D1": "#6B2A40", "#E3F4E1": "#173A22", "#E8F1FC": "#0A2A4D",
             "#B4B2A9": "#636366", "#BDBBB6": "#545456", "#8CCDB8": "#1F4E80", "#F4F3EF": "#232325",
             "#1D9E75": "#0A84FF", "#17896A": "#409CFF", "#0F6E56": "#0A84FF"}
_HEX = re.compile(r"((?<![-\w])color\s*:\s*)(#[0-9A-Fa-f]{6})|(#[0-9A-Fa-f]{6})")

DARK = False
_TEXT, _FILL = LIGHT_TEXT, LIGHT_FILL

def restyle(text):
    """Original colours → the Apple look (light or dark)."""
    if not isinstance(text, str) or "#" not in text:
        return text

    def swap(m):
        if m.group(1):
            return m.group(1) + _TEXT.get(m.group(2).upper(), m.group(2))
        return _FILL.get(m.group(3).upper(), m.group(3))
    return _HEX.sub(swap, text)

dark = restyle          # the old name


def system_is_dark():
    if sys.platform != "darwin":
        return False
    try:
        r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True,
                           timeout=3)
        return r.stdout.strip().lower() == "dark"
    except Exception:
        return False

def wants_dark(appearance):
    return appearance == "dark" or (appearance == "system" and system_is_dark())


def install(dark_mode, modules=()):
    """Turn the look on for the app: patch style sheets and rich text, and swap the QLabel
    used by our modules for one that restyles its text."""
    global DARK, _TEXT, _FILL
    DARK = bool(dark_mode)
    _TEXT, _FILL = (DARK_TEXT, DARK_FILL) if DARK else (LIGHT_TEXT, LIGHT_FILL)
    import charts
    charts.set_theme(DARK)
    from PyQt5.QtWidgets import QWidget, QLabel, QTextBrowser
    set_style = QWidget.setStyleSheet
    QWidget.setStyleSheet = lambda self, s: set_style(self, restyle(s))
    set_text = QLabel.setText
    QLabel.setText = lambda self, s: set_text(self, restyle(s))
    set_html = QTextBrowser.setHtml
    QTextBrowser.setHtml = lambda self, s: set_html(self, restyle(s))

    class ThemedLabel(QLabel):
        def __init__(self, *args, **kwargs):
            if args and isinstance(args[0], str):
                args = (restyle(args[0]),) + args[1:]
            super().__init__(*args, **kwargs)

    for m in modules:
        if getattr(m, "QLabel", None) is QLabel:
            m.QLabel = ThemedLabel


def palette():
    from PyQt5.QtGui import QPalette, QColor
    pal = QPalette()
    if DARK:
        roles = [(QPalette.Window, "#111113"), (QPalette.WindowText, "#F5F5F7"), (QPalette.Base, "#1C1C1E"),
                 (QPalette.AlternateBase, "#232325"), (QPalette.Text, "#F5F5F7"), (QPalette.Button, "#2C2C2E"),
                 (QPalette.ButtonText, "#F5F5F7"), (QPalette.ToolTipBase, "#2C2C2E"),
                 (QPalette.ToolTipText, "#F5F5F7"), (QPalette.Highlight, "#0A84FF"),
                 (QPalette.HighlightedText, "#FFFFFF"), (QPalette.PlaceholderText, "#8E8E93"),
                 (QPalette.Link, "#409CFF"), (QPalette.BrightText, "#FFFFFF")]
        off = "#636366"
    else:
        roles = [(QPalette.Window, "#F5F5F7"), (QPalette.WindowText, "#1D1D1F"), (QPalette.Base, "#FFFFFF"),
                 (QPalette.AlternateBase, "#FAFAFC"), (QPalette.Text, "#1D1D1F"), (QPalette.Button, "#FFFFFF"),
                 (QPalette.ButtonText, "#1D1D1F"), (QPalette.ToolTipBase, "#FFFFFF"),
                 (QPalette.ToolTipText, "#1D1D1F"), (QPalette.Highlight, "#007AFF"),
                 (QPalette.HighlightedText, "#FFFFFF"), (QPalette.PlaceholderText, "#8E8E93"),
                 (QPalette.Link, "#0066CC"), (QPalette.BrightText, "#FFFFFF")]
        off = "#AEAEB2"
    for role, color in roles:
        pal.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        pal.setColor(QPalette.Disabled, role, QColor(off))
    return pal


# ── segmented tabs ────────────────────────────────────────────────────────────

def segmented_tab_bar():
    """A QTabBar drawn like a macOS segmented control: a track, and a raised pill under
    the chosen tab that glides to the next one on a spring — from wherever it is, if you
    change your mind halfway."""
    from PyQt5.QtCore import QRectF, Qt, QVariantAnimation, QAbstractAnimation
    from PyQt5.QtGui import QColor, QPainter
    from PyQt5.QtWidgets import QTabBar
    import motion

    class SegmentedTabBar(QTabBar):
        def __init__(self):
            super().__init__()
            self.setDrawBase(False)
            self.setExpanding(False)
            self._pill = None                       # QRectF on screen now
            self._anim = None
            self.currentChanged.connect(self._glide)

        def _target(self, i=None):
            i = self.currentIndex() if i is None else i
            return QRectF(self.tabRect(i)).adjusted(3, 4, -3, -4) if i >= 0 else None

        def _glide(self, i):
            to = self._target(i)
            if to is None:
                return
            if self._pill is None or motion.REDUCED or not self.isVisible():
                self._pill = to
                self.update()
                return
            frm = QRectF(self._pill)                # presentation value: interruptible
            if self._anim is not None:
                try:
                    self._anim.stop()
                except RuntimeError:
                    pass
            anim = QVariantAnimation(self)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setDuration(motion.duration(0.32))
            anim.setEasingCurve(motion.spring(1.0))

            def step(t, frm=frm, to=to):
                t = float(t)
                self._pill = QRectF(frm.x() + (to.x() - frm.x()) * t, frm.y() + (to.y() - frm.y()) * t,
                                    frm.width() + (to.width() - frm.width()) * t,
                                    frm.height() + (to.height() - frm.height()) * t)
                self.update()
            anim.valueChanged.connect(step)
            anim.finished.connect(lambda: setattr(self, "_anim", None))
            anim.start(QAbstractAnimation.DeleteWhenStopped)
            self._anim = anim

        def _settled(self):
            return getattr(self, "_anim", None) is None     # (Qt asks before __init__ is done)

        def tabLayoutChange(self):
            super().tabLayoutChange()
            if self._settled():
                self._pill = self._target()

        def resizeEvent(self, e):
            super().resizeEvent(e)
            if self._settled():
                self._pill = self._target()

        def paintEvent(self, e):
            if self.count():
                p = QPainter(self)
                p.setRenderHint(QPainter.Antialiasing)
                first, last = self.tabRect(0), self.tabRect(self.count() - 1)
                track = QRectF(first.left(), first.top() + 1, last.right() - first.left() + 1,
                               first.height() - 2)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 20) if DARK else QColor(0, 0, 0, 13))
                p.drawRoundedRect(track, 10, 10)
                pill = self._pill or self._target()
                if pill is not None:
                    p.setBrush(QColor(0, 0, 0, 70 if DARK else 22))          # a soft shadow under it
                    p.drawRoundedRect(pill.translated(0, 1), 8, 8)
                    p.setBrush(QColor("#5A5A5F") if DARK else QColor("#FFFFFF"))
                    p.drawRoundedRect(pill, 8, 8)
                p.end()
            super().paintEvent(e)

    return SegmentedTabBar()
