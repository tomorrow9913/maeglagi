# Public PoC database demo

The public demo uses one explicitly selected workspace in the application database.
`DEMO_WORKSPACE_ID` is the server allowlist for read-only `/api/v1/demo/*` routes; an empty or
unknown value makes those routes unavailable. Private workspace routes still require a signed-in
owner. Use an existing Supabase user's UUID as the owner and a new, dedicated public workspace
UUID. Only that workspace is published; the owner's other workspaces remain private.

The seed source is only `backend/app/demo_data/poc.json`, exported from the existing public PoC
examples. It includes two named people without emails, one project, three text sources, review
snapshots for the two meetings, seven text chunks, six timeline items, the context store, and graph
examples. Meeting source rows have `text/plain` content because no recording bytes exist. Playback
returns 404; no audio file, Storage object, vector, provider key, or real email is fabricated.
Embeddings are `NULL`, so vector search over this fixture cannot produce results until a separate
explicit indexing operation using a compatible model is authorized.

## Preview and apply

First apply the project knowledge database migration to the target database. From `backend/`,
preview the exact counts without connecting to Postgres or Neo4j:

```bash
uv run python -m app.demo_seed --owner <dedicated-owner-uuid> --workspace <public-workspace-uuid>
```

The command writes only with `--execute`, and only to the databases configured for that backend
process:

```bash
uv run python -m app.demo_seed --owner <dedicated-owner-uuid> --workspace <public-workspace-uuid> --execute
```

Review the target `DATABASE_URL` and optional `NEO4J_*` server settings before that command.
The script refuses an existing workspace unless the owner and exact fixture digest marker match;
it generates stable UUIDs for fixture records and skips existing rows on repeat, preserving edits.
It never imports private workspaces. A failed Neo4j write can be retried with the same command:
Postgres rows are committed first, then graph nodes and edges are added idempotently when Neo4j is
configured. The public demo graph requires Neo4j so it preserves the original decisions, tasks,
events, and replacement relationships. Without Neo4j it reports an unavailable graph instead of
silently displaying only directory and material nodes. Private workspace directory graphs can
still be used without Neo4j.

After verifying the seeded workspace, set `DEMO_WORKSPACE_ID` to that workspace UUID on the API
deployment. Do not set it to a private workspace. Publication and production execution are
separate operator actions; neither occurs during a dry run.
