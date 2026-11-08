"""Token prices for budget enforcement and usage reports (defaults/prices.yaml, overridable)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from importlib import resources
from pathlib import Path

import yaml

MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    input: Decimal
    output: Decimal


class PriceBook:
    def __init__(self, models: dict[str, Price], self_hosted: set[str]) -> None:
        self._models = models
        self._self_hosted = self_hosted

    @classmethod
    def load(cls, path: Path | None = None) -> PriceBook:
        raw_text = (
            path.read_text(encoding="utf-8")
            if path is not None
            else resources.files("nexiqon_model_gateway.defaults")
            .joinpath("prices.yaml")
            .read_text(encoding="utf-8")
        )
        raw = yaml.safe_load(raw_text) or {}
        models = {
            name: Price(Decimal(str(p.get("input", 0))), Decimal(str(p.get("output", 0))))
            for name, p in (raw.get("models") or {}).items()
        }
        return cls(models, set(raw.get("self_hosted_providers") or []))

    def cost(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> Decimal:
        """Cost in USD; 0 for self-hosted providers and models without a listed price."""
        if provider in self._self_hosted:
            return Decimal(0)
        price = self._models.get(model)
        if price is None:
            return Decimal(0)
        return (price.input * input_tokens + price.output * output_tokens) / MILLION

    def is_priced(self, provider: str, model: str) -> bool:
        return provider in self._self_hosted or model in self._models
