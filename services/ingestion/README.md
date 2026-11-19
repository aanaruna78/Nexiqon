# ingestion

Turns sources into searchable knowledge. Plane: **data**; runs in the `knowledge` group with retrieval.

```
source --discover--> items --fetch--> file (object storage) --scan--> parse --> document tree
       --> chunk --> embed (model gateway) --> index (retrieval, atomic replace per document)
```

- **Plugins** (`nexiqon-sdk`): connectors `upload`, `web` (robots.txt, sitemaps, include/exclude, depth),
  `s3` (any S3-compatible bucket) and `git` (HTTPS shallow clone). Parsers: Markdown, HTML, text, PDF
  (pages and bookmarks), DOCX, CSV, JSON. Chunkers: `heading-aware` (default) and `token`. Third-party
  plugins register under the `nexiqon.plugins` entry point, and `GET /v1/plugins` lists them for Studio.
- **Safety:** every URL goes through the SSRF-safe fetcher (public addresses only, connection pinned
  to the checked address, redirects re-checked, size caps). Every file is scanned by ClamAV first.
  Infected files are quarantined and never parsed. Connector secrets are operator-provisioned
  (`connector_credentials`) and referenced by name.
- **Workflows (Temporal):** `SyncSource`, `IngestDocument` and `ReindexCollection`. The activities are
  idempotent, and a killed worker resumes. Only changed content is re-embedded: the source version
  (ETag, object ETag, git blob sha) is checked first, then a content hash. A complete sync deletes
  documents the source no longer has.
- **Errors** are recorded on the document as `error_code` for Studio's fix hints. Codes:
  `unsupported_type`, `parse_failed`, `empty_document`, `malware_detected`, `scan_unavailable`,
  `fetch_blocked`, `fetch_failed`, `too_large`, `credentials_missing`, `embedding_failed`,
  `embedding_model_changed`, `profile_unavailable`, `temporarily_unavailable`.
- **Calls to other services** use ingestion's own service identity (ADR 0017).

```bash
uv run pytest services/ingestion        # unit + end-to-end (Postgres, Temporal test server)
```

**Q&A snippets (RT-04).** The `snippets` connector holds reviewed question-and-answer pairs (edit them
with `PATCH /v1/sources/{id}`; the next sync re-indexes only what changed). Each pair becomes a
`snippet://` document, which retrieval ranks above other content by the retrieval profile's
`search.snippet_boost` (default 1.5). A reviewed answer therefore wins over an outdated page until
the page is fixed.

**Download links (RT-06).** `POST /v1/documents/{id}/download-link` returns a link valid for
`download_link_seconds` (default 300). The link names the tenant, document, version and the person
it was issued to, and is signed (HMAC-SHA256, `download_signing_key`; set the same key on every
replica). `GET /v1/downloads/{token}` serves the original file as an attachment only to that
person, in that tenant, while the file is still that version and still visible to them. Anything
else gets "not found".
