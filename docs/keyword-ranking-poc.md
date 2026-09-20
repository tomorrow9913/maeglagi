# Keyword ranking PoC

Branch: `bm25-fallback-search`.

## Problem and choice

The previous candidate cap was unrelated to BM25 ranking quality and could silently discard an
older, highly relevant passage. It has been removed. This PoC uses BM25+ for the existing keyword
path. Standard BM25's length normalization can drive the contribution of a matched term toward
zero in a long document. BM25+ adds a positive floor for each **present** query term. The floor
is conditional: absent terms contribute zero. This favors coverage of distinct query terms in
long parsed documents while preserving term-frequency saturation. The chosen delta is 1.0;
relevance judgments are needed to tune it.

| Variant | Problem addressed | Fit here |
| --- | --- | --- |
| BM25+ | Long documents receive vanishing credit for a matched term | Small SQL change; chosen for the PoC |
| BM25L | Shifts normalized term frequency for long documents | Plausible alternative; needs comparative judgments |
| BM25F | Weights title and body as separate fields | Useful once title relevance and field lengths can be measured |
| BM25-adpt / BM25T | Uses term-specific saturation | More collection statistics and query cost than justified here |
| `bm25x` | Rust search engine implementing several BM25 variants, not itself one ranking formula | Requires a new index and access-control integration |
| PostgreSQL full-text `ts_rank` | Indexed token retrieval, not BM25 | Built-in tokenization does not handle Korean inflection like the current character pairs |

The application still scopes chunks and parsed source text by owner and workspace before scoring,
and retains review-state and processing-stage rules. Null embeddings remain searchable. Vector
retrieval and the existing policy of including newly parsed source text alongside vectors are
unchanged. No extension, migration, or operating configuration is required.

## Limits and validation

The current score uses character length and overlapping Korean pairs rather than word-token BM25.
Its IDF statistics require scanning the eligible corpus, and long source text is scored as one
item while chunks are scored separately. A labeled Korean and English query set should measure
recall and nDCG for BM25, BM25+, and BM25L before production tuning. PostgreSQL integration
checks require `ASK_TEST_DATABASE_URL` against an isolated database; query plans and latency
should be measured there with `EXPLAIN (ANALYZE, BUFFERS)`.

Research: [BM25L motivation](https://experts.illinois.edu/en/publications/when-documents-are-very-long-bm25-fails/),
[BM25 variant reproducibility study](https://pmc.ncbi.nlm.nih.gov/articles/PMC7148026/),
[bm25x project](https://github.com/lightonai/bm25x).
