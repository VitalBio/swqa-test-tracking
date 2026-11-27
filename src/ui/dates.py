"""
The date filter: the Dates bar on the dashboard and Feature Testing, and the date
picker used by a card's own dates and the export.
"""

from datetime import date, timedelta

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QSpinBox, QLabel, QFrame, QComboBox, QDateEdit
from PyQt5.QtCore import QDate, pyqtSignal

from data import store

from ui.common import MUTED, _small_label


class DateScopeRow(QWidget):
    """Pick dates: a mode, plus a number of days or one or two dates. With `card_text`, the
    first choice is the card's own dates (used in the export, to change them for one export)."""

    MODES = [("follow", "Follow the dashboard's dates"), ("all", "All dates"),
             ("days", "The last … days"), ("since", "Since a date"), ("between", "Between two dates")]

    changed = pyqtSignal()

    def __init__(self, dates=None, card_text=None, follow_label=None):
        super().__init__()
        d = dates or {}
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.mode = QComboBox()
        self.mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(14)       # long choices elide instead of widening the row
        if card_text:
            self.mode.addItem(f"The card's own ({card_text})", "card")
        for k, label in self.MODES:
            self.mode.addItem(follow_label if (k == "follow" and follow_label) else label, k)
        self.mode.setCurrentIndex(max(self.mode.findData(d.get("mode", "card" if card_text else "days")), 0))
        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        self.days.setValue(int(d.get("days") or 7))
        self.days.setSuffix(" days")
        today = QDate.currentDate()
        def qdate(text, fallback):
            q = QDate.fromString(text or "", "yyyy-MM-dd")
            return q if q.isValid() else fallback
        self.d_from = QDateEdit(qdate(d.get("from"), today.addDays(-6)))
        self.d_to = QDateEdit(qdate(d.get("to"), today))
        for ed in (self.d_from, self.d_to):
            ed.setCalendarPopup(True)
            ed.setDisplayFormat("MMM d, yyyy")
            ed.dateChanged.connect(lambda *_: self.changed.emit())
        self.and_lbl = QLabel("and")
        for w_ in (self.mode, self.days, self.d_from, self.and_lbl, self.d_to):
            h.addWidget(w_)
        h.addStretch(1)
        self.mode.currentIndexChanged.connect(self._modes)
        self.days.valueChanged.connect(lambda *_: self.changed.emit())
        self._modes()

    def _modes(self, *_):
        m = self.mode.currentData()
        self.days.setVisible(m == "days")
        self.d_from.setVisible(m in ("since", "between"))
        self.and_lbl.setVisible(m == "between")
        self.d_to.setVisible(m == "between")
        self.changed.emit()

    def value(self):
        """{"mode": …, …}; None for "the card's own"."""
        m = self.mode.currentData()
        if m == "card":
            return None
        d = {"mode": m}
        if m == "days":
            d["days"] = self.days.value()
        if m in ("since", "between"):
            d["from"] = self.d_from.date().toString("yyyy-MM-dd")
        if m == "between":
            d["to"] = self.d_to.date().toString("yyyy-MM-dd")
        return d


DATE_PRESETS = ["All dates", "Today", "Yesterday", "Last 7 days", "Last 30 days", "This month",
                "On a date…", "Date range…"]

def _qdate(ed):
    d = ed.date()
    return date(d.year(), d.month(), d.day())

def range_for(name, start=None, end=None):
    """(first day, last day) for a preset, or None for all dates. Presets are relative to today."""
    today = date.today()
    if name == "Today":
        return today, today
    if name == "Yesterday":
        return today - timedelta(days=1), today - timedelta(days=1)
    if name == "Last 7 days":
        return today - timedelta(days=6), today
    if name == "Last 30 days":
        return today - timedelta(days=29), today
    if name == "This month":
        return today.replace(day=1), today
    if name == "On a date…":
        return start, start
    if name == "Date range…":
        return (start, end) if start <= end else (end, start)
    return None

def range_text(rng):
    if rng is None:
        return "All dates"
    if rng[0] == rng[1]:
        return f"{rng[0]:%a %b} {rng[0].day}"
    return f"{rng[0]:%b} {rng[0].day} – {rng[1]:%b} {rng[1].day}"


class DateBar(QFrame):
    """Dates ▾ [preset] [from] – [to] — narrows the dashboard to runs in that range."""
    PRESETS = DATE_PRESETS

    def __init__(self, win):
        super().__init__()
        self.win = win
        saved = win.cfg.get("dash_dates") or {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 10, 8, 0)
        lay.setSpacing(8)
        lay.addWidget(_small_label("Dates"))
        self.preset = QComboBox()
        self.preset.addItems(self.PRESETS)
        self.preset.setMinimumWidth(150)
        self.start, self.end = QDateEdit(), QDateEdit()
        for ed, key in ((self.start, "from"), (self.end, "to")):
            ed.setCalendarPopup(True)
            ed.setDisplayFormat("MMM d, yyyy")
            ed.setMinimumWidth(130)
            d = store.parse_date(saved.get(key, ""))
            ed.setDate(QDate(d.year, d.month, d.day) if d else QDate.currentDate())
            ed.dateChanged.connect(self._changed)
        self.dash_lbl = QLabel("–")
        self.note = _small_label("", MUTED)
        lay.addWidget(self.preset)
        lay.addWidget(self.start)
        lay.addWidget(self.dash_lbl)
        lay.addWidget(self.end)
        lay.addSpacing(6)
        lay.addWidget(self.note, 1)
        i = self.preset.findText(saved.get("preset", "All dates"))
        self.preset.setCurrentIndex(max(i, 0))
        self.preset.currentIndexChanged.connect(self._changed)
        self._apply(save=False)

    def _changed(self, *_):
        self._apply(save=True)
        if self.win.data:
            self.win.dashboard.set_data(self.win.data, animate=True)
            if hasattr(self.win, "testing_page"):
                self.win.testing_page.refresh()

    def current_range(self):
        """(first day, last day), or None for all dates."""
        return range_for(self.preset.currentText(), _qdate(self.start), _qdate(self.end))

    def _apply(self, save):
        name = self.preset.currentText()
        self.start.setVisible(name in ("On a date…", "Date range…"))
        self.dash_lbl.setVisible(name == "Date range…")
        self.end.setVisible(name == "Date range…")
        rng = self.current_range()
        dash = self.win.dashboard
        dash.range = rng
        dash.range_text = range_text(rng)
        tabs = (self.win.data or {}).get("tabs", [])
        dated = [t["title"] for t in tabs if store.date_column(t)]
        bugs = [t["title"] for t in tabs if store.is_bug_tab(t)]
        testing = getattr(self.win, "testing_page", None)
        if rng is not None and testing is not None and self.parent() is testing:
            self.note.setText(f"Showing test sessions dated {dash.range_text}. The dashboard uses the same dates.")
        elif rng is None:
            self.note.setText("")
        else:
            parts = [", ".join(dated)] if dated else []
            if bugs:
                parts.append("new and closed bugs on " + ", ".join(bugs))
            self.note.setText(f"Showing {dash.range_text} for " + ("; ".join(parts) or "dated tabs")
                              + ". Other charts show everything.")
        if save:
            self.win.cfg["dash_dates"] = {"preset": name,
                                          "from": self.start.date().toString("M/d/yyyy"),
                                          "to": self.end.date().toString("M/d/yyyy")}
            store.save_config(self.win.cfg)

    def refresh(self):
        """Presets like "Today" follow the clock; update the text after each sync."""
        self._apply(save=False)
