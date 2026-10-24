"""Payer alias resolution for hospital MRF rows (see data/etl/payer_aliases.yaml)."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path

from app.etl.config import load_yaml

_ID_SUFFIX = re.compile(r"\s*\[[0-9]*\]?\s*$")
_WS = re.compile(r"\s+")
_PAREN = re.compile(r"\([^)]*\)")


def clean_payer(raw: str) -> str:
    """'AETNA [1001]' -> 'AETNA'; also drops a truncated id suffix ('... [35')."""
    s = _WS.sub(" ", (raw or "").strip().upper())
    return _ID_SUFFIX.sub("", s).strip()


def clean_plan(raw: str) -> str:
    return _WS.sub(" ", (raw or "").strip().upper())


@dataclass(frozen=True)
class PayerResolution:
    payer_id: str | None
    line_of_business: str
    product: str
    excluded: bool
    exclude_reason: str
    payer_plan_mismatch: bool


@dataclass(frozen=True)
class _Rule:
    target: str
    payer: re.Pattern[str] | None
    plan: re.Pattern[str] | None

    def match(self, payer: str, plan: str) -> bool:
        if self.payer is not None and not self.payer.search(payer):
            return False
        if self.plan is not None and not self.plan.search(plan):
            return False
        return True


def _rx(s: str | None) -> re.Pattern[str] | None:
    return re.compile(s) if s else None


class PayerResolver:
    def __init__(self, cfg: dict) -> None:
        self.payers: dict[str, dict] = cfg["payers"]
        self.payer_rules = [
            _Rule(r["payer_id"], _rx(r.get("payer")), _rx(r.get("plan")))
            for r in cfg["payer_rules"]
        ]
        self.exclusions = [
            _Rule(r["reason"], _rx(r.get("payer")), _rx(r.get("plan"))) for r in cfg["exclusions"]
        ]
        self.lob_rules: list[tuple[str, re.Pattern[str]]] = [
            (str(r["lob"]), re.compile(r["re"])) for r in cfg["lob_rules"]
        ]
        self.products = [(p, re.compile(rf"\b{re.escape(p)}\b")) for p in cfg["products"]]
        self.tokens = {k: re.compile(v) for k, v in cfg["carrier_tokens"].items()}
        for r in self.payer_rules:
            if r.target not in self.payers:
                raise ValueError(f"payer rule targets unknown payer_id {r.target}")

    @classmethod
    @functools.lru_cache(maxsize=2)
    def load(cls, config_dir: Path | None = None) -> PayerResolver:
        return cls(load_yaml("payer_aliases.yaml", config_dir))

    def _lob(self, payer_id: str | None, payer: str, plan: str) -> str:
        lob: str | None = None
        # "(130% OF MEDICARE)" is a pricing note, not the product.
        for text in (_PAREN.sub(" ", plan), payer):
            for name, rx in self.lob_rules:
                if rx.search(text):
                    lob = name
                    break
            if lob:
                break
        if lob is None:
            return str(self.payers[payer_id]["default_lob"]) if payer_id else "unknown"
        # A plan that only says MEDICARE / MEDICAID under a private carrier is a managed product.
        if lob == "medicare" and payer_id not in (None, "MEDICARE"):
            return "medicare_advantage"
        if lob == "medicaid" and payer_id not in (None, "MASSHEALTH"):
            return "medicaid_managed"
        return lob

    @functools.lru_cache(maxsize=65536)  # noqa: B019 - resolver instances are long-lived singletons
    def resolve(self, payer_raw: str, plan_raw: str) -> PayerResolution:
        payer, plan = clean_payer(payer_raw), clean_plan(plan_raw)
        payer_id = next((r.target for r in self.payer_rules if r.match(payer, plan)), None)
        reason = next((r.target for r in self.exclusions if r.match(payer, plan)), "")
        product = "/".join(p for p, rx in self.products if rx.search(plan))
        mismatch = False
        if payer_id in self.tokens:
            own = self.tokens[payer_id]
            others = [k for k, rx in self.tokens.items() if k != payer_id and rx.search(plan)]
            mismatch = bool(others) and not own.search(plan)
        return PayerResolution(
            payer_id=payer_id,
            line_of_business=self._lob(payer_id, payer, plan),
            product=product,
            excluded=bool(reason),
            exclude_reason=reason,
            payer_plan_mismatch=mismatch,
        )
