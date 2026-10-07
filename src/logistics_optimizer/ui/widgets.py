"""Мелкие виджеты окна: карточка шага с приёмом файлов, карточка с числом, метка способа."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QModelIndex, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ..models import Method
from .theme import Palette

EXCEL_SUFFIXES = (".xlsx", ".xlsm", ".xls")
METHOD_ROLE = Qt.ItemDataRole.UserRole + 2


def dropped_excel_files(event: QDragEnterEvent | QDropEvent) -> list[str]:
    urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
    paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
    return [path for path in paths if Path(path).suffix.lower() in EXCEL_SUFFIXES]


def repolish(widget: QWidget) -> None:
    """Перечитывает стиль после смены динамического свойства."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def link_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("link")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFlat(True)
    return button


class StepCard(QFrame):
    """Шаг в левой колонке: номер, заголовок, содержимое. Умеет принимать файл перетаскиванием."""

    fileDropped = pyqtSignal(str)

    def __init__(self, number: int, title: str, accepts_files: bool = False) -> None:
        super().__init__()
        self.setObjectName("stepCard")
        self.setAcceptDrops(accepts_files)

        self.badge = QLabel(str(number))
        self.badge.setObjectName("stepBadge")
        self.badge.setFixedSize(22, 22)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading = QLabel(title)
        heading.setObjectName("stepTitle")
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.badge)
        top.addWidget(heading, 1)

        self.file_label = QLabel()
        self.file_label.setObjectName("stepFile")
        self.file_label.setVisible(False)
        self.hint = QLabel()
        self.hint.setObjectName("stepHint")
        self.hint.setWordWrap(True)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(14)
        self.actions.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        layout.addLayout(top)
        layout.addWidget(self.file_label)
        layout.addWidget(self.hint)
        layout.addLayout(self.actions)

    def add_action(self, text: str) -> QPushButton:
        button = link_button(text)
        self.actions.insertWidget(self.actions.count() - 1, button)
        return button

    def show_state(self, hint: str, file_name: str = "", done: bool = False) -> None:
        self.hint.setText(hint)
        self.file_label.setText(file_name)
        self.file_label.setToolTip(file_name)
        self.file_label.setVisible(bool(file_name))
        self.badge.setProperty("done", done)
        repolish(self.badge)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if dropped_excel_files(event):
            event.acceptProposedAction()
            self._highlight(True)

    def dragLeaveEvent(self, event) -> None:
        self._highlight(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._highlight(False)
        files = dropped_excel_files(event)
        if files:
            event.acceptProposedAction()
            self.fileDropped.emit(files[0])

    def _highlight(self, on: bool) -> None:
        self.setProperty("dropTarget", on)
        repolish(self)


class StatCard(QFrame):
    """Карточка сводки: подпись, крупное число, пояснение."""

    def __init__(self, caption: str) -> None:
        super().__init__()
        self.setObjectName("statCard")
        self.caption = QLabel(caption)
        self.caption.setObjectName("statCaption")
        self.value = QLabel("—")
        self.value.setObjectName("statValue")
        self.note = QLabel(" ")
        self.note.setObjectName("statNote")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        layout.addWidget(self.caption)
        layout.addWidget(self.value)
        layout.addWidget(self.note)

    def show_value(self, value: str, note: str = " ", tone: str = "") -> None:
        self.value.setText(value)
        self.note.setText(note or " ")
        self.value.setProperty("tone", tone)
        repolish(self.value)


class MethodDelegate(QStyledItemDelegate):
    """Рисует способ доставки цветной меткой, чтобы строки читались с одного взгляда."""

    def __init__(self, colors: Palette, parent=None) -> None:
        super().__init__(parent)
        self.colors = colors

    def _tones(self, method: Method) -> tuple[str, str]:
        colors = self.colors
        if method.is_error:
            return colors.bad, colors.bad_soft
        if method in (Method.DIRECT, Method.DIRECT_GROUP):
            return colors.accent, colors.accent_soft
        if method in (Method.MOSCOW, Method.MOSCOW_GROUP):
            return colors.violet, colors.violet_soft
        return colors.muted, colors.surface_alt

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        text = index.data(Qt.ItemDataRole.DisplayRole)
        method = index.data(METHOD_ROLE)
        if not text or method is None:
            super().paint(painter, option, index)
            return
        blank = QStyleOptionViewItem(option)
        self.initStyleOption(blank, index)
        blank.text = ""
        style = option.widget.style() if option.widget else None
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, blank, painter, option.widget)

        foreground, background = self._tones(Method(method))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(text) + 18
        height = 20
        rect = QRectF(
            option.rect.x() + 8,
            option.rect.y() + (option.rect.height() - height) / 2,
            min(width, option.rect.width() - 12),
            height,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QColor(foreground))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(size.width() + 26, max(size.height(), 30))
