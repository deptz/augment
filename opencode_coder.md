# Product Requirements Document

**Product:** Augment — Draft PR Orchestrator
**Goal:** Convert ambiguous stories into safe, code-scoped, reality-verified Draft PRs.

## Problem

Current “AI coding” tools jump from intent to code. This fails in real engineering environments because:

* Stories are ambiguous.
* Risk is invisible until after damage.
* Changes lack auditability.
* Failures are non-reproducible.
* Teams don’t trust autonomous mutation.

We need CI-grade rigor for *intent → change*.

---

## Core Principles

1. **Intent before execution** – No code without a plan.
2. **Human authority by default** – Execution is gated.
3. **Evidence over magic** – Persist everything.
4. **Reality is final arbiter** – Tests/build decide.
5. **Compute is ephemeral; artifacts are permanent.**
6. **Parallelism is bounded, not free.**

---

## Execution Pipeline (Invariant)

All jobs run this pipeline:

```
Story + Scope
   ↓
PLAN        → plan_vN (read-only)
   ↓
APPROVAL    → binds (job_id, plan_hash)
   ↓
APPLY       → mutate workspace (git)
   ↓
VERIFY      → tests / lint / build
   ↓
PACKAGE     → diff + PR metadata
   ↓
DRAFT_PR    → push branch + create Draft PR
```

Artifacts persisted for every job:

* input_spec
* all plan versions (plan_v1…vN)
* approved_plan_hash
* workspace fingerprint
* git diff / changed files
* validation logs
* full stdout/stderr per stage
* PR metadata

Compute (containers) is destroyed. Evidence remains.

---

## Modes

### Normal Mode (Default)

**Authority:** Human
**Use case:** Production changes, shared systems, risky domains

Flow:

1. PLAN runs.
2. Job enters `WAITING_FOR_APPROVAL`.
3. User reviews plan.
4. User approves:

```http
POST /jobs/:id/approve
{ "plan_hash": "..." }
```

5. APPLY → VERIFY → PACKAGE → DRAFT_PR.

Guarantees:

* No mutation without human consent.
* Approval is bound to a specific plan hash.
* If plan changes, approval is invalid.
* If APPLY diverges from plan, job halts.
* If VERIFY fails, PR is not created.

This enforces: **Intent is owned by humans.**

---

### YOLO Mode

**Authority:** System (under policy)
**Use case:** Docs, scripts, low-risk tooling

YOLO does **not** remove stages. It auto-approves *if and only if* the plan complies with policy.

Flow:

1. PLAN runs.
2. System evaluates `yolo_policy`.
3. If compliant:

   * Auto-approve `(job_id, plan_hash)`
   * Continue pipeline.
4. If not compliant:

   * Fall back to `WAITING_FOR_APPROVAL` (Normal behavior).

Example policy:

```yaml
yolo_policy:
  max_files: 5
  max_loc_delta: 200
  allow_paths:
    - docs/**
    - scripts/**
    - tools/**
  deny_paths:
    - auth/**
    - billing/**
    - migrations/**
  require_tests: false
```

Even in YOLO:

* Plan is generated and stored.
* Plan–diff divergence halts execution.
* VERIFY still gates PR creation.
* All artifacts persist.

YOLO removes *waiting*, not *discipline*.

---

## Plan Specification (Adversarial by Design)

The PLAN stage must output a structured artifact:

```yaml
summary: ...
scope:
  files:
    - path: ...
      change: ...
happy_paths:
  - ...
edge_cases:
  - ...
failure_modes:
  - trigger: ...
    impact: ...
    mitigation: ...
assumptions:
  - ...
unknowns:
  - ...
tests:
  - type: unit|integration|e2e
    target: ...
rollback:
  - ...
cross_repo_impacts:
  - repo: ...
    reason: ...
```

Empty sections are a failure signal.

Plans are **versioned**:

```
plan_v1
plan_v2 (from feedback)
plan_v3
approved_plan = vN
```

No plan is mutated in place.

---

## Safety Mechanisms

1. **Workspace Fingerprinting**

   * Hash of repos + refs + selected paths.
   * Stored with job.

2. **Plan–Apply Guard**

   * After APPLY:

     * Changed files ⊆ plan.scope.files
     * LOC delta within bounds
     * Intent matches plan
   * Mismatch → halt.

3. **Crash Safety**

   * APPLY runs inside a git transaction.
   * On failure: reset to pre-apply commit.

4. **Cross-Repo Awareness**

   * PLAN detects outbound references.
   * Emits warnings for missing repos.

5. **Environment Contracts**

   * Repos declare validation requirements.
   * PLAN surfaces missing env as “incomplete validation.”

6. **Protected Paths**

   * Policy-driven ownership:

     ```yaml
     protected_paths:
       billing/**:
         require: finance_team
       auth/**:
         require: security_team
     ```
   * YOLO cannot bypass.

---

## Parallelism Model

* Stage queues with hard caps:

```yaml
concurrency:
  plan: 5
  apply: 2
  verify: 3
  package: 3
  draft_pr: 3
```

* Job state machine:

```
CREATED → PLANNING → WAITING_FOR_APPROVAL
        → APPLYING → VERIFYING → PACKAGING
        → DRAFTING → COMPLETED | FAILED
```

* Atomic transitions in DB.
* Host-level container limits.
* Requeue on resource pressure.

Parallelism is bounded contention, not chaos.

---

## Success Criteria

* Zero code mutation without a plan.
* Every PR traceable to explicit intent.
* Every failure reproducible.
* Engineers trust the system with real repos.
* YOLO is safe enough to leave on.