"""
⚙ Settings, the admin passcode, chart colours, and the JIRA / GitHub tokens.
"""

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QFrame, QDialog, QFormLayout, QDialogButtonBox, QFileDialog,
    QComboBox, QScrollArea, QListWidget, QListWidgetItem, QSizePolicy, QColorDialog)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from dashboard import charts
from data import store
from integrations import changelog

from app_info import APP_CHANNEL, APP_VERSION
from ui.common import MUTED, _small_label, _visible_rows


# ── settings ──────────────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    """Releases (one Google Sheet link each) and the service-account key."""

    def __init__(self, parent, cfg, first_run=False):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(620)
        self._new_creds = None
        self.sheets = [dict(s) for s in cfg["sheets"]]

        intro = None
        if first_run:
            intro = QLabel("<b>Welcome!</b> Paste the link to your team's test-tracking Google "
                           "Sheet below and click <b>Add</b>. Ask Shiv for the link and the key "
                           "file if you don't have them.")
            intro.setWordWrap(True)

        self.list = QListWidget()
        self.list.setMinimumHeight(110)
        self._fill_list()
        self.url = QLineEdit()
        self.url.setPlaceholderText("Paste a Google Sheet link: https://docs.google.com/spreadsheets/d/…")
        self.url.returnPressed.connect(self._add)
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(self._remove)
        add_row = QHBoxLayout()
        add_row.addWidget(self.url, 1)
        add_row.addWidget(add)
        add_row.addWidget(remove)

        self.creds_lbl = QLabel()
        self.creds_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.creds_lbl.setWordWrap(True)
        pick = QPushButton("Choose key file…")
        pick.clicked.connect(self._pick)
        creds_row = QHBoxLayout()
        creds_row.addWidget(self.creds_lbl, 1)
        creds_row.addWidget(pick)
        self._show_creds(store.CREDS_FILE)

        hint = _small_label(
            "Each release can be its own Google Sheet (File → Make a copy), or a new tab in "
            "the same sheet. New tabs show up by themselves; new sheets are added here.\n"
            "Share every sheet with the service-account email above as an Editor.", MUTED)
        hint.setWordWrap(True)

        colors_btn = QPushButton("🎨 Default chart colours…")
        colors_btn.setToolTip("Admin only: the colours every card uses unless it has its own "
                              "(✎ Edit → Colours… on a card), for everyone")
        colors_btn.clicked.connect(lambda: parent.open_colors(self))
        colors_btn.setEnabled(bool(parent.data) and parent.can_edit)
        columns_btn = QPushButton("🔎 Filters…")
        columns_btn.setToolTip("Admin only: choose which columns get filter buttons. "
                               "Charts are chosen with ✎ Customize on each dashboard card.")
        columns_btn.clicked.connect(lambda: parent.open_columns(self))
        columns_btn.setEnabled(bool(parent.data) and parent.can_edit)
        versions_btn = QPushButton("Versions…")
        versions_btn.setToolTip("Install another version, e.g. go back to the stable build")
        versions_btn.clicked.connect(lambda: parent.open_versions(self))
        admin_row = QHBoxLayout()
        admin_row.addWidget(colors_btn)
        admin_row.addWidget(columns_btn)
        admin_row.addWidget(_small_label("🔒 Needs the admin passcode. Applies to everyone "
                                         "using this release sheet.", MUTED), 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        if intro:
            root.addWidget(intro)
        root.addWidget(_small_label("Release sheets"))
        root.addWidget(self.list)
        root.addLayout(add_row)
        root.addSpacing(6)
        root.addWidget(_small_label("Service account (the robot account the app signs in with)"))
        root.addLayout(creds_row)
        root.addWidget(hint)
        root.addSpacing(6)
        root.addWidget(_small_label("Admin"))
        root.addLayout(admin_row)
        root.addSpacing(6)
        self.appearance = QComboBox()
        for label, key in (("Light", "light"), ("Dark", "dark"), ("Match macOS", "system")):
            self.appearance.addItem(label, key)
        self.appearance.setCurrentIndex(max(self.appearance.findData(cfg.get("appearance", "light")), 0))
        look = QHBoxLayout()
        look.addWidget(_small_label("Appearance"))
        look.addWidget(self.appearance)
        look.addWidget(_small_label("Applies when the app restarts. Exports have their own theme.", MUTED), 1)
        root.addSpacing(6)
        root.addLayout(look)
        ver_row = QHBoxLayout()
        ver_row.addWidget(_small_label(f"App version v{APP_VERSION}"
                                       + (" (testing build)" if APP_CHANNEL == "testing" else ""), MUTED))
        ver_row.addStretch(1)
        ver_row.addWidget(versions_btn)
        root.addLayout(ver_row)
        root.addWidget(buttons)

    def _fill_list(self):
        self.list.clear()
        for s in self.sheets:
            item = QListWidgetItem(f"{s.get('title') or 'New sheet (loads when you save)'}\n{s['url']}")
            self.list.addItem(item)

    def _add(self):
        url = self.url.text().strip()
        if not url:
            return
        if not store.sheet_id(url):
            QMessageBox.warning(self, "Not a sheet link",
                                "That doesn't look like a Google Sheets link. It should start with "
                                "https://docs.google.com/spreadsheets/d/…")
            return
        if any(store.sheet_id(s["url"]) == store.sheet_id(url) for s in self.sheets):
            self.url.clear()
            return
        self.sheets.append({"url": url, "title": ""})
        self.new_url = url
        self.url.clear()
        self._fill_list()

    def _remove(self):
        row = self.list.currentRow()
        if row >= 0:
            del self.sheets[row]
            self._fill_list()

    def _show_creds(self, path):
        email = store.service_account_email(path)
        self.creds_lbl.setText(f"✓ {email}" if email else "No key file yet")

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Service account key", "", "JSON key (*.json)")
        if not path:
            return
        if not store.service_account_email(path):
            QMessageBox.warning(self, "Not a key file",
                                "That file doesn't look like a Google service-account key.")
            return
        self._new_creds = path
        self._show_creds(path)

    def accept(self):
        if self.url.text().strip():
            self._add()
        super().accept()


# ── admin: passcode and chart colours ─────────────────────────────────────────

class NewPasscodeDialog(QDialog):
    def __init__(self, parent, title="Set an admin passcode", intro=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        lbl = QLabel(intro or "Choose a passcode for admin settings like chart colours. "
                              "Anyone who knows it can change them, so share it only with "
                              "other admins.")
        lbl.setWordWrap(True)
        root.addWidget(lbl)
        form = QFormLayout()
        self.first, self.second = QLineEdit(), QLineEdit()
        for box in (self.first, self.second):
            box.setEchoMode(QLineEdit.Password)
        form.addRow("New passcode", self.first)
        form.addRow("Type it again", self.second)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def accept(self):
        if len(self.first.text()) < 4:
            QMessageBox.warning(self, "Too short", "Use at least 4 characters.")
            return
        if self.first.text() != self.second.text():
            QMessageBox.warning(self, "Doesn't match", "The two passcodes are different.")
            return
        super().accept()

    def passcode(self):
        return self.first.text()


class ColorsDialog(QDialog):
    """Pick the colour of anything the charts color: statuses, subsystems, and the
    values of category pies (reasons, workflows…). Applies to every chart, card,
    status dot and export, for everyone."""

    def __init__(self, win, data, overrides):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Chart colours")
        self.setMinimumWidth(660)
        self.overrides = dict(overrides)
        self.changed_passcode = None
        charts.register(data)
        self.entries, self.by_key = [], {}

        def add(section, key, label, tab, default):
            if key in self.by_key:
                if tab not in self.by_key[key]["tabs"]:
                    self.by_key[key]["tabs"].append(tab)
                return
            e = {"section": section, "key": key, "label": label, "tabs": [tab], "default": default}
            self.entries.append(e)
            self.by_key[key] = e

        # 1. statuses, in order of meaning
        for tab in data["tabs"]:
            col = store.derived_columns(tab).get(store.STATUS)
            if not col:
                continue
            values = list(col["options"]) + [store.row_status(tab, r) for r in _visible_rows(tab)]
            for v in charts.status_order(dict.fromkeys(values), col["options"]):
                add("Statuses", v.strip().lower(), v.strip() or "No status", tab["title"],
                    lambda v=v, o=col["options"]: charts.status_colors([v], o, use_overrides=False)[v])
        # 2. subsystems (Subsystem At Fault pie and the component tally)
        sub_tabs = [t["title"] for t in data["tabs"] if store.fault_column(t) or store.component_column(t)]
        for sub in list(charts.SUBSYSTEM_ORDER):
            for t in sub_tabs:
                add("Subsystems", f"{charts.SUBSYSTEM_KEY}:{sub.lower()}", sub, t,
                    lambda sub=sub: charts.subsystem_color(sub, use_overrides=False))
        # 3. each category pie's values (Reason for Error Runs, Workflow Type…)
        for tab in data["tabs"]:
            for c in tab["columns"]:
                col = c["name"].strip().lower()
                if col not in charts.CATEGORY_ORDER or c is store.fault_column(tab):
                    continue
                for v in list(charts.CATEGORY_ORDER.get(col, [])):
                    add(c["name"].strip(), f"{col}:{v.lower()}", v, tab["title"],
                        lambda col=col, v=v: charts.category_color(col, v, use_overrides=False))
        self.sections = list(dict.fromkeys(e["section"] for e in self.entries))
        self.preview_section = self.sections[0] if self.sections else None

        intro = QLabel("Click a colour to change it. Your choices are saved in the sheet, so "
                       "everyone sees them after their next sync, on the dashboard and in exports. "
                       "Anything you don't change keeps its built-in colour. Green is kept for "
                       "finished statuses (Done, Completed, Results…).")
        intro.setWordWrap(True)
        self.rows = QGridLayout()
        self.rows.setHorizontalSpacing(12)
        self.rows.setVerticalSpacing(6)
        self.swatches, self.resets = {}, {}
        i = 0
        for section in self.sections:
            head = _small_label(section.upper(), "#888885", 10)
            head.setStyleSheet("color:#888885; font-size:10px; font-weight:bold; margin-top:8px;")
            self.rows.addWidget(head, i, 0, 1, 4)
            i += 1
            for e in [e for e in self.entries if e["section"] == section]:
                key = e["key"]
                sw = QPushButton()
                sw.setFixedSize(46, 26)
                sw.setCursor(Qt.PointingHandCursor)
                sw.clicked.connect(lambda _, k=key: self._pick(k))
                name = QLabel(e["label"])
                name.setStyleSheet("font-size:13px;")
                where = _small_label(", ".join(e["tabs"]), MUTED)
                where.setToolTip("Used in: " + ", ".join(e["tabs"]))
                where.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)   # shrink, keep Reset visible
                reset = QPushButton("Reset")
                reset.setObjectName("link")
                reset.setToolTip("Go back to the built-in colour")
                reset.clicked.connect(lambda _, k=key: self._reset(k))
                self.swatches[key], self.resets[key] = sw, reset
                self.rows.addWidget(sw, i, 0)
                self.rows.addWidget(name, i, 1)
                self.rows.addWidget(where, i, 2)
                self.rows.addWidget(reset, i, 3)
                i += 1
        self.rows.setColumnStretch(2, 1)
        inner = QWidget()
        inner.setLayout(self.rows)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        scroll.setMinimumHeight(min(32 * i + 10, 400))

        self.preview = charts.DonutChart()
        preview_box = QFrame()
        preview_box.setObjectName("card")
        pl = QVBoxLayout(preview_box)
        self.preview_lbl = _small_label("PREVIEW", "#888885", 10)
        pl.addWidget(self.preview_lbl)
        pl.addWidget(self.preview)

        reset_all = QPushButton("Reset all to built-in colours")
        reset_all.clicked.connect(self._reset_all)
        passcode_btn = QPushButton("Change admin passcode…")
        passcode_btn.clicked.connect(self._change_passcode)
        extra = QHBoxLayout()
        extra.addWidget(reset_all)
        extra.addWidget(passcode_btn)
        extra.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        save = buttons.addButton("Save for everyone", QDialogButtonBox.AcceptRole)
        save.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addWidget(intro)
        if not self.entries:
            root.addWidget(_small_label("Nothing in this sheet is colored yet.", MUTED))
        root.addWidget(scroll)
        root.addWidget(preview_box)
        root.addLayout(extra)
        root.addWidget(buttons)
        self.resize(720, 760)
        self._refresh()

    def color(self, key):
        return self.overrides.get(key) or self.by_key[key]["default"]()

    def _refresh(self):
        for key, sw in self.swatches.items():
            c = self.color(key)
            sw.setStyleSheet(f"QPushButton {{ background:{c}; border:1px solid #BDBBB6; border-radius:5px; }}"
                             f"QPushButton:hover {{ border:2px solid #1A1A18; }}")
            sw.setToolTip(f"{c.upper()} — click to change")
            self.resets[key].setVisible(key in self.overrides)
        shown = [e for e in self.entries if e["section"] == self.preview_section][:10]
        self.preview_lbl.setText(f"PREVIEW · {(self.preview_section or '').upper()}")
        self.preview.set_data([(e["label"], 1, self.color(e["key"])) for e in shown], ("", ""))

    def _pick(self, key):
        e = self.by_key[key]
        self.preview_section = e["section"]
        self._refresh()
        c = QColorDialog.getColor(QColor(self.color(key)), self, f"Colour for {e['label']}")
        if c.isValid():
            self.overrides[key] = c.name().upper()
            self._refresh()

    def _reset(self, key):
        self.overrides.pop(key, None)
        self.preview_section = self.by_key[key]["section"]
        self._refresh()

    def _reset_all(self):
        self.overrides.clear()
        self._refresh()

    def _change_passcode(self):
        dlg = NewPasscodeDialog(self, "Change admin passcode", "Choose a new admin passcode. "
                                "It takes effect when you click Save for everyone.")
        if dlg.exec_() == QDialog.Accepted:
            self.changed_passcode = dlg.passcode()


class TokensDialog(QDialog):
    """GitHub and JIRA tokens for making change logs. Kept in this Mac's Keychain."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Change log tokens")
        self.setMinimumWidth(620)
        creds = changelog.credentials()
        intro = QLabel(
            "To make change logs, the app reads <b>VitalBio/device-sw</b>'s history using your existing "
            "<b>SSH access to GitHub</b> (no GitHub token needed), and the <b>PROD</b> tickets in JIRA using "
            "a JIRA API token. It's kept in this Mac's Keychain, never in the sheet. Coworkers don't need "
            "any of this: the change logs you make are saved to the sheet for everyone.")
        intro.setWordWrap(True)
        self.gh = QLineEdit(creds["github"])
        self.gh.setEchoMode(QLineEdit.Password)
        self.gh.setPlaceholderText("github_pat_…")
        self.email = QLineEdit(creds["jira_email"])
        self.email.setPlaceholderText("you@vitalbio.com")
        self.jira = QLineEdit(creds["jira"])
        self.jira.setEchoMode(QLineEdit.Password)
        self.gh.setPlaceholderText("optional — leave empty to use your SSH access")
        gh_help = QLabel('Optional. Leave it empty: the app uses git over your SSH key. A <a href="https://github.com/'
                         'settings/personal-access-tokens/new">GitHub token</a> (fine-grained, VitalBio/device-sw, '
                         'Contents + Pull requests read-only) also lets it read PR descriptions.')
        jira_help = QLabel('<a href="https://id.atlassian.com/manage-profile/security/api-tokens">Create a '
                           'JIRA API token</a> — signed in as the email above.')
        for lbl in (gh_help, jira_help):
            lbl.setWordWrap(True)
            lbl.setOpenExternalLinks(True)
            lbl.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.result = _small_label("", MUTED)
        self.result.setWordWrap(True)
        test = QPushButton("Test")
        test.clicked.connect(self._test)
        form = QFormLayout()
        form.addRow("GitHub token", self.gh)
        form.addRow("", gh_help)
        form.addRow("JIRA email", self.email)
        form.addRow("JIRA token", self.jira)
        form.addRow("", jira_help)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(test)
        bottom.addWidget(self.result, 1)
        bottom.addWidget(buttons)
        root = QVBoxLayout(self)
        root.addWidget(intro)
        root.addLayout(form)
        root.addLayout(bottom)

    def _test(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        bits = []
        try:
            if self.gh.text().strip():
                bits.append("GitHub ✓ " + changelog.test_github(self.gh.text().strip()))
            else:
                bits.append(f"GitHub over SSH ✓ ({changelog.REPO} at {changelog.test_git()})")
        except Exception as exc:
            bits.append(f"GitHub ✗ {exc}")
        try:
            bits.append("JIRA ✓ " + changelog.test_jira(self.email.text().strip(), self.jira.text().strip()))
        except Exception as exc:
            bits.append(f"JIRA ✗ {exc}")
        QApplication.restoreOverrideCursor()
        self.result.setText(" · ".join(bits))

    def accept(self):
        try:
            changelog.set_secret("github-token", self.gh.text().strip())
            changelog.set_secret("jira-email", self.email.text().strip())
            changelog.set_secret("jira-token", self.jira.text().strip())
        except Exception as exc:
            QMessageBox.warning(self, "Couldn't save", str(exc))
            return
        super().accept()
