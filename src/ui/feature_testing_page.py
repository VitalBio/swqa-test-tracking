"""
The Feature Testing tab: sessions, efforts, instruments and bugs from JIRA.
"""

import html, re
from datetime import date, datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFrame, QComboBox,
    QScrollArea)
from PyQt5.QtCore import Qt, QTimer

from dashboard import blocks
from dashboard import charts
from integrations import changelog
from integrations import feature_testing

from ui.common import INK, MUTED, _open_link, _settings, _small_label


class FeatureTestingPage(QWidget):
    """Feature testing from JIRA's Testing tickets, in sections like the dashboard:
    Overview, What We Tested (by day), Tested in These Dates, Not Tested in These Dates.
    Uses the dashboard's date filter (the Dates bar moves here when this tab is open)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 10, 0, 0)
        root.setSpacing(4)
        top = QHBoxLayout()
        title = QLabel("Feature Testing")
        title.setStyleSheet("font-size:20px; font-weight:bold;")
        top.addWidget(title)
        top.addSpacing(10)
        self.info = _small_label("", MUTED)
        top.addWidget(self.info, 1, Qt.AlignBottom)
        self.product = QComboBox()
        for label in ("All products", "VitalOne", "Viking"):
            self.product.addItem(label, None if label.startswith("All") else label)
        self.product.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.product)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search effort, tester, build, notes, PROD key…")
        self.search.setMinimumWidth(300)
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search)
        self.jql_btn = QPushButton("JQL…")
        self.jql_btn.setObjectName("link")
        self.jql_btn.clicked.connect(self.win.edit_testing_jql)
        top.addWidget(self.jql_btn)
        root.addLayout(top)
        self.date_slot = QVBoxLayout()               # the dashboard's Dates bar sits here on this tab
        self.date_slot.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self.date_slot)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(self.scroll, 1)

    # ── pieces ────────────────────────────────────────────────────────────────

    @staticmethod
    def _card(title, sub=""):
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 16)
        v.setSpacing(10)
        head = QHBoxLayout()
        t = QLabel(title)
        t.setStyleSheet("font-size:15px; font-weight:bold;")
        head.addWidget(t)
        if sub:
            head.addWidget(_small_label(sub, MUTED), 0, Qt.AlignBottom)
        head.addStretch(1)
        v.addLayout(head)
        return card, v

    def _rich(self, text, size=12, color="#1A1A18"):
        lbl = QLabel(text)
        lbl.setTextFormat(Qt.RichText)
        lbl.setOpenExternalLinks(False)
        lbl.linkActivated.connect(self._link)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lbl.setStyleSheet(f"font-size:{size}px; color:{color};")
        return lbl

    @staticmethod
    def _pill(text, bg="#F1EFE8", fg="#52514E"):
        return (f'<span style="background-color:{bg}; color:{fg}; font-size:11px">&nbsp;'
                f'{html.escape(text)}&nbsp;</span>')

    @staticmethod
    def _jira(key, label=None):
        return (f'<a href="{changelog.JIRA_SITE}/browse/{html.escape(key)}" style="color:#2F5E9E; '
                f'text-decoration:none">{html.escape(label or key)}</a>')

    def _effort_table(self, efforts, rng, today):
        """One table: effort (with its tickets), status, assignee, sessions, last session, bugs."""
        lo, hi = (rng[0].isoformat(), rng[1].isoformat()) if rng else ("", "9999")
        th = lambda t, right=False: (f'<th align="{"right" if right else "left"}" style="color:#888885; '
                                     f'font-size:10px; padding:0 0 6px 14px">{t}</th>')
        rows = [f'<tr>{th("EFFORT")}{th("STATUS")}{th("ASSIGNEE")}{th("SESSIONS", True)}'
                f'{th("LAST SESSION", True)}{th("NEW BUGS", True)}{th("SEEN AGAIN", True)}{th("HW REQUESTS", True)}</tr>']
        cell = lambda x, right=False, first=False: (
            f'<td valign="middle" align="{"right" if right else "left"}" style="border-top:1px solid #ECEAE6; '
            f'padding:9px 0 9px {0 if first else 14}px">{x}</td>')
        for e in efforts:
            in_range = [x for x in e["sessions"] if x["date"] and lo <= x["date"] <= hi]
            chain = " → ".join(self._jira(t["key"], (f"PT{t['part']} " if len(e["tickets"]) > 1 else "") + t["key"])
                               for t in e["tickets"])
            new = bool(rng) and bool(e["tickets"][0]["created"]) and lo <= e["tickets"][0]["created"] <= hi
            name = (f'<b>{html.escape(e["name"])}</b>&nbsp; {self._pill(e["product"])}'
                    + (f'&nbsp; {self._pill("New", "#E8F1FC", "#2F5E9E")}' if new else "")
                    + f'<br><span style="font-size:11px">{chain}</span>')
            done = e["status_category"] == "done"
            if e["last"]:
                ago = (today - date.fromisoformat(e["last"])).days
                last = "today" if ago == 0 else f"{ago} day{'s' if ago != 1 else ''} ago"
                color = "#B26B00" if ago > 7 and not done else "#52514E"
            else:
                last, color = "none logged yet", "#8A8984"
            sessions = f"{len(in_range)} of {len(e['sessions'])}" if rng and e["sessions"] else str(len(e["sessions"]))
            settings = _settings(self.win)
            counted = in_range if rng else e["sessions"]      # only the sessions in the chosen dates
            kinds = {}
            for x in counted:
                for k in x["bugs"]:
                    kd = feature_testing.bug_kind(settings, x["ticket"], x, k)
                    kinds[k] = "new" if "new" in (kinds.get(k), kd) else kd
            counts = {"new": sum(v == "new" for v in kinds.values()), "seen": sum(v == "seen" for v in kinds.values())}
            hw_keys = list(dict.fromkeys(k for x in counted for k in x.get("support", [])))
            rows.append("<tr>" + cell(name, first=True)
                        + cell(self._pill(e["status"], "#E3F4E1" if done else "#F1EFE8", "#0B7A0B" if done else "#52514E"))
                        + cell(html.escape(", ".join(e["assignees"]) or "—"))
                        + cell(sessions, True)
                        + cell(f'<span style="color:{color}">{html.escape(last)}</span>', True)
                        + cell(str(counts["new"]) if counts["new"] else '<span style="color:#8A8984">—</span>', True)
                        + cell(str(counts["seen"]) if counts["seen"] else '<span style="color:#8A8984">—</span>', True)
                        + cell(str(len(hw_keys)) if hw_keys else '<span style="color:#8A8984">—</span>', True)
                        + "</tr>")
        return self._rich(f'<table width="100%" cellspacing="0" cellpadding="0">{"".join(rows)}</table>', 12)

    def _link(self, href):
        if href.startswith("kind:"):                  # kind:<ticket>#<session>:<bug>:<new kind>
            ref, _, kind = href[5:].rpartition(":")
            self.win.set_bug_kind(ref, kind)
        elif href.startswith("inst:"):                # inst:<instrument>:hide / :show
            key, _, act = href[5:].rpartition(":")
            self.win.set_instrument_hidden(key, act == "hide")
        else:
            _open_link(href)

    # ── drawing ───────────────────────────────────────────────────────────────

    def _instrument(self, inst, today, admin=False):
        """One instrument: HARDWARE SUPPORT REQUESTED with its open tickets, and when it was last tested."""
        box = QFrame()
        box.setObjectName("tile")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(14, 8, 14, 10)
        bl.setSpacing(3)
        if inst["last"]:
            e, s = inst["last"]
            d = date.fromisoformat(s["date"])
            ago = (today - d).days
            when = "today" if ago == 0 else "yesterday" if ago == 1 else f"{d:%b %-d}"
            last = (f'last tested {when} · {html.escape(e["name"])} '
                    f'{self._jira(s["ticket"], "S" + str(s["n"]))}')
        else:
            last = "no sessions logged on it"
        state = (self._pill("HARDWARE SUPPORT REQUESTED", "#FFF6E5", "#854F0B") if inst["open"] else
                 self._pill("FUNCTIONAL", "#E3F4E1", "#0B7A0B"))
        hide = (f'&nbsp; <a href="inst:{html.escape(inst["key"])}:hide" style="color:#8A8984; font-size:11px">'
                f'hide</a>') if admin else ""
        bl.addWidget(self._rich(f'<b style="font-size:14px">{html.escape(inst["name"])}</b>&nbsp; {state}'
                                f'&nbsp; <span style="color:#8A8984">{last}</span>{hide}', 13))
        for r in inst["open"]:
            kind = r.get("type") if r.get("type") and r.get("type") != "Support Request" else ""
            src = (f' · from {html.escape(r["effort"])} {self._jira(r["ticket"], r["ticket"] + " S" + str(r["n"]))}'
                   if r.get("ticket") else "")
            bl.addWidget(self._rich(
                f'{self._pill(r["status"] or "Open")}&nbsp; {self._jira(r["key"])} {html.escape(r["summary"])}'
                f'<span style="color:#8A8984">{" · " + html.escape(kind) if kind else ""}{src}</span>', 12))
        if not inst["open"]:
            bl.addWidget(self._rich("No open tickets name it.", 12, "#8A8984"))
        return box

    def refresh(self, *_):
        data = self.win.data or {}
        testing = data.get("testing")
        admin = changelog.has_credentials()
        self.jql_btn.setVisible(admin)
        body = QWidget()
        body.setObjectName("dash")
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 10, 8, 20)
        root.setSpacing(14)
        if not testing or not testing.get("tickets"):
            self.info.setText("")
            root.addWidget(_small_label("Click ↻ Sync (top right) to read the Testing tickets from JIRA." if admin else
                                        "Nothing synced from JIRA yet. The admin's app syncs the Testing "
                                        "tickets here for everyone.", MUTED))
            root.addStretch(1)
            self.scroll.setWidget(body)
            return
        try:
            when = datetime.fromisoformat(testing["synced"]).strftime("%b %-d, %H:%M")
        except (KeyError, ValueError):
            when = "?"
        n = len(testing["tickets"])
        self.info.setText(f"{n} Testing ticket{'s' if n != 1 else ''} from JIRA · synced {when}")
        d = self.win.dashboard
        rng, rtext = d.range, d.range_text
        product, q = self.product.currentData(), self.search.text().strip().lower()
        today = date.today()

        def hay(e, s=None):
            bits = [e["name"], e["status"], " ".join(e["assignees"]), " ".join(t["key"] for t in e["tickets"])]
            if s:
                bits += [s["build"], s["system"], " ".join(s["testers"]), " ".join(s["notes"]), " ".join(s["bugs"])]
            return " ".join(bits).lower()

        efforts = [e for e in feature_testing.efforts(testing) if (not product or e["product"] == product)]
        shown = [(e, s) for e, s in feature_testing.sessions_in(testing, rng)
                 if (not product or e["product"] == product) and (not q or q in hay(e, s))]
        tested_keys = {e["key"] for e in feature_testing.efforts_in(testing, rng)}
        tested = [e for e in efforts if e["key"] in tested_keys and (not q or q in hay(e))]
        untested = [e for e in efforts if e["key"] not in tested_keys and e["status_category"] != "done"
                    and (not q or q in hay(e))]
        active = [e for e in efforts if e["status_category"] != "done"]
        stale = [e for e in active if not e["last"] or (today - date.fromisoformat(e["last"])).days > 7]
        testers = {x for _, s in shown for x in s["testers"]}
        bugs = list(dict.fromkeys(k for _, s in shown for k in s["bugs"]))
        info = testing.get("support") or {}
        bug_info = testing.get("bug_info") or {}
        settings = _settings(self.win)
        kind = lambda s, k: feature_testing.bug_kind(settings, s["ticket"], s, k)
        new_bugs = list(dict.fromkeys(k for _, s in shown for k in s["bugs"] if kind(s, k) == "new"))
        seen_bugs = [k for k in dict.fromkeys(k for _, s in shown for k in s["bugs"] if kind(s, k) == "seen")
                     if k not in new_bugs]
        admin_bugs = changelog.has_credentials()
        hw = list(dict.fromkeys(k for _, s in shown for k in s.get("support", [])))
        hw_open = [k for k in hw if not feature_testing.support_resolved(info.get(k))]

        # Overview
        card, v = self._card("Overview", rtext)
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        for label, value, sub, color in (
                ("Sessions", len(shown), rtext, INK),
                ("Efforts tested", len(tested), f"{len(active)} active in JIRA", INK),
                ("Testers", len(testers), ", ".join(sorted(testers))[:40] or "—", INK),
                ("New bugs", len(new_bugs), f"{len(seen_bugs)} seen again" if seen_bugs else "found in testing",
                 charts.PROGRESS if new_bugs else INK),
                ("HW support requests", len(hw), f"{len(hw_open)} still open" if hw else "none made",
                 "#B26B00" if hw_open else INK),
                ("No session in 7+ days", len(stale), "active efforts", "#B26B00" if stale else INK)):
            tiles.addWidget(blocks._tile_widget(label, value, color, sub, None), 1)
        v.addLayout(tiles)
        insts = [i for i in feature_testing.instruments(testing, rng, lambda e: not product or e["product"] == product,
                                                        lambda p: not product or p == product)
                 if i["open"] or i.get("watched")]   # waiting on hardware support, or named in the instruments JQL
        hidden_keys = feature_testing.hidden_instruments(settings)
        hidden = [i for i in insts if i["key"] in hidden_keys]
        insts = [i for i in insts if i["key"] not in hidden_keys]
        if insts or (hidden and admin):
            lbl = QLabel("Instruments")
            lbl.setStyleSheet("font-size:13px; font-weight:bold; color:#52514E; padding-top:8px;")
            v.addWidget(lbl)
            if admin and testing.get("inst_error"):
                v.addWidget(self._rich("Couldn't read the instruments JQL: " + html.escape(testing["inst_error"]),
                                       12, "#B26B00"))
            for inst in insts:
                v.addWidget(self._instrument(inst, today, admin))
            if hidden and admin:                # only the admin sees what's hidden, to show it again
                v.addWidget(self._rich("Hidden: " + ", ".join(
                    f'{html.escape(i["name"])} <a href="inst:{html.escape(i["key"])}:show" style="color:#8A8984; '
                    f'font-size:11px">show</a>' for i in hidden), 12, "#8A8984"))
        root.addWidget(card)

        # What We Tested, by day
        card, v = self._card("What We Tested", f"{len(shown)} session{'s' if len(shown) != 1 else ''} · {rtext}")
        if not shown:
            v.addWidget(_small_label(f"No test sessions logged in {rtext}.", MUTED))
        day = None
        for e, s in shown:
            if s["date"] != day:
                day = s["date"]
                lbl = QLabel(date.fromisoformat(day).strftime("%A, %b %-d"))
                lbl.setStyleSheet("font-size:13px; font-weight:bold; color:#52514E; padding-top:6px;")
                v.addWidget(lbl)
            box = QFrame()
            box.setObjectName("tile")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(14, 10, 14, 12)
            bl.setSpacing(4)
            bl.addWidget(self._rich(
                f'<b style="font-size:14px">{html.escape(e["name"])}</b>&nbsp; {self._pill(e["product"])}'
                f'&nbsp; {self._jira(s["ticket"], "Session " + str(s["n"]))}', 13))
            meta = " · ".join(html.escape(x) for x in (", ".join(s["testers"]), s["time"],
                                                        s["build"] and "Build " + s["build"], s["system"]) if x)
            bl.addWidget(self._rich(meta, 12, "#8A8984"))
            for k in s["bugs"]:                       # each bug: new in this session, or seen again
                b_ = bug_info.get(k) or {}
                is_new = kind(s, k) == "new"
                done_ = b_.get("status_category") == "done"
                flip = (f'&nbsp; <a href="kind:{s["ticket"]}#{s["n"]}:{k}:{"seen" if is_new else "new"}" '
                        f'style="color:#8A8984; font-size:11px">change</a>') if admin_bugs else ""
                bl.addWidget(self._rich(
                    (self._pill("New Bug", "#E8F1FC", "#2F5E9E") if is_new else self._pill("Bug Seen Again"))
                    + f'&nbsp; {self._jira(k)}' + (f' {html.escape(b_["summary"])}' if b_.get("summary") else "")
                    + (f'&nbsp; {self._pill(b_["status"], "#E3F4E1" if done_ else "#F1EFE8", "#0B7A0B" if done_ else "#52514E")}'
                       if b_.get("status") else "") + flip, 12))
            for k in s.get("support", []):
                t_ = info.get(k) or {}
                done_ = feature_testing.support_resolved(t_)
                bl.addWidget(self._rich(
                    f'{self._pill("Hardware Support Request", "#FFF6E5", "#854F0B")}&nbsp; {self._jira(k)}'
                    + (f' {html.escape(t_["summary"])}' if t_.get("summary") else "")
                    + (f'&nbsp; {self._pill(t_["status"], "#E3F4E1" if done_ else "#F1EFE8", "#0B7A0B" if done_ else "#52514E")}'
                       if t_.get("status") else ""), 12))
            notes = "".join(f'<div style="margin-left:{14 * ((len(ln) - len(ln.lstrip())) // 2)}px">'
                            f'{_linkify(ln.strip())}</div>' for ln in s["notes"][:16])
            if len(s["notes"]) > 16:
                notes += (f'<div style="color:#8A8984">… {len(s["notes"]) - 16} more lines — '
                          f'{self._jira(s["ticket"], "open in JIRA")}</div>')
            if notes:
                bl.addWidget(self._rich(notes, 12))
            v.addWidget(box)
        root.addWidget(card)

        # efforts
        card, v = self._card("Tested in These Dates", f"{len(tested)} effort{'s' if len(tested) != 1 else ''} · {rtext}")
        if tested:
            v.addWidget(self._effort_table(tested, rng, today))
        else:
            v.addWidget(_small_label(f"No test efforts with sessions in {rtext}.", MUTED))
        root.addWidget(card)
        card, v = self._card("Not Tested in These Dates", "active efforts with no session in the dates — "
                             "including new tickets with no sessions logged yet")
        if untested:
            v.addWidget(self._effort_table(untested, rng, today))
        else:
            v.addWidget(_small_label("Every active effort was tested in these dates.", MUTED))
        root.addWidget(card)
        root.addStretch(1)
        pos = self.scroll.verticalScrollBar().value()
        self.scroll.setWidget(body)
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(pos))


def _linkify(text):
    """Notes text → HTML with short links: JIRA URLs become their key, Atlantis runs "Atlantis run"."""
    esc = html.escape

    def link(m):
        url = m.group(0).rstrip(").,")
        key = re.search(r"/browse/([A-Z][A-Z0-9]+-\d+)", url)
        label = key.group(1) if key else ("Atlantis run" if "atlantis" in url and "/run/" in url else
                                          (url.split("/")[2] if "//" in url else url))
        return f'<a href="{esc(url, quote=True)}">{esc(label)}</a>'
    parts, last = [], 0
    for m in re.finditer(r"https?://\S+", text):
        parts.append(esc(text[last:m.start()]))
        parts.append(link(m))
        last = m.end()
    parts.append(esc(text[last:]))
    return "".join(parts)
