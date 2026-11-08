# retrieval

The knowledge index and (from Phase 2 slice 3) hybrid search. Plane: **data**; runs in the `knowledge` group.

The index (`retrieval.index_nodes`) holds each document as a tree (document > section > chunk) with
`parent_id` and an `ltree` path. Chunks have 1024-d pgvector embeddings (HNSW, cosine). A generated
`tsvector` covers keyword search, and `acl_groups` plus the classification are copied onto every node, so
search can filter before ranking. RLS confines every query to the tenant.

| Endpoint | Permission |
|---|---|
| `PUT /v1/index/documents/{id}` (atomic replace; stale versions refused) | `retrieval.index.write` (service only) |
| `DELETE /v1/index/documents/{id}`, `DELETE /v1/index/collections/{id}` | `retrieval.index.write` (service only) |
| `GET /v1/index/documents/{id}/outline`, `GET /v1/index/collections/{id}/stats` | `retrieval.index.read` |

```bash
uv run pytest services/retrieval
```
