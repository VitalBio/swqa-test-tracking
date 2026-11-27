"""
Editing a dashboard card: + Add chart, tiles, card settings, its own dates and
filters, and its colours.
"""

import re

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton, QFrame,
    QDialog, QFormLayout, QDialogButtonBox, QComboBox, QCheckBox, QTabWidget, QScrollArea,
    QToolButton, QListWidget, QListWidgetItem, QPlainTextEdit, QAbstractItemView,
    QColorDialog, QTableWidget, QTableWidgetItem)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QPixmap, QIcon

from dashboard import blocks
from dashboard import charts
from dashboard import layout
from data import chartquery
from data import sqldata
from data import store
from ui import theme as ui_theme

from ui.common import AMBER, GREEN, MUTED, RED, _settings, _small_label, _visible_rows
from ui.dates import DateScopeRow


class CardColorsDialog(QDialog):
    """One card's own colours (✎ Edit → Colours…). Lists everything the card's charts
    colour; a value this card doesn't set keeps the default colour (Default chart colours,
    or built-in), so nothing changes until you pick. When another card already gives the
    same value a colour, that's offered as a suggestion. Saved with Done editing, for everyone."""

    def __init__(self, win, tab, card, others):
        super().__init__(win)
        self.setWindowTitle(f"Colours · {layout.card_title(tab, card)}")
        self.setMinimumWidth(640)
        self.colors = dict(card.get("colors") or {})
        found = {}                                     # key → (label, section, default colour)
        ctx = blocks.Ctx(None, "All dates", export=False, settings=_settings(win), data=win.data)
        charts.register(win.data)
        with charts.card_colors({}, record=found):     # all dates, so every value shows up
            for b in card["blocks"]:
                try:
                    blocks.render(b, [tab], ctx)
                except Exception:
                    pass
        self.found = found
        # suggestions: the first other card that colours the same value differently
        self.suggest = {}
        for key, (_, _, default) in found.items():
            for title, color in others.get(key, []):
                if color.upper() != (self.colors.get(key) or default or "").upper():
                    self.suggest[key] = (title, color)
                    break

        intro = QLabel("Click a colour to change it for <b>this card only</b>. Anything you don't "
                       "change keeps its default colour, so the card looks the same until you pick. "
                       "Saved for everyone when you click <b>Done editing</b>.")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self.swatches, self.resets, self.hints, self.uses = {}, {}, {}, {}
        i = 0
        sections = list(dict.fromkeys(sec for _, sec, _ in found.values()))
        for sec in sections:
            head = _small_label(sec.upper(), "#888885", 10)
            head.setStyleSheet("color:#888885; font-size:10px; font-weight:bold; margin-top:8px;")
            grid.addWidget(head, i, 0, 1, 5)
            i += 1
            for key, (label, s_, _) in found.items():
                if s_ != sec:
                    continue
                sw = QPushButton()
                sw.setFixedSize(46, 26)
                sw.setCursor(Qt.PointingHandCursor)
                sw.clicked.connect(lambda _, k=key: self._pick(k))
                name = QLabel(label)
                name.setStyleSheet("font-size:13px;")
                hint = _small_label("", MUTED)
                use = None
                if key in self.suggest:
                    title, color = self.suggest[key]
                    use = QPushButton(f"Use colour from {title}")
                    use.setObjectName("link")
                    pm = QPixmap(12, 12)
                    pm.fill(QColor(color))
                    use.setIcon(QIcon(pm))
                    use.setToolTip(f"{color.upper()}: what {title} uses for {label}")
                    use.clicked.connect(lambda _, k=key, c=color: self._set(k, c))
                reset = QPushButton("Reset")
                reset.setObjectName("link")
                reset.setToolTip("Back to the default colour")
                reset.clicked.connect(lambda _, k=key: self._set(k, None))
                self.swatches[key], self.resets[key], self.hints[key], self.uses[key] = sw, reset, hint, use
                grid.addWidget(sw, i, 0)
                grid.addWidget(name, i, 1)
                grid.addWidget(hint, i, 2)
                if use:
                    grid.addWidget(use, i, 3)
                grid.addWidget(reset, i, 4)
                i += 1
        grid.setColumnStretch(2, 1)
        inner = QWidget()
        inner.setLayout(grid)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        scroll.setMinimumHeight(min(34 * i + 10, 460))

        extra = QHBoxLayout()
        if self.suggest:
            use_all = QPushButton(f"Use all suggestions ({len(self.suggest)})")
            use_all.clicked.connect(lambda: [self._set(k, c) for k, (_, c) in self.suggest.items()])
            extra.addWidget(use_all)
        reset_all = QPushButton("Reset all to default")
        reset_all.clicked.connect(self._reset_all)
        extra.addWidget(reset_all)
        extra.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Apply to card")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addWidget(intro)
        if not found:
            root.addWidget(_small_label("This card's charts don't colour anything yet.", MUTED))
        root.addWidget(scroll)
        root.addLayout(extra)
        root.addWidget(buttons)
        self._refresh()

    def color(self, key):
        return self.colors.get(key) or self.found[key][2] or charts.PENDING

    def _refresh(self):
        for key, sw in self.swatches.items():
            c = self.color(key)
            sw.setStyleSheet(f"QPushButton {{ background:{c}; border:1px solid #BDBBB6; border-radius:5px; }}"
                             f"QPushButton:hover {{ border:2px solid #1A1A18; }}")
            sw.setToolTip(f"{c.upper()} — click to change")
            own = key in self.colors
            self.resets[key].setVisible(own)
            self.hints[key].setText("this card" if own else "default")
            if self.uses[key]:
                self.uses[key].setVisible(self.color(key).upper() != self.suggest[key][1].upper())

    def _pick(self, key):
        c = QColorDialog.getColor(QColor(self.color(key)), self, f"Colour for {self.found[key][0]}")
        if c.isValid():
            self._set(key, c.name().upper())

    def _set(self, key, color):
        if color is None or color.upper() == (self.found[key][2] or "").upper():
            self.colors.pop(key, None)                 # same as the default: nothing to keep
        else:
            self.colors[key] = color.upper()
        self._refresh()

    def _reset_all(self):
        for key in list(self.found):
            self.colors.pop(key, None)
        self._refresh()


class CardScopeDialog(QDialog):
    """✎ Edit → 📅 Dates & filters…: a card's own dates and filters, instead of the dashboard's.
    Off by default; turned on, every chart on the card uses them (saved with Done editing)."""

    DATES = [("follow", "Follow the dashboard's dates"), ("all", "All dates"),
             ("days", "The last … days"), ("since", "Since a date"), ("between", "Between two dates")]

    def __init__(self, win, tab, card):
        super().__init__(win)
        self.setWindowTitle(f"Dates & filters · {layout.card_title(tab, card)}")
        self.setMinimumWidth(620)
        self.tab, self.win = tab, win
        own = dict(card.get("own") or {})
        tabs = win.data["tabs"] if layout.is_custom(tab) else [tab]
        self.tabs = tabs
        names = []
        for t in tabs:
            derived = store.derived_columns(t).get(store.STATUS)
            for c in ([derived] if derived else []) + list(t["columns"]):
                n = c["name"].strip()
                if n and n not in names:
                    names.append(n)
        self.names = names

        self.on = QCheckBox("Use this card's own dates and filters (instead of the dashboard's)")
        self.on.setStyleSheet("font-weight:bold;")
        self.on.setChecked(bool(own.get("on")))
        self.dates = DateScopeRow(own.get("dates") or {"mode": "days", "days": 7})

        self.filters_box = QVBoxLayout()
        self.filters_box.setSpacing(4)
        add = QPushButton("+ Add filter")
        add.setObjectName("link")
        add.clicked.connect(lambda: self._add_filter())
        self.latest = QComboBox()
        self.latest.addItem("All rows", "")
        for n in names:
            self.latest.addItem(f"Only the newest row per {n}", n)
        self.latest.setCurrentIndex(max(self.latest.findData(own.get("latest") or ""), 0))
        self.latest.setToolTip("When a test is run again (e.g. after a fix), only its newest row counts, "
                               "so the card shows where each test stands now")

        form = QFormLayout()
        form.setSpacing(8)
        form.addRow("Dates", self.dates)
        fl = QVBoxLayout()
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addLayout(self.filters_box)
        fl.addWidget(add, 0, Qt.AlignLeft)
        form.addRow("Filters", fl)
        form.addRow("Rows", self.latest)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.body = QWidget()
        self.body.setLayout(form)
        self.on.toggled.connect(self.body.setEnabled)
        self.body.setEnabled(self.on.isChecked())
        note = _small_label("Every chart on this card uses these, on the dashboard and in exports, for "
                            "everyone (saved with Done editing). A note next to the card's title says so. "
                            + ("Filters apply to the tabs that have that column." if layout.is_custom(tab)
                               else ""), MUTED)
        note.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Apply to card")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addWidget(self.on)
        root.addWidget(self.body)
        root.addWidget(note)
        root.addWidget(buttons)
        for f in own.get("filters") or []:
            if f and f[0]:
                self._add_filter(*(list(f) + ["", ""])[:3])

    def _values(self, name):
        out = []
        for t in self.tabs:
            col = blocks.own_column(t, name)
            if col is None:
                continue
            for r in _visible_rows(t):
                v = store.value_of(t, r, col).strip()
                if v and v not in out:
                    out.append(v)
        return sorted(out, key=str.lower)[:300]

    def _add_filter(self, name=None, op="is", value=""):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        c = QComboBox()
        for n in self.names:
            c.addItem(n, n)
        c.setCurrentIndex(max(c.findData(name), 0))
        o = QComboBox()
        for k, label in blocks.OWN_OPS:
            o.addItem(label, k)
        o.setCurrentIndex(max(o.findData(op), 0))
        v = QComboBox()
        v.setEditable(True)
        v.setMinimumWidth(160)
        def fill(*_):
            keep = v.currentText()
            v.clear()
            v.addItems(self._values(c.currentData()))
            v.setCurrentText(keep or value)
        fill()
        c.currentIndexChanged.connect(lambda *_: (v.setCurrentText(""), fill()))
        o.currentIndexChanged.connect(lambda *_: v.setVisible(o.currentData() not in ("is empty", "is not empty")))
        v.setVisible(op not in ("is empty", "is not empty"))
        x = QToolButton()
        x.setText("✕")
        x.setToolTip("Remove this filter")
        x.clicked.connect(lambda: (row.hide(), row.setParent(None), row.deleteLater()))
        for w_ in (c, o, v, x):
            h.addWidget(w_, 1 if w_ is v else 0)
        row.parts = (c, o, v)
        self.filters_box.addWidget(row)

    def result(self):
        filters = []
        for i in range(self.filters_box.count()):
            row = self.filters_box.itemAt(i).widget()
            if row is None or not hasattr(row, "parts"):
                continue
            c, o, v = row.parts
            filters.append([c.currentData(), o.currentData(), v.currentText().strip()])
        return {"on": self.on.isChecked(), "dates": self.dates.value(), "filters": filters,
                "latest": self.latest.currentData() or ""}


def default_spec(tab, data=None):
    """What the Add chart form starts with for a tab."""
    if layout.is_custom(tab):                  # a custom card: start from the first sheet tab
        real = next((t for t in (data or {}).get("tabs", []) if t["columns"]), None)
        return default_spec(real) if real else {"source": "runs", "group": "status", "show": "pie",
                                                 "dates": "follow"}
    short = blocks.short_name(tab["title"])
    if store.is_run_tab(tab):
        reason = next((c["name"].strip() for c in tab["columns"] if store.wants_pie(c)
                       and not store.is_workflow(c)), "status")
        return {"source": "issues", "trackers": [short], "only_failed": True, "group": reason,
                "show": "pie", "dates": "follow"}
    if store.is_bug_tab(tab):
        return {"source": "bugs", "group": "status", "show": "pie", "dates": "ignore"}
    st = store.status_column(tab)
    return {"source": "tab:" + tab["title"], "group": st["name"].strip() if st else tab["columns"][0]["name"],
            "show": "pie", "dates": "follow"}

def spec_from_block(tab, b):
    """The Add chart form's settings for one of the app's own charts (pie, bars, count,
    per day), so it can be edited as a query. None for charts that aren't counts."""
    if b["type"] not in ("pie", "bars", "count", "days"):
        return None
    col = layout.find_column(tab, b.get("column"))
    run = store.is_run_tab(tab)
    status_name = "status" if run else (store.status_column(tab) or {}).get("name", "status").strip()
    name = (status_name if b.get("column") == layout.STATUS_REF else
            "platform" if b.get("column") == layout.PLATFORM_REF else (col["name"].strip() if col else None))
    if run:
        spec = {"source": "issues" if b.get("count") == "issues" else "runs",
                "trackers": [blocks.short_name(tab["title"])], "dates": "follow"}
    else:
        spec = {"source": "tab:" + tab["title"], "dates": "follow"}
    if b["type"] == "pie":
        spec.update(show="pie", group=name)
    elif b["type"] == "bars":
        spec.update(show="bars", group=name, series=status_name)
    elif b["type"] == "count":
        spec.update(show="bars", group=name)
    else:
        spec.update(show="days", series=status_name)
    return spec


class AddChartDialog(QDialog):
    """Add or change a chart: the Simple form writes the SQL for you, or write your own.
    The preview runs the query live, in the dashboard's dates."""

    SHOW = chartquery.SHOW

    DATE_CHOICES = {"bugs": [("created", "Created in the dashboard dates"),
                             ("done", "Done in the dashboard dates"), ("ignore", "All dates")],
                    None: [("follow", "Follow the dashboard dates"), ("ignore", "All dates")]}

    def __init__(self, win, tab, block=None):
        super().__init__(win)
        self.win, self.tab = win, tab
        self.setWindowTitle(("Edit chart" if block else "Add chart") + " — "
                            + ("custom card" if layout.is_custom(tab) else tab["title"]))
        self.db = sqldata.for_context(win.data, win.dashboard.range)
        self.block = dict(block) if block else {"id": layout.new_id(), "type": "sql", "dash": True,
                                                  "export": True, "new_row": False, "size": 1}
        spec = (block or {}).get("simple") if block else None
        if block and block.get("type") != "sql":
            spec = spec_from_block(tab, block)
        if block is None:
            spec = default_spec(tab, win.data)
        self.hand_written = spec is None
        spec = spec or default_spec(tab, win.data)
        self._loading = True

        # ── Simple ──
        self.src = QComboBox()
        for key, label in chartquery.sources(self.db):
            self.src.addItem(label, key)
        self.trackers = {}
        tr_row = QHBoxLayout()
        for t in self.win.data["tabs"]:
            if store.is_run_tab(t):
                box = QCheckBox(blocks.short_name(t["title"]))
                box.toggled.connect(self._changed)
                self.trackers[blocks.short_name(t["title"])] = box
                tr_row.addWidget(box)
        self.only_failed = QCheckBox("Only failed runs")
        self.only_failed.toggled.connect(self._changed)
        tr_row.addWidget(self.only_failed)
        tr_row.addStretch(1)
        self.tr_box = QWidget()
        self.tr_box.setLayout(tr_row)
        tr_row.setContentsMargins(0, 0, 0, 0)
        self.product = QComboBox()
        for v in ("Both", "VitalOne", "Viking"):
            self.product.addItem(v, v)
        self.group = QComboBox()
        self.series = QComboBox()
        self.dates = QComboBox()
        self.cols = QListWidget()
        self.cols.setMaximumHeight(130)
        self.filters_box = QVBoxLayout()
        self.filters_box.setSpacing(4)
        add_filter = QPushButton("+ Add filter")
        add_filter.setObjectName("link")
        add_filter.clicked.connect(lambda: self._add_filter())
        filters = QVBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.addLayout(self.filters_box)
        filters.addWidget(add_filter, 0, Qt.AlignLeft)
        self.filters_w = QWidget()
        self.filters_w.setLayout(filters)

        self.form = QFormLayout()
        self.form.setSpacing(8)
        self.form.addRow("Count", self.src)
        self.form.addRow("From", self.tr_box)
        self.form.addRow("Product", self.product)
        self.form.addRow("Group by", self.group)
        self.form.addRow("Split by", self.series)
        self.form.addRow("Columns", self.cols)
        self.form.addRow("Only where", self.filters_w)
        self.show_blanks = QCheckBox("Show blanks, as")
        self.show_blanks.setToolTip("Count rows where this column is empty, under the name you type")
        self.blank_name = QLineEdit()
        self.blank_name.setMaximumWidth(220)
        self.show_blanks.toggled.connect(self._changed)
        self.show_blanks.toggled.connect(lambda on: self.blank_name.setEnabled(on))
        self.blank_name.textChanged.connect(self._changed)
        blanks = QHBoxLayout()
        blanks.setContentsMargins(0, 0, 0, 0)
        blanks.addWidget(self.show_blanks)
        blanks.addWidget(self.blank_name)
        blanks.addStretch(1)
        self.blanks_w = QWidget()
        self.blanks_w.setLayout(blanks)
        self.form.addRow("Blanks", self.blanks_w)
        self.form.addRow("Dates", self.dates)
        simple = QWidget()
        simple.setLayout(self.form)

        # ── SQL ──
        self.sql = QPlainTextEdit()
        mono = QFont("Menlo")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSize(12)
        self.sql.setFont(mono)
        self.sql.setTabChangesFocus(True)
        self.sql.textChanged.connect(self._sql_typed)
        self.hand_note = QLabel()
        self.hand_note.setWordWrap(True)
        self.hand_note.setStyleSheet(f"color:{AMBER}; font-size:11px;")
        back = QPushButton("Use the Simple form again")
        back.setObjectName("link")
        back.clicked.connect(self._back_to_simple)
        hint = _small_label("Tables: one per tab, by name (e.g. \"Hardware Support Tickets\").  Views: runs, "
                            "issues, all_issues, resolutions, bugs.  :start and :end are the dashboard's "
                            "dates.  Add GROUP_CONCAT(_tab || ':' || _row) AS _rows to make slices "
                            "clickable.", MUTED)
        hint.setWordWrap(True)
        tables = QPushButton("Tables and columns…")
        tables.setObjectName("link")
        tables.clicked.connect(self._show_schema)
        sql_l = QVBoxLayout()
        sql_l.addWidget(self.sql, 1)
        sql_note = QHBoxLayout()
        sql_note.addWidget(self.hand_note, 1)
        sql_note.addWidget(back)
        sql_l.addLayout(sql_note)
        sql_l.addWidget(hint)
        sql_l.addWidget(tables, 0, Qt.AlignLeft)
        sql_w = QWidget()
        sql_w.setLayout(sql_l)
        self.back_btn = back

        self.modes = QTabWidget()
        self.modes.setTabBar(ui_theme.segmented_tab_bar())
        self.modes.addTab(simple, "Simple")
        self.modes.addTab(sql_w, "SQL")

        # ── shared ──
        self.show_btns = {}
        show_row = QHBoxLayout()
        show_row.setSpacing(4)
        for key, label in self.SHOW:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet("QPushButton:checked { background:#E1F5EE; border-color:#1D9E75; color:#0F6E56; }")
            btn.clicked.connect(lambda _, k=key: self._set_show(k))
            self.show_btns[key] = btn
            show_row.addWidget(btn)
        show_row.addStretch(1)
        self.title = QLineEdit(self.block.get("title", ""))
        self.title.textChanged.connect(self._changed)
        self.on_dash = QCheckBox("Show on the dashboard")
        self.on_dash.setChecked(self.block.get("dash", True))
        self.on_export = QCheckBox("In export")
        self.on_export.setChecked(self.block.get("export", True))
        common = QFormLayout()
        common.setSpacing(8)
        common.addRow("Show as", show_row)
        common.addRow("Title", self.title)
        places = QHBoxLayout()
        places.addWidget(self.on_dash)
        places.addWidget(self.on_export)
        places.addStretch(1)
        common.addRow("", places)

        left = QVBoxLayout()
        left.addWidget(self.modes, 1)
        left.addLayout(common)

        # ── preview ──
        self.pv_chart = QScrollArea()
        self.pv_chart.setWidgetResizable(True)
        self.pv_chart.setFrameShape(QFrame.NoFrame)
        self.pv_chart.setMinimumHeight(240)
        self.pv_table = QTableWidget()
        self.pv_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pv_table.verticalHeader().hide()
        self.pv_table.setMaximumHeight(190)
        self.pv_status = _small_label("", MUTED)
        right = QVBoxLayout()
        right.addWidget(_small_label(f"LIVE PREVIEW · {win.dashboard.range_text.upper()}", "#888885", 10))
        right.addWidget(self.pv_chart, 1)
        right.addWidget(self.pv_table)
        right.addWidget(self.pv_status)
        pv = QFrame()
        pv.setObjectName("card")
        pv.setLayout(right)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addLayout(left, 11)
        body.addWidget(pv, 10)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        ok = buttons.addButton("Save chart" if block else "Add chart", QDialogButtonBox.AcceptRole)
        ok.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addLayout(body, 1)
        root.addWidget(buttons)
        self.resize(1160, 720)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._preview)
        for w in (self.src, self.product, self.group, self.series, self.dates):
            w.currentIndexChanged.connect(self._changed)
        self.src.currentIndexChanged.connect(self._source_changed)
        self.cols.itemChanged.connect(self._changed)

        self._load(spec, block)
        self._loading = False
        if self.hand_written:
            self.modes.setCurrentIndex(1)
        self._changed()

    # ── the Simple form ───────────────────────────────────────────────────────

    def _load(self, spec, block):
        self.show_as = (block or {}).get("show") or spec.get("show", "pie")
        self.src.setCurrentIndex(max(self.src.findData(spec.get("source")), 0))
        self._fill_columns()
        for name, box in self.trackers.items():
            box.setChecked(name in (spec.get("trackers") or []) or not spec.get("trackers"))
        self.only_failed.setChecked(bool(spec.get("only_failed")))
        self.product.setCurrentIndex(max(self.product.findData(spec.get("product") or "Both"), 0))
        self.group.setCurrentIndex(max(self.group.findData(spec.get("group")), 0))
        self.series.setCurrentIndex(max(self.series.findData(spec.get("series")), 0))
        self.dates.setCurrentIndex(max(self.dates.findData(spec.get("dates", "follow")), 0))
        chosen = spec.get("columns") or []
        for k in range(self.cols.count()):
            it = self.cols.item(k)
            it.setCheckState(Qt.Checked if (it.data(Qt.UserRole) in chosen or (not chosen and k < 5))
                             else Qt.Unchecked)
        for f in spec.get("filters") or []:
            self._add_filter(*f)
        show_blanks, _ = chartquery.blanks_of(spec)
        self.show_blanks.setChecked(show_blanks)
        self.blank_name.setText((spec.get("blank_label") or "").strip())
        self.blank_name.setEnabled(show_blanks)
        if self.hand_written:
            self.sql.setPlainText((block or {}).get("sql", ""))
        self._set_show(self.show_as, quiet=True)

    def _fill_columns(self):
        spec = {"source": self.src.currentData()}
        cols = chartquery.columns_for(self.db, spec)
        for combo, extra in ((self.group, None), (self.series, "Nothing")):
            keep = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            if extra:
                combo.addItem(extra, None)
            for c in cols:
                combo.addItem(chartquery.friendly(c), c)
            combo.setCurrentIndex(max(combo.findData(keep), 0))
            combo.blockSignals(False)
        self.cols.blockSignals(True)
        self.cols.clear()
        for k, c in enumerate(cols):
            it = QListWidgetItem(chartquery.friendly(c))
            it.setData(Qt.UserRole, c)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if k < 5 else Qt.Unchecked)
            self.cols.addItem(it)
        self.cols.blockSignals(False)
        src = self.src.currentData() or ""
        choices = self.DATE_CHOICES["bugs" if src == "bugs" else None]
        if src.startswith("tab:") and not chartquery.date_columns(self.db, spec):
            choices = [("ignore", "All dates (this tab has no date column)")]
        keep = self.dates.currentData()
        self.dates.blockSignals(True)
        self.dates.clear()
        for v, label in choices:
            self.dates.addItem(label, v)
        self.dates.setCurrentIndex(max(self.dates.findData(keep), 0))
        self.dates.blockSignals(False)
        self._columns = cols

    def _source_changed(self, *_):
        if self._loading:
            return
        self._fill_columns()
        while self.filters_box.count():
            w = self.filters_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._changed()

    def _add_filter(self, col=None, op="is", value=""):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        c = QComboBox()
        for name in getattr(self, "_columns", []):
            c.addItem(chartquery.friendly(name), name)
        c.setCurrentIndex(max(c.findData(col), 0))
        o = QComboBox()
        for k, label in chartquery.OPS:
            o.addItem(label, k)
        o.setCurrentIndex(max(o.findData(op), 0))
        v = QComboBox()
        v.setEditable(True)
        v.setMinimumWidth(140)

        def fill_values(*_):
            keep = v.currentText()
            v.blockSignals(True)
            v.clear()
            try:
                v.addItems([str(x) for x in self.db.distinct(chartquery.table_for(
                    {"source": self.src.currentData(), "dates": "ignore"}), c.currentData())])
            except Exception:
                pass
            v.setCurrentText(keep or value)
            v.blockSignals(False)
        fill_values()
        x = QPushButton("×")
        x.setFixedWidth(30)
        x.clicked.connect(lambda: (row.setParent(None), row.deleteLater(), self._changed()))
        c.currentIndexChanged.connect(fill_values)
        for w in (c, o):
            w.currentIndexChanged.connect(self._changed)
        o.currentIndexChanged.connect(lambda *_: v.setVisible(o.currentData() not in ("is empty", "is not empty")))
        v.currentTextChanged.connect(self._changed)
        for w in (c, o, v, x):
            h.addWidget(w, 1 if w is v else 0)
        v.setVisible(op not in ("is empty", "is not empty"))
        row.parts = (c, o, v)
        self.filters_box.addWidget(row)
        self._changed()

    def spec(self):
        src = self.src.currentData()
        chosen = [n for n, b in self.trackers.items() if b.isChecked()]
        return {
            "source": src,
            "trackers": chosen if len(chosen) < len(self.trackers) else [],
            "only_failed": self.only_failed.isChecked() and src in ("runs", "issues"),
            "product": self.product.currentData() if src == "bugs" else None,
            "group": self.group.currentData(),
            "series": self.series.currentData(),
            "columns": [self.cols.item(k).data(Qt.UserRole) for k in range(self.cols.count())
                        if self.cols.item(k).checkState() == Qt.Checked],
            "filters": [[w.parts[0].currentData(), w.parts[1].currentData(), w.parts[2].currentText()]
                        for w in (self.filters_box.itemAt(k).widget() for k in range(self.filters_box.count()))
                        if w is not None and hasattr(w, "parts")],
            "dates": self.dates.currentData() or "follow",
            "show": self.show_as,
            "show_blanks": self.show_blanks.isChecked(),
            "blank_label": self.blank_name.text().strip(),
        }

    def _visible_fields(self):
        src = self.src.currentData() or ""
        show = {self.tr_box: src in ("runs", "issues", "resolutions") and len(self.trackers) > 0,
                self.product: src == "bugs",
                self.group: self.show_as in ("pie", "bars"),
                self.series: self.show_as in ("bars", "days"),
                self.cols: self.show_as == "table",
                self.blanks_w: self.show_as != "table"}
        for w, on in show.items():
            w.setVisible(on)
            lbl = self.form.labelForField(w)
            if lbl:
                lbl.setVisible(on)
        self.only_failed.setVisible(src in ("runs", "issues"))

    def _set_show(self, key, quiet=False):
        self.show_as = key
        for k, b in self.show_btns.items():
            b.setChecked(k == key)
        self._visible_fields()
        if not quiet:
            self._changed()

    # ── SQL ───────────────────────────────────────────────────────────────────

    def _sql_typed(self):
        if self._loading or getattr(self, "_writing", False):
            return
        self.hand_written = True
        self._changed()

    def _back_to_simple(self):
        self.hand_written = False
        self.modes.setCurrentIndex(0)
        self._changed()

    def _show_schema(self):
        lines = []
        for name in list(self.db.views) + self.db.tables:
            cols = [c for c in self.db.columns_of(name) if c not in ("_tab", "_row")]
            lines.append(f"{sqldata.ident(name)}\n    " + ", ".join(sqldata.ident(c) if not
                         re.fullmatch(r"[a-z_]+", c) else c for c in cols))
        dlg = QDialog(self)
        dlg.setWindowTitle("Tables and columns")
        text = QPlainTextEdit("\n\n".join(lines))
        text.setReadOnly(True)
        text.setFont(self.sql.font())
        QVBoxLayout(dlg).addWidget(text)
        dlg.resize(760, 560)
        dlg.exec_()

    # ── preview ───────────────────────────────────────────────────────────────

    def _changed(self, *_):
        if self._loading:
            return
        self._visible_fields()
        spec = self.spec()
        if not self.hand_written:
            self._writing = True
            try:
                self.sql.setPlainText(chartquery.to_sql(spec, self.db))
            except Exception as exc:
                self.sql.setPlainText(f"-- couldn't write the query: {exc}")
            self._writing = False
        self.hand_note.setText("Written by hand: the Simple form won't change it." if self.hand_written else "")
        self.back_btn.setVisible(self.hand_written)
        self.title.setPlaceholderText(chartquery.default_title(spec) if not self.hand_written else "Query")
        self.blank_name.setPlaceholderText(chartquery.suggested_blank_name(
            spec.get("series") if self.show_as == "days" else spec.get("group")))
        self.timer.start(250)

    def result_block(self):
        spec = self.spec()
        b = dict(self.block)
        b.update(type="sql", sql=self.sql.toPlainText(), show=self.show_as,
                 simple=None if self.hand_written else spec,
                 title=self.title.text().strip() or self.title.placeholderText(),
                 dash=self.on_dash.isChecked(), export=self.on_export.isChecked())
        if not self.hand_written:
            b["unit"] = chartquery.unit_for(spec)
            b["blank_label"] = chartquery.blanks_of(spec)[1]
            b["color_by"] = spec.get("series") if self.show_as in ("bars", "days") and spec.get("series") \
                else spec.get("group")
        for k in ("column", "count", "colors", "which", "columns", "hide_zero"):
            b.pop(k, None)
        return b

    def _preview(self):
        b = self.result_block()
        ctx = blocks.Ctx(self.win.dashboard.range, self.win.dashboard.range_text, settings=_settings(self.win),
                         data=self.win.data)
        try:
            _, cols, rows, ms = blocks.run_query(b, ctx)
        except Exception as exc:
            self.pv_status.setText(f"✗ {exc}")
            self.pv_status.setStyleSheet(f"color:{RED}; font-size:11px;")
            self.pv_table.clear()
            self.pv_table.setRowCount(0)
            self.pv_chart.setWidget(_small_label("Fix the query to see the chart.", MUTED))
            return
        self.pv_status.setText(f"✓ {len(rows)} row{'s' if len(rows) != 1 else ''} · {ms:.0f} ms")
        self.pv_status.setStyleSheet(f"color:{GREEN}; font-size:11px;")
        vis = [i for i, c in enumerate(cols) if not c.startswith("_")]
        self.pv_table.clear()
        self.pv_table.setColumnCount(len(vis))
        self.pv_table.setHorizontalHeaderLabels([cols[i] for i in vis])
        self.pv_table.setRowCount(min(len(rows), 100))
        for r, row in enumerate(rows[:100]):
            for k, i in enumerate(vis):
                self.pv_table.setItem(r, k, QTableWidgetItem("" if row[i] is None else str(row[i])))
        self.pv_table.resizeColumnsToContents()
        try:
            parts = blocks.render(b, [self.tab], ctx) or []
        except Exception as exc:
            parts = []
            self.pv_status.setText(f"✗ {exc}")
        box = QWidget()
        h = QHBoxLayout(box)
        for p in parts:
            h.addWidget(self.win.dashboard._part(self.tab, p, lambda t: None), 1 if p.wide else 0, Qt.AlignTop)
        if not parts:
            spec = self.spec()
            hidden = not self.hand_written and not spec.get("show_blanks") and spec.get("show") != "table"
            dated = spec.get("dates") not in ("ignore",) and self.win.dashboard.range is not None
            msg = "Nothing to chart" + (f" in {self.win.dashboard.range_text}" if dated else "") + "."
            if hidden:
                msg += " Blank cells are hidden — tick “Show blanks” to count them."
            lbl = _small_label(msg, MUTED)
            lbl.setWordWrap(True)
            h.addWidget(lbl, 1)
        h.addStretch(0 if any(p.wide for p in parts) else 1)
        self.pv_chart.setWidget(box)


def tile_default_spec(tab):
    """What a tile's Simple form starts with: % done, like the built-in tile."""
    done = [["status_class", "is", "done"]]
    if store.is_run_tab(tab):
        return {"source": "runs", "trackers": [blocks.short_name(tab["title"])], "show": "stat_pct",
                "dates": "follow", "filters": done}
    if store.is_bug_tab(tab):
        return {"source": "bugs", "show": "stat_pct", "dates": "ignore", "filters": done}
    return {"source": "tab:" + tab["title"], "show": "stat", "dates": "follow", "filters": []}


class TileDialog(AddChartDialog):
    """Change what a dashboard tile's big number shows: the same Simple form / SQL as charts.
    "Percent of all" shows matching / all; "Number" a count. A hand-written query shows its
    first row: n, total → a percent; one value → as is; a second value → the small text."""

    SHOW = chartquery.STAT_SHOW

    def __init__(self, win, tab, tile=None):
        tile = tile or {}
        spec = tile.get("simple")
        if not tile.get("sql"):
            spec = tile_default_spec(tab)
        block = {"id": "tile", "type": "sql", "sql": tile.get("sql", ""), "simple": spec,
                 "show": tile.get("show") or (spec or {}).get("show", "stat_pct"),
                 "title": tile.get("label", "")}
        self.reset_tile = False
        super().__init__(win, tab, block)
        self.setWindowTitle(f"Edit tile — {tab['title']}")
        self.on_dash.hide()
        self.on_export.hide()
        for lay_ in self.findChildren(QFormLayout):
            lbl = lay_.labelForField(self.title)
            if lbl:
                lbl.setText("Label")
        self.title.setToolTip("The small text under the number, e.g. “done” → “14 of 91 done”")
        box = self.findChildren(QDialogButtonBox)[-1]
        for b in box.buttons():
            if box.buttonRole(b) == QDialogButtonBox.AcceptRole:
                b.setText("Save tile")
        default = box.addButton("Use the built-in tile", QDialogButtonBox.ResetRole)
        default.setToolTip("Go back to the tile's own % done")
        default.clicked.connect(self._use_default)
        self.resize(1000, 640)

    def _use_default(self):
        self.reset_tile = True
        self.accept()

    def _fill_columns(self):
        super()._fill_columns()
        table = chartquery.table_for({"source": self.src.currentData(), "dates": "ignore"})
        try:
            if "status_class" in self.db.columns_of(table) and "status_class" not in self._columns:
                self._columns = self._columns + ["status_class"]     # done / active / blocked…
        except Exception:
            pass

    def _visible_fields(self):
        super()._visible_fields()
        split = self.show_as == "stat_split"
        for w in (self.group, self.blanks_w):     # Breakdown: group by a column, like a pie
            w.setVisible(split)
            lbl = self.form.labelForField(w)
            if lbl:
                lbl.setVisible(split)

    def _default_label(self):
        if self.hand_written or self.show_as == "stat_split":
            return ""
        return chartquery.unit_for(self.spec())

    def _changed(self, *_):
        super()._changed()
        if not self._loading:
            self.title.setPlaceholderText(self._default_label() or "Label (optional)")

    def result_tile(self):
        if self.reset_tile:
            return None
        return {"sql": self.sql.toPlainText(), "show": self.show_as,
                "simple": None if self.hand_written else self.spec(),
                "label": self.title.text().strip() or self._default_label()}

    def _preview(self):
        t = self.result_tile() or {}
        try:
            stat = self.win.dashboard.tile_stat(t)
            cols, rows, ms = self.db.query(t.get("sql") or "")
        except Exception as exc:
            self.pv_status.setText(f"✗ {exc}")
            self.pv_status.setStyleSheet(f"color:{RED}; font-size:11px;")
            self.pv_chart.setWidget(_small_label("Fix the query to see the tile.", MUTED))
            return
        self.pv_status.setText(f"✓ {len(rows)} row{'s' if len(rows) != 1 else ''} · {ms:.0f} ms")
        self.pv_status.setStyleSheet(f"color:{GREEN}; font-size:11px;")
        self.pv_table.clear()
        vis = [i for i, c in enumerate(cols) if not c.startswith("_")]
        self.pv_table.setColumnCount(len(vis))
        self.pv_table.setHorizontalHeaderLabels([cols[i] for i in vis])
        self.pv_table.setRowCount(min(len(rows), 20))
        for r, row in enumerate(rows[:20]):
            for k, i in enumerate(vis):
                self.pv_table.setItem(r, k, QTableWidgetItem("" if row[i] is None else str(row[i])))
        box = QWidget()
        h = QVBoxLayout(box)
        tile = self.win.dashboard._tile(self.tab, stat=stat)
        h.addWidget(tile, 0, Qt.AlignTop)
        h.addStretch(1)
        self.pv_chart.setWidget(box)


class CardSettingsDialog(QDialog):
    """A card's own settings: title, where it shows, merging, sections."""

    def __init__(self, win, tab, card, lo, in_view=False):
        super().__init__(win)
        self.setWindowTitle("Card settings")
        self.setMinimumWidth(520)
        self.card, self.tab = card, tab
        self.title = QLineEdit(card.get("title", ""))
        self.title.setPlaceholderText(layout.card_title(tab, dict(card, title="")))
        self.dash = QCheckBox("Show on the dashboard")
        self.dash.setChecked(card["dash"])
        self.export = QCheckBox("Include in the export")
        self.export.setChecked(card["export"])
        self.combine = QCheckBox("In the export, merge with the same card from other tabs "
                                 "(e.g. one Error Analysis for VitalOne + Viking)")
        self.combine.setChecked(card["combine"])
        self.split = QComboBox()
        self.split.addItem("Don't split", None)
        for how, label in layout.SPLITS.items():
            if layout.can_split(tab, how):
                self.split.addItem(label, how)
        self.split.setCurrentIndex(max(self.split.findData(card.get("split")), 0))
        form = QFormLayout()
        form.addRow("Title", self.title)
        form.addRow("", self.dash)
        form.addRow("", self.export)
        form.addRow("", self.combine)
        if self.split.count() > 1:
            form.addRow("Sections", self.split)
        self.action = None
        extra = QHBoxLayout()
        custom = layout.is_custom(tab)
        new = QPushButton("+ Another custom card" if custom else "+ New card for this tab")
        new.clicked.connect(lambda: self._done("new"))
        extra.addWidget(new)
        if custom:
            self.combine.hide()
        if card["id"] not in ("main", "analysis") or in_view or custom:
            delete = QPushButton("Remove this card from the view" if in_view else "Delete this card")
            delete.clicked.connect(lambda: self._done("delete"))
            extra.addWidget(delete)
        if not in_view and not custom:
            reset = QPushButton("Reset tab to built-in")
            reset.setToolTip("Go back to the app's own charts for every card of this tab")
            reset.clicked.connect(lambda: self._done("reset"))
            extra.addWidget(reset)
        else:
            self.combine.hide()
        extra.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addLayout(extra)
        root.addWidget(buttons)

    def _done(self, action):
        self.action = action
        self.accept()

    def apply(self):
        self.card.update(title=self.title.text().strip(), dash=self.dash.isChecked(),
                         export=self.export.isChecked(), combine=self.combine.isChecked(),
                         split=self.split.currentData())
