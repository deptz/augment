# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Augment is an AI-powered JIRA automation platform that:
1. **Documentation Generation**: Enriches JIRA tickets with AI-generated descriptions using PRD/RFC documents, PRs, and code changes
2. **Task Orchestration**: Breaks down epics into team-aligned tasks (Backend/Frontend/QA) with dependency detection
3. **Draft PR Orchestrator**: Converts stories into safe, code-scoped Draft PRs with PLAN → APPROVAL → APPLY → VERIFY → PACKAGE → DRAFT_PR pipeline

## Development Commands

```bash
# Setup
./setup.sh                          # Create venv and install deps
source venv/bin/activate            # Activate virtual environment
cp .env.example .env                # Configure credentials

# Test connections
python main.py test                 # Verify JIRA, Bitbucket, Confluence, LLM connections
python main.py -v test              # Verbose mode for debugging

# CLI usage
python main.py single PROJ-123     # Preview description for single ticket (dry run)
python main.py single PROJ-123 --update  # Actually update the ticket
python main.py batch "project = 'PROJ' AND description is EMPTY"  # Batch process

# API Server (requires Redis for background jobs)
docker run -d -p 6379:6379 redis:latest  # Start Redis
python api_server.py                     # Start FastAPI server (port 8000)
python run_worker.py                     # Start ARQ background worker (separate terminal)

# Testing
pytest                              # Run all tests
pytest tests/test_sprint_planning.py  # Run specific test file
pytest -v                           # Verbose output
pytest --cov=src --cov=api          # With coverage
```

## Architecture

### Entry Points
- `main.py` - CLI interface (Click-based) for single/batch ticket processing
- `api_server.py` - FastAPI wrapper, imports from `api/main.py`
- `run_worker.py` - ARQ worker for async job processing

### Core Services (`src/`)
- `generator.py` - `DescriptionGenerator`: Main orchestrator for ticket description generation
- `planning_service.py` - `PlanningService`: Epic planning, story/task generation, gap analysis
- `llm_client.py` - `LLMClient`: Multi-provider abstraction (OpenAI, Claude, Gemini, Moonshot)
- `jira_client.py` - `JiraClient`: JIRA API with sprint management methods
- `confluence_client.py` - `ConfluenceClient`: PRD/RFC content extraction
- `bitbucket_client.py` - `BitbucketClient`: PR/commit data, supports multiple workspaces

### Planning Subsystem (`src/`)
- `epic_analysis_engine.py` - Analyzes epic structure and identifies gaps
- `team_based_task_generator.py` - Generates team-separated tasks (BE/FE/QA)
- `bulk_ticket_creator.py` - Creates JIRA tickets with dependencies and relationships
- `sprint_planning_service.py` - Capacity-based sprint assignment
- `enhanced_test_generator.py` - Comprehensive test case generation
- `story_coverage_analyzer.py` - Analyzes task coverage for stories

### Draft PR Orchestrator (`src/`)
- `draft_pr_pipeline.py` - Main orchestrator for PLAN → APPROVAL → APPLY → VERIFY → PACKAGE → DRAFT_PR workflow
- `plan_generator.py` - Generates and revises structured plans using LLM/OpenCode
- `plan_comparator.py` - Compares plan versions and highlights differences
- `yolo_policy.py` - YOLO mode auto-approval policy evaluator
- `code_applier.py` - Applies code changes with git transaction safety and plan-apply guards
- `verifier.py` - Runs tests, lint, and build commands for verification
- `package_service.py` - Generates git diff and PR metadata
- `draft_pr_creator.py` - Creates branches and draft PRs in Bitbucket
- `draft_pr_models.py` - Pydantic models for plans, approvals, feedback, fingerprints
- `draft_pr_schemas.py` - JSON schemas for plan validation
- `artifact_store.py` - Persists all artifacts (plans, diffs, logs, PR metadata)

### API Layer (`api/`)
- `main.py` - FastAPI app with CORS, auth, startup/shutdown events
- `dependencies.py` - Service initialization and dependency injection
- `job_queue.py` - Redis/ARQ integration for async processing
- `workers.py` - Background job handlers (large file: ~25k tokens)
- `routes/` - Endpoint modules: generation, planning, jobs, sprint_planning, team_members, draft_pr, etc.
- `models/` - Pydantic request/response models (including `draft_pr.py` for Draft PR endpoints)

### Background Job System
Uses ARQ (async Redis queue). All generation endpoints support `async_mode=true`:
- Jobs tracked by `job_id` or `ticket_key`
- Duplicate prevention: returns 409 if ticket already being processed
- Worker functions defined in `api/workers.py`, registered in `run_worker.py`

### OpenCode Integration
Optional code-aware LLM generation via Docker containers:
- `workspace_manager.py` - Git clone and workspace management
- `opencode_runner.py` - Docker container orchestration
- `opencode_schemas.py` - JSON schemas for results
- Enabled via `OPENCODE_ENABLED=true` and `repos` parameter in API calls

## Key Patterns

### LLM Provider Abstraction
All endpoints accept optional `llm_provider` and `llm_model` parameters to override defaults. Providers: `openai`, `claude`, `gemini`, `kimi`.

### Dry Run Mode
All ticket-modifying operations default to `dry_run=true`. Use `--update` (CLI) or `"dry_run": false` (API) to execute changes.

### Task Dependencies
Uses UUID-based `task_id` for stable dependency resolution. Dependencies reference `task_id` not mutable summaries.

### JIRA Hierarchy
- Epic > Story (siblings, not parent-child)
- Epic > Task (siblings, not parent-child)
- Story-Task relationships via "Work item split" links

### Prompts
Centralized in `src/prompts/` with modular templates (generation.py, planning.py, system.py, test_generation.py, draft_pr_planning.py).

## Configuration

- `config.yaml` - Main config with env var interpolation (`${VAR_NAME:default}`)
- `.env` - Credentials (JIRA, LLM API keys, Redis, Git)
- Team member data stored in SQLite: `data/team_members.db` (auto-created)

## Testing Notes

- Use mocks for API calls (JIRA, LLM, etc.)
- Test files in `tests/` with `conftest.py` for shared fixtures
- Key test files: `test_sprint_planning.py`, `test_team_based_task_generator.py`, `test_bulk_ticket_creator.py`
