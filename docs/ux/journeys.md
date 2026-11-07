# Top journeys (draft)

Targets come from UX.md §6. Each journey gets a usability task at the end of the phase that delivers it.

| # | Journey | Persona | Target | Delivered in |
|---|---|---|---|---|
| J1 | Sign up → pick Domain Pack → add docs URL → first cited answer | P1 | ≤ 10 min unassisted | Phase 4 (ST-13), partial in Phase 2 |
| J2 | Embed the widget on a website | P1/P3 | ≤ 5 min | Phase 4 (ST-15), W-00 basic in Phase 3 |
| J3 | Investigate a wrong answer and fix it | P1 | ≤ 3 min | Phase 3–4 (ST-07, ST-14) |
| J4 | Add an account-lookup tool from an OpenAPI spec and test it | P3 | ≤ 10 min | Phase 3 (ST-09) |
| J5 | Publish a new assistant version safely, roll back if worse | P1 | No regression reaches prod | Phase 4 (QA-02) |
| J6 | Check who can see which documents ("view as") | P2 | Correct in one attempt | Phase 3 (ST-08) |
| J7 | Set model/data policy (e.g. confidential collections stay on-prem) | P2 | Admin can explain the data flow afterwards | Phase 3 (ST-12) |
| J8 | End user gets an answer or reaches a human with context | P4 | Handoff carries summary; no dead ends | Phase 3–4 (CV-02, W-03) |

## J1 in steps (happy path)

1. Sign up (Clerk) → organisation created → tenant provisioned.
2. Choose "SaaS Knowledge Assistant" pack.
3. Paste docs URL; crawl starts with live progress and an estimate.
4. While indexing: brand colour, assistant name.
5. Suggested starter questions appear; ask one; see the answer with section-path citations.
6. Copy the embed snippet; preview on a sample page.

Failure states to design: crawl blocked by robots.txt, login-protected docs, unsupported file types, zero
answerable content, slow crawl, the user leaves mid-way (resume later).
