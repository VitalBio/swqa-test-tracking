"""
The Change Log tab: what changed between two software versions.
"""

import html

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QDialog,
    QComboBox, QTextBrowser)
from PyQt5.QtCore import Qt, QTimer

from integrations import changelog

from ui.common import MUTED, _small_label
from ui.settings_dialogs import TokensDialog


class ChangeLogPage(QWidget):
    """What changed between two software versions: PRs and the PROD tickets they touched."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.logs, self.log = [], None
        self.filter_cat = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 10, 0, 0)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(_small_label("Change log"))
        self.pick = QComboBox()
        self.pick.setMinimumWidth(460)
        self.pick.currentIndexChanged.connect(self._picked)
        top.addWidget(self.pick)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setObjectName("link")
        self.delete_btn.clicked.connect(self._delete)
        top.addWidget(self.delete_btn)
        top.addStretch(1)
        self.from_v, self.to_v = QComboBox(), QComboBox()
        for box in (self.from_v, self.to_v):
            box.setEditable(True)
            box.setMinimumWidth(200)
            box.lineEdit().setPlaceholderText("version or git hash")
        self.make = QPushButton("Make change log")
        self.make.setObjectName("primary")
        self.make.clicked.connect(self._generate)
        tokens = QPushButton("Tokens…")
        tokens.setObjectName("link")
        tokens.clicked.connect(self._tokens)
        self.maker = QWidget()
        mk = QHBoxLayout(self.maker)
        mk.setContentsMargins(0, 0, 0, 0)
        mk.addWidget(_small_label("From"))
        mk.addWidget(self.from_v)
        mk.addWidget(QLabel("→"))
        mk.addWidget(self.to_v)
        mk.addWidget(self.make)
        mk.addWidget(tokens)
        top.addWidget(self.maker)
        self.setup_link = QPushButton("Make change logs (admin)…")
        self.setup_link.setObjectName("link")
        self.setup_link.clicked.connect(self._tokens)
        top.addWidget(self.setup_link)
        root.addLayout(top)

        self.tiles = QHBoxLayout()
        self.tiles.setSpacing(10)
        self.tile_btns = {}
        for cat in changelog.CATEGORIES + [changelog.IN_QA]:
            b = QPushButton()
            b.setCheckable(True)
            b.setMinimumHeight(72)
            b.setToolTip("Show only PRs whose JIRA ticket is in QA (click again to show all)"
                         if cat == changelog.IN_QA else f"Show only {cat} (click again to show all)")
            b.setStyleSheet(f"QPushButton {{ border-left:4px solid {changelog.CATEGORY_COLORS[cat]}; "
                            f"background:#FFFFFF; border-radius:8px; }}"
                            f"QPushButton:checked {{ background:#E1F5EE; border-color:#1D9E75; }}")
            inner = QVBoxLayout(b)
            inner.setContentsMargins(14, 8, 10, 8)
            inner.setSpacing(0)
            num, name = QLabel("0"), QLabel(cat)
            num.setStyleSheet("font-size:24px; font-weight:bold; color:#1A1A18;")
            name.setStyleSheet("font-size:12px; color:#52514E;")
            for lbl in (num, name):
                lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
                inner.addWidget(lbl)
            b.num = num
            b.clicked.connect(lambda on, c=cat: self._filter(c if on else None))
            self.tile_btns[cat] = b
            self.tiles.addWidget(b, 1)
        root.addLayout(self.tiles)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title, author, PR, PROD key, hash…")
        self.search.textChanged.connect(self._render)
        root.addWidget(self.search)
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        self.body.setStyleSheet("QTextBrowser { background:#FFFFFF; border:1px solid #E6E4E0; border-radius:10px; }")
        root.addWidget(self.body, 1)
        self._progress = ""
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self._progress and self.win._set_status(self._progress))

    # ── data ──────────────────────────────────────────────────────────────────

    def refresh(self):
        data = self.win.data or {}
        self.logs = changelog.saved(data.get("settings"))
        keep = self.log["id"] if self.log else None
        self.pick.blockSignals(True)
        self.pick.clear()
        for l in self.logs:
            when = l.get("generated", "")[:10]
            self.pick.addItem(f"{l['from']}  →  {l['to']}   ·  made {when}", l["id"])
        if not self.logs:
            self.pick.addItem("No change logs yet", None)
        i = self.pick.findData(keep)
        self.pick.setCurrentIndex(max(i, 0))
        self.pick.blockSignals(False)
        versions = changelog.versions_in(data)
        for box in (self.from_v, self.to_v):
            text = box.currentText()
            box.clear()
            box.addItems(versions)
            box.setEditText(text)
        if not self.from_v.currentText() and len(versions) > 1:
            self.from_v.setEditText(versions[1])
            self.to_v.setEditText(versions[0])
        admin = changelog.has_credentials()
        self.maker.setVisible(admin)
        self.setup_link.setVisible(not admin)
        self.delete_btn.setVisible(admin and bool(self.logs))
        self._picked()

    def _picked(self, *_):
        lid = self.pick.currentData()
        self.log = next((l for l in self.logs if l["id"] == lid), None)
        self._render()

    def _filter(self, cat):
        self.filter_cat = cat
        for c, b in self.tile_btns.items():
            b.setChecked(c == cat)
        self._render()

    # ── making one ────────────────────────────────────────────────────────────

    def _tokens(self):
        if TokensDialog(self.win).exec_() == QDialog.Accepted:
            self.refresh()

    def _generate(self):
        a, b = self.from_v.currentText().strip(), self.to_v.currentText().strip()
        if not a or not b or a == b:
            QMessageBox.information(self, "Pick two versions", "Pick a From and a To version (or git hashes).")
            return
        unlocked = self.win._admin_unlock(self, "change logs")
        if not unlocked:
            return
        settings, base = unlocked[0], self.win._settings_base   # it saves later, after generating

        def work():
            return changelog.generate(a, b, progress=lambda m: setattr(self, "_progress", m))

        def done(log):
            self.timer.stop()
            self._progress = ""
            self.log = log
            self.win._save_settings(changelog.save(settings, log),
                                    f"Change log {a} → {b} saved for everyone "
                                    f"({len(log['entries'])} PRs, {log['commits']} commits).", base=base)

        def failed(exc):
            self.timer.stop()
            self._progress = ""
            self.win._set_status("")
            QMessageBox.warning(self, "Couldn't make the change log", str(exc))

        self.timer.start(300)
        self.win._run(work, done, failed, busy_msg=f"Making the change log {a} → {b}…")

    def _delete(self):
        if not self.log:
            return
        if QMessageBox.question(self, "Delete change log", f"Delete the change log {self.log['from']} → "
                                f"{self.log['to']} for everyone?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        unlocked = self.win._admin_unlock(self, "change logs")
        if unlocked:
            lid, self.log = self.log["id"], None
            self.win._save_settings(changelog.remove(unlocked[0], lid), "Change log deleted.")

    # ── drawing ───────────────────────────────────────────────────────────────

    def _render(self, *_):
        log = self.log
        counts = {c: 0 for c in changelog.CATEGORIES}
        for e in (log or {}).get("entries", []):
            counts[e["category"]] += 1
        counts[changelog.IN_QA] = len(changelog.qa_entries(log)) if log else 0
        for c, b in self.tile_btns.items():
            b.num.setText(str(counts[c]))
            b.setEnabled(bool(log))
        if not log:
            hint = ("Pick two versions above and click <b>Make change log</b>." if changelog.has_credentials()
                    else "No change logs yet. The admin makes them; they show up here for everyone.")
            self.body.setHtml(f'<p style="color:{MUTED}; font-size:14px; padding:20px">{hint}</p>')
            return
        self.body.setHtml(change_log_html(log, self.search.text(), self.filter_cat))


def change_log_html(log, search="", only=None):
    """The change log as HTML (the Change Log tab, and the export)."""
    esc = html.escape
    q = search.strip().lower()

    qa_ids = {id(e) for e in changelog.qa_entries(log)}

    def hit(e):
        if only == changelog.IN_QA and id(e) not in qa_ids:
            return False
        if only and only != changelog.IN_QA and e["category"] != only:
            return False
        if not q:
            return True
        hay = " ".join([e["title"], e.get("author", ""), str(e.get("pr") or ""), "#" + str(e.get("pr") or ""),
                        " ".join(e.get("commits", [])), e.get("sha", "")] +
                       [t["key"] + " " + t["summary"] for t in e["tickets"]]).lower()
        return q in hay

    linked = sum(1 for e in log["entries"] if e["tickets"])
    not_done, untagged = changelog.warnings(log)
    note = (f"<b>{log['commits']} commits</b> merged between the two builds, in {len(log['entries'])} PRs; "
            f"{linked} reference a {changelog.JIRA_PROJECT} ticket.")
    if not_done:
        note += " Tickets whose JIRA status is not Done: " + ", ".join(
            f'<a href="{esc(t["url"])}">{esc(t["key"])}</a> ({esc(t["status"])})' for t in not_done) + "."
    if untagged:
        note += f" JIRA fix versions are not tagged {esc(untagged)}.x, so they're shown for reference only."
    out = [f'''
<p style="font-size:22px; font-weight:bold; margin:6px 0 2px 0">Change Log</p>
<p style="color:#52514E; margin:0 0 10px 0">{esc(log["repo"].split("/")[-1])} · made {esc(log["generated"][:10])}
from <code>git log {esc(log["base"][:7])}..{esc(log["head"][:7])}</code> and JIRA project {changelog.JIRA_PROJECT}</p>
<table cellspacing="0" cellpadding="8" style="margin-bottom:10px"><tr>
<td style="border:1px solid #E6E4E0"><span style="font-size:10px; color:#8A8984"><b>FROM</b></span><br>
<code style="font-size:14px">{esc(log["from"])}</code></td>
<td style="font-size:18px; color:#8A8984">&nbsp;→&nbsp;</td>
<td style="border:1px solid #E6E4E0"><span style="font-size:10px; color:#8A8984"><b>TO</b></span><br>
<code style="font-size:14px">{esc(log["to"])}</code></td></tr></table>
<table width="100%" cellspacing="0" cellpadding="10" style="margin-bottom:14px"><tr>
<td bgcolor="#FFF6E5" style="border-left:4px solid #F28E2B; font-size:13px">{note}</td></tr></table>''']
    # waiting on QA: the tickets, at the top (when not filtering to a category)
    qa_tickets, seen = [], set()
    for e in log["entries"]:
        if id(e) in qa_ids and hit(e):
            for t in e["tickets"]:
                if changelog.in_qa(t) and t["key"] not in seen:
                    seen.add(t["key"])
                    qa_tickets.append((t, e))
    if qa_tickets and only in (None, changelog.IN_QA):
        color = changelog.CATEGORY_COLORS[changelog.IN_QA]
        rows = "".join(
            f'<tr><td style="padding:3px 10px 3px 0; white-space:nowrap"><a href="{esc(t["url"])}">{esc(t["key"])}</a></td>'
            f'<td style="padding:3px 10px 3px 0">{esc(t["summary"])}</td>'
            f'<td style="padding:3px 10px 3px 0; white-space:nowrap; color:#993556">{esc(t["status"])}</td>'
            f'<td style="padding:3px 0; white-space:nowrap">'
            + (f'<a href="{esc(e["url"])}">PR #{e["pr"]}</a>' if e.get("pr") else esc(e["sha"])) + "</td></tr>"
            for t, e in qa_tickets)
        out.append(f'<p style="font-size:16px; font-weight:bold; margin:16px 0 6px 0">'
                   f'<span style="color:{color}">●</span> In QA '
                   f'<span style="color:#8A8984; font-weight:normal">{len(qa_tickets)} ticket'
                   f'{"s" if len(qa_tickets) != 1 else ""} waiting on QA</span></p>'
                   f'<table width="100%" cellspacing="0" cellpadding="8" style="margin-bottom:8px"><tr>'
                   f'<td bgcolor="#FCEFF4" style="border:1px solid #F4C0D1"><table cellspacing="0">{rows}'
                   f'</table></td></tr></table>')
    for cat in changelog.CATEGORIES:
        items = [e for e in log["entries"] if e["category"] == cat and hit(e)]
        if not items:
            continue
        color = changelog.CATEGORY_COLORS[cat]
        out.append(f'<p style="font-size:16px; font-weight:bold; margin:16px 0 6px 0">'
                   f'<span style="color:{color}">●</span> {esc(cat)} '
                   f'<span style="color:#8A8984; font-weight:normal">{len(items)}</span></p>')
        for e in items:
            pr = (f'<a href="{esc(e["url"])}">PR #{e["pr"]}</a>' if e.get("pr") else
                  f'<a href="{esc(e["url"])}">commit</a>')
            meta = f'{pr} &nbsp; <span style="color:#52514E">{esc(e.get("author", ""))}</span> &nbsp; ' \
                   f'<span style="color:#8A8984">{esc(e["date"])}</span> &nbsp; <code>{esc(e["sha"])}</code>'
            tickets = ""
            for t in e["tickets"]:
                chips = [x for x in (t.get("type"), t.get("priority")) if x]
                chip = "".join(f' <span style="background:#F1EFE8; color:#444441; font-size:11px">&nbsp;{esc(x)}&nbsp;</span>'
                               for x in chips)
                if t.get("status"):
                    done = t.get("status_category") == "done"
                    chip += (f' <span style="background:{"#E3F4E1" if done else "#F1EFE8"}; font-size:11px; '
                             f'color:{"#0B7A0B" if done else "#52514E"}">&nbsp;{esc(t["status"])}&nbsp;</span>')
                for v in t.get("fix_versions", []):
                    chip += f' <span style="background:#F1EFE8; color:#444441; font-size:11px">&nbsp;fix: {esc(v)}&nbsp;</span>'
                tickets += (f'<br><a href="{esc(t["url"])}">{esc(t["key"])}</a> {esc(t["summary"])}{chip}')
            out.append(f'<table width="100%" cellspacing="0" cellpadding="10" style="margin-bottom:8px">'
                       f'<tr><td style="border:1px solid #E6E4E0">'
                       f'<b style="font-size:14px">{esc(e["title"])}</b><br>{meta}'
                       f'{"<hr style=\'color:#ECEAE6\'>" + tickets[4:] if tickets else ""}</td></tr></table>')
    if not any(hit(e) for e in log["entries"]):
        out.append(f'<p style="color:{MUTED}">Nothing matches.</p>')
    return "".join(out)
