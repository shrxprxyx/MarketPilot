"""Load smoke test (SRS §13): 50 concurrent users hitting read endpoints and 5 concurrent
indexing jobs, against a running API. Reports latency percentiles and checks the SRS NFR-01
target of p95 under 300 ms for reads. Exits 1 if the target is missed or any request errors.

    cd apps/api
    uv run python scripts/load_smoke.py --base-url http://localhost:8000/api/v1

The users are spread over several client processes (--procs, by default one per 10 users).
One Python client process tops out at roughly 130-150 requests per second, so a single
process with 50 users would mostly measure its own queue instead of the API.

It registers a throwaway agency (e-mail load-<random>@example.com), so run it against a
development database, never production. Needs the Celery worker for the indexing jobs to
finish; without it the jobs are still created and the script reports them as queued.
"""
import argparse
import asyncio
import json
import random
import secrets
import statistics
import subprocess
import sys
import time

import httpx

P95_TARGET_MS = 300.0
USERS_PER_PROCESS = 10
READ_PATHS = ("/me", "/clients", "/jobs", "/ai/connections", "/tenant")


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct))]


async def _user(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    stop_at: float,
    samples: list[float],
    errors: list[str],
    think_s: float,
) -> None:
    i = 0
    # People do not all click in the same millisecond: spread the first requests over a
    # couple of think times, as a real crowd arrives.
    await asyncio.sleep(random.random() * think_s * 2)
    while time.monotonic() < stop_at:
        path = READ_PATHS[i % len(READ_PATHS)]
        i += 1
        started = time.perf_counter()
        try:
            r = await http.get(path, headers=headers)
            elapsed = (time.perf_counter() - started) * 1000
            if r.status_code == 200:
                samples.append(elapsed)
            else:
                errors.append(f"GET {path} -> {r.status_code}")
        except httpx.HTTPError as exc:
            errors.append(f"GET {path} -> {type(exc).__name__}")
        await asyncio.sleep(think_s * (0.5 + random.random()))  # a person reads between clicks


async def run(
    base_url: str, users: int, seconds: int, jobs: int, think_ms: int
) -> tuple[list[float], list[str], int, int]:
    """One client process. Returns (latency samples in ms, errors, jobs finished, jobs accepted)."""
    suffix = secrets.token_hex(4)
    creds = {
        "email": f"load-{suffix}@example.com",
        "password": secrets.token_urlsafe(16),
        "tenant_name": f"Load {suffix}",
    }
    limits = httpx.Limits(max_connections=users + jobs + 5)
    async with httpx.AsyncClient(base_url=base_url, timeout=30, limits=limits) as http:
        r = await http.post("/auth/register", json=creds)
        r.raise_for_status()
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        c = await http.post("/clients", json={"name": "Load client"}, headers=headers)
        c.raise_for_status()
        client_id = c.json()["id"]

        samples: list[float] = []
        errors: list[str] = []
        stop_at = time.monotonic() + seconds
        job_calls = [
            http.post(
                f"/clients/{client_id}/documents",
                json={"title": f"Load doc {n}", "text": f"Load test document {n}. " * 200},
                headers=headers,
            )
            for n in range(jobs)
        ]
        results = await asyncio.gather(
            *(
                _user(http, headers, stop_at, samples, errors, think_ms / 1000)
                for _ in range(users)
            ),
            *job_calls,
            return_exceptions=True,
        )
        job_responses = [x for x in results[users:] if isinstance(x, httpx.Response)]
        job_ids = [x.json().get("job_id") for x in job_responses if x.status_code == 202]
        if len(job_ids) != jobs:
            errors.append(f"only {len(job_ids)} of {jobs} indexing jobs were accepted")

        done = 0
        for _ in range(60):  # give the worker up to a minute
            polled = [await http.get(f"/jobs/{j}", headers=headers) for j in job_ids]
            states = [r.json()["status"] for r in polled]
            done = sum(s in ("succeeded", "failed") for s in states)
            if done == len(job_ids):
                break
            await asyncio.sleep(1)

    return samples, errors, done, len(job_ids)


def _spawn(argv: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, __file__, "--child", *argv], stdout=subprocess.PIPE, text=True
    )


def main(a: argparse.Namespace) -> int:
    procs = max(1, a.procs or -(-a.users // USERS_PER_PROCESS))
    shares = [a.users // procs + (1 if i < a.users % procs else 0) for i in range(procs)]
    print(
        f"{a.users} users over {procs} client process(es) reading for {a.seconds}s "
        f"(think time ~{a.think_ms} ms), plus {a.jobs} jobs"
    )
    children = [
        _spawn(
            [
                "--base-url", a.base_url, "--users", str(share), "--seconds", str(a.seconds),
                "--jobs", str(a.jobs if i == 0 else 0), "--think-ms", str(a.think_ms),
            ]
        )
        for i, share in enumerate(shares)
        if share > 0
    ]
    samples: list[float] = []
    errors: list[str] = []
    done = accepted = 0
    for child in children:
        out, _ = child.communicate()
        try:
            part = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            errors.append("a client process produced no result")
            continue
        samples += part["samples"]
        errors += part["errors"]
        done += part["done"]
        accepted += part["accepted"]

    if not samples:
        print("No successful requests.")
        return 1
    p95 = percentile(samples, 0.95)
    rate = len(samples) / a.seconds
    print(f"requests: {len(samples)}  errors: {len(errors)}  ({rate:.0f} req/s)")
    print(
        f"latency ms  p50={statistics.median(samples):.0f}  p95={p95:.0f}  "
        f"p99={percentile(samples, 0.99):.0f}  max={max(samples):.0f}"
    )
    print(f"indexing jobs finished: {done}/{accepted}")
    for e in sorted(set(errors))[:5]:
        print("  error:", e)
    ok = p95 < P95_TARGET_MS and not errors
    print(f"p95 target {P95_TARGET_MS:.0f} ms: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8000/api/v1")
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--seconds", type=int, default=15)
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument(
        "--think-ms", type=int, default=250,
        help="average pause between a user's requests (0 = saturation test, no pauses)",
    )
    ap.add_argument(
        "--procs", type=int, default=0,
        help=f"client processes to spread the users over (default: one per {USERS_PER_PROCESS})",
    )
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.child:  # one client process: print its raw results for the parent to merge
        s_, e_, d_, n_ = asyncio.run(run(a.base_url, a.users, a.seconds, a.jobs, a.think_ms))
        print(json.dumps({"samples": s_, "errors": e_, "done": d_, "accepted": n_}))
        sys.exit(0)
    sys.exit(main(a))
