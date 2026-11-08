"""Run the retrieval gold set against a live stack with real models (model bake-off, M-07).

Uploads a pack's eval corpus through ingestion (real parsing, scanning and embeddings), waits for
indexing, then asks every gold question through the gateway and prints the report.

    uv run python -m tools.eval.retrieval_eval --tenant <slug> --model-profile on-prem-standard
    # token: NEXIQON_TOKEN (IdP access token); default gateway http://localhost:8000

The in-process CI gate is services/retrieval/tests/test_eval.py (offline embeddings).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from nexiqon_retrieval.evaluation import evaluate, load_gold

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--gateway", default="http://localhost:8000")
    parser.add_argument("--tenant", required=True, help="workspace slug")
    parser.add_argument("--pack", default="saas-knowledge-assistant")
    parser.add_argument("--model-profile", default="cloud-frontier")
    parser.add_argument("--retrieval-profile", default="standard")
    parser.add_argument("--collection", default="eval-gold")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--rerank", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("NEXIQON_TOKEN")
    if not token:
        sys.exit("Set NEXIQON_TOKEN to an access token for the workspace")
    headers = {"Authorization": f"Bearer {token}", "X-Nexiqon-Tenant": args.tenant}
    pack = ROOT / "packs" / args.pack / "eval"
    gw = httpx.Client(base_url=args.gateway, headers=headers, timeout=60)

    collections = gw.get("/ingestion/v1/collections").json()
    existing = next((c for c in collections if c["name"] == args.collection), None)
    collection = (
        existing
        or gw.post(
            "/ingestion/v1/collections",
            json={
                "name": args.collection,
                "model_profile": args.model_profile,
                "retrieval_profile": args.retrieval_profile,
            },
        ).json()
    )
    pending = []
    for path in sorted((pack / "corpus").glob("*")):
        r = gw.post(
            f"/ingestion/v1/collections/{collection['id']}/documents",
            params={"filename": path.name},
            content=path.read_bytes(),
            headers={"content-type": "text/markdown"},
        )
        r.raise_for_status()
        pending.append(r.json()["document"]["id"])
    for doc_id in pending:
        for _ in range(600):
            status = gw.get(f"/ingestion/v1/documents/{doc_id}").json()
            if status["status"] in ("ready", "failed", "quarantined"):
                if status["status"] != "ready":
                    print(
                        f"warning: {status['uri']} is {status['status']}: {status['error_detail']}",
                        file=sys.stderr,
                    )
                break
            time.sleep(1)

    async def search(question: str) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=args.gateway, headers=headers, timeout=60) as client:
            r = await client.post(
                "/retrieval/v1/search",
                json={
                    "query": question,
                    "collection_ids": [collection["id"]],
                    "model_profile": args.model_profile,
                    "retrieval_profile": args.retrieval_profile,
                    "top_k": args.k,
                    "rerank": args.rerank,
                },
            )
        r.raise_for_status()
        result: dict[str, Any] = r.json()
        return result

    report = asyncio.run(evaluate(load_gold(pack / "gold.yaml"), search, k=args.k))
    print(
        json.dumps(
            {"model_profile": args.model_profile, **report.as_dict()}, indent=2, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
