from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from aqt import gui_hooks, mw
from aqt.qt import QAction, QTimer
from aqt.utils import showInfo

from . import notetype
from .editor import FadingEditorDialog
from .reviewer import install_reviewer_hooks


@dataclass
class FadingAddon:
  """Coordinates add-on lifecycle hooks."""

  package_path: Path
  _tools_action: Optional[QAction] = field(default=None, init=False)
  _inbox_timer: Optional[QTimer] = field(default=None, init=False)
  _inbox_processing: bool = field(default=False, init=False)

  def install_hooks(self) -> None:
    gui_hooks.profile_did_open.append(self._on_profile_did_open)
    gui_hooks.profile_will_close.append(self._on_profile_will_close)
    install_reviewer_hooks()

  # Hook callbacks ---------------------------------------------------------

  def _on_profile_did_open(self) -> None:
    if mw is None:
      return

    if mw.col is not None:
      notetype.ensure_notetype(mw.col)

    if self._tools_action is None:
      self._tools_action = QAction("Fading Occlusion Editor…", mw)
      self._tools_action.setStatusTip("Create fading occlusion cards.")
      self._tools_action.triggered.connect(self._launch_editor_from_menu)
      mw.form.menuTools.addAction(self._tools_action)
    self._start_screenshot_listener()

  def _on_profile_will_close(self) -> None:
    if self._tools_action and mw is not None:
      mw.form.menuTools.removeAction(self._tools_action)
      self._tools_action.deleteLater()
    self._tools_action = None
    self._stop_screenshot_listener()

  # UI actions -------------------------------------------------------------

  def _launch_editor_from_menu(self) -> None:
    self._open_editor_with_image()

  def _open_editor_with_image(self, image_path: Path | None = None, delete_after: bool = False) -> None:
    if mw is None:
      return
    if mw.col is None:
      showInfo("Open a collection to use the editor.")
      return
    dialog = FadingEditorDialog(mw, initial_image=image_path)
    dialog.exec()
    if delete_after and image_path and image_path.exists():
      try:
        image_path.unlink()
      except OSError:
        pass

  # Screenshot inbox ------------------------------------------------------

  def _start_screenshot_listener(self) -> None:
    if mw is None:
      return
    inbox = self._screenshot_inbox()
    inbox.mkdir(parents=True, exist_ok=True)
    if self._inbox_timer is None:
      self._inbox_timer = QTimer(mw)
      self._inbox_timer.setInterval(1000)
      self._inbox_timer.timeout.connect(self._poll_inbox)
    if not self._inbox_timer.isActive():
      self._inbox_timer.start()

  def _stop_screenshot_listener(self) -> None:
    if self._inbox_timer:
      self._inbox_timer.stop()
      self._inbox_timer = None
    self._inbox_processing = False

  def _poll_inbox(self) -> None:
    if self._inbox_processing or mw is None:
      return
    inbox = self._screenshot_inbox()
    try:
      files = sorted(
        [p for p in inbox.glob("*.png") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
      )
    except FileNotFoundError:
      return
    for path in files:
      if path.stat().st_size == 0:
        continue
      self._inbox_processing = True
      mw.activateWindow()
      mw.raise_()
      self._open_editor_with_image(path, delete_after=True)
      self._inbox_processing = False
      break

  def _screenshot_inbox(self) -> Path:
    base = Path.home() / "Library" / "Application Support" / "Anki2"
    return base / "fading_occlusion_inbox"

fading_addon = FadingAddon(package_path=Path(__file__).resolve().parent)
fading_addon.install_hooks()
