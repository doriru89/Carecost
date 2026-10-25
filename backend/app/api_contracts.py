"""Wave-2 API contracts: JSON Schema export + TypeScript types for the frontend.

    python -m app.api_contracts            (from backend/) writes
      contracts/quote_api.schema.json   contracts/chat_api.schema.json
      contracts/catalog.schema.json     contracts/site.schema.json
      frontend/src/generated/contracts/{quote_api,chat_api,catalog}.ts

    python -m app.api_contracts --check    exit 1 if any committed file is stale

Tests (tests/contracts/test_api_contracts.py) fail when the committed files drift.

Schema mode: API payloads (quote, chat, catalog) are exported in *serialization* mode with every
field required, because the server always emits every field (pydantic dumps defaults). That keeps
``kind`` required on Money / Gap, so TypeScript can narrow the unions. Request models have no
defaults at all, so their schema is the same in both modes. ``site.schema.json`` describes a YAML
file people write by hand, so it is exported in *validation* mode (defaults may be omitted).

The TypeScript generator is ~100 lines here instead of an npm dependency: it only needs the subset
of JSON Schema that pydantic emits ($defs/$ref, const, enum, anyOf/oneOf, arrays, records).
"""

from __future__ import annotations

import json
import sys
import typing
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema, models_json_schema

from app.chat import contracts as chat
from app.etl import contracts as etl
from app.quote import contracts as quote
from app.sites import contracts as sites

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"
TS_DIR = REPO_ROOT / "frontend" / "src" / "generated" / "contracts"
ID_BASE = "https://carecost.local/contracts/"


class _EmittedSchema(GenerateJsonSchema):
    """Serialization mode, and every field is required: it is always present in the output."""

    def field_is_required(self, field: Any, total: bool) -> bool:
        if self.mode == "serialization":
            return True
        return super().field_is_required(field, total)


def _union_alias(tp: Any) -> dict[str, Any]:
    """Named union alias (Cell, Gap, Payment, ChatReply) as a $def of refs."""
    args = (
        typing.get_args(typing.get_args(tp)[0])
        if typing.get_origin(tp) is typing.Annotated
        else typing.get_args(tp)
    )
    return {"oneOf": [{"$ref": f"#/$defs/{a.__name__}"} for a in args]}


def _literal_alias(tp: Any, doc: str) -> dict[str, Any]:
    return {"enum": list(typing.get_args(tp)), "type": "string", "description": doc}


# file -> (root models, mode, named aliases added to $defs)
SPECS: dict[str, dict[str, Any]] = {
    "quote_api.schema.json": {
        "title": "QuoteApi",
        "models": [quote.QuoteRequest, quote.QuoteResponse, quote.OurDataResponse],
        "mode": "serialization",
        "aliases": {
            "Cell": _union_alias(etl.Cell),
            "Gap": _union_alias(etl.Gap),
            "Payment": _union_alias(quote.Payment),
            "CertaintyTier": _literal_alias(quote.CertaintyTier, "D8 display gradient"),
            "Likelihood": _literal_alias(quote.Likelihood, "care path likelihood_tier"),
            "BillComponent": _literal_alias(quote.BillComponent, "which part of the bill"),
            "LadderExplanation": _literal_alias(quote.LadderExplanation, "doctor-fee copy key"),
            "ExcludedReason": _literal_alias(quote.ExcludedReason, "why a line is not summed"),
            "TierBasis": _literal_alias(quote.TierBasis, "what a line's likelihood rests on"),
            "SourceCadence": _literal_alias(sites.SourceCadence, "(a) publisher deadline rule"),
            "OurCadence": _literal_alias(sites.OurCadence, "(b) our own refresh schedule"),
        },
        "ts": "quote_api.ts",
    },
    "chat_api.schema.json": {
        "title": "ChatApi",
        "models": [chat.ChatRequest, chat.ChatResponse],
        "mode": "serialization",
        "aliases": {
            "ChatReply": _union_alias(chat.ChatReply),
            "Payment": _union_alias(quote.Payment),
            "Disposition": _literal_alias(chat.Disposition, "redflags.json dispositions"),
        },
        "ts": "chat_api.ts",
    },
    "catalog.schema.json": {
        "title": "CatalogApi",
        "models": [quote.Catalog],
        "mode": "serialization",
        "aliases": {},
        "ts": "catalog.ts",
    },
    "site.schema.json": {
        "title": "SitesFile",
        "models": [sites.SitesFile],
        "mode": "validation",
        "aliases": {},
        "ts": None,  # sites.yaml is server-side input; the browser gets SiteSummary in quotes
    },
}

# Request/response roots by name, for tests and fixtures.
ROOT_MODELS: dict[str, type[BaseModel]] = {
    m.__name__: m for spec in SPECS.values() for m in spec["models"]
}


def build_schema(name: str) -> dict[str, Any]:
    spec = SPECS[name]
    gen = _EmittedSchema if spec["mode"] == "serialization" else GenerateJsonSchema
    refs, top = models_json_schema(
        [(m, spec["mode"]) for m in spec["models"]], schema_generator=gen
    )
    defs: dict[str, Any] = dict(top.get("$defs", {}))
    for alias, body in spec["aliases"].items():
        if alias in defs:
            raise ValueError(f"{name}: alias {alias} collides with a model")
        defs[alias] = body
    roots = [refs[(m, spec["mode"])] for m in spec["models"]]
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ID_BASE + name,
        "title": spec["title"],
        "$defs": dict(sorted(defs.items())),
    }
    if len(roots) == 1:
        schema.update(roots[0])
    else:
        schema["anyOf"] = roots
    return schema


def json_schemas() -> dict[str, dict[str, Any]]:
    return {name: build_schema(name) for name in SPECS}


# --------------------------------------------------------------------------- TypeScript


def _lit(v: Any) -> str:
    return json.dumps(v)


def _ts(s: dict[str, Any]) -> str:
    if "$ref" in s:
        return str(s["$ref"]).rsplit("/", 1)[-1]
    if "const" in s:
        return _lit(s["const"])
    if "enum" in s:
        return " | ".join(_lit(v) for v in s["enum"])
    for key in ("anyOf", "oneOf"):
        if key in s:
            parts = []
            for sub in s[key]:
                part = _ts(sub)
                if part not in parts:
                    parts.append(part)
            return " | ".join(parts)
    t = s.get("type")
    if isinstance(t, list):
        return " | ".join(_ts({**s, "type": x}) for x in t)
    if t == "string":
        return "string"
    if t in ("number", "integer"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "array":
        inner = _ts(s.get("items", {}))
        return f"({inner})[]" if "|" in inner else f"{inner}[]"
    if t == "object":
        if "properties" in s:
            raise ValueError("inline object schemas are not supported; use a model")
        ap = s.get("additionalProperties")
        return f"Record<string, {_ts(ap)}>" if isinstance(ap, dict) else "Record<string, unknown>"
    return "unknown"


def _doc(text: str | None, indent: str = "") -> list[str]:
    if not text:
        return []
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    return [f"{indent}/**", *[f"{indent} * {ln}".rstrip() for ln in lines], f"{indent} */"]


def _prop_name(name: str) -> str:
    return name if name.isidentifier() else json.dumps(name)


def typescript(schema: dict[str, Any], source: str) -> str:
    out = [
        f"// GENERATED from contracts/{source} by `python -m app.api_contracts`. Do not edit.",
        "// A drift test (backend/tests/contracts) fails when this file is stale.",
        "",
    ]
    for name, d in schema["$defs"].items():
        out += _doc(d.get("description"))
        if "properties" in d:
            req = set(d.get("required", []))
            out.append(f"export interface {name} {{")
            for pname, ps in d["properties"].items():
                out += _doc(ps.get("description"), "  ")
                opt = "" if pname in req else "?"
                out.append(f"  {_prop_name(pname)}{opt}: {_ts(ps)};")
            out.append("}")
        else:
            out.append(f"export type {name} = {_ts(d)};")
        out.append("")
    return "\n".join(out)


def typescript_files() -> dict[str, str]:
    files = {}
    for name, spec in SPECS.items():
        if spec["ts"]:
            files[spec["ts"]] = typescript(build_schema(name), name)
    return files


# --------------------------------------------------------------------------- write / check


def _schema_text(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def expected_files() -> dict[Path, str]:
    files = {CONTRACTS_DIR / n: _schema_text(s) for n, s in json_schemas().items()}
    files.update({TS_DIR / n: t for n, t in typescript_files().items()})
    return files


def stale_files() -> list[Path]:
    return [p for p, text in expected_files().items() if not p.exists() or p.read_text() != text]


def write_all() -> list[Path]:
    written = []
    for p, text in expected_files().items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        written.append(p)
    return written


if __name__ == "__main__":  # pragma: no cover
    if "--check" in sys.argv:
        stale = stale_files()
        for p in stale:
            print(f"STALE {p.relative_to(REPO_ROOT)}")
        sys.exit(1 if stale else 0)
    for p in write_all():
        print(p.relative_to(REPO_ROOT))
