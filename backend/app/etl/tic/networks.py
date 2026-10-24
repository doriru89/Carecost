"""The TiC network registry (``data/etl/tic_networks.yaml`` + ``sources.d/tic.yaml``) and the
per-payer visit-code map (``data/etl/tic_visit_codes.yaml``)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.etl.config import CONFIG_DIR, load_codes, load_sources, load_yaml

LOBS = {"commercial", "connector"}
PRODUCTS = {"HMO", "PPO", "POS", "EPO", "INDEMNITY", ""}


@dataclass(frozen=True)
class TicNetwork:
    source_id: str
    payer_id: str
    label: str
    product: str
    lob: str
    url: str
    container: str  # gzip | zip
    registered: bool  # True = a SourceSpec in sources.d/tic.yaml
    toc: str  # discovery TOC source_id
    match: str  # regex on the file URL / name in the TOC
    why: str
    max_bytes: int
    max_raw: int  # decompressed-bytes cap (gzip-bomb guard)
    rewrite: tuple[str, str] | None = None  # applied to TOC URLs before matching

    @property
    def basename(self) -> str:
        return self.url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]


# A TiC gzip inflates ~10-35x (UHC 20x, HP zip 33x). Anything past 60x is refused.
MAX_RATIO = 60


def load_networks(config_dir: Path | None = None) -> list[TicNetwork]:
    cfg = load_yaml("tic_networks.yaml", config_dir)
    sources = load_sources(config_dir)
    out: list[TicNetwork] = []
    seen: set[str] = set()
    for n in cfg["networks"]:
        sid = n["source_id"]
        if sid in seen:
            raise ValueError(f"tic_networks.yaml: duplicate {sid}")
        seen.add(sid)
        if n.get("lob") not in LOBS or n.get("product", "") not in PRODUCTS:
            raise ValueError(f"{sid}: bad lob/product")
        disc = n.get("discover") or {}
        re.compile(disc.get("match", ""))
        if n.get("unregistered"):
            try:
                sources.get(sid)
                raise ValueError(f"{sid}: marked unregistered but present in sources")
            except KeyError:
                pass
            url, container, payer = n["url"], n["container"], n["payer_id"]
            max_bytes = int(n.get("max_bytes", 1_000_000_000))
            registered = False
        else:
            spec = sources.get(sid)
            if spec.format != "tic_in_network":
                raise ValueError(f"{sid}: format {spec.format} is not tic_in_network")
            if not spec.url:
                raise ValueError(f"{sid}: no url")
            url, container, payer = spec.url, spec.container, spec.payer_id or ""
            max_bytes = spec.max_bytes or sources.fetch.default_max_bytes
            registered = True
        if container not in ("gzip", "zip"):
            raise ValueError(f"{sid}: container {container}")
        toc = disc.get("toc", "")
        if toc:
            tspec = sources.get(toc)
            if tspec.format != "tic_table_of_contents" or tspec.payer_id != payer:
                raise ValueError(f"{sid}: discover.toc {toc} is not a {payer} TOC")
        out.append(
            TicNetwork(
                source_id=sid,
                payer_id=payer,
                label=n["label"],
                product=n.get("product", ""),
                lob=n["lob"],
                url=url,
                container=container,
                registered=registered,
                toc=toc,
                match=disc.get("match", ""),
                why=n.get("why", ""),
                max_bytes=max_bytes,
                max_raw=max_bytes * MAX_RATIO,
                rewrite=tuple(disc["rewrite"]) if disc.get("rewrite") else None,  # type: ignore[arg-type]
            )
        )
    return out


def get_network(source_id: str, config_dir: Path | None = None) -> TicNetwork:
    for n in load_networks(config_dir):
        if n.source_id == source_id:
            return n
    raise KeyError(f"unknown TiC network {source_id!r} (see data/etl/tic_networks.yaml)")


# ------------------------------------------------------------------- visit codes


@dataclass(frozen=True)
class VisitMap:
    em_codes: list[str]
    add_ons: list[str]
    payers: dict[str, dict[str, Any]]
    pos_buckets: dict[str, list[str]] = field(default_factory=dict)

    def visit_codes(self, payer_id: str) -> tuple[str, list[str]]:
        """-> (shape, codes) for a payer's office / urgent-care visit."""
        p = self.payers.get(payer_id)
        if p is None:
            return "per_code", list(self.em_codes)
        codes = p["visit_codes"]
        return p["shape"], list(self.em_codes) if codes == "em" else list(codes)

    def pos_bucket(self, service_codes: list[str]) -> str:
        """``non_facility`` (the list includes office POS 11), ``facility`` (no 11, some facility
        POS), else ``unknown``. Payers list overlapping POS sets (HP's non-facility rate lists
        almost every POS, its facility rate adds telehealth 02), so "contains 11" is the
        deciding test, as in research-v3/tic-structure.md."""
        s = set(service_codes)
        if "11" in s:
            return "non_facility"
        if s & set(self.pos_buckets.get("facility", [])):
            return "facility"
        return "unknown"

    @property
    def all_codes(self) -> set[str]:
        out = set(self.em_codes) | set(self.add_ons)
        for p in self.payers.values():
            if p["visit_codes"] != "em":
                out |= set(p["visit_codes"])
        return out


def load_visit_map(config_dir: Path | None = None) -> VisitMap:
    d = load_yaml("tic_visit_codes.yaml", config_dir)
    return VisitMap(d["em_codes"], d["add_ons"], d["payers"], d.get("pos_buckets", {}))


def target_codes(config_dir: Path | None = None) -> set[str]:
    """codes.yaml + every payer's visit codes: the TiC code filter."""
    return load_codes(config_dir).codes | load_visit_map(config_dir).all_codes


__all__ = ["CONFIG_DIR", "TicNetwork", "VisitMap", "load_networks", "get_network"]
