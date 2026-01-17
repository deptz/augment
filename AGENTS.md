# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Augment is an AI-powered JIRA automation platform that:
1. **Documentation Generation**: Enriches JIRA tickets with AI-generated descriptions using PRD/RFC documents, PRs, and code changes
2. **Task Orchestration**: Breaks down epics into team-aligned tasks (Backend/Frontend/QA) with dependency detection

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

# MCP Server Management (for OpenCode integration)
python main.py mcp start    # Start MCP servers (generates docker-compose.mcp.yml)
python main.py mcp stop     # Stop MCP servers
python main.py mcp status   # Check MCP server status
python main.py mcp destroy  # Remove MCP servers and network

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

### API Layer (`api/`)
- `main.py` - FastAPI app with CORS, auth, startup/shutdown events
- `dependencies.py` - Service initialization and dependency injection
- `job_queue.py` - Redis/ARQ integration for async processing
- `workers.py` - Background job handlers (large file: ~25k tokens)
- `routes/` - Endpoint modules: generation, planning, jobs, sprint_planning, team_members, etc.
- `models/` - Pydantic request/response models

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

### MCP Server Integration
Model Context Protocol servers provide read-only access to external data sources for OpenCode containers:
- **Architecture**: MCP servers run as persistent Docker services, separate from ephemeral OpenCode containers
- **Dynamic Compose Generation**: `scripts/generate-mcp-compose.py` generates `docker-compose.mcp.yml` based on `BITBUCKET_WORKSPACES`
  - Single workspace: Creates one Bitbucket MCP instance
  - Multiple workspaces: Creates one Bitbucket MCP instance per workspace (ports 7001, 7002, 7003...)
- **Environment Variable Alignment**: MCP servers use the same variables as main app:
  - `JIRA_SERVER_URL` → mapped to `JIRA_URL` inside containers
  - `CONFLUENCE_SERVER_URL` → mapped to `CONFLUENCE_URL` inside containers
  - `BITBUCKET_EMAIL` → mapped to `BITBUCKET_USERNAME` inside containers
- **Dynamic opencode.json**: Each OpenCode container gets a custom `opencode.json` generated based on repos being analyzed:
  - Extracts workspace from repo URLs
  - Includes appropriate Bitbucket MCP URLs for those workspaces
  - Each workspace gets its own key: `bitbucket-{workspace}` (always used for single or multiple workspaces)
  - Mounted into container at `/app/opencode.json`
- **Management Commands**: `python main.py mcp start/stop/status/destroy`
- **Network**: All services connect to `augment-mcp-network` Docker network

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
Centralized in `src/prompts/` with modular templates (generation.py, planning.py, system.py, test_generation.py).

## Configuration

- `config.yaml` - Main config with env var interpolation (`${VAR_NAME:default}`)
- `.env` - Credentials (JIRA, LLM API keys, Redis, Git)
- Team member data stored in SQLite: `data/team_members.db` (auto-created)
- `docker-compose.mcp.yml` - Dynamically generated by `scripts/generate-mcp-compose.py` based on `BITBUCKET_WORKSPACES`

## Testing Notes

- Use mocks for API calls (JIRA, LLM, etc.)
- Test files in `tests/` with `conftest.py` for shared fixtures
- Key test files: `test_sprint_planning.py`, `test_team_based_task_generator.py`, `test_bulk_ticket_creator.py`
