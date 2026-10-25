"""Merge two verified runs into X1 ``facts.yaml`` and write Austin's review page (brief S0.5).

Per site and field:

* both runs make the claim, both verify, values equal (``models.norm_*``) -> ``agreed``, evidence
  from both runs;
* anything else where at least one run makes a claim (values differ, only one run has it, or one
  side failed the verifier) -> ``disputed``, listed on the review page side by side;
* neither run makes the claim (or both say ``unknown``) -> left out (C3 reads missing as unknown).

``reviews.yaml`` holds Austin's decisions: ``{site_id, field, value, note}``. A decision whose value
matches a verified claim from either run becomes ``austin_reviewed`` with that claim's evidence. A
decision that matches no verified claim any more (the page changed) is not applied and is listed
on the review page as stale.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.site_facts.models import (
    Evidence,
    FactsFile,
    HoursSpan,
    RunSite,
    norm_hours,
    norm_name,
    norm_phone,
)
from app.site_facts.paths import FACTS, REVIEW_DIR, REVIEWS
from app.site_facts.verify import Rejection, VerifyResult

FIELDS = ("official_name", "phone", "hours")


def _key(field_name: str, value: Any) -> Any:
    if field_name == "official_name":
        return norm_name(value)
    if field_name == "phone":
        return norm_phone(value)
    if field_name == "hours":
        return norm_hours([v if isinstance(v, HoursSpan) else HoursSpan(**v) for v in value])
    return value


def _claims(site: RunSite | None) -> dict[str, Any]:
    """field -> claim object (official_name / phone / hours / capabilities.<id>)."""
    if site is None:
        return {}
    out: dict[str, Any] = {f: getattr(site, f) for f in FIELDS if getattr(site, f) is not None}
    for cid, c in site.capabilities.items():
        if c.value != "unknown":
            out[f"capabilities.{cid}"] = c
    return out


def _value(claim: Any) -> Any:
    v = claim.value
    return [s.model_dump() for s in v] if isinstance(v, list) else v


def _dedupe(evs: list[Evidence]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for e in evs:
        k = (e.url, e.quote)
        if k not in seen:
            seen.add(k)
            out.append(e.model_dump())
    return out


@dataclass
class Dispute:
    site_id: str
    field: str
    a: Any  # claim or None
    b: Any
    a_rejected: Rejection | None = None
    b_rejected: Rejection | None = None


@dataclass
class MergeResult:
    facts: dict[str, Any]
    disputes: list[Dispute] = field(default_factory=list)
    agreed: int = 0
    reviewed: int = 0
    stale_reviews: list[dict[str, Any]] = field(default_factory=list)


def _field_type(f: str) -> str:
    return "capabilities" if f.startswith("capabilities.") else f


def merge(
    a: VerifyResult, b: VerifyResult, reviews: list[dict[str, Any]] | None = None
) -> MergeResult:
    rej_a = {(r.site_id, r.field): r for r in a.rejections}
    rej_b = {(r.site_id, r.field): r for r in b.rejections}
    decided = {(r["site_id"], r["field"]): r for r in (reviews or [])}
    res = MergeResult(facts={"version": 1, "sites": {}})
    used_reviews: set[tuple[str, str]] = set()
    site_ids = sorted(set(a.run.sites) | set(b.run.sites))
    for sid in site_ids:
        ca, cb = _claims(a.accepted.get(sid)), _claims(b.accepted.get(sid))
        fields = set(ca) | set(cb)
        # a field one run made but the verifier rejected is still "made" -> disputed
        fields |= {f for (s, f) in rej_a if s == sid and f != "site"}
        fields |= {f for (s, f) in rej_b if s == sid and f != "site"}
        out_site: dict[str, Any] = {}
        for f in sorted(fields):
            x, y = ca.get(f), cb.get(f)
            entry: dict[str, Any]
            rv = decided.get((sid, f))
            if rv is not None:
                match = [
                    c
                    for c in (x, y)
                    if c is not None
                    and _key(_field_type(f), _value(c)) == _key(_field_type(f), rv["value"])
                ]
                if match:
                    entry = {"value": rv["value"], "status": "austin_reviewed",
                             "evidence": _dedupe([e for c in match for e in c.evidence])}  # fmt: skip
                    used_reviews.add((sid, f))
                    res.reviewed += 1
                    _put(out_site, f, entry)
                    continue
            if (
                x is not None
                and y is not None
                and _key(_field_type(f), _value(x)) == _key(_field_type(f), _value(y))
            ):
                entry = {
                    "value": _value(x),
                    "status": "agreed",
                    "evidence": _dedupe(x.evidence + y.evidence),
                }
                res.agreed += 1
            else:
                first = x if x is not None else y
                if first is None:  # both sides rejected: nothing quotable to show as a value
                    res.disputes.append(
                        Dispute(sid, f, None, None, rej_a.get((sid, f)), rej_b.get((sid, f)))
                    )
                    continue
                evs = (x.evidence if x is not None else []) + (y.evidence if y is not None else [])
                entry = {"value": _value(first), "status": "disputed", "evidence": _dedupe(evs)}
                res.disputes.append(Dispute(sid, f, x, y, rej_a.get((sid, f)), rej_b.get((sid, f))))
            _put(out_site, f, entry)
        if out_site:
            res.facts["sites"][sid] = out_site
    res.stale_reviews = [r for k, r in decided.items() if k not in used_reviews]
    FactsFile.model_validate(res.facts)  # the file C3 reads is always valid X1
    return res


def _put(site: dict[str, Any], f: str, entry: dict[str, Any]) -> None:
    if f.startswith("capabilities."):
        site.setdefault("capabilities", {})[f.split(".", 1)[1]] = entry
    else:
        site[f] = entry


def write_facts(res: MergeResult, a_id: str, b_id: str, path: Path = FACTS) -> None:
    head = (
        f"# GENERATED by `python -m app.site_facts merge {a_id} {b_id}` "
        f"({datetime.now(timezone.utc).date().isoformat()}). Contract X1; do not edit by hand:\n"
        "# Austin's decisions go in reviews.yaml and are applied on the next merge.\n"
    )
    path.write_text(
        head + yaml.safe_dump(res.facts, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )


def load_reviews(path: Path = REVIEWS) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return list((yaml.safe_load(path.read_text()) or {}).get("decisions", []))


# ---------------------------------------------------------------------- review page


def _fmt_value(v: Any) -> str:
    if isinstance(v, list):
        return "<br>".join(
            html.escape(f"{','.join(s['days'])} {s['open']}–{s['close']}") for s in v
        )
    return html.escape(str(v))


def _side(claim: Any, rej: Rejection | None, run_id: str) -> str:
    if claim is None and rej is None:
        return f"<td class=none><b>{run_id}</b>: no claim</td>"
    if claim is None:
        return (f"<td class=rej><b>{run_id}</b>: rejected by verifier "
                f"(<code>{html.escape(rej.reason)}</code>)<br><small>{html.escape(rej.detail)}</small></td>")  # type: ignore[union-attr]  # fmt: skip
    evs = "".join(
        f'<li><q>{html.escape(e.quote)}</q><br><a href="{html.escape(e.url)}">{html.escape(e.url)}</a></li>'
        for e in claim.evidence
    )
    return (
        f"<td><b>{run_id}</b>: <span class=v>{_fmt_value(_value(claim))}</span><ul>{evs}</ul></td>"
    )


def write_review(
    res: MergeResult, a_id: str, b_id: str, names: dict[str, str], out_dir: Path = REVIEW_DIR
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in res.disputes:
        val = _value(d.a) if d.a is not None else (_value(d.b) if d.b is not None else None)
        snippet = yaml.safe_dump([{"site_id": d.site_id, "field": d.field, "value": val, "note": ""}],
                                 sort_keys=False, allow_unicode=True).strip()  # fmt: skip
        rows.append(
            f"<tr><td><b>{html.escape(names.get(d.site_id, d.site_id))}</b><br><code>{d.site_id}</code><br>"
            f"<code>{html.escape(d.field)}</code></td>{_side(d.a, d.a_rejected, a_id)}{_side(d.b, d.b_rejected, b_id)}"
            f"<td><pre>{html.escape(snippet)}</pre></td></tr>"
        )
    stale = "".join(f"<li><code>{html.escape(str(r))}</code></li>" for r in res.stale_reviews)
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1"><title>Site facts review</title>
<style>
:root{{--bg:#fff;--fg:#1d1d1f;--mut:#6e6e73;--line:#d2d2d7;--rej:#fff1f0;--none:#f5f5f7}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#161617;--fg:#f5f5f7;--mut:#a1a1a6;--line:#3a3a3c;--rej:#3b1d1d;--none:#232325}}}}
:root[data-theme="dark"]{{--bg:#161617;--fg:#f5f5f7;--mut:#a1a1a6;--line:#3a3a3c;--rej:#3b1d1d;--none:#232325}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,system-ui,sans-serif;margin:0 16px 40px}}
table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid var(--line);padding:8px;vertical-align:top;text-align:left}}
td.rej{{background:var(--rej)}} td.none{{background:var(--none);color:var(--mut)}} q{{font-style:italic}}
.v{{font-weight:600}} pre{{white-space:pre-wrap;font-size:12px}} a{{color:inherit;word-break:break-all}}
.wrap{{overflow-x:auto}} td code,pre{{word-break:break-all}} td{{width:25%}}
</style></head><body>
<h1>Site facts: disagreements to review</h1>
<p>Runs <code>{a_id}</code> vs <code>{b_id}</code>. {res.agreed} claims agreed, {res.reviewed} already decided by you,
<b>{len(res.disputes)} to review</b>. For each row, copy the YAML on the right into
<code>data/sites/site_facts/reviews.yaml</code> under <code>decisions:</code>, set the value you accept, and re-run the merge.
A decision is applied only when its value matches a verified quote from one of the runs.</p>
{"<h2>Stale decisions (no longer match a verified claim)</h2><ul>" + stale + "</ul>" if stale else ""}
<div class=wrap><table><tr><th>Site / field</th><th>{a_id}</th><th>{b_id}</th><th>Decision to copy</th></tr>
{"".join(rows)}</table></div></body></html>"""
    p = out_dir / f"{a_id}__{b_id}.html"
    p.write_text(page, encoding="utf-8")
    return p
