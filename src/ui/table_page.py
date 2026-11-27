"""
A sheet tab shown as a table: sorting, filters, cell editing, adding rows, columns.
"""

from collections import Counter

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QTableView, QHeaderView, QMessageBox, QFrame, QDialog, QFormLayout,
    QDialogButtonBox, QShortcut, QComboBox, QCheckBox, QScrollArea, QStyledItemDelegate,
    QDateEdit, QMenu, QToolButton, QWidgetAction, QListWidget, QListWidgetItem,
    QPlainTextEdit, QAbstractItemView, QListView, QStyle, QStyleOptionViewItem)
from PyQt5.QtCore import (
    Qt, QTimer, QDate, pyqtSignal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
    QPointF, QEvent)
from PyQt5.QtGui import (
    QFont, QColor, QKeySequence, QTextDocument, QAbstractTextDocumentLayout, QCursor)

from dashboard import charts
from data import store

from ui.common import (
    LINK, MUTED, WRAP_MAX_LINES, _breakable, _colors_for, _dot, _links_menu, _natural,
    _nowrap_option, _open_link, _settings, _small_label, _visible_rows)


class ColumnsDialog(QDialog):
    """Admin: which columns get a filter button on their tab. (Charts are chosen per
    card with ✎ Customize; the old chart/pie choices still shape un-customized cards.)"""

    def __init__(self, win, data, settings):
        super().__init__(win)
        self.setWindowTitle("Filters")
        self.setMinimumWidth(640)
        self.settings = dict(settings)

        # every column in the sheet (by name), with its tabs and built-in defaults
        found, order = {}, []
        for tab in data["tabs"]:
            rows = _visible_rows(tab)
            derived = store.derived_columns(tab)
            cols = ([derived[store.PLATFORM]] if store.PLATFORM in derived else []) + \
                [c for c in tab["columns"] if c not in store.status_columns(tab)]
            for c in cols:
                key = c["name"].strip().lower()
                info = found.setdefault(key, {"name": c["name"].strip(), "tabs": [],
                                              "filter": False, "chart": False, "pie": False,
                                              "dropdown": False})
                if key not in order:
                    order.append(key)
                info["tabs"].append(tab["title"])
                info["dropdown"] |= c["kind"] == "dropdown" and not c.get("derived")
                for purpose in ("filter", "chart", "pie"):
                    info[purpose] |= store._default_on(tab, rows, c, purpose)
        self.found, self.order = found, order

        intro = QLabel("Choose which columns get a <b>filter</b> button on their tab. Turn it off "
                       "for columns full of generated or one-off values, like run names or "
                       "patient names. Applies to everyone using this release sheet.<br><br>"
                       "To choose <b>charts</b>, click <b>✎ Customize</b> on a dashboard card.")
        intro.setWordWrap(True)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        for i, text in enumerate(("Column", "Filter", "Used in")):
            grid.addWidget(_small_label(text.upper(), "#888885", 10), 0, i)
        self.boxes = {}
        for i, key in enumerate(order, start=1):
            info = found[key]
            grid.addWidget(QLabel(info["name"]), i, 0)
            for j, purpose in enumerate(("filter",), start=1):
                if purpose == "pie" and not info["dropdown"]:
                    continue                               # pies are for set categories
                box = QCheckBox()
                choice = self.settings.get(self._key(purpose, key))
                box.setChecked(choice == "on" if choice in ("on", "off") else info[purpose])
                box.setToolTip("Built-in default: " + ("on" if info[purpose] else "off"))
                grid.addWidget(box, i, j, Qt.AlignCenter)
                self.boxes[(purpose, key)] = box
            where = _small_label(", ".join(dict.fromkeys(info["tabs"])), MUTED)
            where.setToolTip(where.text())
            grid.addWidget(where, i, 2)
        grid.setColumnStretch(2, 1)
        inner = QWidget()
        inner.setLayout(grid)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        scroll.setMinimumHeight(min(30 * len(order) + 40, 360))
        self.resize(720, min(30 * len(order) + 330, 760))

        note = _small_label("Status columns always have a filter.", MUTED)
        note.setWordWrap(True)
        reset = QPushButton("Reset all to built-in defaults")
        reset.clicked.connect(self._reset)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        save = buttons.addButton("Save for everyone", QDialogButtonBox.AcceptRole)
        save.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(reset)
        bottom.addStretch(1)
        bottom.addWidget(buttons)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addWidget(intro)
        root.addWidget(scroll)
        root.addWidget(note)
        root.addLayout(bottom)

    @staticmethod
    def _key(purpose, key):
        return {"filter": store.FILTER_PREFIX, "chart": store.CHART_PREFIX,
                "pie": store.PIE_PREFIX}[purpose] + key

    def _reset(self):
        for (purpose, key), box in self.boxes.items():
            box.setChecked(self.found[key][purpose])

    def result_settings(self):
        """Only choices that differ from the built-in default are stored."""
        out = {k: v for k, v in self.settings.items() if not k.startswith(store.FILTER_PREFIX)}
        for (purpose, key), box in self.boxes.items():
            if box.isChecked() != self.found[key][purpose]:
                out[self._key(purpose, key)] = "on" if box.isChecked() else "off"
        return out


# ── table model, sorting and filtering ────────────────────────────────────────

SORT_ROLE = Qt.UserRole + 1
LINKS_ROLE = Qt.UserRole + 2      # [(text, url), ...] for a cell with several links, else None

class TabModel(QAbstractTableModel):
    """One sheet tab. Edits call `on_edit(snapshot, col, new, old)` and show at once."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.tab = {"columns": [], "rows": []}
        self.colors, self.status = {}, None
        self.status_cols, self.derived = [], {}

    def set_tab(self, tab):
        self.beginResetModel()
        self.tab = tab
        self.status, self.colors = _colors_for(tab)
        self.status_cols = store.status_columns(tab)
        self.derived = store.derived_columns(tab)
        self.multi = {c["pos"] for c in tab["columns"] if store.is_multi(c, tab["rows"])}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.tab["rows"])

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.tab["columns"])

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.tab["columns"][section]["name"]
        if orientation == Qt.Horizontal and role == Qt.ToolTipRole:
            c = self.tab["columns"][section]
            kind = {"dropdown": "Dropdown", "date": "Date", "number": "Number",
                    "checkbox": "Checkbox"}.get(c["kind"], "Text")
            if c["link"]:
                kind += " with link"
            return f"{c['name']} · {kind}\nClick to sort, click again to reverse."
        return None

    def row(self, r):
        return self.tab["rows"][r]

    def column(self, key):
        """A real column by position, or a derived one ("status", "platform") by name."""
        return self.derived[key] if isinstance(key, str) else self.tab["columns"][key]

    def editable(self, index):
        row, c = self.row(index.row()), index.column()
        return (not store.DATA_READ_ONLY and self.page.win.can_edit and not store.readonly_tab(self.tab)
                and not row["locked"][c])

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, c = self.row(index.row()), index.column()
        col = self.tab["columns"][c]
        value, link = row["values"][c], row["links"][c]
        many = store.cell_links(row, c) if row.get("spans") else []
        many = many if len(many) > 1 else None
        if role == LINKS_ROLE:
            return many
        if role == Qt.DisplayRole:
            if self.page.wrap:
                return _breakable(value)
            first = value.split("\n", 1)[0]
            return first + (" …" if "\n" in value else "")
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignLeft | (Qt.AlignTop if self.page.wrap else Qt.AlignVCenter))
        if role == Qt.EditRole:
            return value
        if role == Qt.ToolTipRole:
            tip = value
            if many:
                tip += "\n\n" + "\n".join(f"🔗 {t}  {u.split('?', 1)[0]}" for t, u in many)
                tip += "\nDouble-click a link to open it."
            elif link:
                tip += f"\n\n🔗 {link}\nDouble-click to open the link."
            if row["locked"][c]:
                tip += "\n\nThis cell has a formula. Change it in the sheet."
            return tip.strip() or None
        if role == Qt.ForegroundRole:
            if link:
                return QColor(LINK)
            if row["locked"][c]:
                return QColor(MUTED)
            return None
        if role == Qt.FontRole and link and not many:
            f = QFont()
            f.setUnderline(True)
            return f
        if role == Qt.DecorationRole and col in self.status_cols and value:
            return _dot(self.colors.get(value, charts.PENDING))
        if role == SORT_ROLE:
            if not value.strip():
                return (1, [])                    # blanks sort last
            if col["kind"] == "date":
                d = store.parse_date(value)
                return (0, [(0, d.toordinal(), "")] if d else _natural(value))
            if col in self.status_cols:
                return (0, [(0, charts.CLASS_ORDER.index(charts.classify(value)), ""), *_natural(value)])
            return (0, _natural(value))
        return None

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return f | Qt.ItemIsEditable if index.isValid() and self.editable(index) else f

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        row, col = self.row(index.row()), self.tab["columns"][index.column()]
        old = row["values"][col["pos"]]
        value = "" if value is None else str(value)
        if value == old:
            return False
        snapshot = dict(row, values=list(row["values"]))
        row["values"][col["pos"]] = value
        self.dataChanged.emit(index, index)
        self.page.win.write_cell(self.tab, snapshot, col, value, old)
        return True


class FilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.words, self.filters, self.show_empty = [], {}, False
        self.setSortRole(SORT_ROLE)

    def set_search(self, text):
        self.words = text.lower().split()
        self.invalidateFilter()

    def set_filter(self, pos, allowed):
        """allowed: a set of values to show, or None for all."""
        if allowed is None:
            self.filters.pop(pos, None)
        else:
            self.filters[pos] = allowed
        self.invalidateFilter()

    def filterAcceptsRow(self, r, parent):
        m = self.sourceModel()
        row = m.row(r)
        if not self.show_empty and store.is_blank(row):
            return False
        for key, allowed in self.filters.items():
            col = m.column(key)
            if not any(p.strip() in allowed for p in store.parts(col, store.value_of(m.tab, row, col))):
                return False
        if self.words:
            hay = " ".join(row["values"]).lower()
            if not all(w in hay for w in self.words):
                return False
        return True

    def lessThan(self, a, b):
        ka, kb = a.data(SORT_ROLE), b.data(SORT_ROLE)
        try:
            return ka < kb
        except TypeError:
            return str(ka) < str(kb)


class FilterButton(QToolButton):
    """ "Status ▾" — a popup checklist of the column's values. All checked = no filter."""
    changed = pyqtSignal(object, object)       # (column pos or derived name, values)

    def __init__(self, col):
        super().__init__()
        self.col, self.values = col, []
        self.setPopupMode(QToolButton.InstantPopup)
        self.menu_ = QMenu(self)
        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        self.list.itemChanged.connect(self._emit)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 8, 8, 8)
        btns = QHBoxLayout()
        for text, state in (("Select all", Qt.Checked), ("Clear", Qt.Unchecked)):
            b = QPushButton(text)
            b.clicked.connect(lambda _, s=state: self._set_all(s))
            btns.addWidget(b)
        lay.addLayout(btns)
        lay.addWidget(self.list)
        act = QWidgetAction(self.menu_)
        act.setDefaultWidget(box)
        self.menu_.addAction(act)
        self.setMenu(self.menu_)
        self._refresh_text()

    def set_values(self, values, counts):
        """Keep the user's choices across syncs; new values start checked."""
        was = self.selected()
        known = set(self.values)
        self.values = values
        self.list.blockSignals(True)
        self.list.clear()
        for v in values:
            item = QListWidgetItem(f"{v or store.blank_label(self.col)}   ({counts.get(v, 0)})")
            item.setData(Qt.UserRole, v)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            checked = was is None or v in was or v not in known
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self.list.addItem(item)
        self.list.setFixedHeight(min(26 * len(values) + 6, 320))
        self.list.blockSignals(False)
        self._refresh_text()

    def selected(self):
        """The checked values, or None when everything is checked."""
        vals = [self.list.item(i) for i in range(self.list.count())]
        on = {i.data(Qt.UserRole) for i in vals if i.checkState() == Qt.Checked}
        return None if len(on) == len(vals) else on

    def select_only(self, values):
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setCheckState(Qt.Checked if item.data(Qt.UserRole) in values else Qt.Unchecked)
        self.list.blockSignals(False)
        self._emit()

    def _set_all(self, state):
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)
        self.list.blockSignals(False)
        self._emit()

    def _emit(self, *_):
        self._refresh_text()
        self.changed.emit(self.col["pos"], self.selected())

    def _refresh_text(self):
        sel = self.selected() if self.list.count() else None
        name = self.col["name"]
        if sel is None:
            text = f"{name}  ▾"
        elif len(sel) == 1:
            text = f"{name}: {next(iter(sel)) or store.blank_label(self.col)}  ▾"
        else:
            text = f"{name}: {len(sel)} of {self.list.count()}  ▾"
        self.setText(text)
        self.setProperty("active", sel is not None)
        self.style().unpolish(self)
        self.style().polish(self)


# ── editing ───────────────────────────────────────────────────────────────────

def _is_long_text(col, rows):
    return col["kind"] == "text" and (
        "note" in col["name"].lower() or any("\n" in r["values"][col["pos"]] for r in rows))

class CellDelegate(QStyledItemDelegate):
    """Dropdowns for dropdown columns, a calendar for dates, a text box otherwise."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page

    def sizeHint(self, option, index):
        """Row height for wrapped text: at least one comfortable line, at most WRAP_MAX_LINES."""
        size = super().sizeHint(option, index)
        line = option.fontMetrics.lineSpacing()
        size.setHeight(max(34, min(size.height() + 14, line * WRAP_MAX_LINES + 14)))
        return size

    def _doc(self, option, index, links):
        """The cell as rich text, each link drawn (and clickable) on its own."""
        text = index.data(Qt.EditRole) or ""
        if not self.page.wrap:
            text = text.split("\n", 1)[0]
        body = store.links_html(text, links, LINK).replace("\n", "<br>")
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(option.font)
        doc.setDefaultStyleSheet(f"a {{ color: {LINK}; text-decoration: underline; }}")
        if not self.page.wrap:
            doc.setDefaultTextOption(_nowrap_option())
        doc.setHtml(f"<span style='color:{option.palette.text().color().name()}'>{body}</span>")
        doc.setTextWidth(option.rect.width() - 8 if self.page.wrap else -1)
        return doc

    def _doc_origin(self, option, doc):
        """Where plain text starts in this cell, so links line up with the other cells."""
        style = option.widget.style() if option.widget else QApplication.style()
        r = style.subElementRect(QStyle.SE_ItemViewItemText, option, option.widget)
        margin = style.pixelMetric(QStyle.PM_FocusFrameHMargin, None, option.widget) + 1
        y = r.top() + (0 if self.page.wrap else max(0, (r.height() - doc.size().height()) / 2))
        return r.left() + margin, y

    def paint(self, painter, option, index):
        links = index.data(LINKS_ROLE)
        if not links:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        doc = self._doc(opt, index, links)
        x, y = self._doc_origin(opt, doc)
        painter.save()
        painter.setClipRect(opt.rect)
        painter.translate(x, y)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    def link_at(self, index, pos):
        """The URL of the link under `pos` (viewport coordinates) in a several-links cell."""
        links = index.data(LINKS_ROLE)
        if not links:
            return None
        opt = QStyleOptionViewItem()
        opt.initFrom(self.page.view.viewport())
        opt.widget = self.page.view
        opt.font = self.page.view.font()
        opt.rect = self.page.view.visualRect(index)
        self.initStyleOption(opt, index)
        doc = self._doc(opt, index, links)
        x, y = self._doc_origin(opt, doc)
        return doc.documentLayout().anchorAt(QPointF(pos.x() - x, pos.y() - y)) or None

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if self.page.wrap:
            option.rect.adjust(0, 7, 0, -7)       # breathing room above and below wrapped text
            option.decorationAlignment = Qt.AlignLeft | Qt.AlignTop   # status dot beside the first line

    def createEditor(self, parent, option, index):
        col = self.page.model.tab["columns"][index.column()]
        value = index.data(Qt.EditRole)
        src = self.page.proxy.mapToSource(index)
        if self.page._needs_dialog(self.page.model.row(src.row()), col):
            QTimer.singleShot(0, self.page.edit_current_in_dialog)
            return None
        if col["kind"] == "dropdown" or col["kind"] == "checkbox":
            combo = QComboBox(parent)
            opts = col["options"] if col["kind"] == "dropdown" else ["TRUE", "FALSE"]
            combo.addItem("— clear —", "")
            for o in opts:
                combo.addItem(o, o)
            if value and value not in opts:
                combo.addItem(value, value)
            if col["kind"] == "dropdown":
                combo.addItem("Select several…", "__multi__")
            colors = charts.status_colors(opts, opts) if col is self.page.model.status else {}
            for i in range(combo.count()):
                v = combo.itemData(i)
                if v in colors:
                    combo.setItemIcon(i, _dot(colors[v]))
            combo.activated.connect(lambda _: self._commit(combo))
            QTimer.singleShot(0, combo.showPopup)
            return combo
        if col["kind"] == "date":
            ed = QDateEdit(parent)
            ed.setCalendarPopup(True)
            ed.setDisplayFormat("M/d/yyyy")
            return ed
        return super().createEditor(parent, option, index)

    def _commit(self, editor):
        if editor.currentData() == "__multi__":
            self.closeEditor.emit(editor, QStyledItemDelegate.RevertModelCache)
            QTimer.singleShot(0, self.page.edit_current_in_dialog)
            return
        self.commitData.emit(editor)
        self.closeEditor.emit(editor)

    def setEditorData(self, editor, index):
        value = index.data(Qt.EditRole)
        if isinstance(editor, QComboBox):
            i = editor.findData(value)
            editor.setCurrentIndex(max(i, 0))
        elif isinstance(editor, QDateEdit):
            d = store.parse_date(value)
            editor.setDate(QDate(d.year, d.month, d.day) if d else QDate.currentDate())
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentData())
        elif isinstance(editor, QDateEdit):
            d = editor.date()
            model.setData(index, f"{d.month()}/{d.day()}/{d.year()}")
        else:
            super().setModelData(editor, model, index)


class CellDialog(QDialog):
    """Editing that doesn't fit in a cell: links (text + URL), several dropdown
    choices at once, and long notes."""

    def __init__(self, parent, col, value, link, rows, multi=False):
        super().__init__(parent)
        self.setWindowTitle(f"Edit {col['name']}")
        self.setMinimumWidth(480)
        self.col = col
        root = QVBoxLayout(self)
        self.text = self.url = self.checks = self.notes = None
        if col["kind"] == "dropdown":
            root.addWidget(_small_label("Pick one or more:"))
            self.checks = QListWidget()
            chosen = set(store.parts(col, value)) if value else set()
            for o in col["options"]:
                item = QListWidgetItem(o)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if o in chosen else Qt.Unchecked)
                self.checks.addItem(item)
            self.checks.setFixedHeight(min(26 * len(col["options"]) + 6, 300))
            root.addWidget(self.checks)
        elif col["link"] or link:
            form = QFormLayout()
            self.text = QLineEdit(value)
            self.url = QLineEdit(link)
            self.url.setPlaceholderText("https://…")
            form.addRow("Text", self.text)
            form.addRow("Link", self.url)
            root.addLayout(form)
        else:
            self.notes = QPlainTextEdit(value)
            self.notes.setMinimumHeight(140)
            root.addWidget(self.notes)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def result_value(self):
        """(text, link or None)"""
        if self.checks is not None:
            on = [self.checks.item(i).text() for i in range(self.checks.count())
                  if self.checks.item(i).checkState() == Qt.Checked]
            return ", ".join(on), None
        if self.url is not None:
            return self.text.text().strip(), self.url.text().strip()
        return self.notes.toPlainText().rstrip(), None


class AddRowDialog(QDialog):
    def __init__(self, parent, tab, rows):
        super().__init__(parent)
        self.setWindowTitle(f"Add to {tab['title']}")
        self.setMinimumWidth(560)
        self.tab = tab
        self.widgets = {}
        form = QFormLayout()
        form.setSpacing(8)
        first = tab["columns"][0]
        nums = [int(r["values"][0]) for r in rows if r["values"][0].strip().isdigit()]
        filled_nums = [int(r["values"][0]) for r in rows
                       if r["values"][0].strip().isdigit() and not store.is_blank(r)]
        for col in tab["columns"]:
            multi = store.is_multi(col, rows)
            if col["kind"] == "dropdown" and not multi:
                w = QComboBox()
                w.addItem("", "")
                for o in col["options"]:
                    w.addItem(o, o)
            elif col["kind"] == "dropdown":
                w = QListWidget()
                w.setFlow(QListView.LeftToRight)
                w.setWrapping(True)
                w.setFixedHeight(60)
                for o in col["options"]:
                    item = QListWidgetItem(o)
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked)
                    w.addItem(item)
            elif col["kind"] == "date":
                w = QDateEdit(QDate.currentDate())
                w.setCalendarPopup(True)
                w.setDisplayFormat("M/d/yyyy")
            elif _is_long_text(col, rows):
                w = QPlainTextEdit()
                w.setFixedHeight(64)
            else:
                w = QLineEdit()
                if col is first and nums:
                    # next run number: the first unused one, e.g. fill placeholder row 4
                    w.setText(str(max(filled_nums, default=0) + 1))
            self.widgets[col["pos"]] = w
            if col["link"]:
                url = QLineEdit()
                url.setPlaceholderText("Link (optional): https://…")
                self.widgets[("link", col["pos"])] = url
                box = QVBoxLayout()
                box.setSpacing(4)
                box.addWidget(w)
                box.addWidget(url)
                form.addRow(col["name"], box)
            else:
                form.addRow(col["name"], w)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        ok = buttons.addButton("Add row", QDialogButtonBox.AcceptRole)
        ok.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setLayout(form)
        scroll.setWidget(inner)
        root = QVBoxLayout(self)
        root.addWidget(scroll)
        root.addWidget(buttons)
        self.resize(600, min(120 + 44 * len(tab["columns"]), 720))

    def values(self):
        vals, links = {}, {}
        for key, w in self.widgets.items():
            if isinstance(key, tuple):
                if w.text().strip():
                    links[key[1]] = w.text().strip()
                continue
            if isinstance(w, QComboBox):
                v = w.currentData()
            elif isinstance(w, QListWidget):
                v = ", ".join(w.item(i).text() for i in range(w.count())
                              if w.item(i).checkState() == Qt.Checked)
            elif isinstance(w, QDateEdit):
                d = w.date()
                v = f"{d.month()}/{d.day()}/{d.year()}"
            elif isinstance(w, QPlainTextEdit):
                v = w.toPlainText().strip()
            else:
                v = w.text().strip()
            if v:
                vals[key] = v
        return vals, links


# ── a tab of the sheet ────────────────────────────────────────────────────────

class TabPage(QWidget):
    def __init__(self, win, tab):
        super().__init__()
        self.win = win
        self.title = tab["title"]
        self.model = TabModel(self)
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model)
        self.proxy.show_empty = win.cfg.get("show_empty_rows", False)
        self.filter_btns = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 10, 0, 0)
        root.setSpacing(8)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(12, 6, 12, 6)
        bl.addWidget(QLabel("🔒 This tab is filled in automatically (from Jira), so it's "
                            "read-only here. Change these in Jira."))
        root.addWidget(self.banner)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search this tab…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        self.filter_row = QHBoxLayout()
        self.filter_row.setSpacing(6)
        self.extra_lbl = _small_label("", LINK)
        self.clear_btn = QPushButton("✕ Clear filters")
        self.clear_btn.setObjectName("link")
        self.clear_btn.clicked.connect(self.clear_filters)
        self.empty_chk = QCheckBox("Show empty rows")
        self.empty_chk.setToolTip("Rows with nothing filled in yet, e.g. run numbers waiting for a run")
        self.empty_chk.setChecked(self.proxy.show_empty)
        self.empty_chk.toggled.connect(self._on_show_empty)
        self.wrap = win.cfg.get("wrap_text", True)
        self.wrap_chk = QCheckBox("Wrap text")
        self.wrap_chk.setToolTip("Show the whole text of each cell on several lines")
        self.wrap_chk.setChecked(self.wrap)
        self.wrap_chk.toggled.connect(self.win.set_wrap)
        self.count_lbl = _small_label("", MUTED)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.search, 2)
        top.addLayout(self.filter_row)
        top.addWidget(self.extra_lbl)
        top.addWidget(self.clear_btn)
        top.addStretch(1)
        top.addWidget(self.wrap_chk)
        top.addWidget(self.empty_chk)
        top.addWidget(self.count_lbl)
        root.addLayout(top)

        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(CellDelegate(self))
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(-1, Qt.AscendingOrder)       # sheet order until a header is clicked
        self.view.horizontalHeader().setSortIndicatorShown(True)
        self.view.horizontalHeader().setSectionsMovable(True)
        self.view.horizontalHeader().setHighlightSections(False)
        self.view.horizontalHeader().setMinimumSectionSize(60)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(34)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(True)
        self._apply_wrap()
        self.view.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed)
        self.view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.doubleClicked.connect(self._on_double_click)
        self._dbl_pos = None
        self.view.viewport().installEventFilter(self)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.selectionModel().currentChanged.connect(lambda *_: self._update_buttons())
        root.addWidget(self.view, 1)

        actions = QHBoxLayout()
        self.add_btn = QPushButton("+ Add row")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self.add_row)
        self.edit_btn = QPushButton("Edit cell…")
        self.edit_btn.clicked.connect(self.edit_current)
        self.link_btn = QPushButton("Open link ↗")
        self.link_btn.clicked.connect(self.open_current_link)
        sheet_btn = QPushButton("Open this tab in Google Sheets")
        sheet_btn.clicked.connect(lambda: _open_link(store.tab_url(self.win.url, self.model.tab)))
        self.hint = _small_label("Double-click a cell to edit it · double-click a link to open it · "
                                 "right-click for more · click a column header to sort", MUTED)
        for b in (self.add_btn, self.edit_btn, self.link_btn):
            actions.addWidget(b)
        actions.addSpacing(10)
        actions.addWidget(self.hint, 1)
        actions.addWidget(sheet_btn)
        root.addLayout(actions)

        QShortcut(QKeySequence("Ctrl+F"), self, self.search.setFocus)
        self.set_tab(tab, first=True)

    # ── data ──────────────────────────────────────────────────────────────────

    def set_tab(self, tab, first=False):
        # keep the selected cell and scroll position across syncs
        cur = self.view.currentIndex()
        keep = None
        if cur.isValid():
            src = self.proxy.mapToSource(cur)
            keep = (self.model.row(src.row())["r"], src.column())
        vscroll = self.view.verticalScrollBar().value()
        hscroll = self.view.horizontalScrollBar().value()

        # Filters, sorting, widths and the selection are tied to columns by name, so
        # they stay on the right column when columns are added, moved or removed.
        old_cols = self.model.tab["columns"]
        new_pos = {c["name"]: c["pos"] for c in tab["columns"]}
        moved = {c["pos"]: new_pos.get(c["name"]) for c in old_cols}
        widths = {c["name"]: self.view.columnWidth(c["pos"]) for c in old_cols}
        sort_col, sort_order = self.proxy.sortColumn(), self.proxy.sortOrder()
        if any(old != new for old, new in moved.items()):
            follow = lambda p: p if isinstance(p, str) else moved.get(p)   # derived keys stay
            self.proxy.filters = {follow(p): v for p, v in self.proxy.filters.items()
                                  if follow(p) is not None}
            btns = {}
            for p, btn in self.filter_btns.items():
                if follow(p) is None:
                    btn.deleteLater()
                else:
                    btns[follow(p)] = btn
            self.filter_btns = btns
            if keep:
                keep = (keep[0], moved.get(keep[1]))
            sort_col = moved.get(sort_col, -1) if sort_col >= 0 else -1

        self.model.set_tab(tab)
        self._build_filters(tab)
        if first:
            self._size_columns()
        else:
            for c in tab["columns"]:
                if c["name"] in widths:
                    self.view.setColumnWidth(c["pos"], widths[c["name"]])
                else:                                  # a new column: fit it to its contents
                    self.view.resizeColumnToContents(c["pos"])
                    w = self.view.columnWidth(c["pos"])
                    self.view.setColumnWidth(c["pos"], max(90, min(w + 16, 340)))
            if sort_col != self.proxy.sortColumn():
                self.view.sortByColumn(sort_col, sort_order)
        self.proxy.invalidateFilter()
        if keep and keep[1] is not None:
            for r, row in enumerate(tab["rows"]):
                if row["r"] == keep[0]:
                    idx = self.proxy.mapFromSource(self.model.index(r, keep[1]))
                    if idx.isValid():
                        self.view.setCurrentIndex(idx)
                    break
        self.view.verticalScrollBar().setValue(vscroll)
        self.view.horizontalScrollBar().setValue(hscroll)
        ro = store.readonly_tab(tab)
        self.banner.setVisible(ro)
        self.add_btn.setVisible(not ro and not store.DATA_READ_ONLY)      # the sheet's data is read-only here
        self.edit_btn.setVisible(not ro and not store.DATA_READ_ONLY)
        self.empty_chk.setVisible(any(store.is_blank(r) for r in tab["rows"]))
        self._update_counts()
        self._update_buttons()

    def _size_columns(self):
        hdr = self.view.horizontalHeader()
        self.view.resizeColumnsToContents()
        for c in range(self.model.columnCount()):
            w = self.view.columnWidth(c)
            self.view.setColumnWidth(c, max(90, min(w + 16, 340)))
        hdr.setStretchLastSection(True)

    def _build_filters(self, tab):
        rows = _visible_rows(tab)
        cols = store.filter_columns(tab, rows, _settings(self.win))
        wanted = {c["pos"] for c in cols}
        for pos in list(self.filter_btns):
            if pos not in wanted:
                btn = self.filter_btns.pop(pos)
                self.proxy.set_filter(pos, None)
                btn.deleteLater()
        for c in cols:
            counts = Counter(p.strip() for r in rows for p in store.parts(c, store.value_of(tab, r, c)))
            values = list(c["options"]) + sorted(v for v in counts if v not in c["options"])
            if c["pos"] == store.STATUS:
                values = charts.status_order(values, c["options"])
            elif store.is_version(c):
                values = sorted(values, key=_natural, reverse=True)       # newest first
            if "" in counts and "" not in values:
                values.append("")
            btn = self.filter_btns.get(c["pos"])
            if btn is None:
                btn = FilterButton(c)
                btn.changed.connect(self._on_filter)
                self.filter_btns[c["pos"]] = btn
                self.filter_row.addWidget(btn)
            btn.col = c
            btn.set_values(values, counts)

    def _on_search(self, text):
        self.proxy.set_search(text)
        self._update_counts()

    def _on_filter(self, pos, allowed):
        self.proxy.set_filter(pos, allowed)
        self._update_counts()

    def set_wrap(self, on):
        self.wrap = on
        self.wrap_chk.blockSignals(True)
        self.wrap_chk.setChecked(on)
        self.wrap_chk.blockSignals(False)
        self._apply_wrap()
        self.model.layoutChanged.emit()          # re-read the text with or without break points

    def _apply_wrap(self):
        self.view.setWordWrap(self.wrap)
        self.view.setTextElideMode(Qt.ElideRight)
        # wrapped rows grow to fit their text (and re-fit when a column is resized)
        self.view.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents if self.wrap else QHeaderView.Fixed)
        if not self.wrap:
            self.view.verticalHeader().setDefaultSectionSize(34)
            for r in range(self.proxy.rowCount()):
                self.view.setRowHeight(r, 34)

    def _on_show_empty(self, on):
        self.proxy.show_empty = on
        self.proxy.invalidateFilter()
        self.win.cfg["show_empty_rows"] = on
        store.save_config(self.win.cfg)
        self._update_counts()

    def clear_filters(self):
        self.search.clear()
        for pos, btn in self.filter_btns.items():
            btn._set_all(Qt.Checked)
        for pos in list(self.proxy.filters):
            self.proxy.set_filter(pos, None)
        self._update_counts()

    def go_to_cell(self, sheet_row, pos):
        """Select one cell (by its sheet row), clearing filters so it's visible."""
        i = next((k for k, r in enumerate(self.model.tab["rows"]) if r["r"] == sheet_row), None)
        if i is None:
            return
        self.clear_filters()
        if self.search.text():
            self.search.clear()
        idx = self.proxy.mapFromSource(self.model.index(i, pos))
        if not idx.isValid():
            return
        self.view.setCurrentIndex(idx)
        self.view.scrollTo(idx, QAbstractItemView.PositionAtCenter)
        self.view.setFocus()

    def show_only(self, filters):
        """filters: {column pos: set of values} — used when a chart is clicked."""
        self.clear_filters()
        for pos, values in filters.items():
            if pos in self.filter_btns:
                self.filter_btns[pos].select_only(values)
            else:
                self.proxy.set_filter(pos, set(values))
        self._update_counts()

    def _update_counts(self):
        total = len([r for r in self.model.tab["rows"] if self.proxy.show_empty or not store.is_blank(r)])
        shown = self.proxy.rowCount()
        self.count_lbl.setText(f"Showing {shown} of {total}" if shown != total else f"{total} rows")
        extra = [self.model.column(p)["name"] + ": " +
                 ", ".join(sorted(v or store.blank_label(self.model.column(p)) for v in vals))
                 for p, vals in self.proxy.filters.items() if p not in self.filter_btns]
        self.extra_lbl.setText("Filtered by " + "; ".join(extra) if extra else "")
        self.clear_btn.setVisible(bool(self.proxy.filters or self.proxy.words))

    # ── editing ───────────────────────────────────────────────────────────────

    def _current(self):
        idx = self.view.currentIndex()
        if not idx.isValid():
            return None, None, None
        src = self.proxy.mapToSource(idx)
        return src, self.model.row(src.row()), self.model.tab["columns"][src.column()]

    def _update_buttons(self):
        src, row, col = self._current()
        self.link_btn.setEnabled(bool(row and row["links"][col["pos"]]))
        self.edit_btn.setEnabled(bool(src and self.model.editable(src)))
        self.add_btn.setEnabled(self.win.can_edit)

    def _needs_dialog(self, row, col):
        return (col["link"] or row["links"][col["pos"]] or col["pos"] in self.model.multi
                or _is_long_text(col, self.model.tab["rows"]))

    def eventFilter(self, obj, event):
        # remember where a double-click landed (before doubleClicked fires), to know which link
        if obj is self.view.viewport() and event.type() == QEvent.MouseButtonDblClick:
            self._dbl_pos = event.pos()
        return super().eventFilter(obj, event)

    def _on_double_click(self, idx):
        src, row, col = self._current()
        if row is None:
            return
        many = store.cell_links(row, col["pos"])
        if len(many) > 1:
            pos = self._dbl_pos or self.view.viewport().mapFromGlobal(QCursor.pos())
            url = self.view.itemDelegate().link_at(idx, pos)
            if url:
                _open_link(url)
            else:
                _links_menu(self, many).exec_(QCursor.pos())
            return
        link = row["links"][col["pos"]]
        if link:
            _open_link(link)
            return
        self.edit_current()

    def edit_current(self):
        src, row, col = self._current()
        if row is None:
            return
        if not self.model.editable(src):
            if not self.win.can_edit:
                QMessageBox.information(self, "Can't edit right now",
                                        "Editing is paused until the app reconnects to Google Sheets.")
            elif row["locked"][col["pos"]]:
                QMessageBox.information(self, "Formula cell",
                                        "This cell is calculated by a formula. Change it in the sheet.")
            return
        if self._needs_dialog(row, col):
            self.edit_current_in_dialog()
        else:
            self.view.edit(self.view.currentIndex())

    def edit_current_in_dialog(self):
        src, row, col = self._current()
        if row is None or not self.model.editable(src):
            return
        pos = col["pos"]
        dlg = CellDialog(self, col, row["values"][pos], row["links"][pos], self.model.tab["rows"])
        if dlg.exec_() != QDialog.Accepted:
            return
        value, link = dlg.result_value()
        if value == row["values"][pos] and (link is None or link == row["links"][pos]):
            return
        snapshot = dict(row, values=list(row["values"]))
        old = row["values"][pos]
        row["values"][pos] = value
        if link is not None:
            row["links"][pos] = link
        self.model.dataChanged.emit(src, src)
        self.win.write_cell(self.model.tab, snapshot, col, value, old, link)

    def open_current_link(self):
        _, row, col = self._current()
        if not row:
            return
        many = store.cell_links(row, col["pos"])
        if len(many) > 1:
            _links_menu(self, many).exec_(self.link_btn.mapToGlobal(self.link_btn.rect().bottomLeft()))
        else:
            _open_link(row["links"][col["pos"]])

    def _context_menu(self, pos):
        idx = self.view.indexAt(pos)
        if not idx.isValid():
            return
        self.view.setCurrentIndex(idx)
        src, row, col = self._current()
        value, link = row["values"][col["pos"]], row["links"][col["pos"]]
        menu = QMenu(self)
        if self.model.editable(src):
            menu.addAction("Edit…", self.edit_current)
            if value:
                menu.addAction("Clear cell", lambda: self.model.setData(src, ""))
        many = store.cell_links(row, col["pos"])
        if len(many) > 1:
            for text, url in many:
                menu.addAction(f"Open {text.replace('&', '&&')[:60]} ↗", lambda u=url: _open_link(u))
        elif link:
            menu.addAction("Open link ↗", lambda: _open_link(link))
        menu.addAction("Copy", lambda: QApplication.clipboard().setText(link if link and not value else value))
        if col["pos"] in self.filter_btns or col["kind"] in ("dropdown", "date") or value:
            menu.addSeparator()
            show = set(store.parts(col, value)) if value else {""}
            menu.addAction(f"Show only “{value or store.blank_label(col)}” in {col['name']}",
                           lambda: self.show_only({col["pos"]: show}))
        menu.exec_(self.view.viewport().mapToGlobal(pos))

    def add_row(self):
        if not self.win.can_edit or store.DATA_READ_ONLY:
            return
        dlg = AddRowDialog(self, self.model.tab, self.model.tab["rows"])
        if dlg.exec_() != QDialog.Accepted:
            return
        values, links = dlg.values()
        if not values:
            return
        self.win.add_row(self.model.tab, values, links)
