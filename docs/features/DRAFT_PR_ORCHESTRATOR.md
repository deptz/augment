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
- Distributed locking prevents concurrent approvals
- Cancellation support at any stage
- Job status persistence for crash recovery

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

## Cancellation Support

Jobs can be cancelled at any stage using the general job cancellation endpoint:

```bash
DELETE /jobs/{job_id}
```

**Cancellation Behavior:**
- Works during any pipeline stage (PLANNING, WAITING_FOR_APPROVAL, APPLYING, VERIFYING, etc.)
- Uses Redis-based cancellation flags for cross-process communication
- Workspace is automatically cleaned up on cancellation
- Job status is updated to "cancelled"
- Cannot approve a cancelled job (approval endpoint checks cancellation status)

**Cancellation Checks:**
- Cancellation is checked before and after each major stage
- If cancelled during WAITING_FOR_APPROVAL, workspace is preserved until cleanup
- If cancelled during APPLY or VERIFY, workspace is rolled back and cleaned up

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
- Verifies workspace state before and after OpenCode execution
- Detects partial modifications on timeout/failure

### Verification Gates
- Tests must pass before PR creation
- Lint must pass (if configured)
- Build must succeed (if configured)
- PR only created if all verification passes
- Detailed error classification (COMMAND_NOT_FOUND, TIMEOUT, SYNTAX_ERROR, etc.)
- Clear error messages for debugging
- Verification commands are optional (if none configured, verification passes by default)

### Artifact Persistence
All artifacts are persisted:
- Input specification
- All plan versions (immutable)
- Approval records
- Workspace fingerprints
- Git diffs
- Validation logs (stdout/stderr)
- PR metadata
- Partial failure recovery information

**Resilience Features:**
- Retry logic with exponential backoff (up to 3 attempts)
- Post-storage validation to ensure artifacts were written
- Handles transient I/O errors gracefully

### Job Status Persistence
- Job status is persisted to Redis at key stages
- Enables crash recovery if worker process fails
- Status includes stage, plan versions, approved plan hash, and results
- TTL: 7 days (configurable)
- Retrieved automatically when querying job status

## Limitations

### Multi-Repository Support

**Current Limitation**: The Draft PR Orchestrator currently supports multiple repositories for analysis during the PLANNING stage, but only creates PRs for the **first repository** in the list.

**What this means:**
- Multiple repos can be analyzed together for comprehensive planning
- Code changes are only applied to the first repository
- Only one PR is created (for the first repository)
- Cross-repo changes are identified in the plan but not automatically coordinated

**Workaround:**
- For multi-repo changes, create separate draft PR jobs for each repository
- Use the plan's `cross_repo_impacts` section to understand dependencies
- Manually coordinate PRs across repositories

**Future Enhancement:**
Full multi-repo support with coordinated PR creation is planned for a future release.

### Branch Name Collisions

**Current Behavior**: Branch names follow the pattern `augment/{ticket_key}-{plan_hash[:8]}`. If a branch with the same name already exists, the system automatically retries with a numeric suffix (e.g., `augment/{ticket_key}-{plan_hash[:8]}-1`, `-2`, etc.) up to 5 attempts.

**What this means:**
- Same ticket approved multiple times will create unique branches
- Retry logic handles collisions automatically
- If all retries fail, job fails with clear error message

### Default Branch Detection

**Current Behavior**: The system automatically detects the default branch of the repository instead of hardcoding "main". It tries:
1. Remote HEAD symbolic reference
2. Common branch names (main, master, develop, dev)
3. Falls back to "main" if detection fails

**What this means:**
- Works with repositories using "master", "develop", or other default branches
- No configuration needed for different default branches
- Graceful fallback if detection fails

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

**Note:** Concurrency limits are configured but not yet enforced in the current implementation. This is a planned enhancement.

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
# Get latest plan
GET /draft-pr/jobs/{job_id}/plan

# List all plan versions (metadata only)
GET /draft-pr/jobs/{job_id}/plans

# Get specific plan version
GET /draft-pr/jobs/{job_id}/plans/{version}
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
4. **List Plan Versions (Optional)**: `GET /draft-pr/jobs/{job_id}/plans` to see all plan iterations
5. **Iterate (Optional)**: `POST /draft-pr/jobs/{job_id}/revise-plan` with feedback
6. **Compare Versions**: `GET /draft-pr/jobs/{job_id}/plans/compare?from_version=1&to_version=2`
7. **Approve**: `POST /draft-pr/jobs/{job_id}/approve` with plan hash
8. **Monitor Progress**: Pipeline continues automatically through APPLY → VERIFY → PACKAGE → DRAFT_PR
9. **Get Results**: `GET /draft-pr/jobs/{job_id}` shows PR URL when completed
10. **Review Artifacts**: `GET /draft-pr/jobs/{job_id}/artifacts` to access all artifacts

## Troubleshooting

### Plan Generation Fails
- Check OpenCode is enabled
- Verify repository access
- Check LLM credentials
- Review plan artifacts for error details

### Approval Fails
- Ensure plan hash matches latest version
- Check job is in `WAITING_FOR_APPROVAL` stage
- Verify plan hasn't been revised
- Check if job was cancelled (cannot approve cancelled jobs)
- Verify no concurrent approval requests (check for lock conflicts)

### Verification Fails
- Check validation logs artifact for detailed error messages
- Verify test/lint/build commands exist in PATH
- Review command output in artifacts
- Check for timeout errors (commands may be taking too long)
- Verify workspace has required dependencies installed

### PR Creation Fails
- Verify Bitbucket credentials
- Check branch doesn't already exist (will retry with suffix)
- Ensure repository permissions
- Check for partial failures: branch pushed but PR creation failed (recovery info in artifacts)

### Job Cancellation
- Jobs can be cancelled via `DELETE /jobs/{job_id}` endpoint
- Cancellation works during any pipeline stage
- Workspace is automatically cleaned up on cancellation
- Cannot approve a cancelled job

### Workspace Issues
- If workspace is missing during plan revision, system attempts to recreate it
- Workspace cleanup happens automatically on completion, failure, or cancellation
- Orphaned workspaces are cleaned up on worker startup

### Error Recovery
- Partial PR creation failures: Branch exists but PR failed (check `partial_failure` artifact)
- Artifact storage failures: Retry logic with exponential backoff (up to 3 attempts)
- Plan corruption: Hash validation detects corrupted plans
- Job status persistence: Job status saved to Redis for crash recovery

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
