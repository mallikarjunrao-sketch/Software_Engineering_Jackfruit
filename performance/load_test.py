import argparse
import asyncio
import csv
import json
import math
import random
import string
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import websockets

RESULTS_DIR = Path(__file__).resolve().parent / "results"
DECISION_LIMIT = 3.0
AVAILABILITY_LIMIT = 2.0


def percentile(values, percent):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percent / 100 * len(ordered)) - 1)]


def summarise(values):
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values),
    }


def new_plate(generator):
    letters = "".join(generator.choices(string.ascii_uppercase, k=4))
    return f"{letters[:2]}{generator.randint(10, 99)}{letters[2:]}{generator.randint(1000, 9999)}"


def unique_plates(count, generator):
    plates = set()
    while len(plates) < count:
        plates.add(new_plate(generator))
    return list(plates)


async def entry_load(base_url, events, concurrency, generator):
    gate = asyncio.Semaphore(concurrency)
    plates = unique_plates(events, generator)
    records = []

    async def one(client, plate):
        async with gate:
            started = time.perf_counter()
            response = await client.post("/api/v1/entries", json={"plate": plate, "vehicleType": "car"})
            records.append((plate, response.status_code, time.perf_counter() - started))

    began = time.perf_counter()
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        await asyncio.gather(*(one(client, plate) for plate in plates))
    return records, time.perf_counter() - began


async def availability_delays(base_url, events, generator):
    ws_url = base_url.replace("http", "ws", 1) + "/ws/availability"
    plates = unique_plates(events, generator)
    delays = []
    async with websockets.connect(ws_url) as socket, httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        free = json.loads(await asyncio.wait_for(socket.recv(), 10))["byType"]["car"]["free"]
        for number, plate in enumerate(plates):
            started = time.perf_counter()
            response = await client.post("/api/v1/entries", json={"plate": plate, "vehicleType": "car"})
            if response.status_code != 201:
                raise RuntimeError(f"Entry failed with {response.status_code}: {response.text}")
            while True:
                message = json.loads(await asyncio.wait_for(socket.recv(), 10))
                if message["byType"]["car"]["free"] == free - number - 1:
                    break
            delays.append(time.perf_counter() - started)
    return delays


def line(label, stats):
    return (
        f"{label}: n={stats['count']} mean={stats['mean'] * 1000:.0f} ms p50={stats['p50'] * 1000:.0f} ms "
        f"p95={stats['p95'] * 1000:.0f} ms p99={stats['p99'] * 1000:.0f} ms max={stats['max'] * 1000:.0f} ms"
    )


async def run(args):
    generator = random.Random(args.seed)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=10) as client:
        health = await client.get("/health")
        health.raise_for_status()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    RESULTS_DIR.mkdir(exist_ok=True)

    print(f"TC-PERF-01: {args.entries} entry events, concurrency {args.concurrency}")
    records, elapsed = await entry_load(args.base_url, args.entries, args.concurrency, generator)
    durations = [duration for _, _, duration in records]
    entry_stats = summarise(durations)
    statuses = {}
    for _, status, _ in records:
        statuses[status] = statuses.get(status, 0) + 1
    with open(RESULTS_DIR / f"entry_latency_{stamp}.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["plate", "status", "seconds"])
        writer.writerows(records)
    entry_pass = entry_stats["p95"] <= DECISION_LIMIT and statuses.get(201, 0) == len(records)
    print(line("  decision time", entry_stats))
    print(f"  status codes: {statuses}, throughput: {len(records) / elapsed:.1f} requests/s")
    print(f"  95th percentile limit {DECISION_LIMIT} s: {'PASS' if entry_pass else 'FAIL'}")

    print(f"TC-PERF-02: {args.events} availability events")
    delays = await availability_delays(args.base_url, args.events, generator)
    delay_stats = summarise(delays)
    delay_pass = delay_stats["max"] <= AVAILABILITY_LIMIT
    print(line("  update delay", delay_stats))
    print(f"  maximum limit {AVAILABILITY_LIMIT} s: {'PASS' if delay_pass else 'FAIL'}")

    summary = {
        "timestamp": stamp,
        "base_url": args.base_url,
        "entry_decision_seconds": entry_stats,
        "entry_status_codes": statuses,
        "entry_pass": entry_pass,
        "availability_delay_seconds": delay_stats,
        "availability_pass": delay_pass,
    }
    (RESULTS_DIR / f"summary_{stamp}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Results saved in {RESULTS_DIR}")
    return 0 if entry_pass and delay_pass else 1


def main():
    parser = argparse.ArgumentParser(description="APMS performance test for NF-001 and NF-002")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--entries", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--events", type=int, default=100)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except (httpx.HTTPError, OSError, RuntimeError, TimeoutError) as error:
        print(f"Could not complete the test: {error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
