from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from anki.decks import DeckId
from aqt import mw
from aqt.qt import (
  QPainter,
  QColor,
  QComboBox,
  QDialog,
  QFileDialog,
  QGraphicsPixmapItem,
  QGraphicsRectItem,
  QGraphicsScene,
  QGraphicsSimpleTextItem,
  QGraphicsView,
  QHBoxLayout,
  QLabel,
  QMessageBox,
  QMimeData,
  QPlainTextEdit,
  QPixmap,
  QPen,
  QPushButton,
  QRectF,
  QSizePolicy,
  Qt,
  QVBoxLayout,
  QWidget,
  QEvent,
  QObject,
  pyqtSignal,
)
from aqt.utils import showWarning

from . import notetype


class CoverGraphicsView(QGraphicsView):
  rectFinalized = pyqtSignal(QRectF)

  def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
    super().__init__(scene, parent)
    self.setRenderHints(self.renderHints() | QPainter.RenderHint.Antialiasing)
    self.setMouseTracking(True)
    self._pixmap_item: QGraphicsPixmapItem | None = None
    self._drawing = False
    self._start_scene_pos = None
    self._temp_rect_item: QGraphicsRectItem | None = None

  def set_pixmap_item(self, item: QGraphicsPixmapItem | None) -> None:
    self._pixmap_item = item
    if item:
      self.fitInView(item, Qt.AspectRatioMode.KeepAspectRatio)

  def has_image(self) -> bool:
    return self._pixmap_item is not None

  def mousePressEvent(self, event) -> None:  # type: ignore[override]
    if (
      event.button() == Qt.MouseButton.LeftButton
      and self._pixmap_item is not None
    ):
      self._drawing = True
      self._start_scene_pos = self.mapToScene(event.position().toPoint())
      if self._temp_rect_item:
        self.scene().removeItem(self._temp_rect_item)
        self._temp_rect_item = None
    super().mousePressEvent(event)

  def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
    if self._drawing and self._start_scene_pos:
      current = self.mapToScene(event.position().toPoint())
      rect = QRectF(self._start_scene_pos, current).normalized()
      if self._temp_rect_item is None:
        self._temp_rect_item = QGraphicsRectItem(rect)
        self._temp_rect_item.setBrush(QColor(0, 0, 0, 80))
        self._temp_rect_item.setPen(QPen(Qt.GlobalColor.white))
        self.scene().addItem(self._temp_rect_item)
      else:
        self._temp_rect_item.setRect(rect)
    super().mouseMoveEvent(event)

  def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
    if self._drawing and self._start_scene_pos:
      self._drawing = False
      current = self.mapToScene(event.position().toPoint())
      rect = QRectF(self._start_scene_pos, current).normalized()
      if self._temp_rect_item:
        self.scene().removeItem(self._temp_rect_item)
        self._temp_rect_item = None
      if rect.width() >= 4 and rect.height() >= 4:
        if self._pixmap_item:
          rect = rect.intersected(self._pixmap_item.boundingRect())
        self.rectFinalized.emit(rect)
    self._start_scene_pos = None
    super().mouseReleaseEvent(event)

  def resizeEvent(self, event) -> None:  # type: ignore[override]
    if self._pixmap_item:
      self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
    super().resizeEvent(event)


@dataclass
class CoverRecord:
  id: str
  rect: QRectF
  step: int
  rect_item: QGraphicsRectItem
  label_item: QGraphicsSimpleTextItem


class ModeSelector(QComboBox):
  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.addItem("Deck default", "")
    self.addItem("Forward (problem -> solution)", "forward")
    self.addItem("Backward (solution -> problem)", "backward")


class FadingEditorDialog(QDialog):
  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self.setWindowTitle("Fading Occlusion Editor")
    self.resize(1024, 720)
    self.setAcceptDrops(True)

    self._scene = QGraphicsScene(self)
    self._view = CoverGraphicsView(self._scene, self)
    self._view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    self._view.setAcceptDrops(False)
    self._view.viewport().installEventFilter(self)
    self._view.rectFinalized.connect(self._add_cover_from_rect)
    self._pixmap_item: QGraphicsPixmapItem | None = None
    self._image_path: Path | None = None
    self._image_width = 0
    self._image_height = 0
    self._covers: list[CoverRecord] = []
    self._next_step = 1

    self._deck_combo = QComboBox(self)
    self._populate_decks()

    self._mode_selector = ModeSelector(self)

    self._notes_edit = QPlainTextEdit(self)
    self._notes_edit.setPlaceholderText("Optional notes / header text...")

    self._load_button = QPushButton("Load Image", self)
    self._load_button.clicked.connect(self._select_image)

    self._undo_button = QPushButton("Undo Last Cover", self)
    self._undo_button.clicked.connect(self._undo_last_cover)
    self._undo_button.setEnabled(False)

    self._save_button = QPushButton("Add Card", self)
    self._save_button.clicked.connect(self._save_card)
    self._save_button.setEnabled(False)

    self._cancel_button = QPushButton("Close", self)
    self._cancel_button.clicked.connect(self.reject)

    main_layout = QVBoxLayout(self)
    controls = QHBoxLayout()
    controls.addWidget(QLabel("Deck:", self))
    controls.addWidget(self._deck_combo, 1)
    controls.addWidget(QLabel("Mode override:", self))
    controls.addWidget(self._mode_selector, 1)
    controls.addWidget(self._load_button)
    controls.addWidget(self._undo_button)
    main_layout.addLayout(controls)

    main_layout.addWidget(self._view, 1)

    notes_layout = QVBoxLayout()
    notes_layout.addWidget(QLabel("Notes / header:", self))
    notes_layout.addWidget(self._notes_edit)
    main_layout.addLayout(notes_layout)

    buttons = QHBoxLayout()
    buttons.addStretch(1)
    buttons.addWidget(self._save_button)
    buttons.addWidget(self._cancel_button)
    main_layout.addLayout(buttons)

  def _populate_decks(self) -> None:
    self._deck_combo.clear()
    if mw is None or mw.col is None:
      return
    for entry in mw.col.decks.all_names_and_ids():
      self._deck_combo.addItem(entry.name, entry.id)
    if self._deck_combo.count() == 0:
      self._deck_combo.addItem("(No decks available)", None)
      self._deck_combo.setEnabled(False)

  def _select_image(self) -> None:
    file_path, _ = QFileDialog.getOpenFileName(
      self,
      "Select image",
      "",
      "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)",
    )
    if not file_path:
      return
    self._load_image(Path(file_path))

  def _add_cover_from_rect(self, rect: QRectF) -> None:
    if rect.width() < 4 or rect.height() < 4:
      return
    color = QColor(0, 0, 0, 255)
    rect_item = QGraphicsRectItem(rect)
    rect_item.setBrush(color)
    rect_item.setPen(QPen(Qt.GlobalColor.white, 2))
    self._scene.addItem(rect_item)

    label = QGraphicsSimpleTextItem(str(self._next_step))
    label.setBrush(Qt.GlobalColor.white)
    label.setPen(QPen(Qt.GlobalColor.black))
    label.setPos(rect.left() + 4, rect.top() + 4)
    self._scene.addItem(label)

    record = CoverRecord(
      id=str(uuid.uuid4()),
      rect=rect,
      step=self._next_step,
      rect_item=rect_item,
      label_item=label,
    )
    self._covers.append(record)
    self._next_step += 1
    self._undo_button.setEnabled(True)

  def _undo_last_cover(self) -> None:
    if not self._covers:
      return
    record = self._covers.pop()
    self._scene.removeItem(record.rect_item)
    self._scene.removeItem(record.label_item)
    self._next_step = max(1, self._next_step - 1)
    self._undo_button.setEnabled(bool(self._covers))

  def _clear_covers(self) -> None:
    while self._covers:
      record = self._covers.pop()
      self._scene.removeItem(record.rect_item)
      self._scene.removeItem(record.label_item)
    self._next_step = 1
    self._undo_button.setEnabled(False)

  def _save_card(self) -> None:
    if mw is None or mw.col is None:
      return
    if not self._image_path or not self._pixmap_item:
      showWarning("Please load an image first.")
      return
    if not self._covers:
      showWarning("Draw at least one cover before saving.")
      return
    deck_value = self._deck_combo.currentData()
    if deck_value is None:
      showWarning("Please select a valid deck.")
      return
    deck_id = DeckId(deck_value)

    col = mw.col
    model = notetype.ensure_notetype(col)
    note = col.newNote(model)

    media_name = col.media.add_file(str(self._image_path))
    note["Image"] = f'<img src="{media_name}">'

    cover_payload = {
      "imageWidth": self._image_width,
      "imageHeight": self._image_height,
      "covers": [
        {
          "id": record.id,
          "step": record.step,
          "x": record.rect.x(),
          "y": record.rect.y(),
          "width": record.rect.width(),
          "height": record.rect.height(),
        }
        for record in self._covers
      ],
    }
    note["CoversJSON"] = json.dumps(cover_payload)
    note["Notes"] = self._notes_edit.toPlainText().strip()
    note["ModeOverride"] = self._mode_selector.currentData() or ""

    try:
      col.add_note(note, deck_id)
    except Exception as exc:  # noqa: BLE001
      showWarning(f"Failed to add note: {exc}")
      return

    mw.reset()
    QMessageBox.information(
      self,
      "Fading Occlusion",
      "Card added to deck.",
    )
    self.accept()

  # Drag & drop ------------------------------------------------------------

  def dragEnterEvent(self, event) -> None:  # type: ignore[override]
    if not self._handle_drag_enter(event):
      super().dragEnterEvent(event)

  def dropEvent(self, event) -> None:  # type: ignore[override]
    if not self._handle_drop(event):
      super().dropEvent(event)

  def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # type: ignore[override]
    if obj is self._view.viewport():
      if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
        return self._handle_drag_enter(event)
      if event.type() == QEvent.Type.Drop:
        return self._handle_drop(event)
    return super().eventFilter(obj, event)

  def _handle_drag_enter(self, event) -> bool:
    if self._mime_has_supported_image(event.mimeData()):
      event.acceptProposedAction()
      return True
    return False

  def _handle_drop(self, event) -> bool:
    path = self._first_supported_path(event.mimeData())
    if path:
      self._load_image(path)
      event.acceptProposedAction()
      return True
    return False

  # Helpers ----------------------------------------------------------------

  _SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}

  def _mime_has_supported_image(self, mime: QMimeData) -> bool:
    return self._first_supported_path(mime) is not None

  def _first_supported_path(self, mime: QMimeData) -> Path | None:
    if not mime.hasUrls():
      return None
    for url in mime.urls():
      local = url.toLocalFile()
      if not local:
        continue
      path = Path(local)
      if path.suffix.lower() in self._SUPPORTED_EXTENSIONS and path.is_file():
        return path
    return None

  def _load_image(self, path: Path) -> None:
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
      showWarning("Unable to load that image file.")
      return

    self._clear_covers()

    if self._pixmap_item:
      self._scene.removeItem(self._pixmap_item)

    self._pixmap_item = QGraphicsPixmapItem(pixmap)
    self._scene.addItem(self._pixmap_item)
    self._view.set_pixmap_item(self._pixmap_item)

    self._image_path = path
    self._image_width = pixmap.width()
    self._image_height = pixmap.height()
    self._save_button.setEnabled(True)
