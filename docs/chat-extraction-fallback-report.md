# Chat extraction fallback implementation

Branch: `feature/chat-extraction-fallback` (based on `origin/main` at `f67a3ad`).

## Changes

- The shared `ExtractionPipeline` uses native structured output when available. Chat-only providers receive the stage prompt and JSON Schema; every response is strictly parsed and validated by its Pydantic stage model before a later stage or storage path can use it.
- Malformed or schema-invalid chat output gets one corrective call. Refusal and token-limit completion stop immediately. A model's explicit rejection of native JSON Schema format falls back to chat; other provider errors do not.
- Extraction role catalog and per-provider defaults now include chat-compatible Claude and NVIDIA NIM models. Provider capability flags remain accurate; no native `structuredOutput` claim was added for either provider.
- Context Store updates use the same validated path. Tests confirm invalid extraction and invalid context updates produce no Context Store or graph writes.
- Backend and frontend documentation/catalog fixtures reflect the extraction option.

## Verification

- `RATE_LIMIT=100000/minute uv run pytest -q`: 374 passed.
- `uv run ruff check app tests`: passed.
- `uv run ruff format --check app tests`: passed.
- `npm --prefix frontend run lint`: passed (ESLint and TypeScript).
- `prettier --check` on changed frontend files: passed.
- `git diff --check`: passed.

No paid provider calls or `.env` edits were made. Real Claude and NVIDIA NIM responses still need validation with an authorized test key; fixtures test the local request, validation, retry and storage boundaries. Native-format rejection detection currently recognizes explicit `unsupported_response_format` errors or 400 responses identifying unsupported `response_format`; an undocumented provider error shape may remain an error rather than falling back.

## Proposed PR

**Title:** Support validated graph extraction with chat-only providers

**Body:**

Allow Claude and NVIDIA NIM chat models to serve the extraction role. The shared extraction pipeline retains native structured output where supported and otherwise requests schema-conforming JSON, strictly validates each stage, and permits one corrective retry. Explicit native JSON Schema incompatibility falls back to chat without retrying auth, rate-limit or transport failures. Update provider defaults and mock catalog; cover stage validation, Context Store update, no-write rejection and provider selection. Verified with the full backend suite, Ruff, frontend lint/typecheck and Prettier. Live provider behavior remains to be checked with authorized credentials.
