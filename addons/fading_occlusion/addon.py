from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from aqt import gui_hooks, mw
from aqt.qt import QAction
from aqt.utils import showInfo

from . import notetype
from .editor import FadingEditorDialog
from .reviewer import install_reviewer_hooks


@dataclass
class FadingAddon:
  """Coordinates add-on lifecycle hooks."""

  package_path: Path
  _tools_action: Optional[QAction] = field(default=None, init=False)

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
      self._tools_action.triggered.connect(self._launch_editor)
      mw.form.menuTools.addAction(self._tools_action)

  def _on_profile_will_close(self) -> None:
    if self._tools_action and mw is not None:
      mw.form.menuTools.removeAction(self._tools_action)
      self._tools_action.deleteLater()
    self._tools_action = None

  # UI actions -------------------------------------------------------------

  def _launch_editor(self) -> None:
    if mw is None:
      return
    if mw.col is None:
      showInfo("Open a collection to use the editor.")
      return
    dialog = FadingEditorDialog(mw)
    dialog.exec()

fading_addon = FadingAddon(package_path=Path(__file__).resolve().parent)
fading_addon.install_hooks()
