from __future__ import annotations

from textwrap import dedent

from anki.collection import Collection
from anki.models import NotetypeDict

NOTE_TYPE_NAME = "Fading Occlusion"


def ensure_notetype(col: Collection) -> NotetypeDict:
  models = col.models
  existing = models.by_name(NOTE_TYPE_NAME)
  if existing:
    return _ensure_latest_structure(models, existing)

  model = models.new(NOTE_TYPE_NAME)

  field_image = models.new_field("Image")
  field_covers = models.new_field("CoversJSON")
  field_notes = models.new_field("Notes")
  field_mode = models.new_field("ModeOverride")

  for field in (field_image, field_covers, field_notes, field_mode):
    models.add_field(model, field)

  template = models.new_template("Fading Card")
  template["qfmt"] = _question_template()
  template["afmt"] = _answer_template()
  models.add_template(model, template)

  model["css"] = _base_css()

  added = models.add(model)
  return models.get(added.id)


def _ensure_latest_structure(models, notetype: NotetypeDict) -> NotetypeDict:
  updated = False

  desired_css = _base_css()
  if notetype.get("css") != desired_css:
    notetype["css"] = desired_css
    updated = True

  desired_qfmt = _question_template()
  desired_afmt = _answer_template()
  templates = notetype.get("tmpls", [])
  if templates:
    if templates[0].get("qfmt") != desired_qfmt:
      templates[0]["qfmt"] = desired_qfmt
      updated = True
    if templates[0].get("afmt") != desired_afmt:
      templates[0]["afmt"] = desired_afmt
      updated = True

  if updated:
    models.save(notetype)

  return notetype


def _base_css() -> str:
  return dedent(
    """
    .fo-card-root {
      position: relative;
      display: inline-block;
      max-width: 100%;
    }

    .fo-card-root img {
      max-width: 100%;
      height: auto;
      display: block;
    }

    .fo-card-header {
      margin-bottom: 12px;
      font-size: 1.1em;
      font-weight: 600;
    }

    #fo-cover-data {
      display: none;
    }

    .fo-overlay-root {
      position: absolute;
      inset: 0;
      pointer-events: none;
    }

    .fo-cover {
      position: absolute;
      background: rgba(0, 0, 0, 1);
      border: 2px solid rgba(255, 255, 255, 0.9);
      box-sizing: border-box;
    }

    .fo-cover-label {
      background: rgba(255, 255, 0, 0.95);
      color: #000;
      font-weight: 600;
      padding: 2px 6px;
      font-size: 0.85em;
      margin: 4px;
      border-radius: 4px;
      display: inline-block;
    }

    .fo-controls {
      margin-top: 12px;
      text-align: center;
    }

    .fo-controls button {
      background: #e11d48;
      color: white;
      border: none;
      padding: 6px 12px;
      border-radius: 4px;
      font-weight: bold;
      cursor: pointer;
    }

    .fo-controls button:hover {
      background: #be123c;
    }

    .fo-controls--hidden {
      display: none;
    }

    .fo-card-notes .fo-controls {
      display: none;
    }
    """
  ).strip()


def _question_template() -> str:
  return dedent(
    """
    {{#Notes}}<div class="fo-card-header">{{Notes}}</div>{{/Notes}}
    <div class="fo-card-root" data-mode="{{ModeOverride}}">
      {{{Image}}}
      <div id="fo-cover-data">{{CoversJSON}}</div>
      <div class="fo-overlay-root-placeholder"></div>
    </div>
    {{#CoversJSON}}
    <div class="fo-controls fo-controls--hidden">
      <button onclick="return pycmd('fo:fail');">
        I was wrong - mark Again
      </button>
    </div>
    {{/CoversJSON}}
    """
  ).strip()


def _answer_template() -> str:
  return dedent(
    """
    {{#Notes}}<div class="fo-card-header">{{Notes}}</div>{{/Notes}}
    <div class="fo-card-root" data-mode="{{ModeOverride}}">
      {{{Image}}}
      <div id="fo-cover-data">{{CoversJSON}}</div>
      <div class="fo-overlay-root-placeholder"></div>
    </div>
    <div class="fo-card-notes">
      {{FrontSide}}
    </div>
    """
  ).strip()
