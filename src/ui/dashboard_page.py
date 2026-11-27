"""
The dashboard: its cards, top tiles, views, and editing cards in place.
"""

import html
from collections import Counter
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton, QFrame,
    QDialog, QFormLayout, QDialogButtonBox, QScrollArea, QMenu, QToolButton, QListWidget,
    QTabBar)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QCursor

from dashboard import blocks
from dashboard import charts
from dashboard import layout
from dashboard import views
from data import chartquery
from data import store
from ui import motion
from ui import theme as ui_theme

from ui.common import (
    MUTED, RED, _FlowColumns, _clear_layout, _colors_for, _open_link, _settings,
    _small_label, _visible_rows, card_key)


class EditTile(QFrame):
    """A chart while its card is being edited: drag ⠿ onto another chart to move it,
    drag the right edge to make it wider or narrower, ⋯ for everything else."""
    MIME = "application/x-test-tracker-block"

    def __init__(self, dash, tab, card, b, parts, target):
        super().__init__()
        self.dash, self.win, self.tab, self.card, self.b = dash, dash.win, tab, card, b
        self.setObjectName("tile_edit")
        self.setAcceptDrops(True)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 6, 14, 8)
        v.setSpacing(6)
        top = QHBoxLayout()
        grip = QLabel("⠿")
        grip.setStyleSheet("font-size:16px; color:#8A8984; padding:0 4px;")
        grip.setCursor(Qt.OpenHandCursor)
        grip.setToolTip("Drag onto another chart to move this one there")
        grip.mousePressEvent = lambda e: setattr(self, "_press", e.pos())
        grip.mouseMoveEvent = self._drag
        top.addWidget(grip)
        name = QLabel(b.get("title") or layout.auto_title(tab, b))
        name.setStyleSheet("font-size:12px; font-weight:bold; color:#52514E;")
        top.addWidget(name, 1)
        more = QToolButton()
        more.setText("⋯")
        more.setPopupMode(QToolButton.InstantPopup)
        more.setMenu(self._menu(more))
        more.setStyleSheet("QToolButton { padding:0 8px; font-size:15px; }")
        top.addWidget(more)
        v.addLayout(top)
        body = QHBoxLayout()
        body.setSpacing(20)
        for k, p in enumerate(parts):
            if k == 0 and p.title.strip().lower() == name.text().strip().lower():
                p = blocks.Part("", p.content, p.pick, p.wide, p.full)    # the tile already names it
            body.addWidget(dash._part(tab, p, target), 1 if p.wide else 0, Qt.AlignTop)
        if not parts:
            body.addWidget(_small_label("Nothing to show in these dates.", MUTED))
        if not any(p.wide for p in parts):
            body.addStretch(1)
        v.addLayout(body)
        where = {(True, True): "Dashboard and export", (True, False): "Dashboard only",
                 (False, True): "Export only", (False, False): "Hidden"}[(b["dash"], b["export"])]
        foot = _small_label(f"{where} · size {int(b.get('size') or 1)}"
                            + (" · starts a new row" if b.get("new_row") else ""), MUTED, 10)
        v.addWidget(foot)
        if not b["dash"]:
            self.setStyleSheet("QFrame#tile_edit { background:#F3F2EF; }")
        self.handle = QFrame(self)
        self.handle.setCursor(Qt.SizeHorCursor)
        self.handle.setToolTip("Drag to make this chart wider or narrower")
        self.handle.setStyleSheet("background:#CCCCC8; border-radius:2px;")
        self.handle.mousePressEvent = self._resize_start
        self.handle.mouseReleaseEvent = self._resize_end

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.handle.setGeometry(self.width() - 7, self.height() // 2 - 18, 5, 36)

    # ── menu ──────────────────────────────────────────────────────────────────

    def _menu(self, parent):
        b, win, tab, card = self.b, self.win, self.tab, self.card
        m = QMenu(parent)
        later = lambda fn: QTimer.singleShot(0, fn)     # after the menu closes: these redraw the card
        m.addAction("Edit…", lambda: later(lambda: win.edit_block(tab, card, b["id"])))
        m.addAction("Duplicate", lambda: later(lambda: win.duplicate_block(tab, card, b["id"])))
        m.addSeparator()
        for label, key in (("Start a new row", "new_row"), ("Show on the dashboard", "dash"),
                           ("Include in the export", "export")):
            act = m.addAction(label)
            act.setCheckable(True)
            act.setChecked(bool(b.get(key)))
            act.toggled.connect(lambda on, k=key: later(lambda: win.set_block(tab, card, b["id"], **{k: on})))
        size = m.addMenu("Size")
        for n in (1, 2, 3, 4):
            act = size.addAction({1: "Small", 2: "Medium", 3: "Large", 4: "Extra large"}[n])
            act.setCheckable(True)
            act.setChecked(int(b.get("size") or 1) == n)
            act.triggered.connect(lambda _, n=n: later(lambda: win.set_block(tab, card, b["id"], size=n)))
        m.addSeparator()
        m.addAction("Remove", lambda: later(lambda: win.remove_block(tab, card, b["id"])))
        return m

    # ── drag to move ──────────────────────────────────────────────────────────

    def _drag(self, e):
        if not (e.buttons() & Qt.LeftButton) or getattr(self, "_press", None) is None:
            return
        if (e.pos() - self._press).manhattanLength() < 6:
            return
        from PyQt5.QtCore import QMimeData
        from PyQt5.QtGui import QDrag
        mime = QMimeData()
        mime.setData(self.MIME, self.b["id"].encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab().scaledToWidth(min(self.width(), 260), Qt.SmoothTransformation))
        self._press = None
        drag.exec_(Qt.MoveAction)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(self.MIME) and bytes(e.mimeData().data(self.MIME)).decode() != self.b["id"]:
            e.acceptProposedAction()
            self.setStyleSheet("QFrame#tile_edit { border:2px solid #1D9E75; }")

    def dragLeaveEvent(self, e):
        self.setStyleSheet("" if self.b["dash"] else "QFrame#tile_edit { background:#F3F2EF; }")

    def dropEvent(self, e):
        src = bytes(e.mimeData().data(self.MIME)).decode()
        after = e.pos().x() > self.width() / 2
        e.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.win.move_block(self.tab, self.card, src, self.b["id"], after))

    # ── drag to resize ────────────────────────────────────────────────────────

    def _resize_start(self, e):
        self._start_x, self._start_w = e.globalPos().x(), self.width()

    def _resize_end(self, e):
        if not hasattr(self, "_start_x"):
            return
        w = max(self._start_w + e.globalPos().x() - self._start_x, 60)
        size = int(self.b.get("size") or 1)
        new = max(1, min(4, round(size * w / max(self._start_w, 1))))
        if new == size and abs(w - self._start_w) > 80:
            new = max(1, min(4, size + (1 if w > self._start_w else -1)))
        if new != size:
            QTimer.singleShot(0, lambda: self.win.set_block(self.tab, self.card, self.b["id"], size=new))


class ViewBar(QFrame):
    """MAIN, the shared views, then your own — above the date filter."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 8, 0, 0)
        h.setSpacing(8)
        h.addWidget(_small_label("View"))
        self.bar = QTabBar()
        self.bar.setDrawBase(False)
        self.bar.setExpanding(False)
        self.bar.setStyleSheet(
            "QTabBar::tab { background:#FFFFFF; border:1px solid #CCCCC8; border-radius:12px; padding:3px 12px;"
            " margin-right:6px; color:#52514E; font-size:12px; }"
            "QTabBar::tab:selected { background:#E1F5EE; border-color:#1D9E75; color:#0F6E56; font-weight:bold; }")
        self.bar.currentChanged.connect(self._picked)
        h.addWidget(self.bar)
        add = QPushButton("+ New view")
        add.setObjectName("link")
        add.clicked.connect(self.win.new_view)
        h.addWidget(add)
        h.addStretch(1)
        self.settings_btn = QPushButton("View settings…")
        self.settings_btn.setToolTip("Rename, add or remove cards, share with everyone, duplicate, delete")
        self.settings_btn.clicked.connect(lambda: self.win.view_settings())
        h.addWidget(self.settings_btn)
        self._ids = []

    def refresh(self):
        self.bar.blockSignals(True)
        while self.bar.count():
            self.bar.removeTab(0)
        self._ids = [views.MAIN]
        self.bar.addTab("MAIN")
        self.bar.setTabToolTip(0, "Every tab's cards, as the admin set them up")
        for v in self.win.all_views():
            i = self.bar.addTab(("👥 " if v["shared"] else "") + v["name"])
            self.bar.setTabToolTip(i, "Shared with everyone by the admin" if v["shared"] else "Only on this computer")
            self._ids.append(v["id"])
        current = self.win.current_view_id()
        self.bar.setCurrentIndex(self._ids.index(current) if current in self._ids else 0)
        self.bar.blockSignals(False)
        self.settings_btn.setVisible(current != views.MAIN)

    def _picked(self, i):
        if 0 <= i < len(self._ids):
            self.win.set_view(self._ids[i])


class ViewSettingsDialog(QDialog):
    """A view's name and cards, and sharing it with everyone (admin)."""

    def __init__(self, win, view, is_admin_view):
        super().__init__(win)
        self.win, self.view = win, views.copy_view(view)
        self.action = None
        self.setWindowTitle(f"View settings — {view['name']}")
        self.setMinimumWidth(620)
        self.name = QLineEdit(view["name"])
        self.list = QListWidget()
        self.list.setMinimumHeight(240)
        add = QToolButton()
        add.setText("+ Add card ▾")
        add.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(add)
        linked = menu.addMenu("From Main (stays in sync with it)")
        copied = menu.addMenu("Copy of a Main card (to change here)")
        for label, ref in views.main_cards(win.data, win.layout_of):
            linked.addAction(label, lambda r=ref: self._add({"ref": r}))
            copied.addAction(label, lambda r=ref: self._add_copy(r))
        blank = menu.addMenu("New empty card for")
        for t in win.data["tabs"]:
            blank.addAction(t["title"], lambda t=t: self._add({"tab": t["title"], "card": {
                "id": layout.new_id(), "title": "New card", "dash": True, "export": True,
                "combine": False, "split": None, "blocks": []}}))
        add.setMenu(menu)
        up, down, remove = QPushButton("↑"), QPushButton("↓"), QPushButton("Remove")
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        remove.clicked.connect(self._remove)
        row = QHBoxLayout()
        for w in (add, up, down, remove):
            row.addWidget(w)
        row.addStretch(1)

        manage = QHBoxLayout()
        if view["shared"]:
            b = QPushButton("Stop sharing")
            b.setToolTip("Take it back to just your computer (admin)")
            b.clicked.connect(lambda: self._done("unshare"))
        else:
            b = QPushButton("👥 Share with everyone…")
            b.setToolTip("Admin passcode: everyone using this release sheet gets this view")
            b.clicked.connect(lambda: self._done("share"))
        manage.addWidget(b)
        dup = QPushButton("Duplicate")
        dup.clicked.connect(lambda: self._done("duplicate"))
        delete = QPushButton("Delete view")
        delete.clicked.connect(lambda: self._done("delete"))
        manage.addWidget(dup)
        manage.addWidget(delete)
        manage.addStretch(1)

        note = _small_label("Cards from Main stay in sync with it. Cards of this view's own can be "
                            "changed with ✎ Edit on the card." + (" This view is shared: changes "
                            "apply to everyone." if view["shared"] else " This view is only on this computer."),
                            MUTED)
        note.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        ok = buttons.addButton("Save", QDialogButtonBox.AcceptRole)
        ok.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("Name", self.name)
        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(_small_label("CARDS (TOP TO BOTTOM)", "#888885", 10))
        root.addWidget(self.list, 1)
        root.addLayout(row)
        root.addWidget(note)
        root.addLayout(manage)
        root.addWidget(buttons)
        self._fill()

    def _label(self, e):
        if "ref" in e:
            title, _, cid = e["ref"].rpartition("|")
            tab = self.win._tab(title)
            card = next((c for c in self.win.layout_of(tab)["cards"] if c["id"] == cid), None) if tab else None
            return f"{layout.card_title(tab, card) if card else e['ref']}   ·  from Main"
        tab = self.win._tab(e["tab"])
        return f"{layout.card_title(tab, e['card']) if tab else e['card'].get('title')}   ·  " \
               f"{len(e['card']['blocks'])} chart{'s' if len(e['card']['blocks']) != 1 else ''}, this view's own"

    def _fill(self, select=None):
        self.list.clear()
        for e in self.view["cards"]:
            self.list.addItem(self._label(e))
        if select is not None and self.list.count():
            self.list.setCurrentRow(max(0, min(select, self.list.count() - 1)))

    def _add(self, entry):
        self.view["cards"].append(entry)
        self._fill(len(self.view["cards"]) - 1)

    def _add_copy(self, ref):
        title, _, cid = ref.rpartition("|")
        tab = self.win._tab(title)
        card = next((c for c in self.win.layout_of(tab)["cards"] if c["id"] == cid), None)
        if card:
            own = layout.copy_layout(card)
            own.update(id=layout.new_id(), title=layout.card_title(tab, card), combine=False)
            self._add({"tab": title, "card": own})

    def _move(self, step):
        i, j = self.list.currentRow(), self.list.currentRow() + step
        cards = self.view["cards"]
        if 0 <= i < len(cards) and 0 <= j < len(cards):
            cards[i], cards[j] = cards[j], cards[i]
            self._fill(j)

    def _remove(self):
        i = self.list.currentRow()
        if 0 <= i < len(self.view["cards"]):
            del self.view["cards"][i]
            self._fill(i)

    def _done(self, action):
        self.action = action
        self.accept()

    def result_view(self):
        self.view["name"] = self.name.text().strip() or self.view["name"]
        return self.view


class Dashboard(QScrollArea):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.body = None
        self.range, self.range_text = None, "All dates"     # set by the DateBar
        self.show_empty = False                    # show cards that have nothing in the dates

    # ── date range ────────────────────────────────────────────────────────────

    def _dated(self, tab):
        """True when the date filter applies to this tab (it has a date column)."""
        return self.range is not None and store.date_column(tab) is not None

    def _rows(self, tab):
        rows = _visible_rows(tab)
        if not self._dated(tab):
            return rows
        dcol, (start, end) = store.date_column(tab), self.range
        keep = []
        for r in rows:
            d = store.parse_date(r["values"][dcol["pos"]])
            if d and start <= d <= end:
                keep.append(r)
        return keep

    def _count_note(self, tab, rows):
        n = len(rows)
        text = f"{n} row{'s' if n != 1 else ''}"
        if self._dated(tab):
            total = len(_visible_rows(tab))
            text = f"{n} of {total} rows · {self.range_text}"
        return text

    def _go_rows(self, tab, rows):
        """Open a tab's table showing exactly these rows (by their first column, e.g. the
        run number), whatever their dates — e.g. open issues carried over from earlier days."""
        # identify rows by the first column whose values are unique (Run Number, Key…)
        filled = [r for r in tab["rows"] if not store.is_blank(r)]
        key = next((c for c in tab["columns"]
                    if len({r["values"][c["pos"]] for r in filled}) == len(filled)), tab["columns"][0])
        runs = [x for r in rows for x in r.get("_runs", [r])]       # a repeated issue opens all its runs
        self._go(tab["title"], {key["pos"]: {r["values"][key["pos"]] for r in runs} or {"\0"}}, dates=False)

    def _go(self, title, filters=None, dates=True):
        """Open a tab's table, filtered like the chart that was clicked — including the dates
        (unless dates=False, e.g. for open issues carried over from earlier days)."""
        filters = dict(filters or {})
        tab = next((t for t in self.win.data["tabs"] if t["title"] == title), None)
        if tab and dates and self._dated(tab):
            dcol = store.date_column(tab)
            if dcol["pos"] not in filters:
                filters[dcol["pos"]] = {r["values"][dcol["pos"]] for r in self._rows(tab)} or {"\0"}
        self.win.show_tab(title, filters or None)

    def set_data(self, data, animate=False):
        """Rebuild the dashboard. With animate (something you did: the dates, a view, first
        load), cards rise in and charts grow; the background sync redraws without motion."""
        animate = animate or not getattr(self, "_shown_once", False)
        self._shown_once = True
        motion.settle_all()
        with motion.entrance(animate):
            self._build(data)
        if animate and not motion.REDUCED:
            QTimer.singleShot(0, self._arrive)

    def _arrive(self):
        body = self.body
        if body is None or body.layout() is None:
            return
        body.layout().activate()
        top, bottom = self.verticalScrollBar().value(), self.verticalScrollBar().value() + self.viewport().height()
        k = 0
        for w in body.children():
            if isinstance(w, QFrame) and w.objectName() in ("card", "tile") and w.isVisible():
                if w.geometry().bottom() < top or w.geometry().top() > bottom:
                    continue                       # off screen: it's simply there when you scroll
                motion.arrive(w, dy=14, delay=min(k * 45, 360))
                k += 1

    def _build(self, data):
        pos = self.verticalScrollBar().value()
        body = QWidget()
        body.setObjectName("dash")
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 14, 8, 20)
        root.setSpacing(14)

        cur = self.win.current_view()
        title = QLabel(html.escape(data["title"]) + (f" <span style='color:#1D9E75'>· {html.escape(cur['name'])}</span>"
                                                     if cur else ""))
        title.setTextFormat(Qt.RichText)
        title.setStyleSheet("font-size:20px; font-weight:bold;")
        when = data.get("fetched_at", "")
        try:
            when = datetime.fromisoformat(when).strftime("%b %-d, %H:%M")
        except ValueError:
            pass
        head = QHBoxLayout()
        head.addWidget(title)
        head.addSpacing(10)
        head.addWidget(_small_label(f"Data as of {when} · hover over a chart for details, click it "
                                    "to see those rows", MUTED), 1, Qt.AlignBottom)
        root.addLayout(head)
        notice = QVBoxLayout()                     # "No Viking runs in …" goes here, at the top
        root.addLayout(notice)
        self._hidden, self._no_runs = 0, []

        view = self.win.current_view()
        if view is not None:                       # a custom view: just its cards
            self._view_cards(root, data, view)
            self._notice(notice)
            root.addStretch(1)
            self._swap(body)
            QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(pos))
            return

        tiles = QGridLayout()
        tiles.setSpacing(10)
        tabs = [t for t in data["tabs"] if _visible_rows(t) or t["rows"]]
        conf = self.win.tile_settings()
        shown = [t for t in tabs if not (conf.get(t["title"]) or {}).get("hidden")]
        for i, tab in enumerate(shown):
            tiles.addWidget(self._tile(tab), i // 4, i % 4)
        for c in range(min(4, len(shown))):
            tiles.setColumnStretch(c, 1)
        tiles_btn = QPushButton("Show ▾")
        tiles_btn.setObjectName("link")
        tiles_btn.setToolTip("Choose which tiles and cards show (on this computer)")
        tiles_btn.clicked.connect(lambda: self._tiles_menu(tabs, tiles_btn))
        new_btn = QPushButton("+ New card")
        new_btn.setObjectName("link")
        new_btn.setToolTip("A card of your own, not tied to one tab: add any charts to it "
                           "(admin, shared with everyone)")
        new_btn.clicked.connect(lambda: QTimer.singleShot(0, self.win.new_custom_card))
        head.addWidget(new_btn, 0, Qt.AlignBottom)
        head.addWidget(tiles_btn, 0, Qt.AlignBottom)
        root.addLayout(tiles)
        hidden_cards = set(self.win.hidden_cards())

        for tab in tabs + [layout.custom_tab()]:
            lo = self.win.layout_of(tab)
            for card in lo["cards"]:
                if not card["dash"] or (card["id"] == "analysis" and not _visible_rows(tab)):
                    continue
                if card_key(tab, card) in hidden_cards and not self.is_editing(tab, card):
                    continue
                if self._skip(tab, card):
                    continue
                try:
                    root.addWidget(self._card(tab, card, lo))
                except Exception as exc:          # a broken layout shows a note, not a crash
                    root.addWidget(_small_label(f"Couldn't draw {layout.card_title(tab, card)}: "
                                                f"{type(exc).__name__}: {exc}", RED))
        self._notice(notice)
        root.addStretch(1)
        self._swap(body)
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(pos))

    def _swap(self, body):
        """Show the new dashboard. The old one is hidden now and deleted once Qt is done with
        whatever rebuilt it: setWidget() would delete it at once, and if that came from a
        button or menu on the old dashboard (+ Add chart, ▦ gallery, ⋯), Qt went on using the
        deleted button or menu and the app crashed."""
        old = self.takeWidget()
        self.setWidget(body)
        self.body = body
        if old is not None:
            old.hide()
            old.setParent(None)
            QTimer.singleShot(0, old.deleteLater)
            self._old_bodies = [old]               # keep Python's reference until then

    def _view_cards(self, root, data, view):
        e = self.win.editing
        if e and e.get("view") == view["id"]:
            view = e["view_obj"]                   # the copy being edited
        got = views.entries(view, data, self.win.layout_of)
        if not got:
            box = QFrame()
            box.setObjectName("card")
            v = QVBoxLayout(box)
            v.setContentsMargins(18, 18, 18, 18)
            v.addWidget(QLabel(f"<b>{html.escape(view['name'])}</b> has no cards yet."))
            add = QPushButton("+ Add cards…")
            add.setObjectName("primary")
            add.clicked.connect(lambda: self.win.view_settings())
            v.addWidget(_small_label("Add cards from the main page (they stay in sync with it), or "
                                     "new cards of your own with any charts you like.", MUTED))
            v.addWidget(add, 0, Qt.AlignLeft)
            root.addWidget(box)
            return
        hidden_cards = set(self.win.hidden_cards())
        for tab, card, lo, entry in got:
            if card_key(tab, card) in hidden_cards and not self.is_editing(tab, card):
                continue
            if self._skip(tab, card):
                continue
            try:
                root.addWidget(self._card(tab, card, lo, linked="ref" in entry))
            except Exception as exc:
                root.addWidget(_small_label(f"Couldn't draw {layout.card_title(tab, card)}: "
                                            f"{type(exc).__name__}: {exc}", RED))

    # ── empty cards ───────────────────────────────────────────────────────────

    def _no_runs_in_dates(self, tab):
        return store.is_run_tab(tab) and self._dated(tab) and not self._rows(tab)

    def _skip(self, tab, card):
        """Leave out a card with nothing to show in the dates: a run tab's cards when it has no
        runs (one line at the top says so), and an Error Analysis with no errors — it stays
        while an earlier error is still unresolved. "show" brings them back; never while editing."""
        if self.show_empty or self.is_editing(tab, card) or blocks.own_of(card):
            return False                       # (a card with its own dates isn't about the dashboard's)
        ctx = blocks.Ctx(self.range, self.range_text, export=False, settings=_settings(self.win),
                         data=self.win.data)
        empty = card["id"] == "analysis" and self._draws_nothing(tab, card, ctx)
        if self._no_runs_in_dates(tab):
            name = blocks.short_name(tab["title"])
            if name not in self._no_runs:
                self._no_runs.append(name)
            empty = empty or card["id"] != "analysis"
        if empty:
            self._hidden += 1
        return empty

    def _draws_nothing(self, tab, card, ctx):
        for b in card["blocks"]:
            if not b["dash"]:
                continue
            try:
                if blocks.render(b, [tab], ctx):
                    return False
            except Exception:
                return False                    # a broken chart shows its error, so keep the card
        return True

    def _notice(self, box):
        """The line at the top: which products had no runs, and how many cards are hidden."""
        if not (self._hidden or self.show_empty):
            return
        if self.show_empty:
            text = "Showing every card, even those with nothing in these dates · "
            link = '<a href="hide">hide them</a>'
        else:
            bits = [f"No {' or '.join(self._no_runs)} runs in {html.escape(self.range_text)}"] if self._no_runs else []
            bits.append(f"{self._hidden} card{'s' if self._hidden != 1 else ''} with nothing to show "
                        f"{'is' if self._hidden == 1 else 'are'} hidden")
            text = " · ".join(bits) + " · "
            link = '<a href="show">show</a>'
        lbl = QLabel(text + link)
        lbl.setTextFormat(Qt.RichText)
        lbl.setStyleSheet(f"color:{MUTED}; font-size:13px;")
        lbl.linkActivated.connect(self._toggle_empty)
        box.addWidget(lbl)

    def _toggle_empty(self, href):
        self.show_empty = href == "show"
        if self.win.data:
            self.set_data(self.win.data, animate=True)

    # ── tiles ─────────────────────────────────────────────────────────────────

    def tile_stat(self, conf):
        """(big, small) for a tile's own query, in the dashboard's dates."""
        ctx = blocks.Ctx(self.range, self.range_text, export=False, settings=_settings(self.win),
                         data=self.win.data)
        _, cols, rows, _ = blocks.run_query({"sql": conf.get("sql") or ""}, ctx)
        big, small, slices = chartquery.tile_stat(cols, rows, conf.get("label", ""))
        if slices:                                # a breakdown: its slices are the bar, in the chart colors
            key = chartquery.color_column(conf.get("sql"), conf.get("simple"))
            colors = blocks._query_colors({"color_by": key}, key, [v for v, _ in slices])
            slices = [(v, n, colors.get(v, charts.PENDING)) for v, n in slices]
        return big, small, slices

    def _tiles_menu(self, tabs, btn):
        conf = self.win.tile_settings()
        menu = QMenu(self)
        menu.addSection("Tiles")
        for t in tabs:
            a = menu.addAction(t["title"])
            a.setCheckable(True)
            a.setChecked(not (conf.get(t["title"]) or {}).get("hidden"))
            a.toggled.connect(lambda on, title=t["title"]: self.win.set_tile(title, hidden=not on))
        menu.addSection("Cards")
        hidden = set(self.win.hidden_cards())
        keys = []
        for t in tabs + [layout.custom_tab()]:
            for card in self.win.layout_of(t)["cards"]:
                if not card["dash"]:
                    continue
                key = card_key(t, card)
                keys.append(key)
                a = menu.addAction(layout.card_title(t, card))
                a.setCheckable(True)
                a.setChecked(key not in hidden)
                a.toggled.connect(lambda on, k=key: self.win.set_card_hidden(k, not on))
        menu.addSeparator()
        menu.addAction("Show all", lambda: (self.win.set_card_hidden(keys, False),
                                            [self.win.set_tile(t["title"], hidden=False) for t in tabs]))
        menu.exec_(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _tile_menu(self, tile, tab):
        conf = self.win.tile_settings().get(tab["title"]) or {}
        menu = QMenu(self)
        menu.addAction("Edit tile…", lambda: self.win.edit_tile(tab))
        if conf.get("sql"):
            menu.addAction("Use the built-in tile", lambda: self.win.set_tile(tab["title"], stat=None))
        menu.addAction("Hide tile", lambda: self.win.set_tile(tab["title"], hidden=True))
        menu.addSeparator()
        menu.addAction(f"Open {tab['title']}", lambda: self._go(tab["title"]))
        menu.exec_(QCursor.pos())

    def _tile(self, tab, stat=None):
        rows = self._rows(tab)
        status, colors = _colors_for(tab, rows)
        tile = QFrame()
        tile.setObjectName("tile")
        tile.setCursor(Qt.PointingHandCursor)
        tile.setToolTip(f"Open {tab['title']} · right-click to change or hide this tile")
        tile.mousePressEvent = (lambda e, t=tab["title"]: self._go(t) if e.button() == Qt.LeftButton else None)
        if stat is None:
            tile.setContextMenuPolicy(Qt.CustomContextMenu)
            tile.customContextMenuRequested.connect(lambda _, t=tile: self._tile_menu(t, tab))
            conf = self.win.tile_settings().get(tab["title"]) or {}
            if conf.get("sql"):
                try:
                    stat = self.tile_stat(conf)
                except Exception as exc:
                    stat = ("—", f"query error: {exc}"[:80], None)
        lay = QVBoxLayout(tile)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        lay.addWidget(_small_label(tab["title"], "#666663", 11))
        mini = charts.MiniBar()
        if status and rows:
            counts = Counter(store.row_status(tab, r) for r in rows)
            order = charts.status_order(list(counts), status["options"])
            mini.set_data([(v or "No status", counts[v], colors.get(v, charts.PENDING)) for v in order])
        if stat is not None and stat[2]:           # a breakdown: the bar shows its slices
            mini.set_data(stat[2])
        if stat is not None:                       # this tile's own number
            big = QLabel(stat[0])
            big.setStyleSheet("font-size:24px; font-weight:bold;")
            sub = _small_label(stat[1] + (f" · {self.range_text}" if self._dated(tab) and stat[1] else ""),
                               "#52514E", 11)
        elif status and rows:
            counts = Counter(store.row_status(tab, r) for r in rows)
            cls = Counter()
            for v, n in counts.items():
                cls[charts.classify(v)] += n
            done, total = cls["done"], len(rows)
            big = QLabel(f"{round(100 * done / total)}%")
            big.setStyleSheet("font-size:24px; font-weight:bold;")
            bits = [f"{done} of {total} done"]
            if cls["blocked"]:
                bits.append(f"{cls['blocked']} " + ("failed" if store.is_run_tab(tab) else "blocked"))
            if cls["active"]:
                bits.append(f"{cls['active']} in progress")
            if self._dated(tab):
                bits.append(self.range_text)
            sub = _small_label(" · ".join(bits), "#52514E", 11)
        else:
            big = QLabel(str(len(rows)))
            big.setStyleSheet("font-size:24px; font-weight:bold;")
            sub = _small_label("rows" + (f" · {self.range_text}" if self._dated(tab) else ""),
                               "#52514E", 11)
        lay.addWidget(big)
        lay.addWidget(sub)
        lay.addWidget(mini)
        return tile

    def _card(self, tab, card, lo, preview=False, linked=False):
        """One dashboard card, drawn from its layout (see layout.py). While it's being
        edited (✎ Edit), each chart is a tile you can drag, resize, and change."""
        ctx = blocks.Ctx(self.range, self.range_text, export=False, settings=_settings(self.win),
                         data=self.win.data)
        ctx = blocks.card_ctx(ctx, tab, card)           # its own dates and filters, if it has them
        editing = not preview and self.is_editing(tab, card)
        frame = QFrame()
        frame.setObjectName("card_edit" if editing else "card")
        lay_ = QVBoxLayout(frame)
        lay_.setContentsMargins(18, 14, 18, 16)
        lay_.setSpacing(10)
        head = QHBoxLayout()
        t = QLabel(layout.card_title(tab, card))
        t.setStyleSheet("font-size:15px; font-weight:bold;")
        head.addWidget(t)
        head.addWidget(_small_label(blocks.card_note(card, [tab], ctx), MUTED), 0, Qt.AlignBottom)
        own = blocks.own_of(card)
        if own:                                         # say so: it isn't following the dashboard's dates
            pill = QLabel("📅 " + (" · ".join(blocks.own_note(own)) or "Own dates"))
            pill.setStyleSheet("font-size:11px; color:#0F6E56; background:#E1F5EE; border-radius:8px; padding:2px 8px;")
            pill.setToolTip(f"This card uses its own dates ({ctx.range_text}) and filters, not the "
                            "dashboard's (✎ Edit → 📅 Dates & filters…)")
            head.addWidget(pill, 0, Qt.AlignBottom)
        head.addStretch(1)
        if editing:
            settings_btn = QPushButton("Card settings…")
            settings_btn.setObjectName("link")
            settings_btn.clicked.connect(lambda: self.win.card_settings(tab, card))
            scope_btn = QPushButton("📅 Dates && filters…")
            scope_btn.setObjectName("link")
            scope_btn.setToolTip("Give this card its own dates and filters, instead of the dashboard's")
            scope_btn.clicked.connect(lambda: QTimer.singleShot(0, lambda: self.win.edit_card_scope(tab, card)))
            colors_btn = QPushButton("🎨 Colours…")
            colors_btn.setObjectName("link")
            colors_btn.setToolTip("This card's own colours, for everyone")
            colors_btn.clicked.connect(lambda: self.win.edit_card_colors(tab, card))
            cancel = QPushButton("Cancel")
            cancel.clicked.connect(self.win.cancel_editing)
            done = QPushButton("Done editing")
            done.setObjectName("primary")
            done.clicked.connect(self.win.finish_editing)
            for w in (settings_btn, scope_btn, colors_btn, cancel, done):
                head.addWidget(w)
        groups = layout.split_groups(tab, card)
        key = card_key(tab, card)
        switch = hide = None
        if groups and not editing and not preview:   # All / VitalOne / Viking / Split
            modes = ["all"] + [n for n, _ in groups] + ["split"]
            switch = ui_theme.segmented_tab_bar()
            for m in modes:
                switch.addTab({"all": "All", "split": "Split"}.get(m, m))
            mode = self.win.card_view(key)
            switch.setCurrentIndex(modes.index(mode) if mode in modes else len(modes) - 1)
            switch.setToolTip("All together, one product, or each product in its own section")
            head.addWidget(switch, 0, Qt.AlignVCenter)
        if not editing and not preview:
            hide = QPushButton("Hide")
            hide.setObjectName("link")
            hide.setToolTip("Hide this card on this computer (Show ▾ at the top brings it back)")
            hide.clicked.connect(lambda: self.win.set_card_hidden(key, True))
        if linked and not editing:
            head.addWidget(_small_label("from Main", MUTED), 0, Qt.AlignBottom)
            if hide:
                head.addWidget(hide)
            open_btn = QPushButton("Open table →")
            open_btn.setObjectName("link")
            open_btn.clicked.connect(lambda: self._go(tab["title"]))
            head.addWidget(open_btn)
        elif not preview and not editing:
            edit = QPushButton("✎ Edit")
            edit.setObjectName("link")
            edit.setToolTip("Add, move, resize and change this card's charts")
            edit.clicked.connect(lambda: self.win.start_editing(tab, card["id"]))
            head.addWidget(edit)
            if hide:
                head.addWidget(hide)
            if not layout.is_custom(tab):           # a custom card has no table of its own
                open_btn = QPushButton("Open table →")
                open_btn.setObjectName("link")
                open_btn.clicked.connect(lambda: self._go(tab["title"]))
                head.addWidget(open_btn)
        lay_.addLayout(head)

        if not preview and not editing and card is lo["cards"][0]:
            for col in layout.new_columns(tab, lo, self.win.known_columns(tab)):
                lay_.addWidget(self._new_column_banner(tab, col))

        target = (lambda t: None) if (preview or editing) else self._target
        if not groups or editing:
            if groups:
                lay_.addWidget(_small_label(f"Shown once per section ({', '.join(n for n, _ in groups)}) "
                                            "when you're done.", MUTED))
            self._card_body(lay_, tab, card, lo, ctx, target, editing)
        else:
            body = QWidget()
            body_lay = QVBoxLayout(body)
            body_lay.setContentsMargins(0, 0, 0, 0)
            body_lay.setSpacing(10)
            lay_.addWidget(body)

            def draw(mode):
                _clear_layout(body_lay)
                picked = next((test for name, test in groups if name == mode), None)
                if mode == "all" or (picked is None and mode != "split" and not preview):
                    self._card_body(body_lay, tab, card, lo, ctx, target)
                elif picked is not None:
                    self._card_body(body_lay, tab, card, lo, ctx.section(picked), target)
                else:
                    for name, test in groups:          # labelled sections, same card
                        sub = ctx.section(test)
                        n = len(sub.all_rows(tab))
                        lbl = QLabel(f"{html.escape(name.upper())} <span style='color:{MUTED}; "
                                     f"font-weight:normal'>· {n} bug{'s' if n != 1 else ''}</span>")
                        lbl.setTextFormat(Qt.RichText)
                        lbl.setStyleSheet("font-size:12px; font-weight:bold; color:#1A1A18; padding-top:8px;"
                                          "border-top:1px solid #ECEAE6;")
                        body_lay.addWidget(lbl)
                        self._card_body(body_lay, tab, card, lo, sub, target)
            modes = ["all"] + [n for n, _ in groups] + ["split"]
            draw(modes[switch.currentIndex()] if switch else "split")
            if switch:
                def switched(i):
                    self.win.set_card_view(key, modes[i])
                    draw(modes[i])
                switch.currentChanged.connect(switched)
        if editing:
            add_row = QHBoxLayout()
            add = QPushButton("+ Add chart")
            add.setObjectName("dashed")
            add.clicked.connect(lambda: QTimer.singleShot(0, lambda: self.win.add_chart(tab, card)))
            gallery = QPushButton("▦ Add from gallery ▾")
            gallery.setObjectName("dashed")
            gallery.clicked.connect(lambda: self._gallery_menu(tab, card, gallery))
            add_row.addWidget(add, 1)
            if layout.gallery(tab):                   # the tab's own charts (a custom card has none)
                add_row.addWidget(gallery, 1)
            else:
                gallery.deleteLater()
            lay_.addLayout(add_row)
            lay_.addWidget(_small_label("Drag ⠿ to move a chart (drop it on another chart) · drag a "
                                        "chart's right edge to resize · ⋯ for edit, export and more", MUTED))
        return frame

    def _card_body(self, lay_, tab, card, lo, ctx, target, editing=False):
        with charts.card_colors(card.get("colors")):           # the card's own colours, if it has any
            self._card_body_(lay_, tab, card, lo, ctx, target, editing)

    def _card_body_(self, lay_, tab, card, lo, ctx, target, editing=False):
        drawn = []
        for b in card["blocks"]:
            if not b["dash"] and not editing:
                continue
            try:
                parts = blocks.render(b, [tab], ctx)
            except Exception as exc:               # one broken chart doesn't take the card down
                parts = [blocks.Part(layout.auto_title(tab, b),
                                     f'<span style="color:{MUTED}">Couldn\'t draw this chart '
                                     f'({html.escape(type(exc).__name__)}: {html.escape(str(exc))})</span>')]
            if parts or editing:
                drawn.append((b, parts or []))
        if not drawn:
            if card["id"] == "main" and not ctx.rows(tab):
                text = "No rows in the chosen dates." if ctx.dated(tab) else "Nothing filled in yet."
            else:
                text = "Nothing to show" + (" in the chosen dates." if ctx.dated(tab) else " yet.")
            lay_.addWidget(_small_label(text, MUTED))
            return

        if editing:                                   # one tile per chart, in its rows
            for row in blocks.rows_of(drawn):
                h = QHBoxLayout()
                h.setSpacing(12)
                for b, parts in row:
                    h.addWidget(EditTile(self, tab, card, b, parts, target),
                                int(b.get("size") or 1), Qt.AlignTop)
                lay_.addLayout(h)
            return

        lines = []
        for row in blocks.rows_of(drawn):
            cur = []
            for b, p in ((b, p) for b, ps in row for p in ps):
                if p.full and not isinstance(p.content, str) or not p.full:
                    cur.append((b, p))
                    continue
                if cur:                                  # tables get a row of their own
                    lines.append(cur)
                lines.append([(b, p)])
                cur = []
            if cur:
                lines.append(cur)
        # rows of charts only (pies…) line up as a grid: equal columns, each chart centred in
        # its own, so a short legend or an empty pie doesn't push the next one sideways
        def charts_only(items):
            return all(not p.wide and not isinstance(p.content, str) for _, p in items)
        grid_rows = [items for items in lines if charts_only(items)]
        cols = max((len(items) for items in grid_rows), default=0) if len(grid_rows) > 1 else 0
        built = {}
        if cols:                                     # every pie in the grid as wide as the widest,
            for items in grid_rows:                  # so the rings sit on the same lines
                for _, p in items:
                    built[id(p)] = self._part(tab, p, target)
            donuts = [d for w_ in built.values() for d in
                      ([w_] if isinstance(w_, charts.DonutChart) else w_.findChildren(charts.DonutChart))]
            widest = max((d.width() for d in donuts), default=0)
            room = (self.viewport().width() - 70 - 28 * (cols - 1)) // cols   # a column's width
            if room > 220:
                widest = min(widest, room)
            for d in donuts:
                d.setFixedWidth(widest)
        for items in lines:
            parts = [p for _, p in items]
            if cols and charts_only(items):
                h = QHBoxLayout()
                h.setSpacing(28)
                for b, p in items:
                    h.addWidget(built[id(p)], 1, Qt.AlignTop | Qt.AlignHCenter)
                for _ in range(cols - len(items)):      # keep the columns the same width
                    h.addWidget(QWidget(), 1)
                lay_.addLayout(h)
                continue
            texts = [p for p in parts if isinstance(p.content, str)]
            if len(texts) > 1 and len(texts) == len(parts):     # side-by-side lists wrap
                flow = _FlowColumns()
                for p in parts:
                    flow.add(self._part(tab, p, target))
                lay_.addWidget(flow)
                continue
            h = QHBoxLayout()
            h.setSpacing(28)
            for b, p in items:
                h.addWidget(self._part(tab, p, target),
                            int(b.get("size") or 1) if p.wide else 0, Qt.AlignTop)
            if not any(p.wide for p in parts):
                h.addStretch(1)
            lay_.addLayout(h)

    # ── editing ───────────────────────────────────────────────────────────────

    def is_editing(self, tab, card):
        e = self.win.editing
        here = self.win.current_view()
        return bool(e) and e["tab"] == tab["title"] and e["card"] == card["id"] and \
            e.get("view") == (here["id"] if here else None)

    def _gallery_menu(self, tab, card, button):
        menu = QMenu(button)
        for label, b in layout.gallery(tab):
            act = menu.addAction(label)
            act.triggered.connect(lambda _, b=b: QTimer.singleShot(0, lambda: self.win.insert_block(tab, card, b)))
        menu.exec_(button.mapToGlobal(button.rect().bottomLeft()))

    def _part(self, tab, part, target):
        c = part.content
        pick = (lambda payload, p=part: target(p.pick(payload))) if part.pick else None
        if isinstance(c, list):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(6)
            for sub in c:
                v.addWidget(self._part(tab, sub, target))
            v.addStretch(1)
        elif isinstance(c, str):
            w = QLabel(c)
            w.setTextFormat(Qt.RichText)
            w.setWordWrap(True)
            w.setStyleSheet("font-size:12px;")
            w.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            w.linkActivated.connect(lambda href, pk=pick: self._link(href, pk))
        else:
            w = c
            if pick and hasattr(w, "picked"):
                w.picked.connect(pick)
            if pick and hasattr(w, "picked_cb"):
                w.picked_cb = pick
        return self._titled(part.title, w) if part.title else w

    def _link(self, href, pick):
        if href.startswith("pick:"):
            if pick:
                pick(href[5:])
        elif href.startswith("cell:"):                 # cell:<sheet row>:<column pos>:<tab title>
            r, pos, title = href[5:].split(":", 2)
            self.win.go_to_cell(title, int(r), int(pos))
        else:
            _open_link(href)

    def _target(self, t):
        """Open what a click on a chart points at."""
        if not t:
            return
        kind, tab, what = t
        if kind == "filters":
            self._go(tab["title"], what)
        else:
            self._go_rows(tab, what)

    def _new_column_banner(self, tab, col):
        box = QFrame()
        box.setObjectName("banner")
        h = QHBoxLayout(box)
        h.setContentsMargins(12, 6, 8, 6)
        lbl = QLabel(f"New column <b>{html.escape(col['name'])}</b> — add a chart for it?")
        lbl.setStyleSheet("font-size:12px;")
        h.addWidget(lbl, 1)
        choose = QPushButton("Choose…")
        choose.clicked.connect(lambda: self.win.start_editing(tab, layout.layout_for(
            tab, _settings(self.win))["cards"][0]["id"], add_column=col["name"]))
        skip = QPushButton("Not needed")
        skip.setObjectName("link")
        skip.setToolTip("Hide this note (just for you). You can still add it later in ✎ Customize.")
        skip.clicked.connect(lambda: self.win.dismiss_column(tab, col["name"]))
        h.addWidget(choose)
        h.addWidget(skip)
        return box

    @staticmethod
    def _titled(title, widget):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(_small_label(title.upper(), "#888885", 10))
        lay.addWidget(widget)
        return box
