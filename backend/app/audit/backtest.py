"""Leave-one-group-out backtest of the two X2 peer modes (brief O item 5).

For every line, its billing group is left out and its price (the median of the line's rows) is
predicted from the other groups of the same peer key:

* ``same_kind``: the median over the other groups (>= 5 groups, else no prediction: a Gap, P5);
* ``same_system_then_kind``: the median over the other groups that share a health system
  (``Site.system_id`` of the sites the group bills at) when there are >= 3 of them, else
  ``same_kind``.

Reported per site kind: lines, coverage (share with a prediction), median absolute percentage
error, share more than 2x off (prediction / actual > 2 or < 0.5), share of actuals inside the
peers' p25-p75 (the range P5 would show), and the same on the lines where the system mode used
system peers (the only lines where the modes differ).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from app.audit.peers import MIN_GROUPS, Line, group_medians, quartiles

SYSTEM_MIN_GROUPS = 3


def _stats(errs: list[tuple[float, float, bool]]) -> dict[str, Any]:
    """errs: (prediction, actual, inside p25-p75)."""
    if not errs:
        return {"n": 0}
    ape = [abs(p - a) / a for p, a, _ in errs]
    off2 = [p / a > 2 or p / a < 0.5 for p, a, _ in errs]
    return {
        "n": len(errs),
        "median_ape": round(statistics.median(ape), 4),
        "share_over_2x_off": round(sum(off2) / len(errs), 4),
        "share_inside_p25_p75": round(sum(i for _, _, i in errs) / len(errs), 4),
    }


def backtest(lines: list[Line]) -> dict[str, Any]:
    gm = group_medians(lines)
    by_kind: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    seen: set[tuple] = set()
    for ln in lines:
        key = (ln.peer_key, ln.group)
        if key in seen:  # one prediction per group and peer key (families share a group)
            continue
        seen.add(key)
        peers = gm[ln.peer_key]
        actual, systems = peers[ln.group]
        if actual <= 0:
            continue
        k = ln.kind
        by_kind[k]["all"].append(1)
        others = [(m, s) for g, (m, s) in peers.items() if g != ln.group]
        if len(others) < MIN_GROUPS:
            continue
        vals = [m for m, _ in others]
        pred = statistics.median(vals)
        q1, q3 = quartiles(vals)
        sk = (pred, actual, q1 <= actual <= q3)
        by_kind[k]["same_kind"].append(sk)
        sys_vals = [m for m, s in others if s & systems] if systems else []
        if len(sys_vals) >= SYSTEM_MIN_GROUPS:
            sp = statistics.median(sys_vals)
            s1, s3 = quartiles(sys_vals)
            ss = (sp, actual, s1 <= actual <= s3)
            by_kind[k]["system_used_kind"].append(sk)
            by_kind[k]["system_used_system"].append(ss)
        else:
            ss = sk
        by_kind[k]["same_system_then_kind"].append(ss)
    out: dict[str, Any] = {}
    for k in sorted(by_kind):
        d = by_kind[k]
        total = len(d["all"])
        out[k] = {
            "lines": total,
            "coverage": round(len(d["same_kind"]) / total, 4) if total else 0.0,
            "same_kind": _stats(d["same_kind"]),
            "same_system_then_kind": _stats(d["same_system_then_kind"]),
            "where_system_peers_used": {
                "n": len(d["system_used_system"]),
                "same_kind": _stats(d["system_used_kind"]),
                "same_system": _stats(d["system_used_system"]),
            },
        }
    return out
