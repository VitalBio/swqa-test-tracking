"""
📤 Export: choosing and arranging sections, then saving the PNG / PDF.
"""

import json, os, re

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QFrame,
    QDialog, QFormLayout, QDialogButtonBox, QFileDialog, QComboBox, QCheckBox, QTabWidget,
    QScrollArea, QDateEdit, QToolButton, QListWidget, QListWidgetItem, QAbstractItemView,
    QInputDialog, QTreeWidget, QTreeWidgetItem, QSplitter, QRadioButton)
from PyQt5.QtCore import Qt, QTimer, QDate, pyqtSignal
from PyQt5.QtGui import QPixmap

from dashboard import blocks
from dashboard import layout
from dashboard import views
from data import store
from export import report as export_report
from export import sections as export_sections
from ui import theme as ui_theme

from ui.common import AMBER, MUTED, _FlowLayout, _settings, _small_label, _visible_rows
from ui.dates import DATE_PRESETS, DateScopeRow, _qdate, range_for, range_text


# ── dashboard ─────────────────────────────────────────────────────────────────

class ArrangePanel(QWidget):
    """The export page's columns, as lists you can drag cards between. Drag the
    dividers to make a column wider or narrower. `changed` fires on every edit."""
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.custom = False
        self._loading = False
        help_ = _small_label("Drag cards between columns and up or down. Drag the dividers between "
                             "columns to change their width. Columns always end flush, so there are "
                             "no gaps.", MUTED)
        help_.setWordWrap(True)
        add = QPushButton("+ Column")
        add.clicked.connect(self._add_column)
        tidy = QPushButton("Remove empty columns")
        tidy.clicked.connect(self._tidy)
        auto = QPushButton("Auto-arrange")
        auto.setToolTip("Let the app arrange the cards (balanced columns, wide page)")
        auto.clicked.connect(self._auto)
        self.page_w = QComboBox()
        for w in (1400, 1800, 2200, 2600, 3000, 3600):
            self.page_w.addItem(f"{w} px wide", w)
        self.page_w.setToolTip("Page width. Wider pages fit more columns side by side.")
        self.page_w.currentIndexChanged.connect(self._edited)
        row = QHBoxLayout()
        for w in (add, tidy, auto):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.page_w)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(12)
        self.splitter.setStyleSheet("QSplitter::handle { background:#CCCCC8; margin:60px 4px; "
                                    "border-radius:2px; } QSplitter::handle:hover { background:#1D9E75; }")
        self.splitter.splitterMoved.connect(self._edited)
        lay_ = QVBoxLayout(self)
        lay_.setContentsMargins(0, 6, 0, 0)
        lay_.addWidget(help_)
        lay_.addLayout(row)
        lay_.addWidget(self.splitter, 1)

    def _new_list(self):
        lst = QListWidget()
        lst.setDragDropMode(QAbstractItemView.DragDrop)
        lst.setDefaultDropAction(Qt.MoveAction)
        lst.setSelectionMode(QAbstractItemView.SingleSelection)
        lst.setWordWrap(True)
        lst.setSpacing(3)
        lst.setMinimumWidth(90)
        lst.setStyleSheet("QListWidget::item { background:#FFFFFF; border:1px solid #E0DDD8; "
                          "border-radius:6px; padding:8px; color:#1A1A18; }"
                          "QListWidget { background:#F0EFEB; }")
        lst.model().rowsInserted.connect(self._edited)
        lst.model().rowsRemoved.connect(self._edited)
        lst.model().rowsMoved.connect(self._edited)
        return lst

    def lists(self):
        return [self.splitter.widget(i) for i in range(self.splitter.count())]

    def _clear(self):
        for lst in self.lists():
            lst.setParent(None)
            lst.deleteLater()

    def load(self, arrangement, titles):
        """Show an arrangement ({"page_width", "columns": [{"share", "cards"}]})."""
        self._loading = True
        self._clear()
        for col in arrangement.get("columns", []):
            lst = self._new_list()
            for key in col.get("cards", []):
                if key in titles:
                    item = QListWidgetItem(titles[key])
                    item.setData(Qt.UserRole, key)
                    lst.addItem(item)
            self.splitter.addWidget(lst)
        shares = [max(float(c.get("share") or 1), 0.05) for c in arrangement.get("columns", [])]
        total = sum(shares) or 1
        self.splitter.setSizes([int(1000 * s / total) for s in shares])
        w = int(arrangement.get("page_width") or 1800)
        i = min(range(self.page_w.count()), key=lambda k: abs(self.page_w.itemData(k) - w))
        self.page_w.setCurrentIndex(i)
        self._loading = False

    def sync(self, titles):
        """Keep a custom arrangement in step with what's ticked: drop unticked cards,
        add newly ticked ones to the shortest column."""
        self._loading = True
        present = set()
        for lst in self.lists():
            for k in reversed(range(lst.count())):
                key = lst.item(k).data(Qt.UserRole)
                if key not in titles:
                    lst.takeItem(k)
                else:
                    lst.item(k).setText(titles[key])
                    present.add(key)
        for key, title in titles.items():
            if key not in present and self.lists():
                lst = min(self.lists(), key=lambda l: l.count())
                item = QListWidgetItem(title)
                item.setData(Qt.UserRole, key)
                lst.addItem(item)
        self._loading = False

    def arrangement(self):
        sizes = self.splitter.sizes()
        total = sum(sizes) or 1
        return {"page_width": self.page_w.currentData(),
                "columns": [{"share": round(s / total, 4),
                             "cards": [lst.item(k).data(Qt.UserRole) for k in range(lst.count())]}
                            for lst, s in zip(self.lists(), sizes)]}

    def _edited(self, *_):
        if self._loading:
            return
        self.custom = True
        self.changed.emit()

    def _add_column(self):
        self.splitter.addWidget(self._new_list())
        n = self.splitter.count()
        self.splitter.setSizes([1000 // n] * n)
        self._edited()

    def _tidy(self):
        for lst in self.lists():
            if lst.count() == 0 and self.splitter.count() > 1:
                lst.setParent(None)
                lst.deleteLater()
        self._edited()

    def _auto(self):
        self.custom = False
        self.changed.emit()


class SectionsPanel(QWidget):
    """The simple export: which products, and which sections (in order) with their options."""
    changed = pyqtSignal()

    def __init__(self, products, data=None):
        super().__init__()
        self.products = products
        self.data = data
        self.sections = export_sections.sections_for(data)
        self.cfg = export_sections.default_config(data)
        self._loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 0)
        root.setSpacing(6)
        prod = QHBoxLayout()
        lbl = QLabel("Products")
        lbl.setStyleSheet("font-weight:bold; font-size:13px;")
        prod.addWidget(lbl)
        self.prod_boxes = {}
        for name in products:
            b = QCheckBox(name)
            b.setChecked(True)
            b.toggled.connect(self._edited)
            self.prod_boxes[name] = b
            prod.addWidget(b)
        prod.addSpacing(10)
        self.side = QRadioButton("Side by Side")
        self.combined = QRadioButton("Combined")
        self.side.setChecked(True)
        self.side.toggled.connect(self._edited)
        prod.addWidget(self.side)
        prod.addWidget(self.combined)
        prod.addStretch(1)
        root.addLayout(prod)
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(0)
        holder = QWidget()
        holder.setLayout(self.list_box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)   # options wrap instead
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)
        self._build()

    def _build(self):
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            w = item.widget()
            if w:                                  # gone now: deleteLater waits for the dialog to close,
                w.hide()                           # which left the old list showing behind the new one
                w.setParent(None)
                w.deleteLater()
        self.rows, self.card_dates = {}, {}
        order = self.cfg["order"]
        for i, sid in enumerate(order):
            name, opts = self.sections[sid]
            box = QFrame()
            box.setObjectName("tile")
            v = QVBoxLayout(box)
            v.setContentsMargins(10, 6, 10, 8)
            v.setSpacing(4)
            head = QHBoxLayout()
            for text, step, enabled in (("↑", -1, i > 0), ("↓", 1, i < len(order) - 1)):
                b = QToolButton()
                b.setText(text)
                b.setEnabled(enabled)
                b.setToolTip("Move up" if step < 0 else "Move down")
                b.setFixedSize(26, 24)
                b.setStyleSheet("QToolButton { padding:0; font-size:12px; }")
                b.clicked.connect(lambda _, s=sid, st=step: self._move(s, st))
                head.addWidget(b)
            on = QCheckBox(name)
            on.setStyleSheet("font-weight:bold; font-size:13px; color:#1A1A18;")
            on.setChecked(bool(self.cfg["on"].get(sid)))
            on.toggled.connect(self._edited)
            head.addWidget(on, 1)
            v.addLayout(head)
            boxes = {}
            if opts:
                flow = _FlowLayout(h=18, v=4)
                flow.setContentsMargins(58, 0, 0, 0)
                for key, label, _ in opts:
                    c = QCheckBox(label)
                    c.setChecked(bool(self.cfg["opts"].get(sid, {}).get(key)))
                    c.toggled.connect(self._edited)
                    boxes[key] = c
                    flow.addWidget(c)
                v.addLayout(flow)
            if sid.startswith(export_sections.CARD):
                tab_, card_ = export_sections.find_card(self.data, sid) if self.data else (None, None)
                own = blocks.own_of(card_) if card_ else None
                if own:                                 # its own dates: keep them, or change them for this export
                    ctx0 = blocks.Ctx(None, "All dates")
                    text = blocks.own_range(own, ctx0)[1]
                    row = DateScopeRow((self.cfg.get("card_dates") or {}).get(sid), card_text=text,
                                       follow_label="The export's dates")
                    row.changed.connect(self._edited)
                    holder_ = QHBoxLayout()
                    holder_.setContentsMargins(58, 0, 0, 0)
                    holder_.addWidget(_small_label("Dates", MUTED))
                    holder_.addWidget(row, 1)
                    v.addLayout(holder_)
                    self.card_dates[sid] = row
                note = _small_label(f"The charts on the {name} dashboard card.", MUTED)
                note.setContentsMargins(58, 0, 0, 0)
                v.addWidget(note)
            if sid == "changelog":
                note = _small_label("The latest change log made in the 📝 Change Log tab.", MUTED)
                note.setContentsMargins(58, 0, 0, 0)
                v.addWidget(note)
            self.rows[sid] = (on, boxes)
            self.list_box.addWidget(box)
        self.list_box.addStretch(1)

    def load(self, cfg):
        self._loading = True
        self.cfg = export_sections.normalized(cfg, self.data)
        for name, b in self.prod_boxes.items():
            b.setChecked(self.cfg["products"].get(name, True))
        (self.side if self.cfg["split"] else self.combined).setChecked(True)
        self._build()
        self._loading = False

    def config(self):
        cfg = export_sections.normalized(self.cfg, self.data)
        cfg["products"] = {n: b.isChecked() for n, b in self.prod_boxes.items()}
        cfg["split"] = self.side.isChecked()
        for sid, (on, boxes) in self.rows.items():
            cfg["on"][sid] = on.isChecked()
            cfg["opts"][sid] = {k: c.isChecked() for k, c in boxes.items()}
        cfg["card_dates"] = {sid: row.value() for sid, row in self.card_dates.items() if row.value()}
        return cfg

    def _edited(self, *_):
        if self._loading:
            return
        self.cfg = self.config()
        self.changed.emit()

    def _move(self, sid, step):
        self.cfg = self.config()
        order = self.cfg["order"]
        i = order.index(sid)
        j = i + step
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
            self._build()
            self.changed.emit()


class ExportDialog(QDialog):
    """Pick the dates, the page style, and which cards and charts go in; saves a PNG
    (or one per card) and a matching PDF. A preview updates as you change things."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Export snapshot")
        saved = win.cfg.get("export") or {}
        self.picks = dict(saved.get("picks") or {})       # only choices that differ from the layouts
        self.layouts = {t["title"]: win.layout_of(t) for t in win.data["tabs"]}

        intro = QLabel("Saves a snapshot for the dates you pick: a <b>PNG</b> for Slack or email and a "
                       "matching <b>PDF</b> where runs, bug keys and notes are clickable. Pick the sections "
                       "and products, or switch Content to Cards for any dashboard card.")
        intro.setWordWrap(True)
        self.preset = QComboBox()
        self.preset.addItems([p for p in DATE_PRESETS])
        self.preset.setCurrentText(saved.get("preset", "Today"))
        self.start, self.end = QDateEdit(QDate.currentDate()), QDateEdit(QDate.currentDate())
        for ed in (self.start, self.end):
            ed.setCalendarPopup(True)
            ed.setDisplayFormat("MMM d, yyyy")
            ed.dateChanged.connect(self._update)
        self.to_lbl = QLabel("to")
        dates = QHBoxLayout()
        dates.addWidget(self.preset)
        dates.addWidget(self.start)
        dates.addWidget(self.to_lbl)
        dates.addWidget(self.end)
        dates.addStretch(1)
        self.preset.currentIndexChanged.connect(self._update)

        self.style = QComboBox()
        for k, label in export_report.STYLES.items():
            self.style.addItem(label, k)
        self.style.setCurrentIndex(max(self.style.findData(saved.get("style", "wide")), 0))
        self.style.setToolTip("Wide: cards in columns — arrange them yourself under “Arrange the page”.\n"
                              "Slack summary: a 16:9 picture with the headline numbers and key charts,\n"
                              "plus the wide page.\n"
                              "One column: every ticked card stacked.\n"
                              "One image per card: a separate PNG for each card.")
        self.style.currentIndexChanged.connect(self._update)

        self.folder = saved.get("folder") or os.path.expanduser("~/Downloads")
        self.folder_lbl = QLabel()
        self.folder_lbl.setMinimumWidth(260)
        pick = QPushButton("Choose folder…")
        pick.clicked.connect(self._pick_folder)
        where = QHBoxLayout()
        where.addWidget(self.folder_lbl, 1)
        where.addWidget(pick)
        self.name_edit = QLineEdit(saved.get("file_name") or "")
        self.name_edit.setPlaceholderText(self.DEFAULT_NAME)
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.setToolTip("The name for the PNG and PDF (no extension). Fill-ins:\n"
                                  "{sheet}  the sheet's title, e.g. v4.20 Test Tracker\n"
                                  "{date}  the day or range, e.g. 2026-11-17 or 2026-11-10 to 2026-11-17\n"
                                  "{profile}  this export profile's name\n"
                                  "Leave it empty for the default.")
        self.name_edit.textChanged.connect(self._update)
        name_row = QHBoxLayout()
        name_row.addWidget(self.name_edit, 1)
        name_row.addWidget(_small_label("{sheet} {date} {profile}", MUTED))

        self.combine_row = QVBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(280)
        self._fill_tree()
        self.tree.itemChanged.connect(self._tree_changed)
        defaults = QPushButton("Back to defaults")
        defaults.setToolTip("Tick exactly what each card's ✎ Customize settings put in the export")
        defaults.clicked.connect(self._defaults)
        tree_head = QHBoxLayout()
        tree_head.addWidget(_small_label("WHAT TO INCLUDE", "#888885", 10))
        tree_head.addStretch(1)
        tree_head.addWidget(defaults)

        self.summary = _small_label("", MUTED)
        self.summary.setWordWrap(True)

        self.profile_note = _small_label("", AMBER)
        self.profile = QComboBox()
        self.profile.setMinimumWidth(180)
        self.profile.setToolTip("Saved export settings: dates, layout, folder, what's ticked, and the arrangement")
        self.profile.currentIndexChanged.connect(self._apply_profile)
        self.save_profile = QPushButton("Save")
        self.save_profile.setToolTip("Save the changes to this profile")
        self.save_profile.clicked.connect(self._save_current)
        save_as = QPushButton("Save as new…")
        save_as.clicked.connect(self._save_as)
        self.delete_profile = QPushButton("Delete")
        self.delete_profile.clicked.connect(self._delete)
        prof_row = QHBoxLayout()
        prof_row.addWidget(self.profile, 1)
        prof_row.addWidget(self.profile_note)
        for b in (self.save_profile, save_as, self.delete_profile):
            prof_row.addWidget(b)

        self.view_box = QComboBox()
        self.view_box.addItem("MAIN", views.MAIN)
        for v in win.all_views():
            self.view_box.addItem(("👥 " if v["shared"] else "") + v["name"], v["id"])
        self.view_box.setCurrentIndex(max(self.view_box.findData(saved.get("view") or win.current_view_id()), 0))
        self.view_box.currentIndexChanged.connect(self._view_changed)

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("Profile", prof_row)
        self.content = QComboBox()
        self.content.addItem("Sections (simple)", "sections")
        self.content.addItem("Cards (advanced)", "cards")
        self.content.setToolTip("Sections: pick End-to-End Runs, Error Analysis, New Bugs… with a few options.\n"
                                "Cards: pick any dashboard card and chart, from MAIN or a view.")
        self.content.setCurrentIndex(max(self.content.findData(saved.get("content", "sections")), 0))
        self.content.currentIndexChanged.connect(self._content_changed)
        form.addRow("Content", self.content)
        self.theme = QComboBox()
        self.theme.addItem("Light", "light")
        self.theme.addItem("Dark", "dark")
        self.theme.setCurrentIndex(max(self.theme.findData(saved.get("theme", "light")), 0))
        self.theme.setToolTip("Light or dark page (Sections)")
        self.theme.currentIndexChanged.connect(self._update)
        form.addRow("View", self.view_box)
        self.view_row_label = form.labelForField(self.view_box)
        form.addRow("Dates", dates)
        layout_row = QHBoxLayout()
        layout_row.addWidget(self.style, 1)
        layout_row.addWidget(_small_label("Theme"))
        layout_row.addWidget(self.theme)
        form.addRow("Layout", layout_row)
        form.addRow("Save to", where)
        form.addRow("File name", name_row)
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(intro)
        left.addLayout(form)
        include = QWidget()
        il = QVBoxLayout(include)
        il.setContentsMargins(0, 6, 0, 0)
        il.addLayout(tree_head)
        il.addWidget(self.tree, 1)
        il.addLayout(self.combine_row)
        self.arrange = ArrangePanel()
        arr = saved.get("arrangement")
        if arr:
            self.arrange.load(arr, {k: k.split("|")[0] for c in arr.get("columns", []) for k in c.get("cards", [])})
            self.arrange.custom = True
        self.arrange.changed.connect(lambda: self.preview_timer.start(300))
        self.arrange.changed.connect(self._profile_state)
        self.side_tabs = QTabWidget()
        self.side_tabs.setTabBar(ui_theme.segmented_tab_bar())
        self.sections = SectionsPanel(export_sections.product_names(win.data), win.data)
        self.sections.load(saved.get("sections") or export_sections.default_config(win.data))
        self.sections.changed.connect(self._update)
        self.side_tabs.addTab(self.sections, "Sections")
        self.side_tabs.addTab(include, "What to include")
        self.side_tabs.addTab(self.arrange, "Arrange the page")
        left.addWidget(self.side_tabs, 1)
        left.addWidget(self.summary)

        self.preview = QLabel("Preparing a preview…")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(f"color:{MUTED}; background:#FFFFFF; border:1px solid #E0DDD8; "
                                   "border-radius:8px;")
        self.preview.setMinimumSize(520, 420)
        self.preview_note = _small_label("", MUTED)
        right = QVBoxLayout()
        right.addWidget(_small_label("PREVIEW", "#888885", 10))
        right.addWidget(self.preview, 1)
        right.addWidget(self.preview_note)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._draw_preview)

        body = QHBoxLayout()
        body.setSpacing(18)
        body.addLayout(left, 1)
        body.addLayout(right, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.go = buttons.addButton("⬇ Export PNG + PDF", QDialogButtonBox.AcceptRole)
        self.go.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.addLayout(body, 1)
        root.addWidget(buttons)
        self.resize(1180, 800)
        self._content_changed(reset=False)
        self._fill_profiles(saved.get("profile", self.DEFAULT_PROFILE))   # last used, as you left it
        self._update()

    # ── profiles ──────────────────────────────────────────────────────────────
    # A profile is a saved set of export settings (dates, layout, folder, what's
    # ticked, the page arrangement). "Default" is the built-in settings and can't be
    # changed; the others are kept on this computer.

    DEFAULT_PROFILE = "Default"

    def _profiles(self):
        return self.win.cfg.setdefault("export_profiles", {})

    def _default_settings(self):
        return {"preset": "Today", "style": "wide", "picks": {}, "arrangement": None,
                "folder": self.folder, "view": views.MAIN, "content": "sections", "theme": "light",
                "file_name": "", "sections": export_sections.default_config(self.win.data)}

    def _content_changed(self, *_, reset=True):
        simple = self.content.currentData() == "sections"
        self.side_tabs.setTabEnabled(0, simple)
        self.side_tabs.setTabEnabled(1, not simple)
        if self.side_tabs.currentIndex() in (0, 1):
            self.side_tabs.setCurrentIndex(0 if simple else 1)
        self.view_box.setEnabled(not simple)
        self.theme.setEnabled(simple)
        self.view_box.setToolTip("" if not simple else "Views apply to Cards (advanced)")
        if reset and self.arrange.custom:
            self.arrange.custom = False               # a different set of cards: arrange afresh
        if reset:
            self._update()

    def current_settings(self):
        return {"preset": self.preset.currentText(), "style": self.style.currentData(),
                "content": self.content.currentData(), "sections": self.sections.config(),
                "theme": self.theme.currentData(),
                "view": self.view_box.currentData(),
                "picks": dict(self.picks), "folder": self.folder,
                "file_name": self.name_edit.text().strip(),
                "arrangement": self.arrange.arrangement() if self.arrange.custom else None}

    def _profile_settings(self, name):
        if name == self.DEFAULT_PROFILE:
            return self._default_settings()
        return self._profiles().get(name)

    def _fill_profiles(self, select):
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.addItem(self.DEFAULT_PROFILE)
        for name in sorted(self._profiles(), key=str.lower):
            self.profile.addItem(name)
        i = self.profile.findText(select)
        self.profile.setCurrentIndex(max(i, 0))
        self.profile.blockSignals(False)
        self._profile_state()

    def _apply_profile(self, *_):
        p = self._profile_settings(self.profile.currentText())
        if not p:
            return
        self._applying = True
        self.preset.setCurrentText(p.get("preset", "Today"))
        self.view_box.blockSignals(True)
        self.view_box.setCurrentIndex(max(self.view_box.findData(p.get("view") or views.MAIN), 0))
        self.view_box.blockSignals(False)
        self.style.setCurrentIndex(max(self.style.findData(p.get("style", "wide")), 0))
        self.content.blockSignals(True)
        self.content.setCurrentIndex(max(self.content.findData(p.get("content", "cards" if p.get("picks")
                                                                         else "sections")), 0))
        self.content.blockSignals(False)
        self.sections.load(p.get("sections") or export_sections.default_config(self.win.data))
        self.theme.setCurrentIndex(max(self.theme.findData(p.get("theme", "light")), 0))
        self._content_changed(reset=False)
        self.folder = p.get("folder") or self.folder
        self.name_edit.setText(p.get("file_name") or "")
        self.picks = dict(p.get("picks") or {})
        self._fill_tree()
        arr = p.get("arrangement")
        if arr:
            self.arrange.load(arr, {k: k.split("|")[0] for c in arr.get("columns", []) for k in c.get("cards", [])})
            self.arrange.custom = True
        else:
            self.arrange.custom = False
        self._applying = False
        self._update()

    def _same(self, a, b):
        keys = ("preset", "style", "picks", "arrangement", "folder", "view", "content", "sections", "theme",
                "file_name")
        keys = [k for k in keys if k in (b or {}) or k == "file_name"]   # older profiles: an option they
        norm = lambda s: json.dumps({k: (s or {}).get(k, "" if k == "file_name" else None)  # lack doesn't count
                                     for k in keys}, sort_keys=True)
        return norm(a) == norm(b)

    def _profile_state(self, *_):
        """Show whether the settings still match the chosen profile."""
        if getattr(self, "_applying", False) or not hasattr(self, "profile"):
            return
        name = self.profile.currentText()
        cur, saved = self.current_settings(), self._profile_settings(name)
        if name == self.DEFAULT_PROFILE:          # Default doesn't care which folder you use
            cur = dict(cur, folder=None)
            saved = dict(saved, folder=None)
        edited = not self._same(cur, saved)
        self.profile_note.setText("● edited" if edited else "")
        self.profile_note.setToolTip("These settings differ from the profile. Save them to the profile, "
                                     "or save as a new one." if edited else "")
        self.save_profile.setEnabled(edited and name != self.DEFAULT_PROFILE)
        self.delete_profile.setEnabled(name != self.DEFAULT_PROFILE)

    def _save_as(self):
        name, ok = QInputDialog.getText(self, "Save export profile",
                                        "Profile name (e.g. “EOD – Slack”, “Weekly bugs”):",
                                        text="" if self.profile.currentText() == self.DEFAULT_PROFILE
                                        else self.profile.currentText())
        name = (name or "").strip()
        if not ok or not name:
            return
        if name.lower() == self.DEFAULT_PROFILE.lower():
            QMessageBox.information(self, "Name taken", "“Default” is the built-in profile. Pick another name.")
            return
        if name in self._profiles() and QMessageBox.question(
                self, "Replace profile", f"Replace the “{name}” profile with these settings?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self._profiles()[name] = self.current_settings()
        store.save_config(self.win.cfg)
        self._fill_profiles(name)

    def _save_current(self):
        name = self.profile.currentText()
        if name != self.DEFAULT_PROFILE:
            self._profiles()[name] = self.current_settings()
            store.save_config(self.win.cfg)
            self._profile_state()

    def _delete(self):
        name = self.profile.currentText()
        if name == self.DEFAULT_PROFILE:
            return
        if QMessageBox.question(self, "Delete profile", f"Delete the “{name}” export profile?",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self._profiles().pop(name, None)
            store.save_config(self.win.cfg)
            self._fill_profiles(self.DEFAULT_PROFILE)
            self._apply_profile()

    # ── what to include ───────────────────────────────────────────────────────

    def view_entries(self):
        """The chosen view's cards, or None for MAIN."""
        vid = self.view_box.currentData() if hasattr(self, "view_box") else views.MAIN
        view = next((v for v in self.win.all_views() if v["id"] == vid), None)
        return views.entries(view, self.win.data, self.win.layout_of) if view else None

    def _tree_card(self, tab, card):
        ckey = export_report.card_key(tab, card)
        item = QTreeWidgetItem([layout.card_title(tab, card)])
        item.setData(0, Qt.UserRole, (ckey, card["export"]))
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Checked if self.picks.get(ckey, card["export"]) else Qt.Unchecked)
        f = item.font(0)
        f.setBold(True)
        item.setFont(0, f)
        for b in card["blocks"]:
            bkey = export_report.block_key(tab, card, b)
            child = QTreeWidgetItem([b.get("title") or layout.auto_title(tab, b)])
            child.setToolTip(0, layout.describe(tab, b))
            child.setData(0, Qt.UserRole, (bkey, b["export"]))
            child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
            child.setCheckState(0, Qt.Checked if self.picks.get(bkey, b["export"]) else Qt.Unchecked)
            item.addChild(child)
        self.tree.addTopLevelItem(item)
        item.setExpanded(item.checkState(0) == Qt.Checked)
        return item

    def _view_changed(self, *_):
        self._fill_tree()
        if self.arrange.custom:
            self.arrange.custom = False               # a different set of cards: arrange afresh
        self._update()

    def _fill_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        merged, groups = {}, {}
        entries = self.view_entries()
        if entries is not None:
            for tab, card, lo, e in entries:
                self._tree_card(tab, card)
            self.tree.blockSignals(False)
            while self.combine_row.count():
                w = self.combine_row.takeAt(0).widget()
                if w:
                    w.deleteLater()
            return
        for tab in self.win.data["tabs"]:
            if not tab["rows"]:
                continue
            for card in self.layouts[tab["title"]]["cards"]:
                combine = export_report.combines(card, self.picks)
                if card["combine"]:
                    groups.setdefault(card["id"], []).append((tab, card))
                if combine and card["id"] in merged:
                    item, tabs = merged[card["id"]]
                    tabs.append(tab)
                    item.setText(0, export_report.combined_title(card, tabs))
                    continue
                item = self._tree_card(tab, card)
                if combine:
                    merged[card["id"]] = (item, [tab])
        self.tree.blockSignals(False)
        # one checkbox per kind of card that can be merged across tabs (e.g. Error Analysis)
        while self.combine_row.count():
            w = self.combine_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        for cid, members in groups.items():
            if len(members) < 2:
                continue
            tabs = [t for t, _ in members]
            card = members[0][1]
            names = " + ".join(blocks.short_name(t["title"]) for t in tabs)
            what = "Error Analysis" if cid == "analysis" else layout.card_title(tabs[0], card)
            box = QCheckBox(f"One combined {what} ({names})")
            box.setToolTip(f"Untick to export a separate {what} card for each of {names}")
            box.setChecked(export_report.combines(card, self.picks))
            box.toggled.connect(lambda on, c=card: self._set_combine(c, on))
            self.combine_row.addWidget(box)

    def _set_combine(self, card, on):
        key = export_report.COMBINE_PREFIX + card["id"]
        if on == card["combine"]:
            self.picks.pop(key, None)
        else:
            self.picks[key] = on
        QTimer.singleShot(0, self._fill_tree)       # not while the checkbox is still signalling
        self._update()

    def _tree_changed(self, item, _col):
        key, default = item.data(0, Qt.UserRole)
        on = item.checkState(0) == Qt.Checked
        if on == default:
            self.picks.pop(key, None)
        else:
            self.picks[key] = on
        if item.parent() is None and on:
            item.setExpanded(True)
        self._update()

    def _defaults(self):
        self.picks = {}
        self._fill_tree()
        self._update()

    # ── dates, files ──────────────────────────────────────────────────────────

    def rng(self):
        return range_for(self.preset.currentText(), _qdate(self.start), _qdate(self.end))

    def label(self):
        """e.g. "Today (Sep 30)", "Last 7 days (Sep 24 – Sep 30)", "Sep 24 – Sep 25"."""
        name, rng = self.preset.currentText(), self.rng()
        if rng is None or name in ("On a date…", "Date range…"):
            return range_text(rng)
        return f"{name} ({range_text(rng).replace(f'{rng[0]:%a} ', '')})"

    DEFAULT_NAME = "{sheet} snapshot {date}"

    def base_name(self):
        """The export's file name (no extension), from the File name pattern."""
        rng = self.rng()
        when = "all dates" if rng is None else (f"{rng[0]:%Y-%m-%d}" if rng[0] == rng[1]
                                                else f"{rng[0]:%Y-%m-%d} to {rng[1]:%Y-%m-%d}")
        pattern = self.name_edit.text().strip() if hasattr(self, "name_edit") else ""
        profile = self.profile.currentText() if hasattr(self, "profile") else ""
        fills = {"sheet": self.win.data["title"], "date": when, "profile": profile}
        name = re.sub(r"\{(\w+)\}", lambda m: fills.get(m.group(1).lower(), m.group(0)),
                      pattern or self.DEFAULT_NAME)
        name = re.sub(r'[\\/:*?"<>|]', "-", name).strip(" .")
        name = re.sub(r"\.(png|pdf)$", "", name, flags=re.I)
        return name or re.sub(r'[\\/:*?"<>|]', "-", f"{self.win.data['title']} snapshot {when}")

    def paths(self):
        base = os.path.join(self.folder, self.base_name())
        return base + ".png", base + ".pdf"

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Save snapshots to", self.folder)
        if folder:
            self.folder = folder
            self._update()

    def snapshot(self):
        arrangement = self.arrange.arrangement() if self.arrange.custom else None
        simple = self.content.currentData() == "sections"
        return export_report.Snapshot(self.win.data, self.rng(), self.label(), _settings(self.win),
                                      layouts=self.layouts, picks=self.picks, style=self.style.currentData(),
                                      arrangement=arrangement, entries=None if simple else self.view_entries(),
                                      sections=self.sections.config() if simple else None,
                                      theme=self.theme.currentData())

    def _update(self, *_):
        name = self.preset.currentText()
        self.start.setVisible(name in ("On a date…", "Date range…"))
        self.to_lbl.setVisible(name == "Date range…")
        self.end.setVisible(name == "Date range…")
        short = self.folder.replace(os.path.expanduser("~"), "~", 1)
        self.folder_lbl.setText(self.folder_lbl.fontMetrics().elidedText(short, Qt.ElideMiddle, 300))
        self.folder_lbl.setToolTip(self.folder)
        rng, bits = self.rng(), []
        for tab in self.win.data["tabs"]:
            if store.is_run_tab(tab):
                n = len(export_report._in_range(tab, rng))
                bits.append(f"{blocks.short_name(tab['title'])}: {n} run{'s' if n != 1 else ''}")
            if store.is_bug_tab(tab):
                made, done = store.created_date_column(tab), store.done_date_column(tab)
                count = lambda c: sum(store.in_range(r["values"][c["pos"]], rng) for r in _visible_rows(tab)) if c else 0
                bits.append(f"bugs: {count(made)} new, {count(done)} closed")
        files = {"cards": f"{self.base_name()} - 1 ….png (one per card) and .pdf",
                 "slack": f"{self.base_name()}.png (summary), “… - full report.png” (wide page) and .pdf"
                 }.get(self.style.currentData(), f"{self.base_name()}.png and .pdf")
        self.summary.setText(f"{self.label()} · " + " · ".join(bits) + f"\nFiles: {files}")
        self.preview_timer.start(350)
        self._profile_state()

    def _draw_preview(self):
        try:
            snap = self.snapshot()
            img = snap.summary_image() if self.style.currentData() == "slack" else snap.image()
        except Exception as exc:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(f"Couldn't draw the preview:\n{type(exc).__name__}: {exc}")
            return
        titles = snap.card_titles()
        if self.style.currentData() in ("wide", "slack"):
            if self.arrange.custom:
                self.arrange.sync(titles)
            elif snap.arrangement:
                self.arrange.load(snap.arrangement, titles)
        self.side_tabs.setTabEnabled(2, self.style.currentData() in ("wide", "slack"))
        if not snap.cards:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Nothing ticked to export.")
            self.preview_note.setText("")
            return
        pm = QPixmap.fromImage(img)
        box = self.preview.size()
        pm.setDevicePixelRatio(1)
        self.preview.setPixmap(pm.scaled(box.width() - 12, box.height() - 12,
                                         Qt.KeepAspectRatio, Qt.SmoothTransformation))
        n = len(snap.cards)
        note = {"slack": "Slack summary (16:9). The wide page is saved next to it, and as the PDF.",
                "wide": "Your arrangement." if self.arrange.custom else "Arranged automatically — "
                        "change it under “Arrange the page”.",
                "cards": "Each card is saved as its own PNG."}.get(self.style.currentData(), "")
        self.preview_note.setText(f"{n} card{'s' if n != 1 else ''} · {note}")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "preview_timer"):
            self.preview_timer.start(250)

    def accept(self):
        self.win.cfg["export"] = dict(self.current_settings(), profile=self.profile.currentText())
        store.save_config(self.win.cfg)
        super().accept()
