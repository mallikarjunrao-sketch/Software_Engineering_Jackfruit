import argparse
import asyncio
import csv
import json
import math
import random
import string
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def percentile(values, percent):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percent / 100 * len(ordered)) - 1)]


def unique_plates(count, generator):
    plates = set()
    while len(plates) < count:
        letters = "".join(generator.choices(string.ascii_uppercase, k=4))
        plates.add(f"{letters[:2]}{generator.randint(10, 99)}{letters[2:]}{generator.randint(1000, 9999)}")
    return list(plates)


async def run(args):
    generator = random.Random(args.seed)
    gate = asyncio.Semaphore(args.gates)
    records = []

    async def one(http, plate):
        async with gate:
            started = time.perf_counter()
            try:
                response = await http.post("/api/v1/entries", json={"plate": plate, "vehicleType": "car"})
                slot = response.json().get("slotId") if response.status_code == 201 else None
                records.append((plate, response.status_code, slot, time.perf_counter() - started))
            except httpx.HTTPError:
                records.append((plate, 0, None, time.perf_counter() - started))

    async with httpx.AsyncClient(base_url=args.base_url, timeout=120) as http:
        (await http.get("/health")).raise_for_status()
        before = (await http.get("/api/v1/availability")).json()["byType"]["car"]
        print(f"TC-PERF-03: {args.events} entry events, {args.gates} simultaneous gates, {before['total']} car slots ({before['free']} free)")
        await asyncio.gather(*(one(http, plate) for plate in unique_plates(args.events, generator)))
        after = (await http.get("/api/v1/availability")).json()["byType"]["car"]

    codes = Counter(status for _, status, _, _ in records)
    failed = sum(count for status, count in codes.items() if status == 0 or status >= 500)
    slots = [slot for _, status, slot, _ in records if status == 201]
    durations = [duration for *_, duration in records]
    expected_free = max(before["free"] - codes.get(201, 0), 0)
    checks = {
        "no failed requests": failed == 0,
        "every request answered 201 or 409": codes.get(201, 0) + codes.get(409, 0) == len(records),
        "no slot given twice": len(slots) == len(set(slots)),
        "availability matches successful entries": after["free"] == expected_free,
    }
    print(f"  status codes: {dict(codes)}, failed requests: {failed}")
    print(f"  latency: p95={percentile(durations, 95) * 1000:.0f} ms, max={max(durations) * 1000:.0f} ms")
    print(f"  car slots free before {before['free']}, after {after['free']}")
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    RESULTS_DIR.mkdir(exist_ok=True)
    with open(RESULTS_DIR / f"capacity_{stamp}.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["plate", "status", "slot", "seconds"])
        writer.writerows(records)
    summary = {"timestamp": stamp, "gates": args.gates, "events": args.events, "status_codes": dict(codes), "failed_requests": failed, "checks": checks, "p95_seconds": percentile(durations, 95), "max_seconds": max(durations)}
    (RESULTS_DIR / f"capacity_{stamp}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Results saved in {RESULTS_DIR}")
    return 0 if all(checks.values()) else 1


def main():
    parser = argparse.ArgumentParser(description="APMS capacity test for NF-004: many slots, simultaneous gates, no failed requests")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--gates", type=int, default=10)
    parser.add_argument("--events", type=int, default=500)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except (httpx.HTTPError, OSError) as error:
        print(f"Could not complete the test: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
