"""Latency of POST /api/quote against a running server (real HTTP over loopback).

    uv run --frozen python -m app.quote.bench --url http://127.0.0.1:8100 -n 200

Sends N sequential requests per case (after 10 warm-up requests), timing each from send to the
full response body read (gzip on), then N requests spread over 8 threads for throughput. Cases:
the golden BCBS HMO and cash shoulder requests (12 sites nearest Harvard Square) and the BCBS one
without ``near`` (every eligible site priced, the best 12 returned).
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

FIX = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def _req(name: str) -> dict:
    d = json.loads((FIX / f"quote_request_{name}_shoulder.json").read_text())
    d.pop("_fixture")
    d.pop("_schema")
    return d


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(p / 100 * (len(xs) - 1)))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8100")
    ap.add_argument("-n", type=int, default=200)
    a = ap.parse_args()
    url = a.url + "/api/quote"
    headers = {"Accept-Encoding": "gzip"}
    with httpx.Client(headers=headers, timeout=30) as c:
        cases = [(n, _req(n)) for n in ("bcbs_hmo", "cash")]
        whole = {k: v for k, v in _req("bcbs_hmo").items() if k != "near"}
        cases.append(("bcbs_hmo_no_near", whole))  # every eligible site priced, best 12 returned
        for name, body in cases:
            for _ in range(10):
                c.post(url, json=body).raise_for_status()
            ms = []
            size = 0
            for _ in range(a.n):
                t = time.perf_counter()
                r = c.post(url, json=body)
                r.raise_for_status()
                _ = r.content
                ms.append((time.perf_counter() - t) * 1000)
                size = int(r.headers.get("content-length", 0))
            print(
                f"{name}: n={a.n} p50={_pct(ms, 50):.1f} ms p95={_pct(ms, 95):.1f} ms "
                f"max={max(ms):.1f} ms mean={statistics.mean(ms):.1f} ms "
                f"gzip body={size} B raw={len(r.content)} B"
            )
        body = _req("bcbs_hmo")

        def one(_):
            t = time.perf_counter()
            with httpx.Client(headers=headers, timeout=30) as cc:
                cc.post(url, json=body).raise_for_status()
            return (time.perf_counter() - t) * 1000

        t0 = time.perf_counter()
        with ThreadPoolExecutor(8) as ex:
            lat = list(ex.map(one, range(a.n)))
        wall = time.perf_counter() - t0
        print(
            f"8 threads: n={a.n} {a.n / wall:.0f} quotes/s p50={_pct(lat, 50):.1f} ms "
            f"p95={_pct(lat, 95):.1f} ms (new connection per request)"
        )


if __name__ == "__main__":  # pragma: no cover
    main()
