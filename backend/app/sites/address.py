"""Address keys and the Greater Boston ZIP scope, identical to the census (research-v3
``build.py``: ``akey`` / ``z5`` / ``inscope``), so monthly registry files join on the census's
``site_key`` = ``<house number> <street core>|<ZIP5>``."""

from __future__ import annotations

import re

LEGACY_ZIPS = {
    "02172": "02472", "02181": "02481", "02167": "02467", "02192": "02492", "02154": "02451",
    "02173": "02421", "02158": "02458", "02160": "02460", "02159": "02459", "02162": "02462",
    "02161": "02461", "02166": "02466", "02168": "02468", "02174": "02474", "02178": "02478",
    "02193": "02493", "02194": "02494",
}  # fmt: skip
EXTRA_ZIPS = {"01801", "01803", "01890", "01906", "01901", "01902", "01904", "01905", "02026",
              "02090", "02021"}  # fmt: skip
SUF = {"STREET": "ST", "ST.": "ST", "AVENUE": "AVE", "AV": "AVE", "AVE.": "AVE", "ROAD": "RD",
       "HIGHWAY": "HWY", "PARKWAY": "PKWY", "PKY": "PKWY", "TURNPIKE": "TPKE", "TPK": "TPKE",
       "BOULEVARD": "BLVD", "DRIVE": "DR", "PLACE": "PL", "SQUARE": "SQ", "LANE": "LN", "COURT": "CT",
       "CENTRE": "CENTER", "CTR": "CENTER", "PLAZA": "PLZ", "CIRCLE": "CIR", "TERRACE": "TER",
       "WY": "WAY", "INDUSTRIAL": "", "PIKE": "TPKE"}  # fmt: skip
NUMW = {"ONE": "1", "TWO": "2", "THREE": "3", "FIRST": "1ST", "SECOND": "2ND", "THIRD": "3RD"}
STOP = re.compile(r"\b(SUITE|STE|UNIT|FL|FLOOR|FLR|BLDG|BUILDING|RM|ROOM|LEVEL|LL|APT|#)\b.*$")
ENDS = {"ST", "AVE", "RD", "HWY", "PKWY", "TPKE", "BLVD", "DR", "PL", "SQ", "LN", "CT", "WAY", "PLZ",
        "CIR", "TER", "MALL", "PARK", "BROADWAY", "LANDING"}  # fmt: skip


def z5(z: object) -> str:
    d = re.sub(r"\D", "", str(z or ""))[:5].zfill(5) if z else ""
    return LEGACY_ZIPS.get(d, d)


def in_scope(z: object) -> bool:
    d = z5(z)
    return d.startswith(("021", "024")) or d in EXTRA_ZIPS or "02201" <= d <= "02228"


def akey(street: str | None, zipc: object) -> str | None:
    s = (street or "").upper().replace(".", " ").replace(",", " , ")
    s = s.split(" , ")[0] if re.match(r"^\s*\d", s) else s.replace(" , ", " ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = STOP.sub("", s)
    s = re.sub(r"[^A-Z0-9 &-]", " ", s)
    toks = [NUMW.get(t, t) for t in s.split()]
    if not toks:
        return None
    m = re.match(r"^(\d+)[A-Z]?$", toks[0]) or re.match(r"^(\d+)[-&]", toks[0])
    if not m:
        i = next((i for i, t in enumerate(toks) if re.match(r"^\d+$", t)), None)
        if i is None:
            return None
        toks = toks[i:]
        m = re.match(r"^(\d+)", toks[0])
    assert m
    num, rest = m.group(1), []
    for t in toks[1:]:
        if t in ("&", "-") or (re.match(r"^\d+$", t) and not rest):
            continue
        t = SUF.get(t, t)
        if t:
            rest.append(t)
        if t in ENDS:
            break
    rest = [r for r in rest if r not in ("N", "S", "E", "W") or len(rest) == 1]
    core = " ".join(rest)
    core = re.sub(r"^(BOSTON[- ])?PROVIDENCE (HWY|TPKE)$", "PROVIDENCE HWY", core)
    core = core.replace("BOSTON-PROVIDENCE", "PROVIDENCE")
    core = re.sub(r"^LIBBEY (PKWY|INDUSTRIAL PKWY)$", "LIBBEY PKWY", core)
    core = re.sub(r"^(CUMMINGS PARK|W CUMMINGS PARK|WEST CUMMINGS PARK).*$", "CUMMINGS PARK", core)
    return f"{num} {core}|{z5(zipc)}"
