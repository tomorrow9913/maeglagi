# Keyword ranking PoC

Branch: `bm25-fallback-search`.

## Decision

Keep the existing literal substring and Korean character-pair matching, then rank a bounded
candidate set with the existing BM25 variant. Each chunk and parsed-source query takes at most
2,000 recent matching rows into the scoring CTE. Candidate selection includes owner, workspace,
source eligibility, and optional graph source IDs before the limit. Output remains at most eight
rows with at most 1,200 characters each. Null embeddings remain searchable.

| Design | Benefit | Cost for this PoC |
| --- | --- | --- |
| PostgreSQL `tsvector` / `ts_rank` | Native GIN index and ranking | The built-in configurations do not stem Korean questions; inflected terms would regress without a separate tokenizer. |
| PostgreSQL BM25 extension | Index-assisted BM25 | Adds an extension and deployment compatibility requirement to Supabase/Render. |
| Pluggable ranker interface | Allows later engines | Adds abstraction before a second ranker or benchmark exists. |
| Bounded substring candidates + BM25 | Preserves Korean matching and current evidence behavior without a new extension | Substring filtering can still scan text; a relevant older row can fall outside the 2,000 most recent matches. IDF is estimated on candidates, not the complete workspace. |

The vector path and its ordering are unchanged. The retrieval layer still includes parsed text
that has no vector when semantic search succeeds. Keyword search is also used when query
embedding fails or no vector hits are available. The same lexical function serves Ask and the
agent knowledge interface.

## Next measurement

Run the PostgreSQL integration tests with `ASK_TEST_DATABASE_URL` against an isolated pgvector
database. Benchmark workspace sizes and Korean/English queries with `EXPLAIN (ANALYZE, BUFFERS)`.
If substring filtering dominates, test `pg_trgm` indexes for terms of at least three characters
and measure two-character Korean pair queries separately. Compare recall against the unbounded
query before choosing an index or a tokenizer extension.
