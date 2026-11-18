"""Wait for URLs to answer with an expected status (used by scripts/bringup.sh, runs inside the compose network).

    python tools/healthcheck.py http://asset-registry:8001/healthz http://apisix:9080/v1/devices=401 --timeout 120
"""

from __future__ import annotations

import argparse
import time

import httpx


def wait(target: str, timeout: float) -> tuple[bool, str]:
    url, _, expect = target.partition("=")
    want = {int(x) for x in expect.split("|")} if expect else set(range(200, 300))
    deadline, last = time.time() + timeout, "no response"
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code in want:
                return True, str(r.status_code)
            last = str(r.status_code)
        except httpx.HTTPError as exc:
            last = type(exc).__name__
        time.sleep(3)
    return False, last


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="+")
    ap.add_argument("--timeout", type=float, default=120)
    a = ap.parse_args()
    failed = 0
    for t in a.targets:
        ok, detail = wait(t, a.timeout)
        print(f"{'OK  ' if ok else 'FAIL'} {t} ({detail})", flush=True)
        failed += not ok
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
