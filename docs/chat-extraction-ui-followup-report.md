# Extraction and UI follow-up

Branch: `feature/chat-extraction-fallback`, continuing commit `6f65dad`.

## Behavior

- Chat extraction stops immediately when a provider marks completion as `refusal` or `content_filter`; it does not spend the corrective retry. This covers Anthropic `stop_reason` through the existing provider metadata mapping. Existing explicit refusal and token-limit handling remain covered.
- Meeting capture shows a continuous two-column transcript with editable speaker selection and auto-growing text. Speaker colors use text only; each utterance has no card or background. Tab adds the next utterance from the final nonempty row, Shift+Tab moves to the previous utterance, and deletion works during recognition without the recognition update restoring the deleted row.
- The meeting source viewer renders serialized speaker lines in the same two-column style. Time ranges remain visible in small muted text, and cited chunks retain a highlight.
- The workspace sidebar has one source list with visible file and meeting actions. It stays alongside Ask on desktop and collapses on mobile. Ask's input plus opens that same sidebar upload dialog; the sidebar source viewer opens in place, and upload/processing events refresh the list. The demo stays under `/demo` with its existing scoped mock provider.

## Checks

- Backend extraction/source-analysis regression: 31 passed.
- Ruff check and format for `app tests`: passed.
- Frontend ESLint and TypeScript: passed.
- Frontend production build: passed. The repository has no frontend test script.
- `git diff --check`: passed.

QA server: `http://localhost:3100/demo/ask` (alternate `http://192.168.45.185:3100/demo/ask`), production server session `71006`; leave running for coordinator to stop. The page returned HTTP 200. Visual and interaction QA is for the coordinator; no microphone or paid provider calls were made.
