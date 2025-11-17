# Fading Occlusion Add-on (Work in Progress)

Development workspace for bringing the sequential “fading flashcards” workflow into Anki’s desktop client via an add-on. The plan is to:

1. Register/maintain a dedicated note type that stores base images plus ordered cover metadata.
2. Provide an image editor (Qt webview hosting a Svelte bundle) so users can draw sequential covers just like in the standalone Next.js app.
3. Override the reviewer UI for those cards: draw covers, honor forward/backward fading, and defer scheduling until all steps succeed.

This folder houses the Python glue, future TS bundles, and metadata (`manifest.json`). The add-on is not yet usable; it will gradually replace the Next.js workflow as features land.
