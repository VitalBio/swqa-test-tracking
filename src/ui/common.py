"""
Small helpers and colours shared by the app's windows: labels, links, background
tasks, and the flowing layouts used by the export list and side-by-side lists.
"""

import json, re

from PyQt5.QtWidgets import QWidget, QGridLayout, QLayout, QLabel, QMenu, QSizePolicy
from PyQt5.QtCore import Qt, QObject, QRunnable, QUrl, pyqtSignal, QRect, QPoint, QSize
from PyQt5.QtGui import QColor, QDesktopServices, QPixmap, QPainter, QIcon

from dashboard import charts
from dashboard import layout
from data import store


INK, MUTED = "#1A1A18", "#999996"
GREEN, AMBER, RED = "#3B6D11", "#854F0B", "#A32D2D"
ACCENT, LINK = "#1D9E75", "#2F5E9E"

BLANK = "(blank)"
WRAP_MAX_LINES = 8          # taller cells are cut off; the tooltip and Edit… show all of it


# ── small helpers ─────────────────────────────────────────────────────────────

def _small_label(text, color="#666663", size=11):
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:{color}; font-size:{size}px;")
    return lbl

def _natural(text):
    """Sort key that orders numbers numerically: PROD-2 before PROD-10."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t)
            for t in re.split(r"(\d+)", (text or "").lower()) if t]

_ZWSP = "\u200b"
def _breakable(text):
    """Let wrapped text break inside long paths, versions and hashes
    (e.g. /tmp/repo/qa/…, staging-808ec07…) by adding invisible break points."""
    text = re.sub(r"([/_\-.:,=])(?=\S)", "\\1" + _ZWSP, text)
    return re.sub(r"(\S{24})(?=\S)", "\\1" + _ZWSP, text)

def _open_link(url):
    if url:
        QDesktopServices.openUrl(QUrl(url))

def _nowrap_option():
    from PyQt5.QtGui import QTextOption
    o = QTextOption()
    o.setWrapMode(QTextOption.NoWrap)
    return o

def _links_menu(parent, links, title=None):
    """A menu with one “Open …” item per link."""
    menu = QMenu(title or "Open link", parent)
    for text, url in links:
        label = (text or url).replace("&", "&&")
        menu.addAction(f"Open {label[:60]} ↗", lambda u=url: _open_link(u))
    return menu

_dots = {}
def _dot(color):
    """A small colored circle shown next to status values."""
    if color not in _dots:
        pm = QPixmap(20, 20)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(3, 3, 14, 14)
        p.end()
        _dots[color] = QIcon(pm)
    return _dots[color]

def _version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])

def _words_of(text):
    return set(re.findall(r"[a-z]+", (text or "").lower()))

def _plural_days(n):
    return f"{n} day{'s' if n != 1 else ''}"

def _visible_rows(tab):
    return [r for r in tab["rows"] if not store.is_blank(r)]

_colors_for = charts.tab_colors

def _settings(win):
    return (win.data or {}).get("settings") or {}


def _card_merger(tab, base, edited, edited_raw):
    """fn(the layout in the sheet now) → the layout to save: the cards you changed, added or
    deleted, on top of the sheet's current cards. Another admin may have saved other cards of
    the same tab while you were editing; theirs stay."""
    def card_json(c):
        return json.dumps(c, sort_keys=True)
    before = layout.layout_for(tab, base)
    def merge(now_raw):
        if not now_raw:
            return edited_raw
        now = layout.layout_for(tab, {layout.key_for(tab): now_raw})
        if [card_json(c) for c in now["cards"]] == [card_json(c) for c in before["cards"]]:
            return edited_raw                          # nobody else changed this tab: save as is
        b = {c["id"]: card_json(c) for c in before["cards"]}
        mine = {c["id"]: c for c in edited["cards"]}
        changed = {i for i, c in mine.items() if b.get(i) != card_json(c)}
        deleted = set(b) - set(mine)
        cards = [mine[c["id"]] if c["id"] in changed else c for c in now["cards"] if c["id"] not in deleted]
        have = {c["id"] for c in cards}
        cards += [c for i, c in mine.items() if i in changed and i not in have]   # cards you added
        out = dict(edited, cards=cards)
        return layout.dump(out)
    return merge


# ── background work ───────────────────────────────────────────────────────────
# Google Sheets calls take a moment, so they run off the UI thread. The pool has
# a single thread, which keeps operations in the order they were requested.

class _TaskSignals(QObject):
    done   = pyqtSignal(object)
    failed = pyqtSignal(object)

class _Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.setAutoDelete(False)
        self.fn = fn
        self.signals = _TaskSignals()

    def run(self):
        try:
            result = self.fn()
        except Exception as exc:
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(result)


def card_key(tab, card):
    """How a dashboard card is named in this computer's settings (hidden cards, card views)."""
    return f"{tab['title']}::{card['id']}"

def _clear_layout(lay_):
    while lay_.count():
        it = lay_.takeAt(0)
        w, sub = it.widget(), it.layout()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif sub is not None:
            _clear_layout(sub)
            sub.deleteLater()


class _FlowLayout(QLayout):
    """Lays its items out left to right and wraps to the next line when the width runs
    out (like words in a paragraph), so it never needs a sideways scroll bar."""

    def __init__(self, parent=None, h=14, v=2):
        super().__init__(parent)
        self._items, self._h, self._v = [], h, v

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, apply):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line = r.x(), r.y(), 0
        # same-width columns when they fit, so ticks line up from row to row
        col = max((it.sizeHint().width() for it in self._items), default=0)
        for it in self._items:
            w = col if col + self._h <= r.width() else it.sizeHint().width()
            if x + w > r.right() + 1 and line:
                x, y, line = r.x(), y + line + self._v, 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), it.sizeHint()))
            x += w + self._h
            line = max(line, it.sizeHint().height())
        return y + line - rect.y() + m.bottom()


class _FlowColumns(QWidget):
    """Puts its widgets side by side, as many to a row as get a readable width (MIN_W each),
    in equal columns; the rest wrap to the next row. (It used to be all in one row only if
    every one fitted at full width, else all in one column.)"""
    MIN_W = 260

    def __init__(self):
        super().__init__()
        self.items, self.cols = [], 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 4, 0, 0)
        self.grid.setHorizontalSpacing(24)
        self.grid.setVerticalSpacing(14)

    def add(self, w):
        w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.items.append(w)
        self._place()

    def _needed(self):
        return sum(w.sizeHint().width() for w in self.items) + 24 * (len(self.items) - 1)

    def _place(self):
        n = len(self.items)
        if not self.width() or self.width() >= self._needed():
            cols = n
        else:
            cols = max(1, min(n, (self.width() + 24) // (self.MIN_W + 24)))
        if cols == self.cols and all(self.grid.indexOf(w) >= 0 for w in self.items):
            return
        self.cols = cols
        for w in self.items:
            self.grid.removeWidget(w)
        for i, w in enumerate(self.items):
            self.grid.addWidget(w, i // cols, i % cols, Qt.AlignTop)
        for c in range(n):                            # equal columns, so the lists line up
            self.grid.setColumnStretch(c, 1 if c < cols else 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()
