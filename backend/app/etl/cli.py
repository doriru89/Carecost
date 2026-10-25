"""Single ETL entry point (identical locally and in GitHub Actions)::

    python -m app.etl [--data-dir D] [--config-dir C] fetch     [--source ID|all] [--import-dir DIR]
    python -m app.etl ...                             stage     [--source ID|all] [--force] [--allow-shrink]
    python -m app.etl ...                             normalize [--source ID|all] [--force]
    python -m app.etl ...                             build     [--build-date YYYY-MM-DD]
                                                                [--baseline-manifest PATH | --first-build]
    python -m app.etl ...                             report    [--build ID] [--out DIR]
    python -m app.etl ...                             tic       discover|run|verify|normalize|report|release|probe

Every subcommand exits non-zero when anything failed, after finishing the other sources.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

from app.etl import build as build_mod
from app.etl import fetch as fetch_mod
from app.etl import normalize as normalize_mod
from app.etl import report as report_mod
from app.etl import stage as stage_mod
from app.etl.config import Paths, SourcesFile, SourceSpec, load_codes, load_sources, load_yaml
from app.etl.payers import PayerResolver
from app.etl.tic import cli as tic_cli


def _log(msg: str) -> None:
    print(msg, flush=True)


def _rate_row_specs(sources: SourcesFile, which: str | None) -> list[SourceSpec]:
    """stage / normalize read hospital MRFs only; other formats are skipped, not failed."""
    out = []
    for spec in sources.select(which):
        if spec.is_rate_row_source:
            out.append(spec)
        else:
            _log(f"SKIP   {spec.source_id}: format {spec.format} is not a hospital MRF")
    return out


def cmd_fetch(a: argparse.Namespace, paths: Paths) -> int:
    sources = load_sources(a.config_dir)
    errors = 0
    for spec in sources.select(a.source):
        if spec.access != "download":
            _log(f"SKIP   {spec.source_id}: access={spec.access} is read by its own pipeline")
            continue
        try:
            if a.import_dir:
                rec = fetch_mod.import_local(spec, Path(a.import_dir), paths)
                if rec is None:
                    _log(f"SKIP   {spec.source_id}: {spec.legacy_filename} not in {a.import_dir}")
                    continue
            else:
                if not spec.url:
                    _log(
                        f"FAIL   {spec.source_id}: no url in sources.yaml (discovery: {spec.discovery})"
                    )
                    errors += 1
                    continue
                rec = fetch_mod.fetch_source(spec, sources.fetch, paths)
            _log(
                f"{rec.status.upper():6} {spec.source_id}: {rec.sha256[:12]} {rec.bytes:,} bytes ({rec.method})"
            )
        except fetch_mod.FetchError as e:
            _log(f"FAIL   {e}")
            errors += 1
    return 1 if errors else 0


def _bytes(rec: fetch_mod.FetchRecord) -> int | None:
    if rec.bytes:
        return rec.bytes
    return rec.path.stat().st_size if rec.path.exists() else None


def _previous_copy(paths: Paths, rec: fetch_mod.FetchRecord) -> fetch_mod.FetchRecord | None:
    """The newest earlier manifest entry of the same source with different content."""
    recs = [r for r in fetch_mod.read_manifest(paths) if r.source_id == rec.source_id]
    older = [r for r in recs if r.sha256 != rec.sha256]
    return older[-1] if older else None


def _stage_one(spec: SourceSpec, rec: fetch_mod.FetchRecord, paths: Paths) -> stage_mod.StageResult:
    out = paths.staging / spec.source_id / f"{rec.sha256}.parquet"
    return stage_mod.stage_file(spec, rec.path, rec.sha256, out)


def _max_size_drop_pct(config_dir: Path | None) -> float:
    try:
        cfg = load_yaml("gates.yaml", config_dir)
    except FileNotFoundError:  # a config dir with sources only (tests) -> the default
        cfg = {}
    return float((cfg.get("truncation") or {}).get("max_size_drop_pct", 50))


def cmd_stage(a: argparse.Namespace, paths: Paths) -> int:
    sources = load_sources(a.config_dir)
    max_drop = _max_size_drop_pct(a.config_dir)
    errors = 0
    for spec in _rate_row_specs(sources, a.source):
        rec = fetch_mod.current(paths, spec.source_id)
        if rec is None:
            _log(f"FAIL   {spec.source_id}: nothing fetched yet")
            errors += 1
            continue
        out = paths.staging / spec.source_id / f"{rec.sha256}.parquet"
        if out.exists() and out.with_suffix(".meta.json").exists() and not a.force:
            _log(f"SKIP   {spec.source_id}: {rec.sha256[:12]} already staged")
            continue
        prev = _previous_copy(paths, rec)
        cur_bytes = _bytes(rec)
        why = (
            stage_mod.size_drop_error(spec.source_id, cur_bytes, _bytes(prev), max_drop)
            if prev is not None and cur_bytes is not None and not a.allow_shrink
            else None
        )
        if why:
            _log(f"FAIL   {why}")
            errors += 1
            continue
        try:
            res = _stage_one(spec, rec, paths)
            _log(
                f"STAGED {spec.source_id}: {res.staged_rows:,} leaves (= independent {res.independent_count:,}), "
                f"{res.items:,} items, {res.seconds}s"
            )
        except Exception as e:  # noqa: BLE001 - report and continue with the other sources
            _log(f"FAIL   {spec.source_id}: {type(e).__name__}: {e}")
            errors += 1
    return 1 if errors else 0


def cmd_normalize(a: argparse.Namespace, paths: Paths) -> int:
    sources = load_sources(a.config_dir)
    codes = load_codes(a.config_dir)
    resolver = PayerResolver.load(a.config_dir)
    errors = 0
    for spec in _rate_row_specs(sources, a.source):
        rec = fetch_mod.current(paths, spec.source_id)
        staged = paths.staging / spec.source_id / f"{rec.sha256}.parquet" if rec else None
        if staged is None or not staged.exists():
            _log(f"FAIL   {spec.source_id}: not staged")
            errors += 1
            continue
        out = paths.normalized / spec.source_id / f"{rec.sha256}.parquet"  # type: ignore[union-attr]
        if out.exists() and out.with_suffix(".stats.json").exists() and not a.force:
            _log(f"SKIP   {spec.source_id}: already normalized")
            continue
        meta = json.loads(staged.with_suffix(".meta.json").read_text())
        try:
            res = normalize_mod.normalize_file(spec, staged, meta, out, codes, resolver)
            _log(
                f"NORM   {spec.source_id}: {res.rate_rows:,} rate rows ({res.payer_rate_rows:,} payer), "
                f"{sum(res.placeholders_dropped.values())} placeholders dropped, {res.seconds}s"
            )
        except Exception as e:  # noqa: BLE001 - report and continue with the other sources
            _log(f"FAIL   {spec.source_id}: {type(e).__name__}: {e}")
            errors += 1
    return 1 if errors else 0


def cmd_build(a: argparse.Namespace, paths: Paths) -> int:
    sources = load_sources(a.config_dir)
    today = date.fromisoformat(a.build_date) if a.build_date else date.today()
    codes, resolver = load_codes(a.config_dir), PayerResolver.load(a.config_dir)

    def materialize(spec: SourceSpec, rec: fetch_mod.FetchRecord) -> None:
        """Stage + normalize a fallback copy that has no built files yet (e.g. a CI cache)."""
        res = _stage_one(spec, rec, paths)
        out = paths.normalized / spec.source_id / f"{rec.sha256}.parquet"
        normalize_mod.normalize_file(
            spec,
            paths.staging / spec.source_id / f"{rec.sha256}.parquet",
            res,
            out,
            codes,
            resolver,
        )

    res = build_mod.run_build(
        paths,
        sources,
        load_yaml("gates.yaml", a.config_dir),
        today,
        config_dir=a.config_dir,
        baseline_manifest=Path(a.baseline_manifest) if a.baseline_manifest else None,
        first_build=a.first_build,
        materialize=materialize,
    )
    for g in res.gate_results:
        if g.status != "pass":
            _log(f"{g.status.upper():5} {g.gate:15} {g.subject:28} {g.detail}")
    _log(f"BUILD  {res.build_id}: {'OK' if res.ok else 'FAILED (LATEST not moved)'} -> {res.dir}")
    return 0 if res.ok else 1


def cmd_report(a: argparse.Namespace, paths: Paths) -> int:
    d = (paths.builds / a.build) if a.build else build_mod.latest_build(paths)
    if d is None or not d.exists():
        _log("FAIL   no build to report on (run build first, or pass --build)")
        return 1
    baseline = load_yaml("coverage_baseline_2026-10-24.yaml", a.config_dir)
    res = report_mod.build_report(d, load_sources(a.config_dir), load_codes(a.config_dir), baseline)
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
        shutil.copy2(res["md"], Path(a.out) / "coverage.md")
        shutil.copy2(res["csv"], Path(a.out) / "coverage.csv")
    _log(
        f"REPORT {d.name}: {res['codes_covered']}/{res['codes_total']} codes, cells {res['cells_old']} -> "
        f"{res['cells_new']}, {res['usable_rows']:,} usable rows -> {res['md']}"
    )
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.etl", description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--data-dir", default=None, help="data root (default: $CARECOST_DATA_DIR or <repo>/data)"
    )
    p.add_argument(
        "--config-dir", type=Path, default=None, help="config dir (default: <repo>/data/etl)"
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download (or --import-dir) into the content-addressed store")
    f.add_argument("--source", default="all")
    f.add_argument("--import-dir", default=None)
    for name, h in (("stage", "raw -> lossless parquet"), ("normalize", "staged -> rate_row")):
        s = sub.add_parser(name, help=h)
        s.add_argument("--source", default="all")
        s.add_argument("--force", action="store_true")
        if name == "stage":
            s.add_argument(
                "--allow-shrink",
                action="store_true",
                help="accept a file much smaller than its previous copy (checked by a human)",
            )
    b = sub.add_parser("build", help="assemble rate_row + sqlite, run gates")
    b.add_argument("--build-date", default=None)
    b.add_argument(
        "--baseline-manifest",
        default=None,
        help="manifest.json to compare row counts against (default: the LATEST build)",
    )
    b.add_argument(
        "--first-build",
        action="store_true",
        help="allow a build with no row-count baseline (a deliberate first build only)",
    )
    r = sub.add_parser("report", help="coverage matrix vs the old DB baseline")
    r.add_argument("--build", default=None)
    r.add_argument("--out", default=None)
    tic_cli.add_parser(sub)
    return p


COMMANDS = {
    "fetch": cmd_fetch,
    "stage": cmd_stage,
    "normalize": cmd_normalize,
    "build": cmd_build,
    "report": cmd_report,
    "tic": tic_cli.cmd,
}


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    paths = Paths.resolve(a.data_dir)
    return COMMANDS[a.cmd](a, paths)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
