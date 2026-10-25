"""``python -m app.etl tic <cmd>``: the TiC pipeline, one payer x network per job.

    tic discover [--month YYYY-MM] [--network ID,..] [--out FILE]   resolve this month's file URLs
    tic run      [--network ID,..|all] [--local-dir DIR] [--discovered FILE] [--previous-release DIR]
                                                   one pass per network (local copy or HTTP stream)
    tic verify   --network ID,.. --local-dir DIR   seek index + range reads == full stream
    tic normalize [--network ID,..|all]            re-cut rate_row with the current target list
    tic extend   [--network ID,..|all] [--local-dir DIR]   read only the items of codes added to
                                                   the list since the run (R9), then normalize
    tic npi-types                                  NPPES type of every single-NPI group with an
                                                   institutional row -> data/etl/tic_npi_types.yaml
    tic report   [--out DIR]                       coverage: code x payer x TIN, Boston TINs, census
    tic release  --month YYYY-MM --out DIR [--previous DIR]   per-network assets + manifest
    tic probe    --network ID [--max-mb N]         download MB/s, inflate GB/s, peak RSS

Failure isolation: every network is its own job. ``run`` keeps going after a failure, records
it in the TiC fetch manifest, leaves that network's CURRENT on its last good run (so its old
``fetched_at`` shows as stale on our side) and exits non-zero at the end.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.etl import fetch
from app.etl.config import Paths
from app.etl.refresh import RefreshRun, with_retry
from app.etl.tic import release as release_mod
from app.etl.tic import report as report_mod
from app.etl.tic.discover import discover
from app.etl.tic.index import atomic_write_text, load_index
from app.etl.tic.networks import TicNetwork, load_networks, target_codes
from app.etl.tic.normalize import normalize_network
from app.etl.tic.ranged import verify_against_stream
from app.etl.tic.run import (
    FetchInfo,
    RunResult,
    TicRunError,
    allowlist,
    current_dir,
    file_chunks,
    http_chunks,
    previous_bytes,
    record_fetch,
    run_pass,
    set_current,
    tic_root,
)
from app.etl.tic.targets import load_targets
from app.etl.tic.zran import file_fetcher


def _log(msg: str) -> None:
    print(msg, flush=True)


def _base_units(paths: Paths) -> dict[str, int]:
    """CMS anesthesia base units (the store's copy of the gov source), for the per-unit flag."""
    from app.etl.gov.pfs import read_base_units

    rec = fetch.current(paths, "cms_anes_base_units_cy2022")
    if rec is None or not rec.path.exists():
        raise TicRunError("cms_anes_base_units_cy2022 is not in the store; `fetch` it first")
    return {c: u for c, (u, _line) in read_base_units(rec.path).items()}


def _flag(d: Path, run: dict[str, Any], paths: Paths, cache: dict[str, Any]) -> dict[str, Any]:
    """A6: O's row flags (app.etl.tic.flags) on a freshly normalized run -> run['flags']."""
    from app.etl.tic import flags as flags_mod

    if "units" not in cache:
        cache["units"] = _base_units(paths)
        cache["npi"] = flags_mod.load_npi_types()
    got = flags_mod.apply(d, cache["units"], cache["npi"])
    run["flags"] = got
    return got


def _select(which: str | None) -> list[TicNetwork]:
    nets = load_networks()
    if not which or which == "all":
        return nets
    want = [w.strip() for w in which.split(",")]
    by = {n.source_id: n for n in nets}
    missing = [w for w in want if w not in by]
    if missing:
        raise SystemExit(f"unknown TiC network(s): {missing}")
    return [by[w] for w in want]


def _local_copy(net: TicNetwork, local_dir: Path) -> tuple[Path, FetchInfo] | None:
    for p in local_dir.rglob(net.basename):
        side = p.with_name(p.name + ".fetch.json")
        if not side.exists():
            raise TicRunError(f"{net.source_id}: {p.name} has no .fetch.json (fetched_at unknown)")
        meta = json.loads(side.read_text())
        size = p.stat().st_size
        if size != meta["bytes"]:
            raise TicRunError(
                f"{net.source_id}: {p.name} is {size} bytes, sidecar says {meta['bytes']}"
            )
        return p, FetchInfo(
            url=fetch.redact(meta["url"]),
            fetched_at=meta["fetched_at"],
            http_last_modified=meta.get("http_last_modified") or None,
            etag=meta.get("etag") or None,
            final_host=meta.get("final_host"),
            local_copy=p.name,
        )
    return None


def cmd_discover(a: argparse.Namespace, paths: Paths) -> int:
    res = discover(_select(a.network), a.month)
    bad = 0
    for d in res:
        _log(
            f"{d.status.upper():12} {d.source_id}: {d.to_json()['url_redacted'] or d.error}"
            + (f"  (blocked hosts: {d.to_json()['blocked']})" if d.blocked else "")
        )
        bad += d.status != "ok"
    out = Path(a.out) if a.out else tic_root(paths) / f"discover-{a.month or 'current'}.json"
    # the real URLs (signed tokens included) are needed to fetch; keep them out of git (data/)
    atomic_write_text(
        out, json.dumps({d.source_id: {**d.to_json(), "url": d.url} for d in res}, indent=1)
    )
    _log(f"wrote {out}")
    return 1 if bad else 0


def _previous_release_bytes(a: argparse.Namespace, source_id: str) -> int | None:
    """Baseline from last month's release manifest (the durable history; the Actions cache is
    only a speed-up and is evicted after 7 days)."""
    if not getattr(a, "previous_release", None):
        return None
    m = Path(a.previous_release) / "manifest.json"
    if not m.exists():
        return None
    e = json.loads(m.read_text()).get("networks", {}).get(source_id) or {}
    return e.get("bytes")


def _one(
    net: TicNetwork,
    a: argparse.Namespace,
    paths: Paths,
    codes: set[str],
    discovered: dict[str, Any],
) -> RunResult:
    prev = previous_bytes(paths, net.source_id) or _previous_release_bytes(a, net.source_id)
    if a.local_dir:
        got = _local_copy(net, Path(a.local_dir))
        if got is None:
            raise TicRunError(f"{net.source_id}: {net.basename} not found under {a.local_dir}")
        path, info = got
        chunks = file_chunks(path)
    else:
        url = (discovered.get(net.source_id) or {}).get("url") or net.url
        net = TicNetwork(**{**net.__dict__, "url": url})
        chunks, hdr = http_chunks(net, allowlist())
        info = FetchInfo(
            url=fetch.redact(url),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    t0 = time.time()
    rr = run_pass(net, chunks, info, paths, codes, prev_bytes=prev)
    if not a.local_dir:
        rr.download_mb_s = round(rr.comp_bytes / max(time.time() - t0, 1e-6) / 1e6, 1)
        rr.fetch.update(
            {k: v for k, v in hdr.items() if k in ("http_last_modified", "etag", "final_host")}
        )
    d = Path(rr.out_dir)
    st = normalize_network(d, net, rr.__dict__, load_targets())
    rr.normalize = st.__dict__
    atomic_write_text(
        d / "run.json", json.dumps(rr.__dict__, indent=1, sort_keys=True, default=str)
    )
    return rr


def cmd_run(a: argparse.Namespace, paths: Paths) -> int:
    """One pass per network, one retry each (P11). A network that still fails keeps its CURRENT
    run (old fetched_at -> stale on our side), is recorded in the fetch manifest and
    intermediate/refresh_status.json, and alerted (app.etl.alert); the command exits 1."""
    codes = target_codes()
    discovered = json.loads(Path(a.discovered).read_text()) if a.discovered else {}
    failed = 0
    refresh = RefreshRun(paths, "insurer TiC files (tic run)")
    for net in _select(a.network):
        rr, errs = with_retry(
            lambda net=net: _one(net, a, paths, codes, discovered), net.source_id, log=_log
        )
        if rr is None:
            failed += 1
            e = refresh.failed(net.source_id, errs, _last_good_run(paths, net.source_id))
            _log(f"FAIL   {net.source_id}: {e['reason']} -> {e['status']}")
            m = tic_root(paths) / "fetch_manifest.jsonl"
            m.parent.mkdir(parents=True, exist_ok=True)
            with m.open("a") as f:
                f.write(
                    json.dumps(
                        {
                            "source_id": net.source_id,
                            "payer_id": net.payer_id,
                            "status": "failed",
                            "error": e["reason"],
                            "attempts": e["attempts"],
                            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
            continue
        set_current(paths, net.source_id, rr.source_sha256)
        record_fetch(paths, rr, "ok")
        refresh.ok(net.source_id, sha256=rr.source_sha256, fetched_at=rr.fetch.get("fetched_at"))
        n = rr.normalize
        _log(
            f"OK     {net.source_id}: {rr.comp_bytes / 1e9:.2f} GB -> {rr.raw_bytes / 1e9:.1f} GB raw in "
            f"{rr.seconds_pass}s ({rr.inflate_gb_s} GB/s, RSS {rr.peak_rss_mb:.0f} MB); "
            f"{rr.target_items} target items, {rr.stage['price_rows']:,} prices, "
            f"{rr.stage['group_rows']:,} groups; rate_row {n['rate_rows']:,}; index {rr.index_bytes / 1e6:.1f} MB"
        )
    if refresh.outcomes and not refresh.finish(log=_log):
        failed = max(failed, 1)
    return 1 if failed else 0


def _last_good_run(paths: Paths, source_id: str) -> dict[str, Any] | None:
    d = current_dir(paths, source_id)
    if d is None or not (d / "run.json").exists():
        return None
    run = json.loads((d / "run.json").read_text())
    return {
        "sha256": run.get("source_sha256"),
        "fetched_at": (run.get("fetch") or {}).get("fetched_at"),
    }


def cmd_verify(a: argparse.Namespace, paths: Paths) -> int:
    bad = 0
    codes = target_codes()
    for net in _select(a.network):
        d = current_dir(paths, net.source_id)
        got = _local_copy(net, Path(a.local_dir))
        if d is None or got is None:
            _log(f"FAIL   {net.source_id}: no current run or no local copy")
            bad += 1
            continue
        idx = load_index(d)
        t0 = time.time()
        rep = verify_against_stream(d, idx, codes, file_fetcher(str(got[0])), d.parent / ".verify")
        rep["seconds"] = round(time.time() - t0, 1)
        rep["comp_bytes"] = idx.meta.comp_bytes
        atomic_write_text(d / "verify.json", json.dumps(rep, indent=1))
        _log(
            f"{'OK    ' if rep['ok'] else 'FAIL  '} {net.source_id}: range read {rep['range_bytes'] / 1e6:.1f} MB "
            f"of {idx.meta.comp_bytes / 1e6:.0f} MB; prices {rep['price_rows_range']:,} == {rep['price_rows_stream']:,}: "
            f"{rep['prices_equal']}; groups equal: {rep['groups_equal']} ({rep['seconds']}s)"
        )
        bad += not rep["ok"]
    return 1 if bad else 0


def cmd_normalize(a: argparse.Namespace, paths: Paths) -> int:
    targets = load_targets()
    cache: dict[str, Any] = {}
    bad = 0
    for net in _select(a.network):
        d = current_dir(paths, net.source_id)
        if d is None:
            _log(f"SKIP   {net.source_id}: no current run")
            continue
        run = json.loads((d / "run.json").read_text())
        try:
            st = normalize_network(d, net, run, targets)
            run["normalize"] = st.__dict__
            fl = _flag(d, run, paths, cache)
        except Exception as e:  # noqa: BLE001
            bad += 1
            _log(f"FAIL   {net.source_id}: {e}")
            continue
        atomic_write_text(d / "run.json", json.dumps(run, indent=1, sort_keys=True, default=str))
        _log(
            f"NORM   {net.source_id}: {st.rate_rows:,} rate rows, {st.matched_tins} TINs matched; "
            f"excluded {st.excluded}; flags {fl['by_flag']}"
        )
    return 1 if bad else 0


def cmd_npi_types(a: argparse.Namespace, paths: Paths) -> int:
    """NPPES (public registry API, no key) for every NPI that is the only NPI of a provider group
    with an institutional row; known NPIs are kept, only missing ones are fetched."""
    import yaml

    from app.etl.config import CONFIG_DIR
    from app.etl.tic import flags as flags_mod

    want: set[str] = set()
    for net in _select("all"):
        d = current_dir(paths, net.source_id)
        if d is not None and (d / "rate_row.parquet").exists():
            want |= flags_mod.single_npis(d)
    have = flags_mod.load_npi_types()
    bad = 0
    for n in sorted(want - set(have)):
        try:
            have[n] = nppes_type(n)
        except Exception as e:  # noqa: BLE001
            bad += 1
            _log(f"FAIL   NPPES {n}: {e}")
        time.sleep(0.25)
    out = CONFIG_DIR / flags_mod.NPI_TYPES_FILE
    doc = {
        "version": 1,
        "source": "CMS NPPES NPI Registry API v2.1 (https://npiregistry.cms.hhs.gov/api/), "
        "written by `python -m app.etl tic npi-types`",
        "npis": dict(sorted(have.items())),
    }
    head = "# GENERATED by `python -m app.etl tic npi-types`; do not edit by hand.\n"
    out.write_text(head + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=110))
    phys = sum(1 for v in have.values() if flags_mod.is_physician(v))
    _log(f"NPI    {len(want)} single NPIs on institutional rows, {len(have)} typed, "
         f"{phys} physician / person -> {out}")  # fmt: skip
    return 1 if bad else 0


PHYSICIAN_GROUP_TAXONOMY = ("193", "207", "208", "2080")
"""NUCC prefixes of a physician practice: 193 group (multi / single specialty), 207-208
allopathic and osteopathic physicians. Hospitals (282N), ASCs (261QA1903X), clinics (261Q),
labs (291U) are not."""


def nppes_type(npi: str) -> dict[str, Any]:
    body, _, _ = fetch.http_get_bytes(
        f"https://npiregistry.cms.hhs.gov/api/?version=2.1&number={npi}",
        ["npiregistry.cms.hhs.gov"],
        2_000_000,
    )
    res = (json.loads(body).get("results") or [None])[0]
    if res is None:
        return {"type": "not_found", "fetched_at": _now()}
    basic = res.get("basic") or {}
    tx = res.get("taxonomies") or []
    prim = next((t for t in tx if t.get("primary")), tx[0] if tx else {})
    code = prim.get("code") or ""
    kind = res.get("enumeration_type") or ""
    name = basic.get("organization_name") or " ".join(
        x for x in (basic.get("first_name"), basic.get("last_name")) if x
    )
    return {
        "type": kind,
        "name": name,
        "taxonomy": code,
        "taxonomy_desc": prim.get("desc") or "",
        "physician_group": kind == "NPI-2" and code.startswith(PHYSICIAN_GROUP_TAXONOMY),
        "fetched_at": _now(),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cmd_extend(a: argparse.Namespace, paths: Paths) -> int:
    from app.etl.config import load_codes
    from app.etl.tic.extend import extend_network
    from app.etl.tic.networks import load_visit_map

    codes = target_codes()
    hand = {c for dom in load_codes().domains.values() for c in dom} | load_visit_map().all_codes
    targets = load_targets()
    cache: dict[str, Any] = {}
    bad = 0
    for net in _select(a.network):
        d = current_dir(paths, net.source_id)
        if d is None:
            _log(f"SKIP   {net.source_id}: no current run")
            continue
        try:
            local = None
            if a.local_dir:
                got = _local_copy(net, Path(a.local_dir))
                local = got[0] if got else None
            e = extend_network(
                net, d, codes, legacy=hand, allowed=allowlist(), local_copy=local, log=_log
            )
            run = json.loads((d / "run.json").read_text())
            st = normalize_network(d, net, run, targets)
            run["normalize"] = st.__dict__
            _flag(d, run, paths, cache)
            atomic_write_text(
                d / "run.json", json.dumps(run, indent=1, sort_keys=True, default=str)
            )
        except Exception as ex:  # noqa: BLE001 - one network never blocks the others
            bad += 1
            _log(f"FAIL   {net.source_id}: {type(ex).__name__}: {ex}")
            continue
        _log(
            f"EXTEND {net.source_id}: +{e['items']} items / +{e['price_rows']:,} prices for "
            f"{len(e['codes_in_file'])} of {len(e['codes_added'])} added codes "
            f"({e['how']}, {e['bytes'] / 1e6:.1f} MB, {e['seconds']}s); rate_row {st.rate_rows:,}"
        )
    return 1 if bad else 0


def cmd_report(a: argparse.Namespace, paths: Paths) -> int:
    res = report_mod.build_report(paths, load_networks(), Path(a.out) if a.out else None)
    _log(f"REPORT {res['md']}: {res['networks_loaded']} networks, {res['rate_rows']:,} rate rows")
    return 0


def cmd_release(a: argparse.Namespace, paths: Paths) -> int:
    res = release_mod.assemble(
        paths, load_networks(), a.month, Path(a.out), Path(a.previous) if a.previous else None
    )
    for sid, s in sorted(res["networks"].items()):
        _log(f"{s['status'].upper():9} {sid}")
    _log(
        f"RELEASE {a.month}: {res['ok']} ok, {res['fallback']} fallback, {res['missing']} missing -> {a.out}"
    )
    return 0 if res["ok"] else 1


def cmd_probe(a: argparse.Namespace, paths: Paths) -> int:
    """Measure download + inflate on the real URL without keeping anything on disk."""
    import resource

    from app.etl.tic.zran import InflatePass

    (net,) = _select(a.network)
    cap = int(a.max_mb * 1e6) if a.max_mb else net.max_bytes
    chunks, hdr = http_chunks(
        TicNetwork(**{**net.__dict__, "max_bytes": net.max_bytes}), allowlist()
    )
    t0 = time.time()
    got = 0

    def capped() -> Iterator[bytes]:
        nonlocal got
        for c in chunks:
            got += len(c)
            yield c
            if got >= cap:
                return

    raw = 0
    try:
        for _off, data in InflatePass(capped(), net.container, max_raw=net.max_raw):
            raw += len(data)
    except Exception as e:  # noqa: BLE001 - a capped probe ends mid-stream on purpose
        if got < cap:
            raise
        _log(f"(stopped at the {cap / 1e6:.0f} MB probe cap: {type(e).__name__})")
    dt = time.time() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rep = {
        "source_id": net.source_id,
        "comp_bytes": got,
        "raw_bytes": raw,
        "seconds": round(dt, 1),
        "download_mb_s": round(got / dt / 1e6, 1),
        "inflate_gb_s_incl_download": round(raw / dt / 1e9, 2),
        "peak_rss_mb": round(rss / 1e6 if rss > 1e7 else rss / 1e3),
        "host": hdr.get("final_host"),
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _log(json.dumps(rep))
    out = tic_root(paths) / "probe.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as f:
        f.write(json.dumps(rep) + "\n")
    return 0


COMMANDS = {
    "discover": cmd_discover, "run": cmd_run, "verify": cmd_verify, "normalize": cmd_normalize,
    "extend": cmd_extend, "npi-types": cmd_npi_types,
    "report": cmd_report, "release": cmd_release, "probe": cmd_probe,
}  # fmt: skip


def add_parser(sub: Any) -> None:
    p = sub.add_parser("tic", help="insurer Transparency-in-Coverage pipeline (A2)")
    ts = p.add_subparsers(dest="tic_cmd", required=True)
    d = ts.add_parser("discover")
    d.add_argument("--month", default=None)
    d.add_argument("--network", default="all")
    d.add_argument("--out", default=None)
    r = ts.add_parser("run")
    r.add_argument("--network", default="all")
    r.add_argument("--local-dir", default=None)
    r.add_argument("--discovered", default=None)
    r.add_argument("--previous-release", default=None, help="dir with last month's manifest.json")
    v = ts.add_parser("verify")
    v.add_argument("--network", default="all")
    v.add_argument("--local-dir", required=True)
    n = ts.add_parser("normalize")
    n.add_argument("--network", default="all")
    x = ts.add_parser("extend")
    x.add_argument("--network", default="all")
    x.add_argument("--local-dir", default=None)
    ts.add_parser("npi-types")
    rp = ts.add_parser("report")
    rp.add_argument("--out", default=None)
    rl = ts.add_parser("release")
    rl.add_argument("--month", required=True)
    rl.add_argument("--out", required=True)
    rl.add_argument("--previous", default=None)
    pr = ts.add_parser("probe")
    pr.add_argument("--network", required=True)
    pr.add_argument("--max-mb", type=float, default=None)


def cmd(a: argparse.Namespace, paths: Paths) -> int:
    return COMMANDS[a.tic_cmd](a, paths)
