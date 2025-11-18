from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from anki.hooks import wrap
from aqt import gui_hooks, mw
from aqt.reviewer import Reviewer

NOTE_TYPE_NAME = "Fading Occlusion"
FAIL_COMMAND = "fo:fail"
FAIL_SHORTCUT = "f"


@dataclass
class CardState:
  steps: list[int]
  index: int = -1


CARD_STATES: dict[int, CardState] = {}

RUNTIME_TEMPLATE = """<script>
    (function() {
      if (!window.foRuntime) {
        window.foRuntime = (function() {
          const cards = new Map();

          function findControlsFor(overlay) {
            if (!overlay || overlay.closest(".fo-card-notes")) {
              return null;
            }
            const root = overlay.closest(".fo-card-root");
            if (!root) {
              return null;
            }
            let sibling = root.nextElementSibling;
            while (sibling) {
              if (
                sibling.classList &&
                sibling.classList.contains("fo-controls")
              ) {
                return sibling;
              }
              sibling = sibling.nextElementSibling;
            }
            return null;
          }

          function setControlsVisible(controls, visible) {
            if (!controls) { return; }
            controls.classList.toggle("fo-controls--hidden", !visible);
          }

          function updateControls(state) {
            if (!state.controls || !state.steps || !state.steps.length) {
              setControlsVisible(state.controls, false);
              return;
            }
            const remaining = state.remainingSteps ? state.remainingSteps.size : state.steps.length;
            const peeled = state.steps.length - remaining;
            const shouldShow = peeled > 0 && remaining > 0;
            setControlsVisible(state.controls, shouldShow);
          }

          function waitForControls(state, attempt = 0) {
            if (!state || attempt > 10) {
              return;
            }
            if (state.controls && document.body.contains(state.controls)) {
              updateControls(state);
              return;
            }
            const candidate = findControlsFor(state.overlay);
            if (candidate) {
              state.controls = candidate;
              updateControls(state);
              return;
            }
            requestAnimationFrame(() => waitForControls(state, attempt + 1));
          }

          function showAll(state) {
            state.stepMap.forEach((covers) => {
              covers.forEach((cover) => { cover.style.display = ""; });
            });
            updateControls(state);
          }

          function hideAll(state) {
            state.stepMap.forEach((covers) => {
              covers.forEach((cover) => { cover.style.display = "none"; });
            });
            setControlsVisible(state.controls, false);
          }

          function peelStep(cardId, step) {
            const state = cards.get(cardId);
            if (!state) { return; }
            const covers = state.stepMap.get(step);
            if (!covers) { return; }
            covers.forEach((cover) => { cover.style.display = "none"; });
            if (state.remainingSteps) {
              state.remainingSteps.delete(step);
            }
            updateControls(state);
          }

          function resetCard(cardId) {
            const state = cards.get(cardId);
            if (!state) { return; }
            if (state.steps) {
              state.remainingSteps = new Set(state.steps);
            }
            showAll(state);
            updateControls(state);
          }

          function hideControls(cardId) {
            const state = cards.get(cardId);
            if (!state) { return; }
            setControlsVisible(state.controls, false);
          }

          function registerCard(data) {
            const overlay = document.getElementById(data.overlayId);
            if (!overlay) {
              console.log("[FadingOcclusion] overlay missing", data.overlayId);
              return;
            }

            const stepMap = new Map();
            overlay.querySelectorAll(".fo-cover").forEach((cover) => {
              const step = Number(cover.dataset.step || 0);
              if (!stepMap.has(step)) {
                stepMap.set(step, []);
              }
              stepMap.get(step).push(cover);
            });

            const steps = Array.isArray(data.steps) ? data.steps.map(Number) : [];
            const state = {
              overlay,
              stepMap,
              controls: null,
              steps,
              remainingSteps: new Set(steps),
            };
            cards.set(data.cardId, state);
            waitForControls(state);

            if (data.context === "reviewQuestion") {
              showAll(state);
            } else {
              hideAll(state);
            }
          }

          return {
            register: registerCard,
            peelStep,
            resetCard,
            hideControls,
          };
        })();
      }
      const payload = __PAYLOAD__;
      const runRegistration = () => {
        if (window.foRuntime) {
          window.foRuntime.register(payload);
        }
      };
      if (window.requestAnimationFrame) {
        window.requestAnimationFrame(runRegistration);
      } else {
        setTimeout(runRegistration, 0);
      }
    })();
  </script>"""


@dataclass
class CoverSpec:
  id: str
  step: int
  x: float
  y: float
  width: float
  height: float


@dataclass
class CoverPayload:
  image_width: float
  image_height: float
  covers: list[CoverSpec]


def install_reviewer_hooks() -> None:
  gui_hooks.card_will_show.append(_inject_overlay_markup)
  gui_hooks.reviewer_will_answer_card.append(_handle_answer_action)
  Reviewer._getTypedAnswer = wrap(Reviewer._getTypedAnswer, _maybe_reveal_step, "around")
  Reviewer._linkHandler = wrap(Reviewer._linkHandler, _handle_link_command, "around")
  Reviewer._shortcutKeys = wrap(Reviewer._shortcutKeys, _inject_shortcuts, "around")


def _matches_note_type(card) -> bool:
  try:
    return card.note_type()["name"] == NOTE_TYPE_NAME
  except Exception:  # noqa: BLE001
    return False


def _inject_overlay_markup(text: str, card: Any, context: str) -> str:
  if not _matches_note_type(card):
    return text

  payload = _parse_payload(card.note()["CoversJSON"])
  if payload is None or not payload.covers:
    return text

  placeholder = '<div class="fo-overlay-root-placeholder"></div>'
  overlay_divs = "\n".join(_render_cover_div(spec, payload) for spec in payload.covers)
  overlay_id = f"fo-overlay-{card.id}"
  note = card.note()
  mode_override = note["ModeOverride"] if "ModeOverride" in note else "forward"
  script_payload = json.dumps({
    "cardId": str(card.id),
    "overlayId": overlay_id,
    "mode": mode_override or "forward",
    "context": context,
    "steps": _unique_steps(payload),
  })

  if context == "reviewQuestion":
    runtime_html = RUNTIME_TEMPLATE.replace("__PAYLOAD__", script_payload)
    overlay_html = f"""
    <div class="fo-overlay-root" id="{overlay_id}" data-card-id="{card.id}">
      {overlay_divs}
    </div>
    {runtime_html}
    """
    CARD_STATES[card.id] = CardState(steps=_unique_steps(payload), index=-1)
  else:
    runtime_html = f"""<script>(function() {{
      const overlay = document.getElementById('{overlay_id}');
      if (!overlay) {{ return; }}
      overlay.querySelectorAll('.fo-cover').forEach((cover) => {{ cover.style.display = 'none'; }});
    }})();</script>"""
    overlay_html = f"""
    <div class="fo-overlay-root" id="{overlay_id}" data-card-id="{card.id}">
      {overlay_divs}
    </div>
    {runtime_html}
    """
    CARD_STATES.pop(card.id, None)

  if placeholder in text:
    replaced = text.replace(placeholder, overlay_html, 1)
    print(f"[FadingOcclusion] Injected overlay for card {card.id} (context: {context})")
    return replaced
  print(f"[FadingOcclusion] Placeholder missing for card {card.id}, appending overlay.")
  return text + overlay_html


def _render_cover_div(spec: CoverSpec, payload: CoverPayload) -> str:
  rel_x = spec.x / payload.image_width
  rel_y = spec.y / payload.image_height
  rel_w = spec.width / payload.image_width
  rel_h = spec.height / payload.image_height

  return f"""
  <div class="fo-cover" data-step="{spec.step}" style="
    left:{rel_x*100:.4f}%;
    top:{rel_y*100:.4f}%;
    width:{rel_w*100:.4f}%;
    height:{rel_h*100:.4f}%;
  ">
    <span class="fo-cover-label">{spec.step}</span>
  </div>
  """


def _parse_payload(raw_json: str | None) -> Optional[CoverPayload]:
  if not raw_json:
    return None
  try:
    data = json.loads(raw_json)
  except json.JSONDecodeError:
    return None

  try:
    image_width = float(data["imageWidth"])
    image_height = float(data["imageHeight"])
    covers = [
      CoverSpec(
        id=cover.get("id", ""),
        step=int(cover.get("step", 0)),
        x=float(cover.get("x", 0)),
        y=float(cover.get("y", 0)),
        width=float(cover.get("width", 0)),
        height=float(cover.get("height", 0)),
      )
      for cover in data.get("covers", [])
    ]
  except (KeyError, ValueError, TypeError):
    return None

  return CoverPayload(image_width=image_width, image_height=image_height, covers=covers)


def _unique_steps(payload: CoverPayload) -> list[int]:
  return sorted({cover.step for cover in payload.covers})


def _handle_answer_action(ease_tuple: tuple[bool, int], reviewer: Reviewer, card: Any) -> tuple[bool, int]:
  proceed, ease = ease_tuple
  if not proceed or not _matches_note_type(card):
    return ease_tuple

  state = CARD_STATES.get(card.id)
  if not state:
    return ease_tuple

  if reviewer.state == "question" and ease == 1:
    _reset_card(card.id)
    CARD_STATES.pop(card.id, None)

  return ease_tuple


def _handle_link_command(reviewer: Reviewer, cmd: str, *, _old) -> None:
  if cmd == FAIL_COMMAND:
    _fail_current_question(reviewer)
    return None
  return _old(reviewer, cmd)


def _inject_shortcuts(reviewer: Reviewer, *, _old):
  shortcuts = list(_old(reviewer))
  if not _has_fail_shortcut(shortcuts):
    shortcuts.append((FAIL_SHORTCUT, lambda reviewer=reviewer: _fail_current_question(reviewer)))
  return shortcuts


def _has_fail_shortcut(shortcuts) -> bool:
  for entry in shortcuts:
    if not isinstance(entry, tuple) or not entry:
      continue
    key = entry[0]
    if isinstance(key, str) and key.lower() == FAIL_SHORTCUT.lower():
      return True
  return False


def _fail_current_question(reviewer: Reviewer) -> bool:
  card = reviewer.card
  if not card or reviewer.state != "question" or not _matches_note_type(card):
    return False

  _reveal_remaining_steps(card.id)
  CARD_STATES.pop(card.id, None)
  reviewer._showAnswer()
  if reviewer.state != "answer":
    return False
  reviewer._answerCard(1)
  return True


def _maybe_reveal_step(reviewer: Reviewer, _old) -> None:
  card = reviewer.card
  if not card or not _matches_note_type(card):
    return _old(reviewer)

  state = CARD_STATES.get(card.id)
  if not state:
    return _old(reviewer)

  if state.index + 1 < len(state.steps):
    state.index += 1
    step_number = state.steps[state.index]
    _hide_controls(card.id)
    _peel_step(card.id, step_number)
    return None

  CARD_STATES.pop(card.id, None)
  return _old(reviewer)


def _peel_step(card_id: int, step_number: int) -> None:
  if mw is None or mw.reviewer is None:
    return
  js = (
    "window.foRuntime && window.foRuntime.peelStep && "
    f"window.foRuntime.peelStep('{card_id}', {step_number});"
  )
  mw.reviewer.web.eval(js)


def _reset_card(card_id: int) -> None:
  if mw is None or mw.reviewer is None:
    return
  js = (
    "window.foRuntime && window.foRuntime.resetCard && "
    f"window.foRuntime.resetCard('{card_id}');"
  )
  mw.reviewer.web.eval(js)


def _hide_controls(card_id: int) -> None:
  if mw is None or mw.reviewer is None:
    return
  js = (
    "window.foRuntime && window.foRuntime.hideControls && "
    f"window.foRuntime.hideControls('{card_id}');"
  )
  mw.reviewer.web.eval(js)


def _reveal_remaining_steps(card_id: int) -> None:
  state = CARD_STATES.get(card_id)
  if not state:
    return
  remaining = state.steps[state.index + 1 :]
  for step in remaining:
    _peel_step(card_id, step)
  state.index = len(state.steps) - 1
