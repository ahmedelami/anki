# Anki Repo – Working Notes for Fading-Card Add-on

Captures the parts of `ankitects/anki` that matter for building a “fading flashcards” add-on mirroring the custom Next.js app.

## High-Level Layout
- `rslib/` – Rust backend (scheduling, storage, stock notetypes). Anything persisted to the collection lives here. Notable pieces:
  - `rslib/src/card/` defines card protobufs + `custom_data` (tiny JSON blobs, max 100 bytes per card).
  - `rslib/src/scheduler/answering/` handles rating cards and consuming the scheduling states pushed from the frontend.
  - `rslib/src/image_occlusion/*` adds the existing occlusion notetype (fields + templates are in `notetype.rs`, request plumbing in `imagedata.rs`).
- `pylib/` – Python bridge exposing backend APIs to the GUI. `pylib/anki/cards.py` defines the `Card` object, `Card.custom_data`, and `Card.question()/answer()` render helpers.
- `qt/aqt/` – PyQt front-end. `qt/aqt/reviewer.py` is the desktop reviewer, `qt/aqt/gui_hooks.py` enumerates extension hooks, `qt/aqt/webview.py` controls WebViews and JS injection.
- `ts/` – Svelte/TS bundles compiled into the WebViews. `ts/reviewer/**` is the review-screen JS; `ts/routes/image-occlusion/**` implements the stock IO editor/reviewer overlays; `ts/routes/deck-options/*` includes the card-state customizer UI.

## Reviewer Flow (qt/aqt/reviewer.py)
- `_get_next_v3_card()` pulls scheduler state (`QueuedCards`, `SchedulingStates`, `SchedulingContext`) from the Rust scheduler and builds the `Card` object.
- `_showQuestion()` / `_showAnswer()` send HTML to the webview by calling `self.web.eval` with `setInnerHTML` defined in `ts/reviewer/index.ts`.
- Answer lifecycle:
  - Space/keyboard triggers `_answerCard(ease)`.
  - `gui_hooks.reviewer_will_answer_card` receives `(proceed, ease)`; an add-on can block native scheduling by returning `(False, ease)` and handling the UI itself.
  - If `proceed` stays `True`, Anki builds an `answer` proto (`V3Scheduler.build_answer`) and calls `aqt.operations.scheduling.answer_card`. After the backend updates, `_after_answering()` fires `gui_hooks.reviewer_did_answer_card` and `nextCard()`.
- State mutation hook:
  - Deck config `cardStateCustomizer` (see `ts/routes/deck-options/CardStateCustomizer.svelte`) lets users paste JS that runs inside the reviewer webview via `RUN_STATE_MUTATION` (bottom of `qt/aqt/reviewer.py`).
  - That JS calls `anki.mutateNextCardStates(key, transform)` (implemented in `ts/reviewer/answering.ts`) to edit the `SchedulingStates`. We can leverage the same infrastructure if we need to queue cards locally before letting the scheduler see them.
- Reviewer web UX lives in `ts/reviewer/index.ts`: `_updateQA()` sets inner HTML, runs hooks (`onUpdateHook`, `onShownHook`), preloads resources, and re-typesets MathJax.

## Webview / Hooking Surfaces
- Hooks defined in `qt/tools/genhooks_gui.py` → generated `qt/aqt/gui_hooks.py`. The key ones for this add-on:
  - `gui_hooks.reviewer_will_answer_card`, `gui_hooks.reviewer_did_answer_card`.
  - `gui_hooks.card_will_show(text, card, kind)` to alter rendered HTML before it appears in the webview.
  - `gui_hooks.card_review_webview_did_init(webview, kind, context)` + `gui_hooks.webview_will_set_content(web_content, context)` to inject JS/CSS for the reviewer.
  - `gui_hooks.reviewer_will_play_question_sounds/answer_sounds` when we need to suppress the normal “answer” beep while the staged steps are still in progress.
- `aqt.webview.WebContent` exposes `head`, `body`, and `js`/`css` bundles we can append to inside `webview_will_set_content`.
- Bridge between Python and JS comes from `aqt.webview.AnkiWebView` → JS `bridgeCommand("command")`, handled by `_linkHandler` in `Reviewer`. Add-ons can register custom handlers using `webview.set_bridge_command`.

## Card Templates & Note Types
- Stock image occlusion notetype (Rust) builds templates that call `anki.imageOcclusion.setup()` at review time (`rslib/src/image_occlusion/notetype.rs`). The review script lives in `ts/routes/image-occlusion/review.ts` and draws rectangles from data embedded in the card fields.
- Image data API: `rslib/src/image_occlusion/imagedata.rs` handles `AddImageOcclusionNoteRequest`, `UpdateImageOcclusionNoteRequest`, etc. When we add a “fading occlusion” note type, we can either piggyback on this plumbing or create a separate set of fields (`CoversJSON`, `Image`, `Mode`, etc.).
- Card fields vs. card custom_data:
  - Fields (HTML) are unlimited and synced. Ideal place to serialize our cover rectangles, grouping, hints.
  - `Card.custom_data` is a tiny JSON (keys ≤8 bytes, ≤100 bytes total) stored inside `Card.data`. Good for runtime flags like `"f":1` (forward/backward) or `"p":2` (current pass) if we need to persist between reviews, but not for the geometry.

## TS/JS Assets
- Reviewer bundle entry: `ts/reviewer/index.ts` (plus `index_wrapper.ts` for legacy). Sets up hooks, handles `_showQuestion`/`_showAnswer`, and exposes `anki.mutateNextCardStates`.
- Mutation helper (`ts/reviewer/answering.ts`):
  - Fetches current `SchedulingStatesWithContext` via protobuf RPC, decodes `customData`, runs the user transform, and pushes the updated states back into the backend. This is how deck-level scripts or add-ons can say “keep this card at the front/back of the queue until some condition is met.”
- Image occlusion UI (Svelte) already implements drag-to-draw masks, grouping shapes, toggling occlude-inactive, etc. We can reuse this component for editing sequential covers instead of reinventing the React canvas from the Next.js app.

## Integration Thoughts
- **Data Model**: Define a dedicated notetype (similar to `image_occlusion_notetype`) whose fields are:
  - `Image`: `<img>` tag stored like stock IO.
  - `Covers`: JSON string of `{ id, step, groupId, rects[] }`.
  - `Mode`: `"forward"`/`"backward"` or default to deck setting.
  - Optional `Notes/Variants` for the “add more annotations” phase.
  The add-on can install/update this notetype via the backend API (`Collection.add_notetype_inner` in Rust or the exposed Python helpers).
- **Editor UI**: Launch a Qt window that hosts the Svelte IO editor bundle (or a new Svelte/TS build) to draw rectangles. Because Anki already builds `ts/routes/image-occlusion/MaskEditor.svelte`, we can add a new route (e.g., `ts/routes/fading-occlusion`) that extends it with sequential numbering and grouping logic borrowed from the Next.js `components/ImageEditor.tsx`.
- **Review UI**:
  - Use `gui_hooks.card_will_show` to detect our notetype (check `card.note_type()["name"]` or a tag). For our cards, replace the HTML with a container that renders the base image plus cover overlays similar to `ts/routes/image-occlusion/review.ts`.
  - Inject a companion JS bundle (via `webview_will_set_content` or `card_review_webview_did_init`) that manages the staged reveal state, listens for space/“wrong” keys, and exposes `bridgeCommand`s back to Python when a staged step completes or fails.
  - Intercept `_answerCard` via `gui_hooks.reviewer_will_answer_card`: while there are unrevealed steps, return `(False, ease)` so built-in scheduling doesn’t fire. Instead, advance to the next cover, update the overlays, and call back into JS to continue the local mini-queue. When the last step completes, call `_answerCard` manually (or set `proceed=True` once the user truly answered).
  - If the learner marks it wrong mid-pass, push the card to the back of a local queue. `anki.mutateNextCardStates` gives us the ability to keep the scheduler pointed at the same card until our local criteria pass, then set `states.current.customData` / `card.custom_data` so the backend knows the staged review is done.
- **State Tracking**:
  - During a review session we can keep an in-memory map `card.id -> { stepIndex, passIndex }` in Python (lives in the add-on module). Because the reviewer restarts its state when leaving the deck, we can optionally persist this to `card.custom_data` to survive app restarts. Keys like `"s"` (current step) and `"p"` (current pass) fit inside the 100-byte custom data limit.
  - The JS overlay mirrors this state to decide which rectangles stay hidden. Use the same `getDisplayCoords()` math as `components/ReviewMode.tsx` (the Next.js app) or reuse the canvas transform helpers from `ts/routes/image-occlusion/review.ts`.
- **Queue Semantics**:
  - Forward fade: one pass through all steps while staying on the same card. Only after the final reveal do we hand the card back to Anki’s scheduler and let the user choose Again/Good/Hard/Easy.
  - Backward fade: maintain a `passNumber` exactly like the Next.js logic. After each pass, if not done, mutate states so the card moves to the back of the local queue but stays at the front of Anki’s queue. Once all passes succeed, call the original `_answerCard`.
  - Implementation detail: the add-on can override the spacebar handler. When the user presses space, JS sends `bridgeCommand("fading:next")`; Python increments the step or, if steps exhausted, calls `_answerCard` (with whichever ease is currently selected) so the card graduates and the scheduler handles spacing.

## Handy Entry Points / APIs
- Python:
  - `aqt.mw.col` – the current collection. Methods like `col.add_notetype`, `col.models`, `col.decks`, `col.conf`.
  - `aqt.mw.reviewer` – the reviewer instance; we can patch attributes or register callbacks.
  - `aqt.addons` – add-on manager (if we need to register config or resources).
- JS:
  - `globalThis.anki` namespace already exports `mutateNextCardStates` and `imageOcclusion`. Our bundle can hang new helpers there for debugging or for deck-level scripts.
  - `bridgeCommand("...")` to talk back to Python; handle commands via `web.set_bridge_command`.
  - `onUpdateHook`/`onShownHook` arrays (in `ts/reviewer/index.ts`) allow us to register DOM setup/teardown logic without touching legacy templates.

These notes should be enough context to start drafting the incremental add-on plan: reuse the stock IO editor to author covers, store structured JSON in a custom notetype, intercept reviewer hooks to run the staged fade logic, only invoke Anki’s scheduler once the multi-step lifecycle is satisfied, and lean on `mutateNextCardStates`/`card.custom_data` to keep the queue deterministic.

## Implementation Plan (Add-on Milestones)

1. **Scaffold Add-on**
   - Create a development add-on folder (e.g., `anki/addons/fading-occlusion` while working in this repo) with `__init__.py`, `manifest.json`, and a packaging script. Register a config schema for global preferences (default fading mode, keyboard overrides).
   - Wire up logging helpers and a dev reload entry point so we can iterate quickly while running `./run` in Anki.

2. **Data Model + Note Type**
   - On add-on load, ensure a custom notetype exists (clone the stock Image Occlusion but rename to “Fading Occlusion”). Fields:
     - `Image`: stored `<img>` tag referencing media.
     - `Covers`: JSON string describing ordered steps (`[{ id, step, mode, rects: [...] }]`).
     - `Notes`/`Extra`: freeform text for annotations.
     - Optional `ModeOverride`: “forward/backward” toggle per card.
   - Provide helper API to fetch/parse the JSON into Python objects, reuse `anki.image_occlusion` parser when possible.

3. **Authoring UI**
   - Add a Tools menu action (“Create Fading Card…”) that opens a PyQt window hosting a webview pointed at our Svelte editor bundle.
   - Reuse `ts/routes/image-occlusion/MaskEditor.svelte` as the base: extend it with sequential numbering, grouping (`G`), move mode, undo, etc., mirroring `components/ImageEditor.tsx` from the Next.js app.
   - On save, serialize cover metadata to JSON, embed the image, and create/update a note in the custom notetype.

4. **Reviewer Overlay**
   - Hook `gui_hooks.card_review_webview_did_init`/`webview_will_set_content` to inject our JS overlay whenever the card’s notetype matches.
   - The JS bundle:
     - Parses the stored JSON, draws covers (similar to `ts/routes/image-occlusion/review.ts` drawing logic).
     - Listens for `space`/`B`/`1` and sends `bridgeCommand` messages (`fadingNext`, `fadingWrong`) to Python.
     - Tracks per-card state (current step index, pass count) and toggles cover visibility.
   - Python side:
     - Maintain in-memory map + optional `card.custom_data` persistence for stage/pass info.
     - Intercept `gui_hooks.reviewer_will_answer_card`: if the card still has pending steps, return `(False, ease)` so Anki doesn’t schedule yet.
     - When JS reports “card complete,” call `_answerCard` with the pending ease; when “wrong,” rebuild queue state (see below).

5. **Queue & State Management**
   - Local queue replicates the Next.js logic:
     - Forward mode: stay on card while steps remain; once done, call `_answerCard` using whichever ease button is selected.
     - Backward mode: use `passNumber` to determine starting step per pass; after each pass (except final), move card to end of local queue and re-request it by mutating states (`anki.mutateNextCardStates`) so scheduler re-shows it immediately.
   - Save minimal state in `card.custom_data` (e.g., `{"f":0,"s":2,"p":1}`) so leaving/reopening the deck resumes where you left off without corrupting the scheduler.

6. **User Controls & Later Queue**
   - Surface UI buttons mirroring the Next.js app (Save for Later, Restart). Hook those into Anki’s existing later queue or implement a per-add-on deferred list stored in deck config/card custom data.
   - Expose a deck option toggle to choose default fading mode; allow per-card overrides via field or custom data.

7. **Testing & Manual QA**
   - Provide lightweight Jest-esque unit tests for the JS overlay logic (step transitions, backward passes).
   - Document manual test steps (create card, add multiple covers, review forward/backward, fail mid-pass, verify queue order) so the user can validate after each milestone.
