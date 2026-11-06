import argparse
import asyncio
import csv
import json
import random
import string
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

RESULTS_DIR = Path(__file__).resolve().parent / "results"
UPTIME_TARGET_PERCENT = 99.5


def uptime_percent(results):
    if not results:
        raise ValueError("No health checks were recorded")
    return 100 * sum(1 for up in results if up) / len(results)


def new_plate(generator):
    letters = "".join(generator.choices(string.ascii_uppercase, k=4))
    return f"{letters[:2]}{generator.randint(10, 99)}{letters[2:]}{generator.randint(1000, 9999)}"


async def check(http):
    started = time.perf_counter()
    try:
        health, availability = await asyncio.gather(http.get("/health"), http.get("/api/v1/availability"))
        up = health.status_code == 200 and availability.status_code == 200
    except httpx.HTTPError:
        up = False
    return up, time.perf_counter() - started


async def run(args):
    generator = random.Random(args.seed)
    log = []
    traffic_errors = 0
    deadline = time.monotonic() + args.minutes * 60
    next_entry = time.monotonic()

    async with httpx.AsyncClient(base_url=args.base_url, timeout=10) as http:
        print(f"TC-REL-01: soak test for {args.minutes} minutes, health check every {args.interval} s")
        while time.monotonic() < deadline:
            cycle = time.monotonic()
            up, seconds = await check(http)
            log.append((datetime.now().isoformat(timespec="seconds"), up, seconds))
            if time.monotonic() >= next_entry:
                try:
                    response = await http.post("/api/v1/entries", json={"plate": new_plate(generator), "vehicleType": "car"})
                    if response.status_code >= 500:
                        traffic_errors += 1
                except httpx.HTTPError:
                    traffic_errors += 1
                next_entry += args.entry_every
            await asyncio.sleep(max(0, args.interval - (time.monotonic() - cycle)))

    results = [up for _, up, _ in log]
    uptime = uptime_percent(results)
    passed = uptime >= UPTIME_TARGET_PERCENT
    print(f"  checks: {len(results)}, failed: {results.count(False)}, traffic errors: {traffic_errors}")
    print(f"  uptime: {uptime:.2f}% (target {UPTIME_TARGET_PERCENT}%): {'PASS' if passed else 'FAIL'}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    RESULTS_DIR.mkdir(exist_ok=True)
    with open(RESULTS_DIR / f"uptime_log_{stamp}.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "up", "seconds"])
        writer.writerows(log)
    summary = {"timestamp": stamp, "minutes": args.minutes, "checks": len(results), "failed_checks": results.count(False), "traffic_errors": traffic_errors, "uptime_percent": uptime, "passed": passed}
    (RESULTS_DIR / f"uptime_{stamp}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Results saved in {RESULTS_DIR}")
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description="APMS soak test for NF-003: compute uptime from health checks")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--minutes", type=float, default=5)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--entry-every", type=float, default=3.0, help="seconds between background entries")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except (httpx.HTTPError, OSError) as error:
        print(f"Could not complete the test: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
