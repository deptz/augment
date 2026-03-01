#!/usr/bin/env python3
"""
Benchmark OpenSandbox lifecycle: create sandbox and release (optional: multiple runs).

Use this script to measure sandbox create/release overhead when OPENSANDBOX_ENABLED
is true and the OpenSandbox server is reachable. Run from repo root with the same
env (or .env) as the worker so that OPENSANDBOX_DOMAIN and related config are set.

Usage:
  # From repo root, with venv activated and OpenSandbox server running:
  export OPENSANDBOX_ENABLED=true
  export OPENSANDBOX_DOMAIN=localhost:8080
  python scripts/benchmark_sandbox.py

  # Write results to a file:
  python scripts/benchmark_sandbox.py --output results.json

  # Run multiple create/release cycles and report min/mean/max:
  python scripts/benchmark_sandbox.py --runs 5 --output results.json

Interpretation:
  - create_seconds: time until create_sandbox() returns (sandbox is running).
  - total_seconds: create + sandbox.kill() + release_sandbox (full lifecycle).
  - Use these numbers to baseline sandbox overhead in your environment. For full
    plan generation or execute_generic timing, run a real Draft PR plan job or
    single-ticket generation with repos and check job duration in logs or the jobs API.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def load_sandbox_config() -> dict:
    """Load OpenSandbox config from config.yaml (env interpolation) or env."""
    try:
        from src.config import Config
        cfg = Config()
        return cfg.get_sandbox_config()
    except Exception:
        pass
    # Fallback: env-only
    domain = os.environ.get("OPENSANDBOX_DOMAIN", "localhost:8080")
    return {
        "enabled": os.environ.get("OPENSANDBOX_ENABLED", "").strip().lower() in ("true", "1", "yes"),
        "domain": domain,
        "api_key": os.environ.get("OPENSANDBOX_API_KEY", ""),
        "protocol": os.environ.get("OPENSANDBOX_PROTOCOL", "http"),
        "max_concurrent": 5,
        "request_timeout_seconds": 30,
    }


async def run_one(client, job_id: str, image: str, timeout_seconds: int) -> dict:
    """One create -> kill -> release cycle. Returns dict with create_seconds and total_seconds."""
    t0 = time.perf_counter()
    sandbox = await client.create_sandbox(
        job_id=job_id,
        image=image,
        env={"BENCHMARK": "1"},
        timeout=timedelta(seconds=timeout_seconds),
        resource={"cpu": "2", "memory": "4Gi"},
    )
    t1 = time.perf_counter()
    try:
        async with sandbox:
            await sandbox.kill()
    except Exception:
        try:
            await sandbox.kill()
        except Exception:
            pass
    finally:
        client.release_sandbox(job_id)
    t2 = time.perf_counter()
    return {
        "create_seconds": round(t1 - t0, 3),
        "total_seconds": round(t2 - t0, 3),
    }


async def main() -> dict:
    parser = argparse.ArgumentParser(description="Benchmark OpenSandbox create/release lifecycle")
    parser.add_argument("--output", "-o", type=str, help="Write JSON results to this file")
    parser.add_argument("--runs", "-n", type=int, default=1, help="Number of create/release cycles (default 1)")
    args = parser.parse_args()

    sb = load_sandbox_config()
    if not sb.get("enabled"):
        print("OPENSANDBOX_ENABLED is not true. Set OPENSANDBOX_ENABLED=true and ensure OpenSandbox server is configured.", file=sys.stderr)
        sys.exit(1)

    try:
        from src.sandbox_client import SandboxClient
    except ImportError as e:
        print(f"Sandbox client import failed: {e}. Install opensandbox and opensandbox-code-interpreter.", file=sys.stderr)
        sys.exit(1)

    client = SandboxClient(
        domain=sb["domain"],
        api_key=sb.get("api_key") or "",
        protocol=sb.get("protocol", "http"),
    )
    image = sb.get("image", "opensandbox/code-interpreter:v1.0.1")
    timeout_seconds = 60

    results = []
    for i in range(args.runs):
        job_id = f"bench-{int(time.time())}-{i}"
        try:
            r = await run_one(client, job_id, image, timeout_seconds)
            results.append(r)
            print(f"Run {i + 1}/{args.runs}: create={r['create_seconds']}s total={r['total_seconds']}s")
        except Exception as e:
            print(f"Run {i + 1}/{args.runs}: FAILED {e}", file=sys.stderr)
            results.append({"error": str(e)})

    out = {
        "runs": args.runs,
        "results": results,
        "summary": None,
    }
    if results and "error" not in results[0]:
        creates = [r["create_seconds"] for r in results]
        totals = [r["total_seconds"] for r in results]
        out["summary"] = {
            "create_seconds": {"min": min(creates), "max": max(creates), "mean": round(sum(creates) / len(creates), 3)},
            "total_seconds": {"min": min(totals), "max": max(totals), "mean": round(sum(totals) / len(totals), 3)},
        }
        print("Summary:", json.dumps(out["summary"], indent=2))

    if args.output:
        with open(args.output, "w") as f:
            json.dump(out, f, indent=2)
        print(f"Wrote {args.output}")

    return out


if __name__ == "__main__":
    asyncio.run(main())
