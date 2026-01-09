# Augment

**Augment** is an AI-powered JIRA automation platform designed to streamline project management workflows. It offers two core capabilities that work seamlessly together:

1. **AI-Powered Documentation Generation**: Automatically enrich JIRA tickets with comprehensive, context-aware descriptions by analyzing Product Requirements Documents (PRDs), Pull Requests, and code changes
2. **Intelligent Task Orchestration**: Break down epics into well-structured, team-aligned tasks with automatic dependency detection and sprint-ready planning capabilities

Whether you're backfilling documentation for existing tickets or planning new features, Augment helps teams maintain high-quality project documentation and efficient task management with minimal manual effort.

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Running with Docker (Docker Hub Image)](#running-with-docker-docker-hub-image)
- [Configuration](#configuration)
- [Usage](#usage)
- [API Documentation](#api-documentation)
- [JIRA Requirements](#jira-requirements)
- [Documentation](#documentation)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Features

### Core Capabilities
- **Safe by Default**: Dry-run mode enabled by default, ensuring you can preview changes before applying them
- **Multi-LLM Support**: Choose from OpenAI GPT, Anthropic Claude, Google Gemini, or Moonshot AI (KIMI) - switch providers anytime
- **Runtime Model Selection**: Select different LLM models per request via API parameters for optimal performance
- **Team-Based Task Generation**: Automatically separates work into Backend, Frontend, and QA tasks with appropriate assignments
- **AI-Powered Dependencies**: Intelligently detects and manages task dependencies and relationships with stable task_id resolution
- **Stable Dependency Resolution**: Uses UUID-based task identifiers to ensure dependencies remain valid even when task summaries are edited
- **Comprehensive Test Generation**: Generates detailed test cases for stories and tasks with context-aware scenarios
- **Background Job Processing**: All generation endpoints support asynchronous processing with real-time job tracking and cancellation
- **Duplicate Prevention**: Prevents duplicate processing of tickets that are already being handled
- **Ticket-Based Job Tracking**: Query job status by ticket key for easy integration with status pages and monitoring dashboards
- **Sprint Planning & Timeline Management**: Capacity-based sprint planning with automatic task assignment and timeline visualization
- **Team Member Management**: Built-in SQLite database for managing team members, teams, and boards with flexible many-to-many relationships

### JIRA Integration
- **Native JIRA Integration**: Creates real JIRA tickets with proper keys, hierarchies, and relationships
- **Advanced Relationship Management**: Automatically establishes "Work item split", "Blocks", and "Relates to" links between tickets
- **JIRA Hierarchy Compliance**: Respects JIRA's hierarchy rules - tasks are created under epics with story relationships via links
- **ADF Format Support**: Generates descriptions in Atlassian Document Format for rich text rendering in JIRA
- **Duplicate Prevention**: Intelligently prevents duplicate relationships and links from being created

### Context & Data Sources
- **Rich Context Gathering**: Leverages PRDs, RFCs, story tickets, pull requests, and commit history to generate accurate, comprehensive descriptions
- **Multi-Story Integration**: Automatically discovers and incorporates context from multiple linked story tickets
- **Development Panel API**: Uses JIRA's Development Panel API to fetch accurate PR and commit data
- **PRD Hierarchy Discovery**: Automatically locates PRD documents from parent EPIC tickets
- **Code Analysis**: Analyzes actual code changes from diffs to understand implementation details and technical context

## Quick Start

Get up and running with Augment in minutes. Choose between the command-line interface for quick operations or the REST API for integration and automation.

### Command Line Interface

Perfect for one-off tasks and quick documentation updates:

1. **Set up the environment:**
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

2. **Configure your credentials:**
   ```bash
   cp .env.example .env
   nano .env  # Add your API credentials
   ```

3. **Verify your connections:**
   ```bash
   source venv/bin/activate
   python main.py test
   ```

4. **Generate documentation for a single ticket (preview mode):**
   ```bash
   python main.py single PROJ-123
   ```

5. **Process multiple tickets (preview mode):**
   ```bash
   python main.py batch "project = 'PROJ' AND description is EMPTY"
   ```

### REST API Interface

Ideal for automation, integrations, and programmatic access:

1. **Start Redis (required for background job processing):**
   ```bash
   # Using Docker (recommended)
   docker run -d -p 6379:6379 redis:latest
   
   # Or use an existing Redis instance
   # Configure REDIS_HOST and REDIS_PORT in .env
   ```

2. **Start the API server:**
   ```bash
   python api_server.py
   ```

3. **Start the background worker (in a separate terminal):**
   ```bash
   python run_worker.py
   ```

4. **Access the interactive API documentation:**
   - **Swagger UI**: http://localhost:8000/docs
   - **ReDoc**: http://localhost:8000/redoc

5. **Try your first API call:**
   ```bash
   # Synchronous request (immediate response)
   curl -X POST "http://localhost:8000/generate/single" \
     -H "Content-Type: application/json" \
     -d '{"ticket_key": "PROJ-123", "update_jira": false}'
   
   # Asynchronous request (background processing)
   curl -X POST "http://localhost:8000/generate/single" \
     -H "Content-Type: application/json" \
     -d '{"ticket_key": "PROJ-123", "update_jira": false, "async_mode": true}'
   ```

For comprehensive API documentation, see [API Documentation](docs/api/API_DOCUMENTATION.md).

## Installation

### Prerequisites

Before you begin, ensure you have:

- **Python 3.10 or higher** - Check with `python3 --version`
- **pip** or **poetry** - For dependency management
- **JIRA account** with API access - Required for all operations
- **LLM API key** - Choose one: OpenAI, Anthropic (Claude), Google (Gemini), or Moonshot AI (KIMI)
- **Redis** - Required for background job processing (can be local or external instance)
- **(Optional) Bitbucket account** - For code analysis and PR context
- **(Optional) Confluence account** - For PRD/RFC document access

### Setup Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/deptz/augment.git
   cd augment
   ```

2. **Run the setup script:**
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```
   This script will create a virtual environment and install all required dependencies.

3. **Configure your credentials:**
   ```bash
   cp .env.example .env
   # Edit .env with your JIRA and LLM API credentials
   ```

4. **Verify your installation:**
   ```bash
   source venv/bin/activate
   python main.py test
   ```
   This will test connections to all configured services.

## Running with Docker (Docker Hub Image)

You can run Augment without cloning the repository by using the prebuilt image from Docker Hub.

### 1. Prerequisites

- Docker installed and running
- A Redis instance (can be a Docker container)
- Your own `config.yaml` and `.env` files on the host

At minimum, your `.env` should define:

- Jira: `JIRA_SERVER_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN`
- LLM: `LLM_PROVIDER` and the corresponding API key (e.g. `OPENAI_API_KEY`)
- Redis: `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`

### 2. Pull the Docker image

```bash
docker pull pujitriwibowo/augment:0.1.0
# Or track the latest stable build:
docker pull pujitriwibowo/augment:latest
```

### 3. Prepare configuration on the host

In an empty directory on your machine:

```bash
curl -O https://raw.githubusercontent.com/deptz/augment/main/config.yaml
curl -O https://raw.githubusercontent.com/deptz/augment/main/.env.example
cp .env.example .env
# Edit .env with your Jira, LLM, and Redis settings
mkdir -p exports
```

Ensure your `.env` contains a Redis host reachable from inside Docker. For example, if you run Redis as a container named `augment-redis` on the same Docker network, set:

```env
REDIS_HOST=augment-redis
REDIS_PORT=6379
REDIS_DB=0
```

### 4. Start Redis (Docker)

```bash
docker network create augment-net

docker run -d \
  --name augment-redis \
  --network augment-net \
  redis:7-alpine
```

### 5. Run the API container

From the directory containing your `config.yaml`, `.env`, and `exports`:

```bash
docker run --rm \
  --name augment-api \
  --network augment-net \
  -p 8000:8000 \
  -e PYTHONPATH=/app \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -v "$PWD/.env:/app/.env:ro" \
  -v "$PWD/exports:/app/exports" \
  pujitriwibowo/augment:0.1.0
```

This starts the FastAPI server inside the container. You can then access:

- Swagger UI: http://localhost:8000/docs  
- ReDoc: http://localhost:8000/redoc

### 6. Run the background worker container

In a separate terminal, from the same directory:

```bash
docker run --rm \
  --name augment-worker \
  --network augment-net \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -v "$PWD/.env:/app/.env:ro" \
  -v "$PWD/exports:/app/exports" \
  pujitriwibowo/augment:0.1.0 \
  python run_worker.py
```

The worker container will connect to the same Redis instance and process background jobs created by the API.

## Configuration

### Required Configuration

**JIRA (Required):**
```bash
JIRA_SERVER_URL=https://your-company.atlassian.net
JIRA_USERNAME=your-email@company.com
JIRA_API_TOKEN=your-jira-api-token
JIRA_PRD_CUSTOM_FIELD=customfield_10001
JIRA_RFC_CUSTOM_FIELD=customfield_10002  # Optional: for RFC document links
JIRA_TEST_CASE_CUSTOM_FIELD=customfield_10003  # Optional: for test cases custom field
JIRA_MANDAYS_CUSTOM_FIELD=customfield_10004  # Optional: for mandays estimation (used for planning and timeline generation)
```

**LLM (Required - choose one provider):**
```bash
# OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=your-openai-key
OPENAI_MODEL=gpt-5-mini

# OR Anthropic (Claude)
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=your-anthropic-key
ANTHROPIC_MODEL=claude-sonnet-4-5

# OR Google (Gemini)
LLM_PROVIDER=gemini
GOOGLE_API_KEY=your-google-key
GOOGLE_MODEL=gemini-2.5-flash

# OR Moonshot AI (KIMI)
LLM_PROVIDER=kimi
MOONSHOT_API_KEY=your-moonshot-key
MOONSHOT_MODEL=moonshot-v1-8k
```

### Optional Configuration

**Bitbucket (for code analysis):**
```bash
# For multiple workspaces (recommended):
BITBUCKET_WORKSPACES=workspace1,workspace2,mid-kelola-indonesia
# OR for single workspace (backward compatible):
# BITBUCKET_WORKSPACE=your-workspace
BITBUCKET_EMAIL=your-email@company.com
BITBUCKET_API_TOKEN=your-atlassian-api-token
```

> **Note:** Multiple workspaces support allows searching for pull requests and commits across different Bitbucket workspaces using the same credentials. Use `BITBUCKET_WORKSPACES` (comma-separated) for multiple workspaces, or `BITBUCKET_WORKSPACE` for a single workspace (backward compatible).

**Confluence (for PRD/RFC content):**
```bash
CONFLUENCE_SERVER_URL=https://your-company.atlassian.net/wiki
CONFLUENCE_USERNAME=your-email@company.com
CONFLUENCE_API_TOKEN=your-confluence-api-token
```

**Authentication (for API security):**
```bash
AUTH_ENABLED=false
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=your-generated-hash
```

**Redis (for background job processing):**
```bash
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0
```

**Worker Configuration (Optional):**
```bash
WORKER_MAX_JOBS=10  # Maximum concurrent jobs per worker instance
WORKER_JOB_TIMEOUT=3600  # Job timeout in seconds (1 hour)
WORKER_KEEP_RESULT=3600  # How long to keep job results in Redis in seconds (1 hour)
```

**LLM Advanced Settings (Optional):**
```bash
LLM_SYSTEM_PROMPT=You are a technical documentation assistant...  # Custom system prompt
LLM_TEMPERATURE=0.7  # LLM temperature (0.0-1.0, higher = more creative)
LLM_MAX_TOKENS=  # Global max_tokens override (empty = use provider defaults)
```

**Dynamic Additional Context Management:**
The system automatically calculates the optimal character limit for `additional_context` based on:
- Actual token usage of the prompt (system + base prompt)
- Configured `max_tokens` or provider defaults
- Reserved tokens for response generation (30% of max_tokens)
- Remaining token budget after prompt construction

This ensures `additional_context` is dynamically sized to fit within your token budget:
- **Large token budgets** (e.g., 20k tokens): Can accommodate ~36k+ characters of additional context
- **Medium token budgets** (e.g., 8k tokens): Can accommodate ~10k+ characters of additional context
- **Small token budgets** (e.g., 2k tokens): Automatically reduces or eliminates additional context if prompt is too large

The system counts tokens used by the base prompt first, then allocates remaining budget to `additional_context` with no hard cap, maximizing context utilization while respecting token limits.

**Processing Settings (Optional):**
```bash
MAX_CONCURRENT_REQUESTS=5  # Max parallel API requests
REQUEST_TIMEOUT=30  # Request timeout in seconds
BATCH_SIZE=10  # Number of tickets to process per batch
INCLUDE_CODE_ANALYSIS=true  # Analyze code diffs from PRs
STORY_DESCRIPTION_MAX_LENGTH=800  # Max story description length
STORY_DESCRIPTION_SUMMARY_THRESHOLD=1200  # Threshold for summarization
MAX_TASKS_PER_STORY=10  # Maximum tasks per story
```

**Sprint Planning Settings (Optional):**
```bash
SPRINT_DURATION_DAYS=14  # Default sprint length in days
TEAM_CAPACITY_DAYS=10.0  # Default team capacity per sprint in days
AUTO_CREATE_SPRINTS=false  # Auto-create sprints if needed
```

**Environment Settings (Optional):**
```bash
ENVIRONMENT=development  # Set to "production" for production mode
```

**CORS Configuration (Optional):**
```bash
# Comma-separated list of allowed origins for Cross-Origin Resource Sharing
# Example: http://localhost:5173,http://localhost:3000,https://example.com
# If not set, defaults to common localhost ports for development
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

**Team Member Database (Optional):**
```bash
TEAM_MEMBER_DB_PATH=data/team_members.db  # Custom database path (absolute or relative to project root)
```

See [`.env.example`](.env.example) for all available configuration options.

### Team Member Database

Augment uses a lightweight SQLite database to store team member information, team definitions, and board configurations for sprint planning and capacity management.

**Key Features:**
- **Zero Configuration**: The database is automatically created on first use - no manual setup required
- **Auto-Initialization**: Schema is automatically initialized when the module is first imported
- **Directory Management**: Parent directories are created automatically if they don't exist
- **Version Control Safe**: Database files are excluded from git by default (contains user-specific data)
- **Startup Verification**: API server automatically verifies database readiness on startup
- **Health Monitoring**: Database status is included in the `/health` endpoint for easy monitoring

**Database Location:**
- **Default**: `data/team_members.db` (relative to project root)
- **Custom Path**: Set `TEAM_MEMBER_DB_PATH` environment variable to use a custom location
  ```bash
  # Absolute path
  export TEAM_MEMBER_DB_PATH=/path/to/custom/team_members.db
  
  # Relative path (relative to project root)
  export TEAM_MEMBER_DB_PATH=custom_data/my_team.db
  ```
- The database stores: team members, teams, boards, and their relationships

### Finding Your JIRA Custom Field ID

1. Go to Jira Settings → Issues → Custom Fields
2. Find your PRD, RFC, Test Case, or Mandays field and click "..." → Configure
3. Look at the URL - the ID will be in the format `customfield_XXXXX`
4. Use `JIRA_PRD_CUSTOM_FIELD` for PRD document links (required)
5. Use `JIRA_RFC_CUSTOM_FIELD` for RFC document links (optional)
6. Use `JIRA_TEST_CASE_CUSTOM_FIELD` for test cases custom field (optional)
7. Use `JIRA_MANDAYS_CUSTOM_FIELD` for mandays estimation (optional) - must be a number field type

**Note on Mandays Custom Field:**
- The mandays custom field stores the total effort estimation in days (calculated from cycle time estimates)
- For tasks: stores the total_days from cycle_time_estimate
- For stories: automatically calculated as the sum of all child task mandays
- Used for planning and timeline generation
- Must be configured as a number field type in JIRA

For detailed setup instructions, see:
- [API Setup Guide](docs/api/API_SETUP.md)
- [API Authentication Setup](docs/api/API_AUTH_SETUP.md)
- [Bitbucket Configuration](README.md#bitbucket-configuration) (below)

## Usage

### Sprint Planning & Timeline Management

The system includes comprehensive sprint planning capabilities with team member management:

#### 1. Team Member Management

**Create a Team Member:**
```bash
curl -X POST "http://localhost:8000/team-members" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "John Doe",
    "email": "john@example.com",
    "level": "Senior",
    "capacity_days_per_sprint": 8.0,
    "team_ids": [1]
  }'
```

**List Team Members:**
```bash
# List all members
curl "http://localhost:8000/team-members"

# Filter by team
curl "http://localhost:8000/team-members?team_id=1"

# Filter by level
curl "http://localhost:8000/team-members?level=Senior"
```

**Get Team Capacity:**
```bash
curl "http://localhost:8000/team-members/role/1/capacity?board_id=1"
```

#### 2. Sprint Planning

**Plan Epic Tasks to Sprints (Preview Mode):**
```bash
curl -X POST "http://localhost:8000/sprint/plan/epic" \
  -H "Content-Type: application/json" \
  -d '{
    "epic_key": "EPIC-100",
    "board_id": 1,
    "sprint_capacity_days": 10.0,
    "start_date": "2025-01-15",
    "sprint_duration_days": 14,
    "team_id": 1,
    "dry_run": true,
    "async_mode": false
  }'
```

**Create Timeline Schedule (Async Mode):**
```bash
curl -X POST "http://localhost:8000/sprint/timeline" \
  -H "Content-Type: application/json" \
  -d '{
    "epic_key": "EPIC-100",
    "board_id": 1,
    "start_date": "2025-01-15",
    "sprint_duration_days": 14,
    "team_capacity_days": 10.0,
    "team_id": 1,
    "dry_run": true,
    "async_mode": true
  }'

# Check job status
curl "http://localhost:8000/jobs/{job_id}"
```

**Assign Tickets to Sprint:**
```bash
curl -X POST "http://localhost:8000/sprint/123/assign" \
  -H "Content-Type: application/json" \
  -d '{
    "sprint_id": 123,
    "issue_keys": ["TASK-1", "TASK-2", "TASK-3"],
    "dry_run": false
  }'
```

**Key Features:**
- **Dry Run Mode**: All sprint planning endpoints default to `dry_run=true` for safe preview
- **Async Mode**: Long-running operations support `async_mode=true` for background processing
- **Capacity-Based Planning**: Automatically assigns tasks to sprints based on team capacity and task estimates
- **Dependency Awareness**: Respects task dependencies when assigning to sprints
- **Team Integration**: Uses team member data for accurate capacity calculations

### Documentation Backfilling Mode

Enrich existing JIRA tickets with comprehensive descriptions:

```bash
# Verify all connections are working
python main.py test

# Preview description for a single ticket (safe mode)
python main.py single PROJ-123

# Generate and update description for a single ticket
python main.py single PROJ-123 --update

# Preview descriptions for multiple tickets matching a JQL query
python main.py batch "project = 'PROJ' AND description is EMPTY"

# Generate and update descriptions for multiple tickets
python main.py batch "project = 'PROJ' AND description is EMPTY" --update
```

### Team-Based Planning Mode

Plan and organize tasks with intelligent team assignment:

```bash
# Start the API server
python api_server.py

# Access interactive API documentation
# http://localhost:8000/docs
```

**Example API Request:**
```bash
curl -X POST "http://localhost:8000/plan/tasks/team-based" \
  -H "Content-Type: application/json" \
  -d '{
    "story_keys": ["STORY-123"],
    "epic_key": "EPIC-100",
    "dry_run": false,
    "llm_provider": "openai",
    "llm_model": "gpt-5-mini"
  }'
```

**Task Dependency Resolution:**

The system uses stable task identifiers (UUID) to ensure dependencies remain valid even when task summaries are edited:

- Each task receives a unique `task_id` (UUID) during generation
- Dependencies reference `task_id` instead of mutable summaries
- Automatic conversion from summary-based to task_id-based dependencies
- Backward compatible with existing summary-based dependencies
- Robust matching with fuzzy fallback for edge cases

**API Response includes task_id:**
```json
{
  "task_details": [
    {
      "task_id": "550e8400-e29b-41d4-a716-446655440000",
      "summary": "[BE] Implement user authentication API",
      "depends_on_tasks": ["550e8400-e29b-41d4-a716-446655440001"],
      "team": "backend"
    }
  ]
}
```

**Sync Stories from PRD:**
```bash
# Synchronous mode (default)
curl -X POST "http://localhost:8000/plan/stories/sync-from-prd" \
  -H "Content-Type: application/json" \
  -d '{
    "epic_key": "EPIC-100",
    "dry_run": true,
    "async_mode": false,
    "existing_ticket_action": "skip"
  }'

# Asynchronous mode (background job)
curl -X POST "http://localhost:8000/plan/stories/sync-from-prd" \
  -H "Content-Type: application/json" \
  -d '{
    "epic_key": "EPIC-100",
    "dry_run": true,
    "async_mode": true,
    "existing_ticket_action": "skip"
  }'

# Check job status
curl "http://localhost:8000/jobs/{job_id}"
```

**PRD Table Format:**
The endpoint expects a table in the PRD document with:
- Section heading: "Story Ticket List", "Story Tickets", "Story List", or similar
- Table columns: Title, Description, Acceptance Criteria (columns are auto-detected)
- Missing columns are handled gracefully

**PRD Table Updates:**
When stories are created or updated, the system automatically:
- Creates a "JIRA Ticket" column in the PRD table if it doesn't exist
- Updates the corresponding PRD table row with a clickable JIRA link
- Uses UUID-based matching for exact row identification (from dry run preview)
- Falls back to fuzzy matching by story title if UUID is not available
- Formats links as proper HTML anchor tags for Confluence compatibility

### Generated Description Format

The tool generates descriptions in this structured format:

```
**Purpose:**
A 1-2 sentence summary of why this task was necessary, based on PRD/RFC goals.

**Scopes:**
- Concrete work item 1 (from PR titles and commits)
- Concrete work item 2
- Concrete work item 3

**Expected Outcome:**
- Expected result 1 (from PRD/RFC objectives)
- Expected result 2
```

## API Documentation

### Endpoint Categories

**Documentation & Description Generation:**
- `POST /generate/single` - Generate description for a single ticket
- `POST /generate/batch` - Process multiple tickets via JQL queries

**Task Planning & Generation:**
- `POST /plan/tasks/generate` - Generate contextual tasks for stories
- `POST /plan/tasks/team-based` - Generate team-separated tasks (Backend/Frontend/QA)
- `POST /plan/tasks/bulk-create` - Create multiple JIRA tickets with dependencies
- All task generation endpoints return `task_id` (UUID) for stable dependency resolution

**Bulk Creation:**
- `POST /plan/epic/create` - Execute complete planning workflow and create tickets (supports async_mode)
- `POST /plan/stories/create` - Generate and create story tickets for an epic (supports async_mode)
- `POST /plan/tasks/create` - Generate and create task tickets for stories (supports async_mode)

**Story Sync from PRD:**
- `POST /plan/stories/sync-from-prd` - Sync story tickets from PRD table to JIRA (supports async_mode)

**Test Case Generation:**
- `POST /plan/tests/comprehensive` - Generate complete test suites for epics
- `POST /plan/tests/story` - Generate test cases for specific stories
- `POST /plan/tests/task` - Generate test cases for specific tasks

**JIRA Operations:**
- `POST /jira/update-ticket` - Update any JIRA ticket (summary, description, test cases, links)
- `POST /jira/create-ticket` - Create a new JIRA Task ticket
- `POST /jira/create-story-ticket` - Create a new JIRA Story ticket (automatically updates PRD table with JIRA link)
- `POST /jira/update-story-ticket` - Update an existing JIRA Story ticket (title, description, test cases, parent epic, links; automatically updates PRD table)
- `POST /jira/bulk-update-stories` - Bulk update multiple story tickets with different values (supports preview and async modes; automatically updates PRD tables)
- `POST /jira/bulk-create-tasks` - Bulk create multiple task tickets (creates all tickets first, then all links)
- `POST /jira/bulk-create-stories` - Bulk create multiple story tickets (creates all tickets first, then all links; automatically updates PRD tables)

**Job Management:**
- `GET /jobs/{job_id}` - Get status and results of a background job
- `GET /jobs` - List all background jobs (with filtering by status/job_type)
- `GET /jobs/ticket/{ticket_key}` - Get current job status for a specific ticket key
- `DELETE /jobs/{job_id}` - Cancel a running job

**Sprint Planning:**
- `GET /sprint/board/{board_id}/sprints` - List sprints for a board
- `GET /sprint/{sprint_id}` - Get sprint details
- `POST /sprint/create` - Create new sprint
- `PUT /sprint/{sprint_id}` - Update sprint
- `POST /sprint/{sprint_id}/assign` - Assign tickets to sprint (dry_run=true by default)
- `POST /sprint/{sprint_id}/remove` - Remove tickets from sprint
- `GET /sprint/{sprint_id}/issues` - Get sprint issues
- `POST /sprint/plan/epic` - Plan epic tasks to sprints (capacity-based, dry_run=true by default, async_mode supported)
- `POST /sprint/timeline` - Create timeline schedule for epic (dry_run=true by default, async_mode supported)
- `GET /sprint/timeline/{epic_key}` - Get timeline for epic

**Team Management:**
- `GET /team-members` - List team members (with optional filters)
- `GET /team-members/{member_id}` - Get team member details
- `POST /team-members` - Create team member
- `PUT /team-members/{member_id}` - Update team member
- `DELETE /team-members/{member_id}` - Delete team member (soft delete)
- `GET /team-members/roles` - Get list of all roles/teams
- `GET /team-members/levels` - Get list of all career levels
- `GET /team-members/role/{role_id}/capacity` - Get role capacity

**Utility & Configuration:**
- `GET /health` - Service health check
- `GET /models` - Available LLM providers and models

### Interactive Documentation

When the API server is running:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI Spec**: http://localhost:8000/openapi.json

For complete API documentation, see:
- [API Documentation](docs/api/API_DOCUMENTATION.md)

## JIRA Requirements

### Issue Type Hierarchy

This system works with JIRA instances that have the following hierarchy:
- **Epic** (hierarchyLevel: 1) → **Story** (hierarchyLevel: 0) 
- **Epic** (hierarchyLevel: 1) → **Task** (hierarchyLevel: 0)
- **Story** and **Task** are siblings under Epic (Tasks cannot be children of Stories)

### Required Link Types

The system automatically detects available link types in your JIRA instance. Common link types used:
- **Work item split** (inward: "split from", outward: "split to") - for story-task relationships
- **Blocks** (inward: "is blocked by", outward: "blocks") - for task dependencies  
- **Relates** (inward: "relates to", outward: "relates to") - fallback for general relationships

For detailed information about ticket linking, see [Technical Documentation](docs/technical/TECHNICAL.md#ticket-linking-strategy).

## Documentation

Comprehensive documentation is available in the [`docs/`](docs/) directory:

### Quick Links
- [Documentation Index](docs/README.md) - Complete documentation index
- [API Documentation](docs/api/API_DOCUMENTATION.md) - Complete API reference
- [Contributing Guide](CONTRIBUTING.md) - How to contribute to the project

### Documentation Categories
- **[API Documentation](docs/api/)** - API setup, authentication, and reference
- **[Features](docs/features/)** - Feature documentation and enhancements
- **[Guides](docs/guides/)** - Step-by-step guides and how-tos
- **[Templates](docs/templates/)** - PRD and RFC templates
- **[Technical](docs/technical/)** - Technical deep-dives and implementation details

### PRD/RFC Templates

To ensure optimal extraction, structure your PRD/RFC documents using the provided templates:
- [PRD Template](docs/templates/sample-prd-template.md) - Product Requirements Document template
- [RFC Template](docs/templates/sample-rfc-template.md) - Request for Comments template

## LLM Configuration

### Supported Providers

| Provider | Models Available | API Key Required |
|----------|------------------|------------------|
| **OpenAI** | o1, o3, o3-mini, o4-mini, gpt-5, gpt-5-mini, gpt-5-turbo, gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-4 | `OPENAI_API_KEY` |
| **Anthropic (Claude)** | claude-haiku-4-5, claude-opus-4-1, claude-opus-4-0, claude-sonnet-4-0, claude-3-7-sonnet-latest, claude-3-5-sonnet-latest, claude-3-5-haiku-latest | `ANTHROPIC_API_KEY` |
| **Google (Gemini)** | gemini-2.5-pro, gemini-2.5-flash, gemini-2.5-flash-lite, gemini-2.0-flash, gemini-2.0-flash-lite | `GOOGLE_API_KEY` |
| **Moonshot AI (KIMI)** | moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k, moonshot-v1-auto, kimi-latest, kimi-k2-thinking, kimi-k2-thinking-turbo, kimi-k2-turbo-preview | `MOONSHOT_API_KEY` |

### Model Selection

All API endpoints support optional `llm_provider` and `llm_model` parameters:

```bash
# Check available models
curl http://localhost:8000/models

# Use specific model
curl -X POST "http://localhost:8000/generate/single" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123",
    "llm_provider": "openai",
    "llm_model": "gpt-5-mini",
    "update_jira": false
  }'
```

For detailed model selection guide, see [API Documentation](docs/api/API_DOCUMENTATION.md#model-selection).

## Background Job Processing

Augment supports asynchronous background processing for all generation endpoints using ARQ (async Redis queue). This enables long-running operations to be processed without blocking the API, making it ideal for batch operations and large-scale processing.

### Key Features

- **Real-Time Job Tracking**: Monitor job progress in real-time via `GET /jobs/{job_id}`
- **Ticket-Based Queries**: Query job status by ticket key via `GET /jobs/ticket/{ticket_key}` for easy integration
- **Duplicate Prevention**: Automatically rejects duplicate requests for tickets already being processed
- **Job Cancellation**: Cancel running jobs via API when needed
- **Job Persistence**: Jobs survive server restarts (stored in Redis)
- **Multiple Job Types**: Supports batch processing, single ticket generation, story generation, task generation, and test generation

### Usage

**Start Background Worker:**
```bash
# In a separate terminal
python run_worker.py
```

**Worker Configuration:**
The worker can be configured via `config.yaml` or environment variables:
- `max_jobs`: Maximum concurrent jobs per worker (default: 10)
- `job_timeout`: Job timeout in seconds (default: 3600)
- `keep_result`: How long to keep job results in Redis in seconds (default: 3600)

You can run multiple worker instances for increased throughput. Each worker instance will process jobs independently from the shared Redis queue. The total concurrent job capacity is `max_jobs × number_of_workers`.

**Use Async Mode:**
```bash
# Single ticket generation (async)
curl -X POST "http://localhost:8000/generate/single" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123",
    "async_mode": true,
    "update_jira": false
  }'

# Returns: {"job_id": "...", "status": "started", "status_url": "/jobs/..."}

# Check job status by job ID
curl "http://localhost:8000/jobs/{job_id}"

# Check job status by ticket key
curl "http://localhost:8000/jobs/ticket/PROJ-123"

# Cancel job
curl -X DELETE "http://localhost:8000/jobs/{job_id}"
```

**Supported Endpoints with Async Mode:**
- `POST /generate/single` - Single ticket generation
- `POST /generate/batch` - Batch processing (always async)
- `POST /plan/stories/generate` - Story generation
- `POST /plan/stories/sync-from-prd` - PRD story sync
- `POST /plan/tasks/generate` - Task generation
- `POST /plan/tests/comprehensive` - Comprehensive test generation
- `POST /plan/epic/create` - Epic planning and ticket creation
- `POST /plan/stories/create` - Story creation for epic
- `POST /plan/tasks/create` - Task creation for stories
- `POST /sprint/plan/epic` - Sprint planning
- `POST /sprint/timeline` - Timeline creation
- `POST /jira/bulk-update-stories` - Bulk story updates

For more details, see [Background Jobs Documentation](docs/api/API_DOCUMENTATION.md#background-job-processing).

## Troubleshooting

### Common Issues

1. **"Import could not be resolved" errors**
   - Run `pip install -r requirements.txt` in your virtual environment

2. **Jira connection fails**
   - Check your server URL (don't include `/rest/api`)
   - Verify your API token is correct
   - Ensure your user has necessary permissions

3. **Custom field not found**
   - Verify the custom field ID in Jira admin
   - Check field permissions and context

4. **JIRA hierarchy errors**
   - Tasks are now created under epics (not stories) to comply with JIRA hierarchy rules
   - Story-task relationships are created via "Work item split" links

5. **Bitbucket connection fails (401 Unauthorized)**
   - Verify you're using an Atlassian API token (same type as Jira/Confluence)
   - Ensure you're using your Atlassian account email, not Bitbucket username
   - Create API token at: https://id.atlassian.com/manage-profile/security/api-tokens

6. **Confluence connection fails (404 Not Found)**
   - Ensure server URL includes `/wiki` suffix: `https://your-domain.atlassian.net/wiki`
   - Verify you have access to Confluence in your Atlassian account

7. **LLM rate limits**
   - Reduce `MAX_CONCURRENT_REQUESTS` in config
   - Add delays between requests if needed

8. **Redis connection fails**
   - Verify Redis is running: `redis-cli ping` (should return `PONG`)
   - Check `REDIS_HOST` and `REDIS_PORT` in `.env`
   - Ensure Redis is accessible from your API server

9. **Background jobs not processing**
   - Ensure `run_worker.py` is running in a separate terminal
   - Check worker logs for errors
   - Verify Redis connection from worker process
   - Check worker configuration: `max_jobs`, `job_timeout`, and `keep_result` settings

10. **Jobs processing slowly or timing out**
   - Increase `WORKER_MAX_JOBS` to allow more concurrent jobs per worker
   - Increase `WORKER_JOB_TIMEOUT` if jobs are timing out before completion
   - Run multiple worker instances for increased throughput
   - Check Redis performance and connection

10. **Duplicate request rejected (409 Conflict)**
    - This is expected behavior - the ticket is already being processed
    - Check the existing job status using `GET /jobs/ticket/{ticket_key}`
    - Wait for the existing job to complete before retrying
    - Use the `X-Active-Job-Id` header from the error response to track the existing job

11. **Task dependencies not resolving correctly**
    - The system uses stable task_id (UUID) for dependency resolution
    - Dependencies are automatically converted from summary to task_id during generation
    - If dependencies fail, check logs for dependency resolution attempts
    - Ensure all tasks in a batch are created together for proper dependency mapping
    - The system supports both task_id and summary-based dependencies (backward compatible)

### Debug Mode

Enable verbose logging for troubleshooting:

```bash
python main.py -v test
python main.py -v single PROJ-123
```

### Success Indicators

When everything is working correctly, `python main.py test` should show:
```
Jira connection successful
Bitbucket connection successful  
Confluence connection successful
LLM connection successful
All configured services are working!
```

## Project Structure

```
augment/
├── src/                    # Source code
│   ├── jira_client.py     # Jira API client (includes sprint API methods)
│   ├── bitbucket_client.py # Bitbucket API client
│   ├── confluence_client.py # Confluence API client
│   ├── llm_client.py      # LLM provider abstraction
│   ├── generator.py        # Main generation logic
│   ├── planning_service.py # Planning orchestration
│   ├── sprint_planning_service.py # Sprint planning logic
│   ├── team_member_db.py  # Team member database setup
│   ├── team_member_service.py # Team member CRUD operations
│   └── prompts/           # Prompt templates
├── api/                   # API server code
│   ├── routes/           # API endpoints
│   │   ├── sprint_planning.py # Sprint planning endpoints
│   │   └── team_members.py # Team management endpoints
│   ├── models/           # Request/response models
│   │   ├── sprint_planning.py # Sprint planning models
│   │   └── team_members.py # Team member models
│   └── main.py          # FastAPI application
├── data/                  # Data directory (auto-created, gitignored)
│   └── team_members.db  # SQLite database for team members (auto-created on first use)
├── docs/                  # Documentation
│   ├── api/             # API documentation
│   ├── features/        # Feature documentation
│   ├── guides/          # How-to guides
│   ├── templates/       # PRD/RFC templates
│   ├── technical/       # Technical docs
├── tests/                # Test files
│   └── test_sprint_planning.py # Sprint planning tests
├── config.yaml          # Configuration file
├── requirements.txt     # Python dependencies
├── .env.example        # Environment variables template
└── README.md           # This file
```

## Contributing

We welcome contributions from the community! Whether you're fixing bugs, adding features, or improving documentation, your help makes Augment better for everyone.

Please read our [Contributing Guidelines](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_sprint_planning.py

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src --cov=api
```

**Test Coverage:**
- Sprint planning service tests
- JIRA sprint API method tests
- Team member service tests
- Dependency-aware task assignment tests
- Topological sort algorithm tests

### Quick Contribution Steps

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Add tests if applicable
5. Ensure all tests pass (`pytest`)
6. Commit your changes (`git commit -m 'Add some amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## License

This project is licensed under the O'Saasy License - see the [LICENSE](LICENSE.md) file for details.
