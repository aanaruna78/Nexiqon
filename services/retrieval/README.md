# retrieval

The knowledge index, hybrid search and citation checks. Plane: **data**; runs in the `knowledge`
group with ingestion.

**Index.** `retrieval.index_nodes` holds each document as a tree (document > section > chunk) with
`parent_id` and an `ltree` path. Chunks have 1024-d pgvector embeddings (HNSW, cosine) and record the
embedding model; a generated `tsvector` covers keyword search. Access groups and classification are
copied onto every node. RLS confines every query to the tenant. Ingestion writes it (service-only).

**Search** (`POST /v1/search`) runs as the caller:

1. The query is embedded through the model gateway with the caller's token. Vector search covers
   only chunks of that embedding model.
2. Keyword search uses an OR of the query terms with the language-neutral `simple` configuration, so
   it works for every script. Per-language stemming is a later refinement.
3. The filters (collections, access groups, classification ceiling per actor type) are SQL predicates
   in the same statement as the HNSW scan, with pgvector's iterative scan: **filter before rank**.
   Owners and admins see all groups (`acl_bypass_roles`); widgets see at most `internal`.
4. Weighted reciprocal-rank fusion and de-duplication, then optional reranking through the model
   profile's reranker.
5. **Small-to-big**: hits are grouped by parent section and expanded to the whole section within the
   context budget; sibling hits merge. Citations read `Doc \u203a Section, p.4`.
6. The answer **abstains** when the best evidence (cosine similarity, or rerank score) is below
   `min_evidence_score`. Timings are returned. `nexiqon.retrieval.search.duration` (ms, excluding
   reranking) feeds the Grafana panel and the P95 > 100 ms alert.

**Answer contract** (`POST /v1/citations/verify`). Grounded answers cite passages as `[n]`. The check
removes citations to passages the caller cannot see, quotes not found in the passage, and markers on
sentences their passages do not support. It abstains when none remain.

**Quality gate.** `make eval-retrieval` runs the SaaS Knowledge Assistant gold set
(`packs/saas-knowledge-assistant/eval`; English, Spanish and Arabic) with offline embeddings. It
requires Recall@5 >= 0.8, small-to-big >= the flat baseline, and P95 < 100 ms. For real models (M-07),
use `python -m tools.eval.retrieval_eval --tenant <slug> --model-profile <profile>` against a stack.

| Endpoint | Permission |
|---|---|
| `POST /v1/search`, `POST /v1/citations/verify` | `retrieval.search.run` / `.verify` (members, end users, widgets) |
| `PUT/DELETE /v1/index/...` | `retrieval.index.write` (service only) |
| `GET /v1/index/documents/{id}/outline`, `.../collections/{id}/stats` | `retrieval.index.read` |
