"""
Updates and release notes: What's new, and installing another version.
"""

import os, re, sys

from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QDialog, QDialogButtonBox,
    QListWidget, QListWidgetItem, QTextBrowser)
from PyQt5.QtCore import Qt

from data import store

from app_info import APP_CHANNEL, APP_VERSION, REPO
from ui.common import MUTED, _Task, _open_link, _small_label, _version_tuple


# ── what's new ────────────────────────────────────────────────────────────────

def _changelog_text():
    """CHANGELOG.md, bundled into the app by build_mac.sh (the repo root when run from source)."""
    here = getattr(sys, "_MEIPASS", None) or \
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # src/ui/ → repo root
    try:
        with open(os.path.join(here, "CHANGELOG.md"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""

def _changelog_sections(text):
    """[(version tuple or None, heading, markdown body)] in the file's order (newest first)."""
    out = []
    for m in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.S | re.M):
        head = m.group(1).strip()
        out.append((_version_tuple(head) if re.match(r"v?\d+\.\d+\.\d+", head) else None,
                    head, m.group(2).strip()))
    return out


class WhatsNewDialog(QDialog):
    """What changed in each version (from CHANGELOG.md). After an update it opens once by
    itself, showing just what's new since the version you had."""

    def __init__(self, parent, since=None):
        super().__init__(parent)
        self.setWindowTitle("What's new")
        self.resize(680, 640)
        secs = _changelog_sections(_changelog_text())
        newer = [s for s in secs if since and s[0] and s[0] > _version_tuple(since)]
        root = QVBoxLayout(self)
        root.setSpacing(10)
        title = QLabel(f"What's new in v{APP_VERSION}" if newer else "What's new")
        title.setStyleSheet("font-size:20px; font-weight:bold;")
        root.addWidget(title)
        sub = (f"Updated from v{since} · {len(newer)} version{'s' if len(newer) != 1 else ''} of changes"
               if newer else f"You have v{APP_VERSION}" + (" (testing build)" if APP_CHANNEL == "testing" else ""))
        root.addWidget(_small_label(sub, MUTED))
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setStyleSheet("QTextBrowser { background: transparent; font-size:13px; }")
        root.addWidget(self.view, 1)
        self.all_btn = QPushButton("Show every version")
        self.all_btn.setObjectName("link")
        self.all_btn.clicked.connect(lambda: (self._show(secs), self.all_btn.hide()))
        self.all_btn.setVisible(bool(newer))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(self.all_btn)
        row.addStretch(1)
        row.addWidget(buttons)
        root.addLayout(row)
        self._show(newer or secs)

    def _show(self, secs):
        mine = _version_tuple(APP_VERSION)
        md = []
        for v, head, body in secs:
            if v and v > mine:
                continue                               # e.g. a newer entry in a source checkout
            tag = "  ·  *this version*" if v == mine else ""
            md.append(f"## {head}{tag}\n\n{body}\n")
        if not md:
            md = ["No release notes in this build."]
        self.view.setMarkdown("\n".join(md))
        self.view.verticalScrollBar().setValue(0)


def _fetch_releases():
    """[{tag, name, date, testing, zip}] newest first, from GitHub (testing builds included)."""
    import requests          # bundles its own certificates, unlike urllib in the built app
    r = requests.get(f"https://api.github.com/repos/{REPO}/releases?per_page=50",
                     headers={"Accept": "application/vnd.github+json"}, timeout=10)
    r.raise_for_status()
    out = []
    for rel in r.json():
        if rel.get("draft") or not _version_tuple(rel.get("tag_name")):
            continue
        zip_url = next((a["browser_download_url"] for a in rel.get("assets", [])
                        if a["name"].endswith("-mac.zip")), None)
        if zip_url:
            out.append({"tag": rel["tag_name"], "date": (rel.get("published_at") or "")[:10],
                        "testing": bool(rel.get("prerelease")), "zip": zip_url})
    return sorted(out, key=lambda x: _version_tuple(x["tag"]), reverse=True)


def _local_builds():
    """Builds kept on this Mac (~/Library/Application Support/TestTracker/builds/Test-Tracker-X.Y.Z.zip),
    e.g. a testing build to fall back to that was never published."""
    folder = os.path.join(store.DATA_DIR, "builds")
    out = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        m = re.match(r"Test-Tracker-(\d+\.\d+\.\d+)\.zip$", name)
        if m:
            out.append({"tag": "v" + m.group(1), "date": "", "testing": True, "local": True,
                        "zip": "file://" + os.path.join(folder, name).replace(" ", "%20")})
    return out


class VersionsDialog(QDialog):
    """Install any published version — to go back to the stable build, or try a testing one."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Versions")
        self.setMinimumWidth(560)
        intro = QLabel(f"You have <b>v{APP_VERSION}</b> ({'testing build' if APP_CHANNEL == 'testing' else 'stable'}). "
                       "Pick a version to install it instead — for example to go back to the stable "
                       "build if something in a testing build isn't right. Your settings and the "
                       "sheet aren't affected.")
        intro.setWordWrap(True)
        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        self.list.addItem("Loading the list of versions from GitHub…")
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.install = buttons.addButton("Install this version", QDialogButtonBox.AcceptRole)
        self.install.setObjectName("primary")
        self.install.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        page = QPushButton("Open releases page ↗")
        page.setObjectName("link")
        page.clicked.connect(lambda: _open_link(f"https://github.com/{REPO}/releases"))
        bottom = QHBoxLayout()
        bottom.addWidget(page)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        root = QVBoxLayout(self)
        root.addWidget(intro)
        root.addWidget(self.list, 1)
        root.addLayout(bottom)
        self.releases = []
        self.task = _Task(_fetch_releases)
        self.task.signals.done.connect(self._got)
        self.task.signals.failed.connect(self._failed)
        win.net_pool.start(self.task)

    def _got(self, releases):
        releases = releases + _local_builds()
        self.releases = releases
        self.list.clear()
        newest_stable = next((r["tag"] for r in releases if not r["testing"]), None)
        for r in releases:
            bits = [r["tag"], "on this Mac" if r.get("local") else ("testing build" if r["testing"] else "stable")]
            if r["tag"] == newest_stable:
                bits[1] = "latest stable"
            if _version_tuple(r["tag"]) == _version_tuple(APP_VERSION):
                bits.append("installed")
            item = QListWidgetItem(f"{bits[0]}   ·   {' · '.join(bits[1:])}   ·   {r['date']}")
            item.setData(Qt.UserRole, r)
            self.list.addItem(item)
        if not releases:
            self.list.addItem("No published versions found.")
        self.list.currentItemChanged.connect(lambda cur, _: self.install.setEnabled(
            bool(cur and cur.data(Qt.UserRole))))

    def _failed(self, exc):
        if _local_builds():
            self._got([])
            self.list.addItem(f"Couldn't reach GitHub ({type(exc).__name__}) — showing the builds on this Mac.")
            return
        self.list.clear()
        self.list.addItem(f"Couldn't reach GitHub ({type(exc).__name__}). Try again in a minute, "
                          "or use the releases page.")

    def chosen(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None
