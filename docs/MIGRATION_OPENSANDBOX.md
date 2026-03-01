# OpenSandbox Migration Guide

This guide covers the migration to OpenSandbox for all code-aware flows in Augment.

## Summary

**Code-aware flows** (single ticket generation, task generation, story coverage, and Draft PR) now use **OpenSandbox only** when `repos` are provided. There is **no host Docker path** for these flows: the legacy OpenCodeRunner and host-based workspace/verification are not used when `repos` are supplied. All code execution (OpenCode, git, verify) runs inside ephemeral OpenSandbox containers.

- **Without `repos`**: Endpoints use direct LLM only (no code analysis). No sandbox required.
- **With `repos`**: OpenSandbox must be enabled and reachable; otherwise the API returns 503 and the worker fails with a clear error.

## Required configuration

To use any code-aware flow with `repos`:

1. **Environment**
   - `OPENSANDBOX_ENABLED=true`
   - `OPENSANDBOX_DOMAIN=<host>:<port>` (e.g. `localhost:8080`)
   - Optional: `OPENSANDBOX_PROTOCOL`, `OPENSANDBOX_API_KEY` if your server requires them.

2. **Worker**
   - The worker process must have OpenSandbox configured (same env or `config.yaml`). On startup, the worker checks OpenSandbox availability and runs orphan sandbox cleanup when enabled.

3. **Config file** (`config.yaml`)
   - `opensandbox.enabled` is driven by `OPENSANDBOX_ENABLED` (via `${OPENSANDBOX_ENABLED:false}`). Ensure `opensandbox.server.domain` (or env `OPENSANDBOX_DOMAIN`) points to your OpenSandbox server.

## Behavior when OpenSandbox is disabled

- **API**: If a request includes `repos` and OpenSandbox is disabled (or unavailable), the API returns **503** with a message that OpenSandbox is required when repos are provided, and that the user should enable `OPENSANDBOX_ENABLED` and ensure the worker has sandbox configured.
- **Worker**: If a job with `repos` is queued and OpenSandbox is disabled or unavailable, the job fails with a **clear error** (e.g. "OpenSandbox is required when repos are provided. Enable OPENSANDBOX_ENABLED and ensure the worker has sandbox configured.").

## Optional cleanup

Removing `OPENCODE_ENABLED` or legacy OpenCode/workspace cleanup from `run_worker.py` is **not required** for correctness. You may do it for simplicity if you no longer need the legacy path. When `repos` are provided, the code path is OpenSandbox-only regardless.

## WorkspaceManager when sandbox is disabled

**WorkspaceManager** is still used in these cases:

1. **Plan revision workspace lookup** – When the Draft PR pipeline revises a plan (e.g. after feedback), the revision step may use WorkspaceManager to resolve the workspace for the plan.
2. **Worker orphan workspace cleanup** – When `OPENCODE_ENABLED` is set, `run_worker` may run orphan workspace cleanup for legacy host workspaces.

When all code-aware flows use OpenSandbox (i.e. `repos` are provided and OpenSandbox is enabled), **no host workspace is created** for those flows; clone and execution happen only inside the sandbox. If sandbox is disabled and the user passes `repos`, the request is **rejected (503)**.

## Performance

To measure OpenSandbox lifecycle and optional plan/execute timing:

- Run the **sandbox benchmark script**: `python scripts/benchmark_sandbox.py` (requires `OPENSANDBOX_ENABLED=true` and a reachable OpenSandbox server). It times sandbox create → release (and optionally a minimal run). Results are printed to stdout and can be written to a file with `--output`.
- **Interpretation**: The script reports wall-clock time for create and release. Use it to baseline sandbox overhead in your environment. For full plan generation or `execute_generic` timing, run a real Draft PR plan job or single-ticket generation with `repos` and check job duration in logs or the jobs API.

See the script docstring and `--help` for options. A "Performance" subsection is also in the README OpenSandbox section if present.

## See also

- [README](README.md) – OpenSandbox setup and usage (see "OpenSandbox Integration" under Configuration).
- [OpenSandbox Integration Plan](OPENSANDBOX_INTEGRATION_PLAN.md) – Architecture and implementation details.
