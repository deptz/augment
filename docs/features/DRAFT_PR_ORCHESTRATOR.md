# Draft PR Orchestrator

## Overview

The Draft PR Orchestrator is a complete pipeline for converting ambiguous stories into safe, code-scoped, reality-verified Draft PRs. It enforces CI-grade rigor for the *intent → change* workflow with human-in-the-loop approval, safety guards, and comprehensive artifact persistence.

## Core Principles

1. **Intent before execution** – No code without a plan
2. **Human authority by default** – Execution is gated
3. **Evidence over magic** – Persist everything
4. **Reality is final arbiter** – Tests/build decide
5. **Compute is ephemeral; artifacts are permanent**
6. **Parallelism is bounded, not free**

## Execution Pipeline

All jobs follow this invariant pipeline:

```
Story + Scope
   ↓
PLAN        → plan_vN (read-only, immutable)
   ↓
APPROVAL    → binds (job_id, plan_hash)
   ↓
APPLY       → mutate workspace (git transaction)
   ↓
VERIFY      → tests / lint / build
   ↓
PACKAGE     → diff + PR metadata
   ↓
DRAFT_PR    → push branch + create Draft PR
```

### Pipeline Stages

- **PLAN**: Generate structured plan with scope, tests, failure modes
- **APPROVAL**: Human approval (or YOLO auto-approval) bound to plan hash
- **APPLY**: Execute code changes with git transaction safety
- **VERIFY**: Run tests, lint, and build commands
- **PACKAGE**: Generate git diff and PR metadata
- **DRAFT_PR**: Create branch and Draft PR in Bitbucket

## Modes

### Normal Mode (Default)

**Authority:** Human  
**Use case:** Production changes, shared systems, risky domains

**Flow:**
1. PLAN runs automatically
2. Job enters `WAITING_FOR_APPROVAL` stage
3. User reviews plan via API
4. User approves with plan hash
5. Pipeline continues: APPLY → VERIFY → PACKAGE → DRAFT_PR

**Guarantees:**
- No mutation without human consent
- Approval is bound to specific plan hash
- If plan changes, approval is invalidated
- If APPLY diverges from plan, job halts
- If VERIFY fails, PR is not created

### YOLO Mode

**Authority:** Policy-based auto-approval  
**Use case:** Low-risk changes (docs, scripts, tools)

**Flow:**
1. PLAN runs automatically
2. YOLO policy evaluates plan
3. If compliant: Auto-approve and continue
4. If not compliant: Fall back to normal mode

**Policy Checks:**
- File count limit (default: 5 files)
- LOC delta limit (default: 200 lines)
- Path restrictions (allow/deny patterns)
- Protected paths (require team approval)
- Required tests (optional)

## Plan Specification

Plans are structured YAML/JSON artifacts with:

- **Summary**: High-level overview
- **Scope**: Files to modify (added, modified, deleted, renamed)
- **Happy Paths**: Expected successful scenarios
- **Edge Cases**: Boundary conditions to handle
- **Failure Modes**: Potential failures with triggers, impact, mitigation
- **Assumptions**: Assumptions about system state
- **Unknowns**: Areas requiring investigation
- **Tests**: Tests to run (unit, integration, e2e)
- **Rollback**: Steps to revert changes
- **Cross-Repo Impacts**: Impacts on other repositories

## Plan Iteration

Users can iterate on plans:

1. **Review Plan**: Get latest plan version
2. **Submit Feedback**: Provide feedback, concerns, change requests
3. **Generate Revision**: System generates new plan version
4. **Compare Versions**: See what changed between versions
5. **Approve**: Approve when satisfied

**Features:**
- Immutable plan versions (never modified)
- Feedback history tracked per version
- Version comparison highlights changes
- Previous approval invalidated on revision

## Safety Mechanisms

### Plan Hash Binding
- Approval is cryptographically bound to plan hash
- If plan changes, approval is invalid
- Prevents executing modified plans

### Plan-Apply Guards
- Verifies actual changes match approved plan
- Checks changed files ⊆ plan.scope.files
- Warns on large LOC deltas
- Halts execution on divergence

### Git Transaction Safety
- Creates checkpoint before changes
- Atomic operations with rollback on failure
- No partial mutations possible
- Automatic reset to checkpoint on error

### Verification Gates
- Tests must pass before PR creation
- Lint must pass (if configured)
- Build must succeed (if configured)
- PR only created if all verification passes

### Artifact Persistence
All artifacts are persisted:
- Input specification
- All plan versions (immutable)
- Approval records
- Workspace fingerprints
- Git diffs
- Validation logs (stdout/stderr)
- PR metadata

## Configuration

### YOLO Policy

```yaml
draft_pr:
  yolo_policy:
    max_files: 5              # Maximum files that can be changed
    max_loc_delta: 200        # Maximum lines of code change
    allow_paths:              # Allowed path patterns
      - "docs/**"
      - "scripts/**"
      - "tools/**"
    deny_paths:               # Denied path patterns
      - "auth/**"
      - "billing/**"
      - "migrations/**"
    require_tests: false       # Whether tests are required
```

### Verification Commands

```yaml
draft_pr:
  verification:
    test_command: "pytest"           # Test command
    lint_command: "ruff check"       # Lint command
    build_command: ""                 # Build command (optional)
```

### Protected Paths

```yaml
draft_pr:
  protected_paths:
    billing/**:
      require: finance_team
    auth/**:
      require: security_team
```

Protected paths cannot be auto-approved by YOLO mode.

### Concurrency Limits

```yaml
draft_pr:
  concurrency:
    plan: 5        # Max concurrent planning jobs
    apply: 2       # Max concurrent apply jobs
    verify: 3      # Max concurrent verify jobs
    package: 3     # Max concurrent package jobs
    draft_pr: 3    # Max concurrent draft PR jobs
```

## API Usage

### Create Draft PR Job

```bash
POST /draft-pr/create
{
  "story_key": "STORY-123",
  "repos": [
    {
      "url": "https://bitbucket.org/workspace/repo.git",
      "branch": "develop"
    }
  ],
  "mode": "normal"
}
```

### Review Plan

```bash
GET /draft-pr/jobs/{job_id}/plan
```

### Revise Plan

```bash
POST /draft-pr/jobs/{job_id}/revise-plan
{
  "feedback": "Add rate limiting",
  "specific_concerns": ["Missing rate limiting"],
  "feedback_type": "addition"
}
```

### Approve Plan

```bash
POST /draft-pr/jobs/{job_id}/approve
{
  "plan_hash": "abc123..."
}
```

### Get Artifacts

```bash
GET /draft-pr/jobs/{job_id}/artifacts
GET /draft-pr/jobs/{job_id}/artifacts/git_diff
GET /draft-pr/jobs/{job_id}/artifacts/validation_logs
```

## Workflow Example

1. **Create Job**: `POST /draft-pr/create` with story key and repos
2. **Monitor Status**: `GET /draft-pr/jobs/{job_id}` to see stage progression
3. **Review Plan**: `GET /draft-pr/jobs/{job_id}/plan` to review generated plan
4. **Iterate (Optional)**: `POST /draft-pr/jobs/{job_id}/revise-plan` with feedback
5. **Compare Versions**: `GET /draft-pr/jobs/{job_id}/plans/compare?from_version=1&to_version=2`
6. **Approve**: `POST /draft-pr/jobs/{job_id}/approve` with plan hash
7. **Monitor Progress**: Pipeline continues automatically through APPLY → VERIFY → PACKAGE → DRAFT_PR
8. **Get Results**: `GET /draft-pr/jobs/{job_id}` shows PR URL when completed

## Troubleshooting

### Plan Generation Fails
- Check OpenCode is enabled
- Verify repository access
- Check LLM credentials

### Approval Fails
- Ensure plan hash matches latest version
- Check job is in `WAITING_FOR_APPROVAL` stage
- Verify plan hasn't been revised

### Verification Fails
- Check validation logs artifact
- Verify test/lint/build commands exist
- Review command output in artifacts

### PR Creation Fails
- Verify Bitbucket credentials
- Check branch doesn't already exist
- Ensure repository permissions

## Best Practices

1. **Review Plans Thoroughly**: Check scope, tests, failure modes before approval
2. **Use Normal Mode for Production**: YOLO only for low-risk changes
3. **Iterate on Plans**: Use revise-plan to refine before approval
4. **Monitor Verification**: Check validation logs if verification fails
5. **Review Artifacts**: All artifacts preserved for debugging and audit

## Architecture

### Core Components

- **DraftPRPipeline**: Main orchestrator managing all stages
- **PlanGenerator**: Generates and revises structured plans
- **CodeApplier**: Applies code changes with git transaction safety
- **Verifier**: Runs tests, lint, and build commands
- **PackageService**: Generates git diff and PR metadata
- **DraftPRCreator**: Creates branches and Draft PRs
- **ArtifactStore**: Persists all artifacts for auditability

### Data Models

- **PlanSpec**: Structured plan specification
- **PlanVersion**: Immutable plan version with hash
- **Approval**: Approval record binding job_id and plan_hash
- **WorkspaceFingerprint**: Reproducible workspace state
- **PlanFeedback**: User feedback for plan iteration

For complete API documentation, see [API Documentation](../api/API_DOCUMENTATION.md#draft-pr-orchestrator).
