"""
Test Tracker — a desktop dashboard for software release testing.

It reads a shared Google Sheet (one tab per tracker: features, end-to-end runs,
bugs…), shows a dashboard of where testing stands, and lets you edit cells,
which are written straight back to the sheet. Set it up under ⚙ Settings;
see README.md.

This file is the main window; the rest of the app is in packages next to it:
    app_info.py   name, version (bump APP_VERSION for a release), where releases live
    ui/           the windows: dashboard, tables, Feature Testing, Change Log, export, dialogs
    dashboard/    what a dashboard card draws (blocks, charts, layouts, views)
    data/         the Google Sheet, the offline cache, and the sheet as SQL
    export/       the PNG / PDF export
    integrations/ JIRA and GitHub: change logs and feature testing

Run from source (from the repo root):
    pip install -r requirements.txt
    python src/test_tracker.py

Build a double-clickable app:
    ./scripts/build_mac.sh
"""

import os, subprocess, sys
from datetime import date, datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QDialog, QDialogButtonBox, QShortcut, QComboBox, QTabWidget,
    QMenu, QPlainTextEdit, QAbstractItemView, QInputDialog)
from PyQt5.QtCore import Qt, QThreadPool, QTimer, QUrl
from PyQt5.QtGui import QKeySequence

from dashboard import blocks
from dashboard import charts
from dashboard import layout
from dashboard import views
from data import store
from integrations import changelog
from integrations import feature_testing
from ui import motion
from ui import theme as ui_theme

from app_info import APP_CHANNEL, APP_TITLE, APP_VERSION, INSTALL_CMD, REFRESH_MS, REPO
from ui.common import (
    AMBER, GREEN, MUTED, RED, _Task, _card_merger, _open_link, _settings, _small_label,
    _version_tuple)
from ui.dates import DateBar
from ui.settings_dialogs import ColorsDialog, NewPasscodeDialog, SettingsDialog
from ui.updates import (
    VersionsDialog, WhatsNewDialog, _changelog_sections, _changelog_text, _fetch_releases)
from ui.card_editors import (
    AddChartDialog, CardColorsDialog, CardScopeDialog, CardSettingsDialog, TileDialog,
    default_spec, spec_from_block)
from ui.table_page import ColumnsDialog, TabPage
from ui.export_dialog import ExportDialog
from ui.dashboard_page import Dashboard, ViewBar, ViewSettingsDialog
from ui.change_log_page import ChangeLogPage
from ui.feature_testing_page import FeatureTestingPage


STYLESHEET = """
    QMainWindow, QWidget#central, QDialog, QScrollArea, QWidget#dash { background: #F5F5F2; }
    QLabel { color: #1A1A18; background: transparent; }
    QLineEdit, QDateEdit, QPlainTextEdit {
        background: #FFFFFF; color: #1A1A18;
        border: 1px solid #CCCCC8; border-radius: 7px;
        padding: 5px 10px; font-size: 13px;
        selection-background-color: #1D9E75;
    }
    QLineEdit:focus, QDateEdit:focus, QPlainTextEdit:focus { border: 2px solid #1D9E75; padding: 4px 9px; }
    QComboBox {
        background: #FFFFFF; border: 1px solid #CCCCC8; border-radius: 7px;
        padding: 4px 10px; font-size: 13px;
    }
    QComboBox:hover { border-color: #B4B2A9; }
    QComboBox::drop-down { border: none; width: 18px; }
    QTableView {
        background: #FFFFFF; color: #1A1A18;
        border: 1px solid #E6E4E0; border-radius: 12px;
        gridline-color: #F0EEE9; font-size: 13px;
        alternate-background-color: #FAFAF8;
    }
    QTableView::item { padding: 0 10px; border: none; }
    QTableView::item:selected { background: #E1F5EE; color: #1A1A18; }
    QHeaderView::section {
        background: #FFFFFF; color: #666663; font-size: 11px; font-weight: 600;
        padding: 7px 10px; border: none; border-bottom: 1px solid #E0DDD8;
        border-right: 1px solid #F0EEE9;
    }
    QPushButton, QToolButton {
        background: #FFFFFF; color: #1A1A18;
        border: 1px solid #CCCCC8; border-radius: 7px;
        padding: 5px 14px; font-size: 13px;
    }
    QPushButton:hover, QToolButton:hover   { background: #FAFAF8; border-color: #B4B2A9; }
    QPushButton:pressed, QToolButton:pressed { background: #EEECEA; }
    QPushButton:disabled { color: #AAAAA6; }
    QToolButton::menu-indicator { image: none; }
    QToolButton[active="true"] { background: #E1F5EE; border-color: #1D9E75; color: #0F6E56; }
    QPushButton#primary {
        background: #1D9E75; color: #FFFFFF; border: 1px solid #1D9E75; font-weight: 600;
    }
    QPushButton#primary:hover   { background: #17896A; border-color: #17896A; }
    QPushButton#primary:pressed { background: #0F6E56; border-color: #0F6E56; }
    QPushButton#primary:disabled { background: #8CCDB8; border-color: #8CCDB8; }
    QPushButton#update {
        background: #1D9E75; color: #FFFFFF; border: none; font-weight: 600;
        padding: 3px 12px; font-size: 11px; border-radius: 10px;
    }
    QPushButton#link { border: none; background: transparent; color: #2F5E9E; padding: 2px 4px; }
    QPushButton#link:hover { color: #0F6E56; }
    QPushButton#link:pressed { color: #17896A; }
    QFrame#card { background: #FFFFFF; border: 1px solid #E6E4E0; border-radius: 14px; }
    QFrame#card_edit { background: #FFFFFF; border: 2px dashed #1D9E75; border-radius: 14px; }
    QFrame#tile_edit { background: #FFFFFF; border: 1px dashed #B4B2A9; border-radius: 10px; }
    QPushButton#dashed { border: 1px dashed #B4B2A9; background: #FAFAF8; color: #52514E; padding: 10px;
                         border-radius: 10px; }
    QPushButton#dashed:hover { border-color: #1D9E75; color: #0F6E56; }
    QFrame#tile { background: #FFFFFF; border: 1px solid #E6E4E0; border-radius: 12px; }
    QFrame#tile:hover { border-color: #8CCDB8; }
    QFrame#banner { background: #FFF6E5; border: 1px solid #F3D9A4; border-radius: 10px; }
    QTabWidget::pane { border: none; }
    QTabBar::tab {
        background: transparent; color: #52514E; padding: 7px 16px; margin: 0; font-size: 13px;
        border: none;
    }
    QTabBar::tab:selected { color: #1A1A18; }
    QTabBar::tab:hover:!selected { color: #1A1A18; }
    QCheckBox { font-size: 12px; color: #52514E; }
    QListWidget { background: #FFFFFF; border: 1px solid #E6E4E0; border-radius: 10px; font-size: 13px; }
    QToolTip { background: #FFFFFF; color: #1A1A18; border: 1px solid #E0DDD8; border-radius: 6px;
               padding: 4px 6px; }
    QMenu { background: #FFFFFF; border: 1px solid #E0DDD8; border-radius: 8px; padding: 4px; }
    QMenu::item { padding: 5px 18px; border-radius: 5px; color: #1A1A18; }
    QMenu::item:selected { background: #1D9E75; color: #FFFFFF; }
    QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical { background: #CCCCC8; border-radius: 3px; min-height: 30px; margin: 0 2px; }
    QScrollBar::handle:vertical:hover { background: #B4B2A9; }
    QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
    QScrollBar::handle:horizontal { background: #CCCCC8; border-radius: 3px; min-width: 30px; margin: 2px 0; }
    QScrollBar::handle:horizontal:hover { background: #B4B2A9; }
    QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
    QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


# ── main window ───────────────────────────────────────────────────────────────

class TrackerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 820)
        self.setMinimumSize(980, 600)
        self.setStyleSheet(STYLESHEET)

        self.editing = None            # the card being edited on the dashboard (✎ Edit)
        self.adopted_key = store.adopt_inventory_key()
        self.cfg = store.load_config()
        self.url = self.cfg.get("current") or (self.cfg["sheets"][0]["url"] if self.cfg["sheets"] else "")
        self.data = store.load_cache(self.url) if self.url else None
        self.source = None
        self.can_edit = False
        self.last_sync = None
        self.pages = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.net_pool = QThreadPool(self)          # update checks, kept off the sheet queue
        self._tasks = set()

        self._build_ui()
        if self.data:
            self._show_data(self.data)

        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self._sync(quiet=True))
        self.timer.start(REFRESH_MS)
        QTimer.singleShot(0, self._start)
        QTimer.singleShot(1500, self._check_for_update)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._check_for_update)
        self.update_timer.start(3600 * 1000)          # and again every hour

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 14, 20, 10)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(_small_label("Release"))
        self.release = QComboBox()
        self.release.setMinimumWidth(260)
        self.release.setMaximumWidth(420)
        self.release.setMinimumHeight(32)
        self.release.activated.connect(self._on_release_picked)
        top.addWidget(self.release)
        top.addStretch(1)
        self.export_btn = QPushButton("⬇ Export snapshot")
        self.export_btn.setToolTip("Save a PNG + PDF snapshot of the charts for a date range")
        self.export_btn.clicked.connect(self._export)
        self.open_btn = QPushButton("Open in Google Sheets ↗")
        self.open_btn.clicked.connect(self._open_sheet)
        self.sync_btn = QPushButton("↻ Sync")
        self.sync_btn.setToolTip("Pull the latest data from the Google Sheet, and the Testing tickets "
                                 "from JIRA if you have a JIRA token (⌘R)")
        self.sync_btn.clicked.connect(lambda: self._sync(quiet=False))
        settings_btn = QPushButton("⚙ Settings")
        settings_btn.clicked.connect(lambda: self._open_settings())
        for b in (self.export_btn, self.open_btn, self.sync_btn, settings_btn):
            top.addWidget(b)
        root.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.setTabBar(ui_theme.segmented_tab_bar())
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)       # no line under the tabs
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_menu)
        self._peek = None                           # a hidden tab opened for now (e.g. from "Open table")
        self.dashboard = Dashboard(self)
        self.date_bar = DateBar(self)
        dash_page = QWidget()
        dash_lay = QVBoxLayout(dash_page)
        dash_lay.setContentsMargins(0, 0, 0, 0)
        dash_lay.setSpacing(0)
        self.view_bar = ViewBar(self)
        dash_lay.addWidget(self.view_bar)
        self.view_bar.refresh()
        dash_lay.addWidget(self.date_bar)
        dash_lay.addWidget(self.dashboard, 1)
        self.tabs.addTab(dash_page, "📊 Dashboard")
        self.changelog_page = ChangeLogPage(self)
        self.tabs.addTab(self.changelog_page, "📝 Change Log")
        self.testing_page = FeatureTestingPage(self)
        self.tabs.addTab(self.testing_page, "🧪 Feature Testing")
        self._dash_layout = dash_lay
        self.tabs.currentChanged.connect(self._place_date_bar)
        self._tab_at = 0
        self.tabs.currentChanged.connect(self._tab_motion)
        self.tabs.currentChanged.connect(self._unpeek)
        QTimer.singleShot(0, self._place_tabs)          # tabs hidden on this computer
        self.empty = QLabel("Add your test-tracking Google Sheet in ⚙ Settings to get started.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(f"color:{MUTED}; font-size:14px;")
        self.dashboard.setWidget(self.empty)
        root.addWidget(self.tabs, 1)

        status_row = QHBoxLayout()
        self.status_lbl = _small_label("Ready.", MUTED)
        self.conn_lbl = _small_label("")
        self.jira_lbl = _small_label("")
        self.jira_lbl.mousePressEvent = lambda e: (self.sync_testing(force=True)
                                                   if changelog.has_credentials() else None)
        self.update_btn = QPushButton()
        self.update_btn.setObjectName("update")
        self.update_btn.hide()
        self.update_btn.clicked.connect(self._install_update)
        status_row.addWidget(self.status_lbl, 1)
        status_row.addWidget(self.update_btn)
        status_row.addSpacing(10)
        status_row.addWidget(self.conn_lbl)
        status_row.addSpacing(10)
        status_row.addWidget(self.jira_lbl)
        version_btn = QPushButton(f"v{APP_VERSION}" + (" testing" if APP_CHANNEL == "testing" else ""))
        version_btn.setObjectName("link")
        version_btn.setStyleSheet(f"color:{MUTED}; font-size:11px; margin-left:6px;")
        version_btn.setCursor(Qt.PointingHandCursor)
        version_btn.setToolTip("Check for updates")
        version_btn.clicked.connect(lambda: self._check_for_update(manual=True))
        news_btn = QPushButton("What's new")
        news_btn.setObjectName("link")
        news_btn.setStyleSheet(f"color:{MUTED}; font-size:11px; margin-left:4px;")
        news_btn.setCursor(Qt.PointingHandCursor)
        news_btn.setToolTip("What changed in each version")
        news_btn.clicked.connect(lambda: self.show_whats_new())
        status_row.addWidget(news_btn)
        status_row.addWidget(version_btn)
        root.addLayout(status_row)

        QShortcut(QKeySequence("Ctrl+R"), self, lambda: self._sync(quiet=False))
        self._fill_releases()
        QTimer.singleShot(1200, self._whats_new_after_update)

    # ── what's new ────────────────────────────────────────────────────────────

    def show_whats_new(self, since=None):
        dlg = WhatsNewDialog(self, since)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.show()                                  # not modal: the app keeps working behind it
        return dlg

    def _whats_new_after_update(self):
        """Opens What's new once, the first time a new version starts (not on a first install)."""
        seen = self.cfg.get("seen_version")
        if seen == APP_VERSION:
            return
        self.cfg["seen_version"] = APP_VERSION
        store.save_config(self.cfg)
        if not seen and self.cfg.get("sheets"):      # set up before versions were remembered (≤ 2.4.11)
            older = [h for v, h, _ in _changelog_sections(_changelog_text())
                     if v and v < _version_tuple(APP_VERSION)]
            seen = older[0] if older else None
        if seen and _version_tuple(APP_VERSION) > _version_tuple(seen):
            self.show_whats_new(since=seen)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, msg):
        self.status_lbl.setText(msg)

    def _set_conn(self, state, detail=""):
        text, color = {
            "none":       ("● No sheet yet", MUTED),
            "connecting": ("● Connecting to Google Sheets…", AMBER),
            "sheets":     (f"● Google Sheets · synced {self.last_sync:%H:%M}" if self.last_sync
                           else "● Google Sheets", GREEN),
            "offline":    ("● Offline — showing last synced data", RED),
        }[state]
        self.can_edit = state == "sheets"
        self.conn_lbl.setText(text)
        self.conn_lbl.setStyleSheet(f"color:{color}; font-size:11px;")
        self.conn_lbl.setToolTip(detail)
        for page in self.pages.values():
            page._update_buttons()

    def _set_jira(self, state=None, detail=""):
        """The JIRA dot beside the Google Sheets one: when Feature Testing was last synced from
        JIRA (saved in the sheet, so everyone sees it), or syncing / failed in the admin's app."""
        if state is None:
            state = "syncing" if getattr(self, "_testing_busy", False) else getattr(self, "_jira_state", "ok")
        self._jira_state = state if state in ("failed",) else "ok"
        synced = ((self.data or {}).get("testing") or {}).get("synced") or ""
        try:
            when = datetime.fromisoformat(synced)
        except ValueError:
            when = None
        if when is None:
            stamp = ""
        elif when.date() == date.today():
            stamp = f"{when:%H:%M}"
        else:
            stamp = f"{when:%b %-d %H:%M}"
        stale = when is None or (datetime.now() - when).total_seconds() > 3 * feature_testing.SYNC_MINUTES * 60
        if state == "syncing":
            text, color = "● JIRA · syncing…", AMBER
        elif state == "failed":
            text, color = "● JIRA sync failed" + (f" · last {stamp}" if stamp else ""), RED
        elif when is None:
            text, color = "● JIRA · not synced yet", MUTED
        else:
            text, color = f"● JIRA · synced {stamp}", AMBER if stale else GREEN
        mine = changelog.has_credentials()
        tip = detail or ("Feature Testing, from JIRA's Testing tickets. " +
                         ("Synced by your app every few minutes — click to sync now." if mine
                          else "Synced by the admin's app every few minutes."))
        self.jira_lbl.setText(text)
        self.jira_lbl.setStyleSheet(f"color:{color}; font-size:11px;")
        self.jira_lbl.setToolTip(tip)
        self.jira_lbl.setCursor(Qt.PointingHandCursor if mine else Qt.ArrowCursor)

    def _fill_releases(self):
        self.release.blockSignals(True)
        self.release.clear()
        for s in self.cfg["sheets"]:
            self.release.addItem(s.get("title") or s["url"], s["url"])
        self.release.addItem("+ Add another release…", "__add__")
        i = self.release.findData(self.url)
        self.release.setCurrentIndex(max(i, 0) if self.cfg["sheets"] else 0)
        self.release.blockSignals(False)

    def _on_release_picked(self, i):
        url = self.release.itemData(i)
        if url == "__add__":
            self._fill_releases()
            self._open_settings()
            return
        if url and url != self.url:
            self._switch(url)

    def _switch(self, url):
        self.url = url
        self.cfg["current"] = url
        store.save_config(self.cfg)
        self.source = None
        self.data = store.load_cache(url)
        for page in self.pages.values():
            self.tabs.removeTab(self.tabs.indexOf(page))
            page.deleteLater()
        self.pages = {}
        if self.data:
            self._show_data(self.data)
        else:
            self.dashboard.setWidget(QLabel())
        self._fill_releases()
        self._connect()

    def set_wrap(self, on):
        """The Wrap text switch applies to every tab and is remembered."""
        self.cfg["wrap_text"] = on
        store.save_config(self.cfg)
        for page in self.pages.values():
            page.set_wrap(on)

    def _export(self):
        if not self.data:
            QMessageBox.information(self, "Nothing to export yet", "Connect to a release sheet first.")
            return
        dlg = ExportDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        png, pdf = dlg.paths()
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            snap = dlg.snapshot()
            png = snap.save_png(png)[0]
            snap.save_pdf(pdf)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Couldn't export", f"{type(exc).__name__}: {exc}")
            return
        QApplication.restoreOverrideCursor()
        self._set_status(f"Saved {os.path.basename(png)} and .pdf")
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", png])          # show them in Finder
        else:
            _open_link(QUrl.fromLocalFile(os.path.dirname(png)).toString())

    def _open_sheet(self):
        page = self.tabs.currentWidget()
        if isinstance(page, TabPage):
            _open_link(store.tab_url(self.url, page.model.tab))
        elif self.url:
            _open_link(self.url)

    def go_to_cell(self, title, sheet_row, pos):
        """Open a tab's table with one cell selected (e.g. a run's Notes)."""
        page = self.pages.get(title)
        if page is None:
            return
        self._reveal(title)
        self.tabs.setCurrentWidget(page)
        page.go_to_cell(sheet_row, pos)

    def show_tab(self, title, filters=None):
        page = self.pages.get(title)
        if page is None:
            return
        self._reveal(title)
        self.tabs.setCurrentWidget(page)
        if filters:
            page.show_only(filters)

    # ── hidden tabs (this computer only; the sheet is unchanged) ──────────────

    # ── dashboard tiles (this computer only) ──────────────────────────────────

    def tile_settings(self):
        """{tab title: {"hidden": bool, "sql", "show", "simple", "label"}} for this sheet."""
        return self.cfg.setdefault("tiles", {}).setdefault(self.url or "", {})

    def set_tile(self, title, hidden=None, stat=False):
        """Hide/show a tile, and/or set its stat (a dict from TileDialog; None = built-in)."""
        conf = self.tile_settings()
        t = dict(conf.get(title) or {})
        if hidden is not None:
            t["hidden"] = hidden
        if stat is not False:
            for k in ("sql", "show", "simple", "label"):
                t.pop(k, None)
            t.update(stat or {})
        t = {k: v for k, v in t.items() if v not in (None, False, "")}
        if t:
            conf[title] = t
        else:
            conf.pop(title, None)
        store.save_config(self.cfg)
        if self.data:
            self.dashboard.set_data(self.data)

    def hidden_cards(self):
        return self.cfg.setdefault("hidden_cards", {}).setdefault(self.url or "", [])

    def set_card_hidden(self, keys, hide):
        keys = [keys] if isinstance(keys, str) else keys
        cur = self.hidden_cards()
        for k in keys:
            if hide and k not in cur:
                cur.append(k)
            elif not hide and k in cur:
                cur.remove(k)
        store.save_config(self.cfg)
        if self.data:
            self.dashboard.set_data(self.data)
        if hide and len(keys) == 1:
            self._set_status(f"Hid {keys[0].split('::')[0]} card. Show ▾ (top of the dashboard) "
                             "brings it back.")

    def card_view(self, key):
        """A split card's view on this computer: "all", a section name, or "split" (default)."""
        return self.cfg.setdefault("card_views", {}).setdefault(self.url or "", {}).get(key, "split")

    def set_card_view(self, key, mode):
        views_ = self.cfg.setdefault("card_views", {}).setdefault(self.url or "", {})
        if mode == "split":
            views_.pop(key, None)
        else:
            views_[key] = mode
        store.save_config(self.cfg)

    def edit_tile(self, tab):
        dlg = TileDialog(self, tab, self.tile_settings().get(tab["title"]))
        if dlg.exec_() == QDialog.Accepted:
            self.set_tile(tab["title"], stat=dlg.result_tile())

    def hidden_tabs(self):
        return self.cfg.setdefault("hidden_tabs", {}).setdefault(self.url or "", [])

    def _builtin_tabs(self):
        """(name, page, label) for the app's own tabs that can be hidden (not the Dashboard)."""
        return [("Change Log", self.changelog_page, "📝 Change Log"),
                ("Feature Testing", self.testing_page, "🧪 Feature Testing")]

    def _place_tabs(self, data=None):
        """After the Dashboard: Change Log, Feature Testing, then one page per sheet tab in
        the sheet's order — leaving out the ones hidden on this computer."""
        data = data or self.data
        hidden = set(self.hidden_tabs()) - {self._peek}
        self._placing = True
        try:
            self._place(data, hidden)
        finally:
            self._placing = False

    def _place(self, data, hidden):
        order = list(self._builtin_tabs())
        for tab in (data or {}).get("tabs", []):
            page = self.pages.get(tab["title"])
            if page is None:
                page = TabPage(self, tab)
                self.pages[tab["title"]] = page
            elif page.model.tab is not tab:
                page.set_tab(tab)
            order.append((tab["title"], page, tab["title"]))
        at = 1
        for name, page, label in order:
            i = self.tabs.indexOf(page)
            if name in hidden:
                if i >= 0:
                    if self.tabs.currentWidget() is page:
                        self.tabs.setCurrentIndex(0)
                    self.tabs.removeTab(self.tabs.indexOf(page))
                continue
            if i != at:
                if i >= 0:
                    self.tabs.removeTab(i)
                self.tabs.insertTab(at, page, label)
            if name in self.pages and store.readonly_tab(self.pages[name].model.tab):
                self.tabs.setTabToolTip(at, "Filled in automatically; read-only here")
            at += 1

    def set_tab_hidden(self, title, hide):
        hidden = self.hidden_tabs()
        if hide and title not in hidden:
            hidden.append(title)
        elif not hide and title in hidden:
            hidden.remove(title)
        if self._peek == title:
            self._peek = None
        store.save_config(self.cfg)
        self._place_tabs()
        page = self.pages.get(title) or next((p for n, p, _ in self._builtin_tabs() if n == title), None)
        if not hide and page is not None:
            self.tabs.setCurrentWidget(page)
        self._set_status(f"Hid “{title}” from the top bar on this computer." if hide
                         else f"Showing “{title}” again.")

    def _reveal(self, title):
        """Opening a hidden tab from the dashboard shows it for now, without un-hiding it."""
        if title in self.hidden_tabs() and self._peek != title:
            self._peek = title
            self._place_tabs()
            self._placing = True                    # the caller selects it next
            QTimer.singleShot(0, lambda: setattr(self, "_placing", False))

    def _unpeek(self, _=None):
        """Leaving a hidden tab that was opened for now hides it again."""
        if getattr(self, "_placing", False):
            return
        if self._peek and self.tabs.currentWidget() is not self.pages.get(self._peek):
            self._peek = None
            QTimer.singleShot(0, self._place_tabs)

    def _tab_menu(self, pos):
        bar = self.tabs.tabBar()
        i = bar.tabAt(pos)
        page = self.tabs.widget(i) if i >= 0 else None
        named = {p: n for n, p, _ in self._builtin_tabs()}
        named.update({p: t for t, p in self.pages.items()})
        title = named.get(page)                      # None for the Dashboard: it always stays
        menu = QMenu(self)
        if title:
            menu.addAction(f"Hide “{title}” from the top bar", lambda: self.set_tab_hidden(title, True))
        known = set(named.values())
        hidden = [t for t in self.hidden_tabs() if t in known]
        sub = menu.addMenu("Hidden tabs") if hidden else None
        for t in hidden:
            sub.addAction(f"Show “{t}”", lambda t=t: self.set_tab_hidden(t, False))
        if not hidden:
            none = menu.addAction("No hidden tabs")
            none.setEnabled(False)
        menu.addSeparator()
        note = menu.addAction("Only on this computer; the sheet isn't changed")
        note.setEnabled(False)
        menu.exec_(bar.mapToGlobal(pos))

    # ── background runner ─────────────────────────────────────────────────────

    def _run(self, fn, on_done, on_error=None, busy_msg=None):
        if busy_msg:
            self._set_status(busy_msg)
            self.sync_btn.setEnabled(False)
        task = _Task(fn)

        def finish():
            self._tasks.discard(task)
            if busy_msg:
                self.sync_btn.setEnabled(True)

        task.signals.done.connect(lambda r: (finish(), on_done(r)))
        task.signals.failed.connect(lambda e: (finish(), (on_error or self._on_error)(e)))
        self._tasks.add(task)
        self.pool.start(task)

    def _on_error(self, exc, note="Your change was not saved."):
        msg = store.describe_error(exc)
        self._set_status(msg.splitlines()[0])
        if store.is_connection_error(exc):          # a refused save isn't being offline
            self._set_conn("offline", msg)
        QMessageBox.warning(self, "Problem", f"{msg}\n\n{note}".strip())

    # ── connecting & syncing ──────────────────────────────────────────────────

    def _start(self):
        if not self.cfg["sheets"]:
            self._set_conn("none")
            self._open_settings(first_run=True)
            return
        self._connect()

    def _connect(self):
        if not self.url:
            self._set_conn("none")
            return
        url = self.url
        self._set_conn("connecting")
        self._run(lambda: store.SheetSource(url), self._on_connected, self._on_connect_failed,
                  busy_msg="Connecting to Google Sheets…")

    def _on_connected(self, source):
        if source.url != self.url:
            return                              # the user switched release meanwhile
        self.source = source
        self._run(source.fetch, lambda d: self._on_fetched(d, "Loaded from Google Sheets."),
                  lambda e: self._on_connect_failed(e), busy_msg="Loading…")

    def _on_connect_failed(self, exc):
        msg = store.describe_error(exc)
        self._set_conn("offline", msg)
        self._set_status("Not connected to Google Sheets. Click ↻ Sync to retry.")
        extra = ("\n\nShowing the last synced data. Editing is paused until the connection works."
                 if self.data else "")
        QMessageBox.warning(self, "Couldn't connect to Google Sheets", msg + extra)

    def _sync(self, quiet):
        if self.source is None:
            if not quiet:
                self._connect()
            return
        if quiet and (self._tasks or self._busy_editing()):
            return            # something is running, or someone is mid-edit; skip this tick
        src = self.source

        def fetched(d):
            self._on_fetched(d, None if quiet else "Synced.")
            if not quiet:
                self.sync_testing(now=True)          # the Sync button refreshes JIRA too
        self._run(src.fetch, fetched,
                  on_error=(lambda e: self._set_conn("offline", store.describe_error(e))) if quiet
                           else (lambda e: self._on_error(e, note="")),
                  busy_msg=None if quiet else "Syncing…")

    def _busy_editing(self):
        return QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None \
            or any(p.view.state() == QAbstractItemView.EditingState for p in self.pages.values())

    def _on_fetched(self, data, msg=None):
        if data["url"] != self.url:
            return
        self.last_sync = datetime.now()
        self._set_conn("sheets")
        for s in self.cfg["sheets"]:
            if s["url"] == data["url"] and s.get("title") != data["title"]:
                s["title"] = data["title"]
                store.save_config(self.cfg)
                self._fill_releases()
        self._show_data(data)
        store.save_cache(self.url, data)
        if msg:
            self._set_status(msg)

    def _show_data(self, data):
        self.data = data
        charts.set_overrides(store.color_overrides(data.get("settings")))
        charts.register(data)
        self.view_bar.refresh()                   # shared views may have changed in the sheet
        self.changelog_page.refresh()
        self.testing_page.refresh()
        self._set_jira()
        QTimer.singleShot(1500, self.sync_testing)      # keep the JIRA testing data fresh (admin's app)
        self.setWindowTitle(f"{APP_TITLE} — {data['title']}")
        titles = [t["title"] for t in data["tabs"]]
        for title in list(self.pages):
            if title not in titles:
                page = self.pages.pop(title)
                if self.tabs.indexOf(page) >= 0:
                    self.tabs.removeTab(self.tabs.indexOf(page))
                page.deleteLater()
        self._place_tabs(data)
        self.date_bar.refresh()
        self.dashboard.set_data(data)

    # ── writing ───────────────────────────────────────────────────────────────

    def _after_write(self, msg):
        self._set_status(msg)
        store.save_cache(self.url, self.data)
        self.dashboard.set_data(self.data)
        QTimer.singleShot(1500, lambda: self._sync(quiet=True))    # pick up the sheet's formatting

    def write_cell(self, tab, snapshot, col, new, old, link=None, force=False):
        if self.source is None:
            return
        src = self.source
        label = f"{col['name']} → “{new or 'blank'}”"
        self._run(lambda: src.write_cell(tab, snapshot, col, new, old, link, force),
                  lambda _: self._after_write(f"Saved {label}."),
                  lambda exc: self._write_failed(exc, tab, snapshot, col, new, link),
                  busy_msg=f"Saving {label}…")

    def _write_failed(self, exc, tab, snapshot, col, new, link):
        if isinstance(exc, store.ConflictError) and exc.current is not None:
            reply = QMessageBox.question(
                self, "Changed by someone else",
                f"Since your last sync, someone changed {col['name']} in this row to:\n\n"
                f"   “{exc.current or 'blank'}”\n\nReplace it with yours?\n\n   “{new or 'blank'}”",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.write_cell(tab, snapshot, col, new, exc.current, link, force=True)
                return
            self._set_status("Kept their change.")
        elif isinstance(exc, store.ConflictError):
            QMessageBox.information(self, "Row changed", str(exc))
        else:
            self._on_error(exc)
        self._sync(quiet=False)          # show what's really in the sheet

    def add_row(self, tab, values, links):
        if self.source is None:
            return
        src = self.source
        self._run(lambda: src.add_row(tab, values, links),
                  lambda how: (self._set_status("Row added." if how == "appended"
                                                else f"Filled in row {values.get(0, '')}."),
                               self._sync(quiet=False)),
                  lambda exc: (self._on_error(exc), self._sync(quiet=True)),
                  busy_msg="Adding row…")

    # ── settings ──────────────────────────────────────────────────────────────

    def _open_settings(self, first_run=False):
        dlg = SettingsDialog(self, self.cfg, first_run)
        if self.adopted_key and first_run:
            self._set_status("Using the service-account key from Qave Inventory.")
        if dlg.exec_() != QDialog.Accepted:
            return
        if dlg._new_creds:
            store.install_credentials(dlg._new_creds)
        self.cfg["sheets"] = dlg.sheets
        look = dlg.appearance.currentData()
        look_changed = look != self.cfg.get("appearance", "light")
        self.cfg["appearance"] = look
        store.save_config(self.cfg)
        if look_changed and QMessageBox.question(
                self, "Appearance", "Restart Test Tracker now to switch its look?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            self._restart()
            return
        urls = [s["url"] for s in dlg.sheets]
        new = getattr(dlg, "new_url", None)
        target = new if new in urls else (self.url if self.url in urls else (urls[0] if urls else ""))
        self._fill_releases()
        if target != self.url or dlg._new_creds or self.source is None:
            if target:
                self._switch(target)
            else:
                self.url = ""
                self._set_conn("none")

    # ── card layouts ──────────────────────────────────────────────────────────

    def layout_of(self, tab):
        """The tab's card layout: the admin's saved one, or the built-in default
        (or the copy being edited, while a card of this tab is in edit mode)."""
        if self.editing and self.editing["tab"] == tab["title"]:
            return self.editing["layout"]
        return layout.layout_for(tab, _settings(self))

    def known_columns(self, tab):
        """Columns this app has already seen (or been told to ignore) on a tab, so
        only columns added later get the “New column” note. Kept on this computer."""
        sheets = self.cfg.setdefault("known_columns", {})
        known = sheets.setdefault(store.sheet_id(self.url) or self.url, {})
        key = tab["title"].strip().lower()
        if key not in known:
            known[key] = [c["name"].strip() for c in tab["columns"]]
            store.save_config(self.cfg)
        return known[key]

    def dismiss_column(self, tab, name):
        self.known_columns(tab).append(name.strip())
        store.save_config(self.cfg)
        self.dashboard.set_data(self.data)

    def layouts_elsewhere(self, tab):
        """[(release name, layout)] saved for a tab of the same name in other release sheets."""
        out = []
        for s in self.cfg["sheets"]:
            if s["url"] == self.url:
                continue
            raw = ((store.load_cache(s["url"]) or {}).get("settings") or {}).get(layout.key_for(tab))
            if raw:
                lo = layout.layout_for(tab, {layout.key_for(tab): raw})
                if lo.get("custom"):
                    out.append((s.get("title") or s["url"], lo))
        return out

    # ── views ─────────────────────────────────────────────────────────────────

    def all_views(self):
        return views.all_views(self.cfg, self.url, _settings(self)) if self.url else []

    def current_view_id(self):
        return self.cfg.setdefault("current_view", {}).get(store.sheet_id(self.url) or self.url, views.MAIN)

    def current_view(self):
        """The custom view on screen, or None for MAIN (or if it was deleted)."""
        vid = self.current_view_id()
        if vid == views.MAIN:
            return None
        return next((v for v in self.all_views() if v["id"] == vid), None)

    def set_view(self, view_id):
        if self.editing:
            self.cancel_editing()
        self.cfg.setdefault("current_view", {})[store.sheet_id(self.url) or self.url] = view_id
        store.save_config(self.cfg)
        self.view_bar.refresh()
        if self.data:
            self.dashboard.set_data(self.data, animate=True)

    def new_view(self):
        if not self.data:
            return
        name, ok = QInputDialog.getText(self, "New view", "Name your view (e.g. “EOD”, “Viking only”):")
        if not ok or not name.strip():
            return
        v = views.new_view(name)
        views.private(self.cfg, self.url).append(v)
        store.save_config(self.cfg)
        self.set_view(v["id"])
        self.view_settings()

    def _save_view(self, view, settings=None, msg=None, base=None):
        """Shared views go to the sheet (needs the unlocked admin settings); yours to this computer."""
        if view.get("shared"):
            if settings is None:
                settings = _settings(self)
                base = dict(settings)
            settings = dict(settings)
            settings[views.PREFIX + view["id"]] = views.dump(view)
            self._save_settings(settings, msg or f"Saved the shared view “{view['name']}” for everyone.", base=base)
        else:
            mine = views.private(self.cfg, self.url)
            i = next((k for k, v in enumerate(mine) if v["id"] == view["id"]), None)
            if i is None:
                mine.append(view)
            else:
                mine[i] = view
            store.save_config(self.cfg)
            self.view_bar.refresh()
            self.dashboard.set_data(self.data)
            self._set_status(msg or f"Saved the view “{view['name']}”.")

    def view_settings(self):
        view = self.current_view()
        if view is None:
            return
        settings = None
        if view["shared"]:
            box = QMessageBox(self)
            box.setWindowTitle("Shared view")
            box.setText(f"“{view['name']}” is shared with everyone. Changing it needs the admin passcode. "
                        "You can also make your own copy to change freely.")
            change = box.addButton("Change it (admin)", QMessageBox.AcceptRole)
            mine = box.addButton("Make my own copy", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Cancel)
            box.exec_()
            if box.clickedButton() is mine:
                self._duplicate_view(view)
                return
            if box.clickedButton() is not change:
                return
            unlocked = self._admin_unlock(self, "shared views")
            if not unlocked:
                return
            settings = unlocked[0]
        dlg = ViewSettingsDialog(self, view, bool(settings))
        if dlg.exec_() != QDialog.Accepted:
            return
        new = dlg.result_view()
        new["shared"] = view["shared"]
        if dlg.action == "delete":
            if QMessageBox.question(self, "Delete view", f"Delete the view “{view['name']}”"
                                    + (" for everyone?" if view["shared"] else "?"),
                                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
            if view["shared"]:
                settings = dict(settings)
                settings.pop(views.PREFIX + view["id"], None)
                self.cfg.setdefault("current_view", {})[store.sheet_id(self.url) or self.url] = views.MAIN
                self._save_settings(settings, f"Deleted the shared view “{view['name']}”.")
            else:
                mine = views.private(self.cfg, self.url)
                mine[:] = [v for v in mine if v["id"] != view["id"]]
                self.set_view(views.MAIN)
            return
        if dlg.action == "duplicate":
            self._duplicate_view(new)
            return
        if dlg.action == "share":
            unlocked = self._admin_unlock(self, "shared views")
            if not unlocked:
                return
            mine = views.private(self.cfg, self.url)
            mine[:] = [v for v in mine if v["id"] != view["id"]]
            store.save_config(self.cfg)
            new["shared"] = True
            self._save_view(new, unlocked[0], f"Shared “{new['name']}” with everyone.")
            return
        if dlg.action == "unshare":
            settings = dict(settings)
            settings.pop(views.PREFIX + view["id"], None)
            new["shared"] = False
            views.private(self.cfg, self.url).append(new)
            store.save_config(self.cfg)
            self._save_settings(settings, f"“{new['name']}” is now only on this computer.")
            return
        self._save_view(new, settings)

    def _duplicate_view(self, view):
        copy_ = views.copy_view(view)
        copy_.update(id=layout.new_id(), name=f"{view['name']} (my copy)", shared=False)
        for e in copy_["cards"]:
            if "card" in e:
                e["card"]["id"] = layout.new_id()
        views.private(self.cfg, self.url).append(copy_)
        store.save_config(self.cfg)
        self.set_view(copy_["id"])
        self._set_status(f"Made “{copy_['name']}”, your own copy.")

    # ── editing cards on the dashboard ────────────────────────────────────────
    # ✎ Edit on a card (admin passcode) works on a copy of the tab's layout; Done
    # editing saves it to the sheet for everyone, Cancel throws it away.

    def _tab(self, title):
        if title == layout.CUSTOM:
            return layout.custom_tab()
        return next((t for t in (self.data or {}).get("tabs", []) if t["title"] == title), None)

    def start_editing(self, tab, card_id, add_column=None):
        if self.editing and (self.editing["tab"], self.editing["card"]) != (tab["title"], card_id):
            if QMessageBox.question(self, "Still editing", "Save the card you're editing first?",
                                    QMessageBox.Save | QMessageBox.Discard) == QMessageBox.Save:
                self.finish_editing()
            else:
                self.cancel_editing()
        view = self.current_view()
        if view is not None:                      # a card of a custom view
            settings = stored = None
            if view["shared"]:
                unlocked = self._admin_unlock(self, "shared views")
                if not unlocked:
                    return
                settings, stored = unlocked
            self.editing = {"tab": tab["title"], "card": card_id, "view": view["id"],
                            "view_obj": views.copy_view(view), "shared": view["shared"],
                            "settings": settings, "stored": stored,
                            "base": getattr(self, "_settings_base", None)}
            self._redraw()
            self._set_status("Editing a card of “" + view["name"] + "” — Done editing saves it"
                             + (" for everyone." if view["shared"] else "."))
            return
        unlocked = self._admin_unlock(self, "dashboard cards")
        if not unlocked:
            return
        settings, stored = unlocked
        lo = layout.copy_layout(layout.layout_for(tab, settings))
        card = next((c for c in lo["cards"] if c["id"] == card_id), lo["cards"][0] if lo["cards"] else None)
        self.editing = {"tab": tab["title"], "card": card["id"] if card else None, "layout": lo,
                        "settings": settings, "stored": stored, "base": getattr(self, "_settings_base", None)}
        self.dashboard.set_data(self.data)
        if card:
            self._set_status(f"Editing {layout.card_title(tab, card)} — Done editing saves it for everyone.")
        if add_column:
            col = layout.find_column(tab, add_column)
            spec = default_spec(tab)
            spec.update(group=add_column.strip(), show="pie" if col and col["kind"] == "dropdown" else "bars")
            if col and col["kind"] == "date":
                spec.update(show="days")
            self.add_chart(tab, card, spec=spec)

    def _edit_card(self, card_id=None):
        e = self.editing
        if not e:
            return None
        if e.get("view"):
            return next((x["card"] for x in e["view_obj"]["cards"]
                         if "card" in x and x["card"]["id"] == (card_id or e["card"])), None)
        return next((c for c in e["layout"]["cards"] if c["id"] == (card_id or e["card"])), None)

    def _redraw(self):
        self.dashboard.set_data(self.data)

    def cancel_editing(self):
        e, self.editing = self.editing, None
        if e and e.get("settings") and e["settings"].get(store.PASSCODE_KEY) != e["stored"]:
            self._save_settings(e["settings"], "Admin passcode set.", base=e.get("base"))
        self._redraw()
        self._set_status("Changes thrown away.")

    def finish_editing(self):
        e, self.editing = self.editing, None
        if not e:
            return
        if e.get("view"):
            vo = e["view_obj"]
            vo["shared"] = e["shared"]
            self._save_view(vo, e["settings"], base=e.get("base"))
            return
        tab = self._tab(e["tab"])
        settings = dict(e["settings"])
        key = layout.key_for({"title": e["tab"]})
        if e.get("reset"):
            settings.pop(key, None)
        else:
            lo = dict(e["layout"], columns=[c["name"].strip() for c in (tab or {}).get("columns", [])])
            settings[key] = layout.dump(lo)
        if tab and not layout.is_custom(tab):
            known = self.known_columns(tab)
            known += [c["name"].strip() for c in tab["columns"] if c["name"].strip() not in known]
            store.save_config(self.cfg)
        self._redraw()
        merge = None
        if tab and not e.get("reset") and e.get("base") is not None:
            merge = {key: _card_merger(tab, e["base"], e["layout"], settings[key])}
        self._save_settings(settings, f"Saved the {e['tab']} cards for everyone.", base=e.get("base"),
                            merge=merge)

    def new_custom_card(self):
        """+ New card on the dashboard: a card not tied to one tab. Opens it for editing with the
        Add chart form ready; Done editing saves it for everyone (Cancel throws it away)."""
        if self.current_view() is not None:
            QMessageBox.information(self, "New card", "Custom cards go on the main dashboard. Switch "
                                    "to Main, or add a card to this view from its settings.")
            return
        name, ok = QInputDialog.getText(self, "New card", "Card title:")
        if not ok or not name.strip():
            return
        tab = layout.custom_tab()
        if self.editing:
            self.start_editing(tab, None)              # asks to save the card being edited first
            if not self.editing or self.editing["tab"] != layout.CUSTOM:
                return
        else:
            self.start_editing(tab, None)
            if not self.editing:
                return                                 # passcode cancelled
        card = layout.new_custom_card(name.strip())
        self.editing["layout"]["cards"].append(card)
        self.editing["card"] = card["id"]
        self.editing["reset"] = False
        self._redraw()
        self._set_status(f"New card “{card['title']}” — add charts, then Done editing saves it for everyone.")
        QTimer.singleShot(0, lambda: self.add_chart(tab, card))

    def edit_card_scope(self, tab, card):
        """✎ Edit → 📅 Dates & filters…: kept in the copy being edited (Done editing saves it)."""
        dlg = CardScopeDialog(self, tab, card)
        if dlg.exec_() != QDialog.Accepted:
            return
        own = dlg.result()
        if own["on"] or card.get("own"):
            card["own"] = own
        self._redraw()
        self._set_status("Card dates & filters changed — Done editing saves them for everyone.")

    def edit_card_colors(self, tab, card):
        """✎ Edit → Colours…: the card's own colours, kept in the copy being edited (Done
        editing saves them to the sheet for everyone)."""
        others = {}                               # key → [(card title, colour)], other cards first found
        for t in self.data.get("tabs", []):
            try:
                cards = self.layout_of(t)["cards"]
            except Exception:
                continue
            for c in cards:
                if c is card or (t["title"] == tab["title"] and c["id"] == card["id"]):
                    continue
                for key, color in (c.get("colors") or {}).items():
                    others.setdefault(key, []).append((layout.card_title(t, c), color))
        dlg = CardColorsDialog(self, tab, card, others)
        if dlg.exec_() != QDialog.Accepted:
            return
        if dlg.colors:
            card["colors"] = dlg.colors
        else:
            card.pop("colors", None)
        self._redraw()
        self._set_status("Card colours changed — Done editing saves them for everyone.")

    def card_settings(self, tab, card):
        e = self.editing
        dlg = CardSettingsDialog(self, tab, card, e.get("layout"), in_view=bool(e.get("view")))
        if dlg.exec_() != QDialog.Accepted:
            return
        if e.get("view"):                          # a view's own card
            cards = e["view_obj"]["cards"]
            if dlg.action == "delete":
                cards[:] = [x for x in cards if x.get("card") is not card]
                self.finish_editing()
                return
            dlg.apply()
            if dlg.action == "new":
                name, ok = QInputDialog.getText(self, "New card", "Card title:")
                if ok and name.strip():
                    new = {"id": layout.new_id(), "title": name.strip(), "dash": True, "export": True,
                           "combine": False, "split": None, "blocks": []}
                    cards.append({"tab": tab["title"], "card": new})
                    e["card"] = new["id"]
            self._redraw()
            return
        if dlg.action == "reset":
            if QMessageBox.question(self, "Reset to built-in",
                                    f"Go back to the app's own charts for every {tab['title']} card? "
                                    "This applies to everyone when you click Done editing.",
                                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                e["layout"] = layout.default_layout(tab, _settings(self))
                e["card"] = e["layout"]["cards"][0]["id"]
                e["reset"] = True
        elif dlg.action == "delete":
            e["layout"]["cards"] = [c for c in e["layout"]["cards"] if c is not card]
            e["card"] = e["layout"]["cards"][0]["id"]
        else:
            dlg.apply()
            if dlg.action == "new":
                name, ok = QInputDialog.getText(self, "New card", "Card title:")
                if ok and name.strip():
                    new = {"id": layout.new_id(), "title": name.strip(), "dash": True, "export": True,
                           "combine": False, "split": None, "blocks": []}
                    e["layout"]["cards"].append(new)
                    e["card"] = new["id"]
            e["reset"] = False
        self._redraw()

    def add_chart(self, tab, card, spec=None):
        dlg = AddChartDialog(self, tab)
        if spec:
            dlg._loading = True
            dlg._load(spec, None)
            dlg._loading = False
            dlg._changed()
        if dlg.exec_() == QDialog.Accepted:
            self.insert_block(tab, card, dlg.result_block())

    def insert_block(self, tab, card, b):
        card = self._edit_card(card["id"]) or card
        card["blocks"].append(b)
        self.editing["reset"] = False
        self._redraw()

    def _block(self, card, block_id):
        card = self._edit_card(card["id"])
        i = next((k for k, b in enumerate(card["blocks"]) if b["id"] == block_id), None) if card else None
        return card, i

    def edit_block(self, tab, card, block_id):
        card, i = self._block(card, block_id)
        if i is None:
            return
        b = card["blocks"][i]
        if b["type"] != "sql" and spec_from_block(tab, b) is None:
            title, ok = QInputDialog.getText(
                self, "Edit chart", f"“{layout.auto_title(tab, b)}” is one of the app's own charts "
                "(it isn't a simple count, so it can't become a query). You can rename it:",
                text=b.get("title") or layout.auto_title(tab, b))
            if ok:
                b["title"] = title.strip() if title.strip() != layout.auto_title(tab, dict(b, title="")) else ""
                self._redraw()
            return
        dlg = AddChartDialog(self, tab, b)
        if dlg.exec_() == QDialog.Accepted:
            card["blocks"][i] = dlg.result_block()
            self.editing["reset"] = False
            self._redraw()

    def duplicate_block(self, tab, card, block_id):
        card, i = self._block(card, block_id)
        if i is not None:
            nb = layout.copy_layout(card["blocks"][i])
            nb.update(id=layout.new_id(), new_row=False)
            card["blocks"].insert(i + 1, nb)
            self._redraw()

    def remove_block(self, tab, card, block_id):
        card, i = self._block(card, block_id)
        if i is not None:
            removed = card["blocks"].pop(i)
            if removed.get("new_row") and i < len(card["blocks"]):
                card["blocks"][i]["new_row"] = True       # keep the next chart on its own row
            self._redraw()

    def set_block(self, tab, card, block_id, **changes):
        card, i = self._block(card, block_id)
        if i is not None:
            card["blocks"][i].update(changes)
            self.editing["reset"] = False
            self._redraw()

    def move_block(self, tab, card, src_id, target_id, after):
        card, i = self._block(card, src_id)
        _, j = self._block(card, target_id)
        if i is None or j is None or i == j:
            return
        blocks_ = card["blocks"]
        b = blocks_.pop(i)
        if b.get("new_row") and i < len(blocks_):
            blocks_[i]["new_row"] = True                  # the chart after it keeps its row start
        j = next(k for k, x in enumerate(blocks_) if x["id"] == target_id)
        if after:
            b["new_row"] = False
            blocks_.insert(j + 1, b)
        else:                                             # take the target's place in its row
            b["new_row"], blocks_[j]["new_row"] = blocks_[j].get("new_row", False), False
            blocks_.insert(j, b)
        self._redraw()

    # ── admin: chart colours ──────────────────────────────────────────────────

    def _admin_unlock(self, parent, what):
        """Ask for the admin passcode (or set one the first time). Returns
        (settings, passcode hash before) or None if cancelled / wrong."""
        if not (self.data and self.can_edit and self.source):
            QMessageBox.information(parent, "Not connected",
                                    "Connect to the Google Sheet first, then try again.")
            return None
        settings = dict(self.data.get("settings") or {})
        self._settings_base = dict(settings)       # what this change starts from (see _save_settings)
        stored = settings.get(store.PASSCODE_KEY)
        if not stored:
            dlg = NewPasscodeDialog(parent)
            if dlg.exec_() != QDialog.Accepted:
                return None
            settings[store.PASSCODE_KEY] = store.hash_passcode(dlg.passcode())
            self.admin_unlocked = self.url
        elif getattr(self, "admin_unlocked", None) != self.url:
            code, ok = QInputDialog.getText(parent, "Admin passcode",
                                            f"Enter the admin passcode to change {what}:",
                                            QLineEdit.Password)
            if not ok:
                return None
            if not store.check_passcode(code, stored):
                QMessageBox.warning(parent, "Wrong passcode",
                                    "That passcode isn't right.\n\nForgot it? See “Admin "
                                    "passcode” in the README for how to reset it.")
                return None
            self.admin_unlocked = self.url          # don't ask again until the app restarts
        return settings, stored

    def open_colors(self, parent=None):
        unlocked = self._admin_unlock(parent or self, "chart colours")
        if not unlocked:
            return
        settings, stored = unlocked
        dlg = ColorsDialog(self, self.data, store.color_overrides(settings))
        if dlg.exec_() != QDialog.Accepted:
            if settings.get(store.PASSCODE_KEY) != stored:
                self._save_settings(settings, "Admin passcode set.")   # keep a newly set passcode
            return
        settings = {k: v for k, v in settings.items() if not k.startswith(store.COLOR_PREFIX)}
        settings.update({store.COLOR_PREFIX + k: v for k, v in dlg.overrides.items()})
        if dlg.changed_passcode:
            settings[store.PASSCODE_KEY] = store.hash_passcode(dlg.changed_passcode)
        self._save_settings(settings, "Chart colours saved for everyone.")

    def open_columns(self, parent=None):
        unlocked = self._admin_unlock(parent or self, "filters")
        if not unlocked:
            return
        settings, stored = unlocked
        dlg = ColumnsDialog(self, self.data, settings)
        if dlg.exec_() != QDialog.Accepted:
            if settings.get(store.PASSCODE_KEY) != stored:
                self._save_settings(settings, "Admin passcode set.")
            return
        self._save_settings(dlg.result_settings(), "Filters saved for everyone.")

    def _save_settings(self, settings, msg, base=None, merge=None):
        """Save shared settings. Only what changed from `base` (the copy this change started
        from: by default the one taken at the admin passcode) is written, on top of the
        sheet as it is now. So two admins changing different things — cards, colours, views —
        no longer undo each other's work: before, the whole copy was written back, putting
        back anything another admin had changed since this app's last sync."""
        if base is None:
            base = getattr(self, "_settings_base", None)
        if base is None:
            base = (self.data or {}).get("settings") or {}
        changes = {k: settings.get(k) for k in set(base) | set(settings) if settings.get(k) != base.get(k)}
        for k, fn in (merge or {}).items():       # keys that merge with the sheet's value instead
            if k in changes:
                changes[k] = fn
        src = self.source
        def saved(merged):
            self.data["settings"] = merged
            self._show_data(self.data)
            store.save_cache(self.url, self.data)
            self._set_status(msg if changes else "Nothing to save.")
        if not changes:
            self._set_status("Nothing changed.")
            return
        self._run(lambda: src.update_settings(changes), saved, busy_msg="Saving settings…")

    # ── updates ───────────────────────────────────────────────────────────────

    def _check_for_update(self, manual=False):
        """Look for a newer release on GitHub. Runs at launch, every hour, and when
        the version number in the bottom-right corner is clicked."""
        def latest():
            import requests          # bundles its own certificates, unlike urllib in the built app
            if APP_CHANNEL == "testing":         # testing builds also see newer testing builds
                found = _fetch_releases()
                if not found:
                    raise RuntimeError("no release found")
                self._latest_zip = found[0]["zip"]
                return found[0]["tag"]
            self._latest_zip = None
            try:
                r = requests.get(f"https://api.github.com/repos/{REPO}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json"}, timeout=8)
                r.raise_for_status()
                return r.json()["tag_name"]
            except Exception:
                # GitHub's API allows 60 checks an hour per network; the release page
                # has no such limit, and redirects to …/releases/tag/vX.Y.Z
                r = requests.head(f"https://github.com/{REPO}/releases/latest",
                                  allow_redirects=True, timeout=8)
                r.raise_for_status()
                tag = r.url.rstrip("/").rsplit("/", 1)[-1]
                if not _version_tuple(tag):
                    raise RuntimeError("no release found")
                return tag

        task = _Task(latest)

        def got(tag):
            self._tasks.discard(task)
            if _version_tuple(tag) > _version_tuple(APP_VERSION):
                self.latest = tag
                self.update_btn.setText(f"⬆ Update to {tag}")
                self.update_btn.setToolTip("A newer version is available. Click to install it.")
                self.update_btn.show()
                if manual:
                    self._install_update()
            elif manual:
                QMessageBox.information(self, "No updates",
                                        f"You have the latest version (v{APP_VERSION}).")

        def failed(exc):
            self._tasks.discard(task)
            if manual:
                reply = QMessageBox.question(
                    self, "Couldn't check for updates",
                    f"Couldn't reach GitHub to check for updates ({type(exc).__name__}).\n\n"
                    "Open the releases page in your browser instead?",
                    QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    _open_link(f"https://github.com/{REPO}/releases/latest")

        task.signals.done.connect(got)
        task.signals.failed.connect(failed)
        self._tasks.add(task)
        self.net_pool.start(task)

    def _install_update(self):
        if not (getattr(sys, "frozen", False) and sys.platform == "darwin"):
            _open_link(f"https://github.com/{REPO}/releases/latest")
            return
        reply = QMessageBox.question(
            self, "Update Test Tracker",
            f"Install {self.latest} now?\n\nThe app will close, update, and reopen by itself "
            "in about a minute. Nothing in the sheet is affected.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return
        self._run_installer(getattr(self, "_latest_zip", None))

    def _run_installer(self, zip_url=None):
        """Download and install a release (the newest stable one unless zip_url is given);
        the app closes, updates, and reopens by itself."""
        env = dict(os.environ)
        if zip_url:
            env["TRACKER_ZIP_URL"] = zip_url
        subprocess.Popen(["/bin/bash", "-c", INSTALL_CMD], start_new_session=True, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._set_status("Installing… the app will reopen by itself.")
        QTimer.singleShot(800, QApplication.quit)

    def open_versions(self, parent=None):
        dlg = VersionsDialog(self)
        if dlg.exec_() != QDialog.Accepted or not dlg.chosen():
            return
        r = dlg.chosen()
        if not (getattr(sys, "frozen", False) and sys.platform == "darwin"):
            _open_link(f"https://github.com/{REPO}/releases/tag/{r['tag']}")
            return
        reply = QMessageBox.question(
            parent or self, "Install another version",
            f"Install {r['tag']} ({'testing build' if r['testing'] else 'stable'}) in place of "
            f"v{APP_VERSION}?\n\nThe app will close, install it, and reopen by itself in about a minute.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            self._run_installer(r["zip"])

    def _tab_motion(self, i):
        """The page you picked slides in from its tab's side (left of the last one, or right)."""
        page, old = self.tabs.widget(i), self.tabs.widget(self._tab_at)
        if page is not None and old is not None and i != self._tab_at and self.isVisible():
            motion.switch_page(page.parentWidget(), old, page, 28 if i > self._tab_at else -28)
        self._tab_at = i

    def _place_date_bar(self, *_):
        """One Dates bar for the dashboard and the Feature Testing tab: it moves to whichever is open."""
        if self.tabs.currentWidget() is self.testing_page:
            if self.date_bar.parent() is not self.testing_page:
                self.testing_page.date_slot.addWidget(self.date_bar)
        elif self.date_bar.parent() is self.testing_page:
            self._dash_layout.insertWidget(1, self.date_bar)       # back under the view bar
        self.date_bar.refresh()

    # ── feature testing from JIRA ─────────────────────────────────────────────

    def sync_testing(self, force=False, now=False):
        """Read the Testing tickets from JIRA and save them to the sheet's hidden tab, so
        everyone sees them. Only the app with the JIRA token does this, at most every few
        minutes (or now, with force)."""
        import time
        if not (self.data and self.source and self.can_edit and changelog.has_credentials()):
            if force:
                QMessageBox.information(self, "Can't sync", "Connect to the sheet, and add your JIRA token "
                                        "(Change Log → Tokens…), then try again.")
            return
        if getattr(self, "_testing_busy", False):
            return
        if not (force or now) and time.time() - getattr(self, "_testing_at", 0) < feature_testing.SYNC_MINUTES * 60:
            return
        self._testing_busy, self._testing_at = True, time.time()
        self._set_jira("syncing")
        query, src = feature_testing.jql(_settings(self)), self.source
        inst_query = feature_testing.inst_jql(_settings(self))

        def work():
            snap = feature_testing.snapshot(query, inst_query=inst_query)
            src.save_testing(feature_testing.to_rows(snap))
            return snap

        def done(snap):
            self._testing_busy = False
            self.data["testing"] = snap
            store.save_cache(self.url, self.data)
            self.testing_page.refresh()
            self._set_jira("ok")
            if force or now:
                self._set_status(f"Synced the sheet and {len(snap['tickets'])} Testing tickets from JIRA."
                                 if now else f"Synced {len(snap['tickets'])} Testing tickets from JIRA.")

        def failed(exc):
            self._testing_busy = False
            self._set_jira("failed", f"Couldn't sync from JIRA: {exc}")
            if force:
                QMessageBox.warning(self, "Couldn't sync from JIRA", str(exc))
            else:
                self._set_status(f"Feature testing sync: {exc}")

        self._run(work, done, failed, busy_msg="Syncing feature testing from JIRA…" if force else None)

    def set_bug_kind(self, ref, kind):
        """Admin: correct whether a bug linked in a test session was new or seen again."""
        unlocked = self._admin_unlock(self, "bug labels in feature testing")
        if not unlocked:
            return
        settings = dict(unlocked[0])
        settings[feature_testing.BUG_KIND_PREFIX + ref] = kind
        self._save_settings(settings, f"Marked {ref.rpartition(':')[2]} as "
                            + ("a new bug." if kind == "new" else "seen again."))

    def set_instrument_hidden(self, key, hide):
        """Admin: hide an instrument from Feature Testing's Instruments (and the export) for everyone,
        or show it again."""
        unlocked = self._admin_unlock(self, "hiding instruments")
        if not unlocked:
            return
        settings = dict(unlocked[0])
        settings[feature_testing.HIDE_INST_PREFIX + key] = "1" if hide else ""
        self._save_settings(settings, f"{'Hid' if hide else 'Showing'} {key.upper()} in Instruments.")

    def edit_testing_jql(self):
        unlocked = self._admin_unlock(self, "the feature-testing JQL")
        if not unlocked:
            return
        settings = unlocked[0]
        dlg = QDialog(self)
        dlg.setWindowTitle("Feature testing JQL")
        dlg.setMinimumWidth(640)
        edit = QPlainTextEdit(feature_testing.jql(settings))
        edit.setMinimumHeight(140)
        inst = QPlainTextEdit(feature_testing.inst_jql(settings))
        inst.setMinimumHeight(90)
        lay_ = QVBoxLayout(dlg)
        lay_.addWidget(_small_label("Which JIRA tickets count as feature testing. Saved in the sheet; your app "
                                    "syncs them for everyone.", MUTED))
        lay_.addWidget(edit)
        head = QLabel("Instruments")
        head.setStyleSheet("font-weight:bold; padding-top:8px;")
        lay_.addWidget(head)
        lay_.addWidget(_small_label('Instruments to always show, with every open ticket whose title names them. '
                                    'Each summary ~ "…" is one instrument (e.g. summary ~ "Proto-0028*"). '
                                    'Hardware support requests logged in test sessions still show for any '
                                    'other instrument. Leave empty to only use the test sessions.', MUTED))
        lay_.addWidget(inst)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay_.addWidget(buttons)
        if dlg.exec_() != QDialog.Accepted:
            return
        settings = dict(settings)
        settings[feature_testing.JQL_KEY] = " ".join(edit.toPlainText().split())
        settings[feature_testing.INST_JQL_KEY] = " ".join(inst.toPlainText().split())
        self._save_settings(settings, "Feature-testing JQL saved.")
        QTimer.singleShot(500, lambda: self.sync_testing(force=True))

    def _restart(self):
        """Quit and open the app again (e.g. to switch light / dark)."""
        if getattr(sys, "frozen", False) and sys.platform == "darwin":
            bundle = os.path.abspath(os.path.join(os.path.dirname(sys.executable), "..", ".."))
            subprocess.Popen(["/bin/sh", "-c", f'sleep 1; open -n "{bundle}"'], start_new_session=True)
        else:
            subprocess.Popen([sys.executable] + sys.argv, start_new_session=True)
        QTimer.singleShot(200, QApplication.quit)

    def closeEvent(self, event):
        self.pool.waitForDone(5000)     # let an in-flight save finish
        super().closeEvent(event)


ERROR_LOG = os.path.join(store.DATA_DIR, "errors.log")

def _install_error_net():
    """An unexpected Python error is written to errors.log and shown as a message, instead of
    PyQt's default of closing the app on the spot. A hard crash (inside Qt) also leaves its
    stack in errors.log, so it can be found afterwards."""
    import faulthandler, traceback
    try:
        if os.path.exists(ERROR_LOG) and os.path.getsize(ERROR_LOG) > 2_000_000:
            os.replace(ERROR_LOG, ERROR_LOG + ".old")
        log = open(ERROR_LOG, "a", encoding="utf-8")
        log.write(f"\n── started v{APP_VERSION} at {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        log.flush()
        faulthandler.enable(log)
    except OSError:
        log = None
    showing = [False]

    def hook(kind, value, tb):
        text = "".join(traceback.format_exception(kind, value, tb))
        sys.__stderr__.write(text)
        if log:
            log.write(f"\n{datetime.now():%Y-%m-%d %H:%M:%S} v{APP_VERSION}\n{text}")
            log.flush()
        if showing[0] or QApplication.instance() is None:
            return
        showing[0] = True
        try:
            QMessageBox.warning(QApplication.activeWindow(), "Something went wrong",
                                f"That didn't work: {kind.__name__}: {value}\n\nThe app is still running. "
                                f"Details were saved to:\n{ERROR_LOG}")
        finally:
            showing[0] = False
    sys.excepthook = hook


if __name__ == "__main__":
    _install_error_net()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")   # consistent look on all platforms including macOS
    dark_mode = ui_theme.wants_dark(store.load_config().get("appearance", "light"))
    # dark mode restyles labels in the modules that make them: this window, the ui/ windows and cards
    ui_theme.install(dark_mode, modules=[sys.modules[__name__], blocks]
                     + [m for n, m in list(sys.modules.items()) if n.startswith("ui.")])
    app.setPalette(ui_theme.palette())
    window = TrackerApp()
    window.show()
    sys.exit(app.exec_())
