"""Demo business APIs for development and tests (T-04). NOT part of the platform.

Two independent "customer" datasets, each reached with its own bearer token: an account and
plan lookup, and a case (support request) API. Responses deliberately include a field the
tool definition should not pass on (``internal_notes``), to show result minimisation.

Run: ``uvicorn nexiqon_tool_gateway.mock_apis:app --port 9000`` (the dev stack does this).
"""

from __future__ import annotations

import hashlib
import itertools
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

TOKENS = {"demo-token-acme": "acme", "demo-token-globex": "globex"}
PLANS = {"acme": ["Free", "Team", "Enterprise"], "globex": ["Starter", "Growth"]}
app = FastAPI(
    title="Demo business APIs", version="1.0.0", servers=[{"url": "http://mock-apis:9000"}]
)
_cases: dict[str, dict[str, dict[str, Any]]] = {"acme": {}, "globex": {}}
_ids = itertools.count(1001)


def _dataset(authorization: str | None) -> str:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token not in TOKENS:
        raise HTTPException(status_code=401, detail="invalid token")
    return TOKENS[token]


class Account(BaseModel):
    account_id: str
    customer_id: str
    plan: str
    status: str
    seats: int
    renews_on: date
    internal_notes: str


@app.get(
    "/accounts/{customer_id}",
    response_model=Account,
    operation_id="getAccount",
    summary="Look up a customer's account and plan",
)
async def get_account(
    customer_id: str, authorization: str | None = Header(default=None)
) -> Account:
    dataset = _dataset(authorization)
    seed = int(hashlib.sha256(f"{dataset}:{customer_id}".encode()).hexdigest(), 16)
    plans = PLANS[dataset]
    return Account(
        account_id=f"{dataset[:3]}-{seed % 100000:05d}",
        customer_id=customer_id,
        plan=plans[seed % len(plans)],
        status="active",
        seats=1 + seed % 50,
        renews_on=date(2026, 12, 1) + timedelta(days=seed % 90),
        internal_notes=f"credit-risk score {seed % 1000}",  # must never reach a model
    )


class CaseIn(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=4000)


class Case(BaseModel):
    case_id: str
    subject: str
    status: str


@app.post(
    "/cases",
    response_model=Case,
    status_code=201,
    operation_id="createCase",
    summary="Open a support case for the customer",
)
async def create_case(body: CaseIn, authorization: str | None = Header(default=None)) -> Case:
    dataset = _dataset(authorization)
    case = {
        "case_id": f"C-{next(_ids)}",
        "subject": body.subject,
        "status": "open",
        "description": body.description,
    }
    _cases[dataset][case["case_id"]] = case
    return Case(**case)


@app.get(
    "/cases/{case_id}",
    response_model=Case,
    operation_id="getCase",
    summary="Check the status of a support case",
)
async def get_case(case_id: str, authorization: str | None = Header(default=None)) -> Case:
    case = _cases[_dataset(authorization)].get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    return Case(**case)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
