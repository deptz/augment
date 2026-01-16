# Augment REST API - Complete Guide

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Setup & Installation](#setup--installation)
4. [Authentication](#authentication)
5. [LLM Model Selection](#llm-model-selection)
6. [Background Job Processing](#background-job-processing)
7. [OpenCode Integration](#opencode-integration)
8. [API Endpoints](#api-endpoints)
9. [Usage Examples](#usage-examples)
10. [Troubleshooting](#troubleshooting)
11. [Production Deployment](#production-deployment)

---

## Overview

This REST API provides programmatic access to Augment, allowing you to:

- Generate descriptions for single tickets
- Process multiple tickets via JQL queries (batch processing)
- Generate team-based tasks (Backend/Frontend/QA) for stories
- Generate contextual tasks using epic information
- Generate comprehensive test cases for stories, tasks, and entire epics
- **Create Draft PRs from stories** with complete PLAN → APPROVAL → APPLY → VERIFY → PACKAGE → DRAFT_PR pipeline
- Choose custom LLM providers and models (OpenAI, Anthropic, Google Gemini, Moonshot AI)
- Extract context from both PRD (Product Requirements Documents) and RFC (Request for Comments) documents
- Choose between read-only mode (preview) or update mode (write to JIRA)
- Monitor job progress for long-running batch operations

### Key Features

- **Enhanced Task Generation Response**: Comprehensive task details including descriptions, dependencies, and estimates
- **Team Assignment**: Backend, Frontend, QA, DevOps, or Fullstack team assignment
- **Dependencies**: Task dependencies and team blocking relationships
- **Test Cases**: AI-generated test cases for each task with context-aware scenarios
- **Summary Statistics**: Total tasks, estimated effort, and planning metrics

### Document Type Support

**Product Requirements Documents (PRDs)**
- Purpose: Business requirements, user stories, feature specifications
- Key Sections: Target population, user problems, business value, proposed solutions

**Request for Comments (RFCs)**
- Purpose: Technical design documents, architecture specifications, implementation plans
- Key Sections: Overview, Technical Design, Security & Performance, Rollout, Concerns

---

## Quick Start

### Safety First

**IMPORTANT**: The API operates in **PREVIEW MODE** by default to prevent accidental JIRA updates. You must explicitly set `update_jira: true` to actually update JIRA tickets.

### 1. Start the API Server

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
python api_server.py
```

The API will be available at:
- **API Base URL**: http://localhost:8000
- **Interactive Docs**: http://localhost:8000/docs (Swagger UI)
- **Alternative Docs**: http://localhost:8000/redoc

### 2. Test a Single Ticket (Preview Mode)

```bash
curl -X POST "http://localhost:8000/generate/single" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123"
  }'
```

This will show you what description would be generated **without updating JIRA**.

### 3. Actually Update a Single Ticket

```bash
curl -X POST "http://localhost:8000/generate/single" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123",
    "update_jira": true
  }'
```

### 4. Check Available Models

```bash
curl http://localhost:8000/models
```

### 5. Interactive Documentation

Visit http://localhost:8000/docs for the interactive Swagger UI where you can test all endpoints directly in your browser.

---

## Setup & Installation

### Prerequisites

- Python 3.10+
- Valid `config.yaml` file with JIRA/LLM credentials
- All dependencies from `requirements.txt`
- **Redis** (required for background job processing) - Can be external or local instance

### Option 1: Local Development

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Start Redis:**
   ```bash
   # Using Docker
   docker run -d -p 6379:6379 redis:latest
   
   # Or use external Redis instance
   # Configure REDIS_HOST, REDIS_PORT in .env
   ```

3. **Start the API server:**
   ```bash
   ./start_api.sh
   # Or: python api_server.py
   ```

4. **Start the background worker (in separate terminal):**
   ```bash
   python run_worker.py
   ```

5. **Access the API:**
   - API: http://localhost:8000
   - Interactive Docs: http://localhost:8000/docs
   - Alternative Docs: http://localhost:8000/redoc

### Option 2: Docker

1. **Build and run with Docker Compose:**
   ```bash
   docker-compose up --build
   ```

2. **Or build manually:**
   ```bash
   docker build -t augment-api .
   docker run -p 8000:8000 -v $(pwd)/config.yaml:/app/config.yaml:ro augment-api
   ```

### Document Type Configuration

Configure the JIRA custom fields that contain PRD/RFC document URLs:

```yaml
# config.yaml
jira:
  prd_custom_field: customfield_10001  # Replace with your actual field ID
  rfc_custom_field: customfield_10002  # Replace with your actual field ID
```

```bash
# .env
JIRA_PRD_CUSTOM_FIELD=customfield_10001
JIRA_RFC_CUSTOM_FIELD=customfield_10002
```

### Finding Your Custom Field IDs

1. **Via JIRA UI:**
   - Go to JIRA Administration → Issues → Custom Fields
   - Find your PRD/RFC fields and note their IDs (e.g., `customfield_10001`)

2. **Via JIRA REST API:**
   ```bash
   curl -X GET "https://your-jira-instance.atlassian.net/rest/api/3/field" \
     -H "Authorization: Basic <base64-encoded-email:token>" \
     | jq '.[] | select(.name | contains("PRD") or contains("RFC")) | {id, name}'
   ```

### CORS Configuration

The API supports configurable Cross-Origin Resource Sharing (CORS) settings to control which origins can access the API.

**Configuration Options:**

1. **Via Environment Variable:**
   ```bash
   # .env
   CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000,https://example.com
   ```

2. **Via config.yaml:**
   ```yaml
   cors:
     allowed_origins: ${CORS_ALLOWED_ORIGINS:http://localhost:5173,http://localhost:3000}
   ```
   
   Or as a YAML list:
   ```yaml
   cors:
     allowed_origins:
       - http://localhost:5173
       - http://localhost:3000
       - https://example.com
   ```

**Default Behavior:**
- If `CORS_ALLOWED_ORIGINS` is not configured, the API defaults to allowing common localhost ports (5173, 3000, and others) for development
- In development mode (`ENVIRONMENT=development`), all origins are allowed (`allow_origins=["*"]`)
- In production mode (`ENVIRONMENT=production`), only configured origins are allowed

**Format:**
- Comma-separated string: `http://localhost:5173,http://localhost:3000`
- YAML list: `- http://localhost:5173`

**Best Practices:**
- In production, explicitly configure allowed origins for security
- Use environment variables for sensitive or environment-specific origins
- Include both `http://localhost` and `http://127.0.0.1` variants if needed
- Always use HTTPS for production origins

---

## Authentication

The API supports optional HTTP Basic Authentication to secure access to all endpoints except health checks.

### Quick Setup

1. **Generate a password hash:**
   ```bash
   python generate_password_hash.py
   ```

2. **Set environment variables:**
   ```bash
   export AUTH_ENABLED=true
   export AUTH_USERNAME=admin
   export AUTH_PASSWORD_HASH=your_generated_hash_here
   ```

3. **Restart the API server:**
   ```bash
   python api_server.py
   ```

### Configuration Reference

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `AUTH_ENABLED` | Enable/disable authentication | `false` | No |
| `AUTH_USERNAME` | Username for authentication | `admin` | Yes (if enabled) |
| `AUTH_PASSWORD_HASH` | SHA-256 hash of password | - | Yes (if enabled) |

### Usage Examples

#### Using curl
```bash
curl -u username:password "http://localhost:8000/generate/single" \
  -H "Content-Type: application/json" \
  -d '{"ticket_key": "PROJ-123"}'
```

#### Using Python requests
```python
import requests
from requests.auth import HTTPBasicAuth

response = requests.post(
    "http://localhost:8000/generate/single",
    json={"ticket_key": "PROJ-123"},
    auth=HTTPBasicAuth("admin", "your_password")
)
```

#### Using Swagger UI
1. Visit `http://localhost:8000/docs`
2. Click the "Authorize" button
3. Enter your username and password
4. Click "Authorize"

### Public Endpoints (No Authentication Required)

Even when authentication is enabled, these endpoints remain publicly accessible:
- `GET /` - Basic health check
- `GET /health` - Comprehensive health check
- `GET /docs` - Swagger UI documentation
- `GET /redoc` - ReDoc documentation

### Security Best Practices

1. **Use Strong Passwords**: Choose complex passwords with mixed case, numbers, and symbols
2. **Secure Hash Storage**: Store password hashes in environment variables, not in config files
3. **HTTPS in Production**: Always use HTTPS in production environments
4. **Regular Rotation**: Rotate passwords periodically

---

## LLM Model Selection

The API supports dynamic LLM model selection, allowing you to choose different models and providers for each request.

### Supported Providers and Models

| Provider | Models Available | API Key Required |
|----------|------------------|------------------|
| **OpenAI** | o1, o3, o3-mini, o4-mini, gpt-5, gpt-5-mini, gpt-5-turbo, gpt-4.1, gpt-4.1-mini, gpt-4.1-nano, gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-4 | `OPENAI_API_KEY` |
| **Anthropic (Claude)** | claude-haiku-4-5, claude-sonnet-4-5, claude-opus-4-1, claude-opus-4-0, claude-sonnet-4-0, claude-3-7-sonnet-latest, claude-3-5-sonnet-latest, claude-3-5-haiku-latest | `ANTHROPIC_API_KEY` |
| **Google (Gemini)** | gemini-2.5-pro, gemini-2.5-flash, gemini-2.5-flash-lite, gemini-2.0-flash, gemini-2.0-flash-lite | `GOOGLE_API_KEY` |
| **Moonshot AI (KIMI)** | moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k, moonshot-v1-auto, kimi-latest, kimi-k2-thinking, kimi-k2-thinking-turbo, kimi-k2-turbo-preview | `MOONSHOT_API_KEY` |

### Model Selection Rules

1. **Explicit Parameters**: If both `llm_provider` and `llm_model` are provided, they are used
2. **Provider Only**: If only `llm_provider` is specified, the default model for that provider is used
3. **Model Only**: If only `llm_model` is specified, the provider is inferred from the model name
4. **Defaults**: If neither is specified, the configured default provider and model are used
5. **Validation**: Invalid provider/model combinations return a 422 validation error

### Usage Examples

```bash
# Use specific OpenAI model
curl -X POST "http://localhost:8000/generate/single" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123",
    "llm_provider": "openai",
    "llm_model": "gpt-5-mini",
    "update_jira": false
  }'

# Use Claude for better reasoning
curl -X POST "http://localhost:8000/generate/single" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123",
    "llm_provider": "claude",
    "llm_model": "claude-sonnet-4-5",
    "update_jira": false
  }'
```

### Best Practices

**Complex Technical Documentation:**
- Use `o1` or `o3` for advanced reasoning
- Use `claude-opus-4-1` for sophisticated analysis
- Use `gpt-5` for advanced text generation

**High-Volume Batch Processing:**
- Use `gpt-5-mini` for efficient processing
- Use `claude-3-5-haiku-latest` for fast Claude processing
- Use `gpt-4o-mini` for cost efficiency

---

## API Endpoints

### Health & Status

#### `GET /`
Basic health check

**Response:**
```json
{
  "message": "Augment API",
  "status": "healthy",
  "version": "1.0.0"
}
```

#### `GET /health`
Detailed health check with service status including database readiness

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-15T10:30:00",
  "services": {
    "team_member_db": "ready",
    "jira": "connected",
    "bitbucket": "connected", 
    "confluence": "connected",
    "llm": "connected"
  }
}
```

**Service Status Values:**
- `team_member_db`: `"ready"` if database is accessible and properly initialized, or error message if not
- Other services: `"connected"` if healthy, or error message if not
- Overall `status`: `"healthy"` if all services are ready, `"degraded"` if some services have issues

#### `GET /models`
Get supported LLM providers and models

**Response:**
```json
{
  "providers": ["openai", "claude", "gemini", "kimi"],
  "models": {
    "openai": ["o1", "o3", "gpt-5", "gpt-5-mini", ...],
    "claude": ["claude-sonnet-4-5", "claude-opus-4-1", ...],
    "gemini": ["gemini-2.5-pro", "gemini-2.5-flash", ...],
    "kimi": ["moonshot-v1-8k", "kimi-latest", ...]
  },
  "default_provider": "openai"
}
```

### Single Ticket Processing

#### `POST /generate/single`
Generate description for a single ticket

**SAFETY FIRST**: By default operates in PREVIEW MODE (no JIRA updates). Must explicitly set `update_jira: true` to update JIRA.

**Request Body:**
```json
{
  "ticket_key": "PROJ-123",
  "update_jira": false,
  "llm_provider": "openai",
  "llm_model": "gpt-5-mini"
}
```

**Response:**
```json
{
  "ticket_key": "PROJ-123",
  "summary": "Implement user authentication",
  "generated_description": "## Purpose\n\nThis task implements...",
  "success": true,
  "llm_provider": "openai",
  "llm_model": "gpt-5-mini",
  "updated_in_jira": false
}
```

### Batch Processing

#### `POST /generate/batch`

**Note**: Batch processing always runs asynchronously and returns a job_id immediately.
Process multiple tickets based on JQL query (asynchronous)

**SAFETY FIRST**: By default operates in PREVIEW MODE (no JIRA updates). Must explicitly set `update_jira: true` to update JIRA.

**Request Body:**
```json
{
  "jql": "project = PROJ AND description is EMPTY",
  "max_results": 50,
  "update_jira": false,
  "llm_provider": "openai",
  "llm_model": "gpt-5-mini"
}
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "started",
  "message": "Batch processing started in PREVIEW mode",
  "status_url": "/jobs/550e8400-e29b-41d4-a716-446655440000"
}
```

## Background Job Processing

All generation endpoints support asynchronous background processing using ARQ (async Redis queue). This allows long-running operations to be processed without blocking the API.

### Features

- **Job Tracking**: Monitor job progress in real-time via `/jobs/{job_id}`
- **Ticket-Based Status**: Query job status by ticket key via `GET /jobs/ticket/{ticket_key}`
- **Duplicate Prevention**: Automatically rejects duplicate requests for tickets already being processed
- **Job Cancellation**: Cancel running jobs via `DELETE /jobs/{job_id}`
- **Job Persistence**: Jobs survive server restarts (stored in Redis)
- **Multiple Job Types**: Supports batch, single, story generation, task generation, and test generation
- **Backward Compatible**: All endpoints default to synchronous mode (`async_mode: false`)

### Setup

1. **Configure Redis:**
   ```bash
   # .env
   REDIS_HOST=localhost
   REDIS_PORT=6379
   REDIS_PASSWORD=
   REDIS_DB=0
   ```

2. **Start Background Worker:**
   ```bash
   # In a separate terminal
   python run_worker.py
   ```

3. **Configure Worker Settings (Optional):**
   
   Worker configuration can be set in `config.yaml` or via environment variables:
   
   ```yaml
   # config.yaml
   worker:
     max_jobs: 10  # Maximum concurrent jobs per worker
     job_timeout: 3600  # Job timeout in seconds (1 hour)
     keep_result: 3600  # How long to keep job results in Redis (1 hour)
   ```
   
   Or via environment variables:
   ```bash
   WORKER_MAX_JOBS=10
   WORKER_JOB_TIMEOUT=3600
   WORKER_KEEP_RESULT=3600
   ```
   
   **Multiple Workers:**
   You can run multiple worker instances for increased throughput. Each worker processes jobs independently from the shared Redis queue. Total concurrent capacity = `max_jobs × number_of_workers`.

### Supported Endpoints

All these endpoints support `async_mode: true` parameter:

- `POST /generate/single` - Single ticket generation
- `POST /generate/batch` - Batch processing (always async)
- `POST /plan/stories/generate` - Story generation
- `POST /plan/stories/sync-from-prd` - Sync story tickets from PRD table
- `POST /plan/tasks/generate` - Task generation
- `POST /plan/epic/create` - Epic planning and ticket creation
- `POST /plan/stories/create` - Story creation for epic
- `POST /plan/tasks/create` - Task creation for stories
- `POST /plan/tests/comprehensive` - Comprehensive test generation
- `POST /sprint/plan/epic` - Sprint planning for epic tasks
- `POST /sprint/timeline` - Timeline schedule creation

### Usage Examples

#### Async Single Ticket Generation

```bash
# Request with async_mode
curl -X POST "http://localhost:8000/generate/single" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123",
    "async_mode": true,
    "update_jira": false
  }'

# Response
{
  "job_id": "abc-123-def-456",
  "status": "started",
  "message": "Ticket PROJ-123 queued for processing",
  "status_url": "/jobs/abc-123-def-456",
  "jql": "",
  "max_results": 1,
  "update_jira": false,
  "safety_note": "JIRA will only be updated if update_jira is explicitly set to true"
}
```

#### Check Job Status

```bash
curl "http://localhost:8000/jobs/abc-123-def-456"

# Response
{
  "job_id": "abc-123-def-456",
  "job_type": "single",
  "status": "completed",
  "progress": {
    "message": "Completed successfully"
  },
  "results": {
    "ticket_key": "PROJ-123",
    "summary": "Ticket Summary",
    "generated_description": "...",
    "success": true
  },
  "started_at": "2025-01-15T10:00:00",
  "completed_at": "2025-01-15T10:00:05",
  "successful_tickets": 1,
  "failed_tickets": 0
}
```

#### List All Jobs

```bash
# List all jobs
curl "http://localhost:8000/jobs"

# Filter by status
curl "http://localhost:8000/jobs?status=completed"

# Filter by job type
curl "http://localhost:8000/jobs?job_type=single"

# Combined filters
curl "http://localhost:8000/jobs?status=processing&job_type=story_generation"
```

#### Get Job Status by Ticket Key

```bash
# Get current job status for a specific ticket
curl "http://localhost:8000/jobs/ticket/PROJ-123"

# Response (if active job exists)
{
  "job_id": "abc-123-def-456",
  "job_type": "single",
  "status": "started",
  "ticket_key": "PROJ-123",
  "progress": {
    "message": "Processing ticket PROJ-123..."
  },
  "started_at": "2025-01-15T10:00:00",
  "processed_tickets": 0,
  "successful_tickets": 0,
  "failed_tickets": 0
}

# Response (if no active job, returns latest completed job)
{
  "job_id": "abc-123-def-456",
  "job_type": "single",
  "status": "completed",
  "ticket_key": "PROJ-123",
  "progress": {
    "message": "Completed successfully"
  },
  "results": {
    "ticket_key": "PROJ-123",
    "success": true
  },
  "started_at": "2025-01-15T10:00:00",
  "completed_at": "2025-01-15T10:00:05",
  "successful_tickets": 1,
  "failed_tickets": 0
}

# Response (if no job found)
{
  "detail": "No job found for ticket key: PROJ-123"
}
```

**Use Cases:**
- Status pages that display processing status for specific tickets
- Monitoring tools that track tickets rather than jobs
- Integration with ticket management systems
- Checking if a ticket is currently being processed before submitting a new request

#### Cancel a Job

```bash
curl -X DELETE "http://localhost:8000/jobs/abc-123-def-456"

# Response
{
  "message": "Job abc-123-def-456 cancelled successfully",
  "status": "cancelled"
}
```

### Duplicate Prevention

The system automatically prevents duplicate processing of the same ticket when it's actively being processed. This feature applies to:

- **Single Ticket Generation**: Prevents processing the same ticket concurrently
- **Batch Processing**: Skips tickets that are already being processed in other jobs
- **Story Generation**: Prevents generating stories for the same epic concurrently
- **Task Generation**: Prevents generating tasks for the same story concurrently

**How It Works:**

1. When you submit a job request, the system checks if the ticket(s) are already being processed
2. If an active job exists (status: `started` or `processing`), the request is rejected with a `409 Conflict` response
3. The response includes the existing job ID in the `X-Active-Job-Id` header
4. Once a job completes, fails, or is cancelled, the ticket can be reprocessed

**Example - Duplicate Request:**

```bash
# First request (succeeds)
curl -X POST "http://localhost:8000/generate/single" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123",
    "async_mode": true
  }'

# Response
{
  "job_id": "job-1",
  "status": "started",
  "message": "Ticket PROJ-123 queued for processing"
}

# Second request for same ticket (rejected)
curl -X POST "http://localhost:8000/generate/single" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123",
    "async_mode": true
  }'

# Response (409 Conflict)
{
  "detail": "Ticket PROJ-123 is already being processed in job job-1"
}

# Headers
X-Active-Job-Id: job-1
X-Active-Job-Status-Url: /jobs/job-1
```

**Batch Processing Behavior:**

In batch processing, if some tickets are already being processed:
- The batch job will still be created
- Duplicate tickets will be skipped with an error message
- Other tickets in the batch will be processed normally
- The batch job results will indicate which tickets were skipped and why

**Best Practices:**

1. **Check Status First**: Use `GET /jobs/ticket/{ticket_key}` to check if a ticket is already being processed
2. **Handle 409 Responses**: In your application, handle `409 Conflict` responses gracefully
3. **Use Existing Job ID**: When you receive a 409, use the provided job ID to track the existing job
4. **Retry After Completion**: Wait for the existing job to complete before retrying

### Job Status Values

- `started`: Job has been queued
- `processing`: Job is currently running
- `completed`: Job finished successfully
- `failed`: Job encountered an error
- `cancelled`: Job was cancelled

### Job Types

- `batch`: Batch ticket processing
- `single`: Single ticket generation
- `story_generation`: Story generation for epics
- `prd_story_sync`: PRD story sync operations
- `task_generation`: Task generation for stories
- `test_generation`: Test case generation
- `sprint_planning`: Sprint planning for epic tasks
- `timeline_planning`: Timeline schedule creation
- `draft_pr`: Draft PR orchestrator jobs

### Job Results Format

Results format depends on job type:

**Single Ticket (`single`):**
```json
{
  "ticket_key": "PROJ-123",
  "summary": "...",
  "generated_description": "...",
  "success": true
}
```

**Batch Processing (`batch`):**
```json
[
  {"ticket_key": "PROJ-123", "success": true, ...},
  {"ticket_key": "PROJ-124", "success": true, ...}
]
```

**Story/Task Generation (`story_generation`, `task_generation`):**
```json
{
  "epic_key": "EPIC-100",
  "success": true,
  "created_tickets": ["STORY-1", "STORY-2"],
  "story_details": [...],
  "task_details": [...]
}
```

**Bulk Creation (`epic_creation`, `story_creation`, `task_creation`):**
```json
{
  "epic_key": "EPIC-100",
  "success": true,
  "creation_results": {
    "created_tickets": {
      "stories": ["STORY-1", "STORY-2"],
      "tasks": ["TASK-1", "TASK-2", "TASK-3"]
    },
    "success": true
  },
  "planning_results": {...}
}
```

**Test Generation (`test_generation`):**
```json
{
  "success": true,
  "total_test_cases": 15,
  "story_tests": {...},
  "task_tests": {...}
}
```

### Best Practices

1. **Use Async for Long Operations**: Use `async_mode: true` for operations that may take more than a few seconds
2. **Poll Job Status**: Check job status periodically using `/jobs/{job_id}`
3. **Handle Failures**: Check `status` and `error` fields for failed jobs
4. **Cancel When Needed**: Use `DELETE /jobs/{job_id}` to cancel stuck or unwanted jobs
5. **Monitor Worker**: Ensure `run_worker.py` is running for async jobs to be processed

---

## OpenCode Integration

OpenCode enables **code-aware LLM generation** by giving the AI direct access to your repository contents. When enabled, the system clones your repositories to a temporary workspace and runs OpenCode in a Docker container with filesystem access, allowing it to analyze actual code structure, patterns, and implementations.

### When to Use OpenCode

Use OpenCode when you want AI-generated content that:
- References **actual file paths** and code structure
- Understands **existing patterns** in your codebase
- Identifies **impacted files** for changes
- Creates **implementation-specific** task breakdowns
- Performs **code-aware coverage analysis**

### Prerequisites

1. **Docker**: Must be installed and running
2. **Git credentials**: For cloning private repositories
3. **Enable OpenCode**: Set `OPENCODE_ENABLED=true` in configuration

### Configuration

```bash
# Enable OpenCode
OPENCODE_ENABLED=true

# Docker image (uses default if not specified)
OPENCODE_DOCKER_IMAGE=ghcr.io/anomalyco/opencode

# Concurrency and limits
OPENCODE_MAX_CONCURRENT=2    # Max concurrent containers
OPENCODE_MAX_REPOS=5         # Max repositories per job
OPENCODE_TIMEOUT=20          # Job timeout in minutes
OPENCODE_CLONE_TIMEOUT=300   # Git clone timeout in seconds
OPENCODE_SHALLOW_CLONE=true  # Use shallow clone

# Git credentials for private repositories
GIT_USERNAME=your-git-username
GIT_PASSWORD=your-git-token
```

### Supported Endpoints

The `repos` parameter can be added to these endpoints:

| Endpoint | Description |
|----------|-------------|
| `POST /generate/single` | Code-aware ticket description generation |
| `POST /plan/tasks/generate` | Code-aware task breakdown |
| `POST /analyze/story-coverage` | Code-aware coverage analysis |

### Usage Examples

#### Single Ticket with Code Analysis

```bash
curl -X POST "http://localhost:8000/generate/single" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123",
    "async_mode": true,
    "repos": [
      "https://github.com/org/backend-api.git",
      {"url": "https://github.com/org/frontend.git", "branch": "develop"}
    ]
  }'
```

#### Task Generation with Code Context

```bash
curl -X POST "http://localhost:8000/plan/tasks/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "story_keys": ["STORY-456", "STORY-457"],
    "async_mode": true,
    "repos": [
      {"url": "https://bitbucket.org/company/api.git", "branch": "main"}
    ]
  }'
```

#### Coverage Analysis with Code Inspection

```bash
curl -X POST "http://localhost:8000/analyze/story-coverage" \
  -H "Content-Type: application/json" \
  -d '{
    "story_key": "STORY-789",
    "async_mode": true,
    "repos": ["https://github.com/org/monorepo.git"],
    "additional_context": "Focus on the auth module"
  }'
```

### Repository Specification

The `repos` parameter accepts an array of repository specifications:

**String format** (simple):
```json
"repos": ["https://github.com/org/repo.git"]
```

**Object format** (with branch):
```json
"repos": [
  {"url": "https://github.com/org/repo.git", "branch": "develop"}
]
```

**Mixed format**:
```json
"repos": [
  "https://github.com/org/repo1.git",
  {"url": "https://github.com/org/repo2.git", "branch": "feature/xyz"}
]
```

### Response Enhancements

When OpenCode is used, responses include additional metadata:

#### Ticket Description Response
```json
{
  "ticket_key": "PROJ-123",
  "generated_description": "...",
  "success": true,
  "llm_provider": "opencode",
  "opencode_metadata": {
    "impacted_files": ["src/api/users.py", "tests/test_users.py"],
    "components": ["backend", "api"],
    "acceptance_criteria": ["AC1", "AC2"],
    "confidence": "high"
  }
}
```

#### Coverage Analysis Response
```json
{
  "story_key": "STORY-789",
  "coverage_percentage": 75.0,
  "gaps": [
    {
      "requirement": "User password reset",
      "severity": "important",
      "suggestion": "Add task for password reset email flow"
    }
  ],
  "suggestions_for_updates": [
    {
      "task_key": "TASK-1",
      "current_description": "...",
      "suggested_description": "...",
      "ready_to_submit": {...}
    }
  ],
  "suggestions_for_new_tasks": [
    {
      "summary": "Implement password reset endpoint",
      "description": "Create POST /api/auth/reset-password...",
      "gap_addressed": "User password reset",
      "ready_to_submit": {...}
    }
  ]
}
```

### Important Notes

1. **Async Mode Required**: When `repos` is provided, `async_mode` must be `true` (OpenCode execution takes 5-20 minutes)

2. **LLM Bypass**: Direct LLM calls are bypassed when using OpenCode; the container handles LLM interaction internally with full code context

3. **API Keys**: LLM API keys are automatically passed to the OpenCode container from your configuration

4. **Cancellation**: Jobs can be cancelled during execution; the system checks for cancellation at multiple points including during SSE streaming

5. **Cleanup**: Workspaces and containers are automatically cleaned up after job completion or failure

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "Docker is not available" | Ensure Docker daemon is running |
| "Image pull failed" | Check network connectivity; image is pre-pulled on worker startup |
| "Clone timeout" | Increase `OPENCODE_CLONE_TIMEOUT`; check repository access |
| "Job timeout" | Increase `OPENCODE_TIMEOUT`; reduce repository count |
| "OpenCode is not enabled" | Set `OPENCODE_ENABLED=true` in config |

---

## Draft PR Orchestrator

The Draft PR Orchestrator converts ambiguous stories into safe, code-scoped, reality-verified Draft PRs through a complete pipeline: **PLAN → APPROVAL → APPLY → VERIFY → PACKAGE → DRAFT_PR**.

### Overview

The Draft PR Orchestrator provides:

- **Structured Planning**: AI-generated plans with scope, tests, failure modes, and rollback procedures
- **Human-in-the-Loop**: Approval workflow ensures no code changes without human consent
- **Safety Guards**: Plan-apply guards verify changes match approved plans
- **Verification**: Automatic test, lint, and build execution before PR creation
- **Artifact Persistence**: All plans, diffs, logs, and PR metadata are stored for auditability
- **Plan Iteration**: Revise plans based on feedback with version comparison

### Execution Pipeline

All Draft PR jobs follow this invariant pipeline:

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

### Modes

**Normal Mode (Default)**
- Requires human approval before APPLY stage
- Approval is bound to specific plan hash
- If plan changes, approval is invalidated
- Use for production changes, shared systems, risky domains

**YOLO Mode**
- Auto-approval based on policy compliance
- Policy checks: file count, LOC delta, path restrictions, protected paths
- Falls back to normal mode if policy not compliant
- Use for low-risk changes (docs, scripts, tools)

### Prerequisites

1. **OpenCode Enabled**: Required for APPLY stage (code changes)
2. **Bitbucket Access**: Required for DRAFT_PR stage (PR creation)
3. **Git Credentials**: Required for repository cloning
4. **Redis**: Required for background job processing

### Configuration

Add to `config.yaml`:

```yaml
draft_pr:
  # YOLO Mode Policy
  yolo_policy:
    max_files: 5
    max_loc_delta: 200
    allow_paths: ["docs/**", "scripts/**", "tools/**"]
    deny_paths: ["auth/**", "billing/**", "migrations/**"]
    require_tests: false
  
  # Verification Commands
  verification:
    test_command: "pytest"
    lint_command: "ruff check"
    build_command: ""  # Optional
  
  # Protected Paths (require team approval)
  protected_paths:
    billing/**:
      require: finance_team
    auth/**:
      require: security_team
  
  # Concurrency Limits
  concurrency:
    plan: 5
    apply: 2
    verify: 3
    package: 3
    draft_pr: 3
```

### API Endpoints

#### `POST /draft-pr/create`

Create a new Draft PR job. Starts the PLAN stage.

**Request Body:**
```json
{
  "story_key": "STORY-123",
  "repos": [
    {
      "url": "https://bitbucket.org/workspace/repo.git",
      "branch": "develop"
    }
  ],
  "scope": {
    "files": ["src/api/", "tests/"]
  },
  "additional_context": "Focus on API endpoints only",
  "mode": "normal"
}
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "stage": "PLANNING",
  "status_url": "/jobs/550e8400-e29b-41d4-a716-446655440000"
}
```

**Parameters:**
- `story_key` (required): JIRA story key
- `repos` (required): List of repositories (max 5)
- `scope` (optional): File path constraints
- `additional_context` (optional): Additional context for planning
- `mode` (optional): `"normal"` or `"yolo"` (default: `"normal"`)

#### `GET /draft-pr/jobs/{job_id}`

Get job status and current pipeline stage.

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "job_type": "draft_pr",
  "status": "processing",
  "stage": "WAITING_FOR_APPROVAL",
  "progress": {
    "message": "Plan v1 generated. Waiting for approval."
  },
  "plan_versions": [
    {
      "version": 1,
      "plan_hash": "abc123...",
      "plan_spec": {
        "summary": "Add user authentication endpoint",
        "scope": {
          "files": [
            {"path": "src/api/auth.py", "change": "added"},
            {"path": "tests/test_auth.py", "change": "added"}
          ]
        },
        "happy_paths": ["User can login with valid credentials"],
        "edge_cases": ["Invalid credentials", "Expired tokens"],
        "failure_modes": [
          {
            "trigger": "Database connection failure",
            "impact": "Login fails",
            "mitigation": "Retry with exponential backoff"
          }
        ],
        "tests": [
          {"type": "unit", "target": "auth service"},
          {"type": "integration", "target": "auth API"}
        ],
        "rollback": ["Revert commit", "Remove database migrations"]
      }
    }
  ],
  "approved_plan_hash": null,
  "workspace_fingerprint": {
    "repos": [...],
    "fingerprint_hash": "def456..."
  }
}
```

**Pipeline Stages:**
- `CREATED`: Job created
- `PLANNING`: Generating plan
- `WAITING_FOR_APPROVAL`: Waiting for human approval
- `REVISING`: Generating revised plan
- `APPLYING`: Applying code changes
- `VERIFYING`: Running tests/lint/build
- `PACKAGING`: Generating PR diff and metadata
- `DRAFTING`: Creating Draft PR
- `COMPLETED`: Pipeline completed
- `FAILED`: Pipeline failed

#### `GET /draft-pr/jobs/{job_id}/plan`

Get the latest plan version.

**Response:**
```json
{
  "version": 1,
  "plan_hash": "abc123...",
  "plan_spec": {...},
  "created_at": "2025-01-15T10:00:00Z"
}
```

#### `GET /draft-pr/jobs/{job_id}/plans/{version}`

Get a specific plan version by version number.

#### `POST /draft-pr/jobs/{job_id}/revise-plan`

Submit feedback to generate a revised plan version.

**Request Body:**
```json
{
  "feedback": "The plan should also include rate limiting",
  "specific_concerns": [
    "Missing rate limiting",
    "No mention of error handling for invalid tokens"
  ],
  "requested_changes": "Add rate limiting middleware and error handling",
  "feedback_type": "addition"
}
```

**Response:**
```json
{
  "plan_version": 2,
  "plan_hash": "xyz789...",
  "changes_summary": "Added rate limiting and error handling sections"
}
```

**Note:** Cannot revise if plan is already approved.

#### `GET /draft-pr/jobs/{job_id}/plans/compare`

Compare two plan versions.

**Query Parameters:**
- `from_version`: Source version number
- `to_version`: Target version number

**Response:**
```json
{
  "from_version": 1,
  "to_version": 2,
  "changes": {
    "added": ["rate_limiting", "error_handling"],
    "modified": ["scope.files"],
    "removed": []
  },
  "summary": "Plan v2 adds rate limiting and error handling",
  "changed_sections": ["scope", "tests", "failure_modes"]
}
```

#### `POST /draft-pr/jobs/{job_id}/approve`

Approve a plan to proceed to APPLY stage.

**Request Body:**
```json
{
  "plan_hash": "abc123..."
}
```

**Response:**
```json
{
  "approved": true,
  "plan_hash": "abc123...",
  "stage": "APPLYING",
  "results": {
    "stage": "COMPLETED",
    "pr_results": {
      "pr_id": 12345,
      "pr_url": "https://bitbucket.org/workspace/repo/pull-requests/12345"
    }
  }
}
```

**Safety Checks:**
- Plan hash must match latest plan version
- Job must be in `WAITING_FOR_APPROVAL` stage
- Prevents duplicate approvals
- Re-verifies plan before approval (TOCTOU protection)

#### `GET /draft-pr/jobs/{job_id}/artifacts`

List all artifacts for a job.

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "artifacts": [
    "input_spec",
    "workspace_fingerprint",
    "plan_v1",
    "plan_v2",
    "approval",
    "git_diff",
    "validation_logs",
    "pr_metadata"
  ]
}
```

#### `GET /draft-pr/jobs/{job_id}/artifacts/{artifact_type}`

Get a specific artifact.

**Example:**
```bash
GET /draft-pr/jobs/{job_id}/artifacts/git_diff
GET /draft-pr/jobs/{job_id}/artifacts/plan_v1
GET /draft-pr/jobs/{job_id}/artifacts/validation_logs
```

### Usage Examples

#### Example 1: Create Draft PR (Normal Mode)

```bash
curl -X POST "http://localhost:8000/draft-pr/create" \
  -H "Content-Type: application/json" \
  -d '{
    "story_key": "STORY-123",
    "repos": [
      {
        "url": "https://bitbucket.org/workspace/api-repo.git",
        "branch": "develop"
      }
    ],
    "mode": "normal"
  }'
```

#### Example 2: Review and Approve Plan

```bash
# 1. Get job status
curl "http://localhost:8000/draft-pr/jobs/{job_id}"

# 2. Review latest plan
curl "http://localhost:8000/draft-pr/jobs/{job_id}/plan"

# 3. Approve plan
curl -X POST "http://localhost:8000/draft-pr/jobs/{job_id}/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "plan_hash": "abc123..."
  }'
```

#### Example 3: Revise Plan Based on Feedback

```bash
# 1. Submit feedback
curl -X POST "http://localhost:8000/draft-pr/jobs/{job_id}/revise-plan" \
  -H "Content-Type: application/json" \
  -d '{
    "feedback": "Add rate limiting to the plan",
    "specific_concerns": ["Missing rate limiting"],
    "feedback_type": "addition"
  }'

# 2. Compare versions
curl "http://localhost:8000/draft-pr/jobs/{job_id}/plans/compare?from_version=1&to_version=2"

# 3. Approve revised plan
curl -X POST "http://localhost:8000/draft-pr/jobs/{job_id}/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "plan_hash": "xyz789..."
  }'
```

#### Example 4: YOLO Mode (Auto-Approval)

```bash
curl -X POST "http://localhost:8000/draft-pr/create" \
  -H "Content-Type: application/json" \
  -d '{
    "story_key": "STORY-123",
    "repos": [
      {
        "url": "https://bitbucket.org/workspace/docs-repo.git",
        "branch": "main"
      }
    ],
    "mode": "yolo"
  }'
```

YOLO mode will auto-approve if the plan complies with policy (e.g., < 5 files, < 200 LOC, only docs/scripts paths).

### Plan Specification

Plans follow a structured format:

```json
{
  "summary": "High-level summary",
  "scope": {
    "files": [
      {"path": "src/api/auth.py", "change": "added"},
      {"path": "src/api/auth.py", "change": "modified"},
      {"path": "old_file.py", "change": "deleted"}
    ]
  },
  "happy_paths": ["User can login with valid credentials"],
  "edge_cases": ["Invalid credentials", "Expired tokens"],
  "failure_modes": [
    {
      "trigger": "Database connection failure",
      "impact": "Login fails",
      "mitigation": "Retry with exponential backoff"
    }
  ],
  "assumptions": ["Database is available", "JWT secret is configured"],
  "unknowns": ["Exact error response format"],
  "tests": [
    {"type": "unit", "target": "auth service"},
    {"type": "integration", "target": "auth API"}
  ],
  "rollback": ["Revert commit", "Remove database migrations"],
  "cross_repo_impacts": [
    {"repo": "frontend-repo", "reason": "API contract changes"}
  ]
}
```

### Safety Mechanisms

1. **Plan Hash Binding**: Approval is bound to specific plan hash
2. **Plan-Apply Guards**: Verifies changes match approved plan
3. **Git Transactions**: Atomic changes with rollback on failure
4. **Verification Gates**: PR only created if tests/lint/build pass
5. **Artifact Persistence**: All evidence stored for auditability
6. **Workspace Fingerprinting**: Reproducible workspace state

### Troubleshooting

| Issue | Solution |
|-------|----------|
| "OpenCode is not enabled" | Set `OPENCODE_ENABLED=true` in config |
| "Bitbucket client required" | Configure Bitbucket credentials in config |
| "Plan hash mismatch" | Plan was revised; approve latest version |
| "Verification failed" | Check validation logs artifact for details |
| "Branch already exists" | Use different job_id or ticket_key |
| "Workspace not found" | Workspace may have been cleaned up; restart job |

### Best Practices

1. **Review Plans Thoroughly**: Check scope, tests, and failure modes before approval
2. **Use Normal Mode for Production**: YOLO mode only for low-risk changes
3. **Iterate on Plans**: Use revise-plan to refine before approval
4. **Monitor Verification**: Check validation logs if verification fails
5. **Review Artifacts**: All artifacts are preserved for debugging

---

### Job Management Endpoints

#### `GET /jobs/ticket/{ticket_key}`

Get the current job status for a specific ticket key.

**Parameters:**
- `ticket_key` (path): The JIRA ticket key (e.g., "PROJ-123", "STORY-456")

**Response:**
- Returns active job if ticket is currently being processed (status: `started` or `processing`)
- Returns latest completed/failed job if no active job exists
- Returns `404` if no job found for the ticket key

**Example:**
```bash
curl "http://localhost:8000/jobs/ticket/PROJ-123"
```

**Supported Ticket Types:**
- Single ticket generation jobs
- Batch processing jobs (if ticket is in the batch)
- Story generation jobs (epic_key)
- Task generation jobs (story_key)
- Test generation jobs (epic_key, story_key, or task_key)

#### `GET /jobs/{job_id}`
Get status of a batch processing job

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "progress": {
    "processed": 25,
    "total": 25
  },
  "result": {
    "total_tickets": 25,
    "processed_tickets": 25,
    "successful": 20,
    "failed": 2,
    "skipped": 3
  }
}
```

### Story Sync from PRD

#### `POST /plan/stories/sync-from-prd`
Sync story tickets from PRD table to JIRA. Supports both synchronous and asynchronous processing.

**Request Body:**
```json
{
  "epic_key": "EPIC-100",
  "prd_url": "https://company.atlassian.net/wiki/spaces/PROJ/pages/123456789/PRD",
  "dry_run": true,
  "async_mode": false,
  "existing_ticket_action": "skip",
  "llm_provider": "openai",
  "llm_model": "gpt-5-mini"
}
```

**Parameters:**
- `epic_key` (optional): JIRA epic key. If provided, PRD URL will be read from epic's PRD custom field.
- `prd_url` (optional): PRD document URL. Required if epic_key is not provided.
- `dry_run` (default: true): Set to false to actually create JIRA tickets.
- `async_mode` (default: false): Run in background (async mode). If true, returns job_id for status tracking.
- `existing_ticket_action` (default: "skip"): Action when story ticket already exists:
  - `"skip"`: Don't create, log and continue
  - `"update"`: Update existing ticket description/acceptance criteria
  - `"error"`: Return error and stop processing
- `llm_provider` (optional): LLM provider to use.
- `llm_model` (optional): LLM model to use.

**Response (Synchronous):**
```json
{
  "epic_key": "EPIC-100",
  "operation_mode": "planning",
  "success": true,
  "created_tickets": {
    "stories": ["STORY-1", "STORY-2"]
  },
  "story_details": [...],
  "task_details": [],
  "execution_time_seconds": 2.5
}
```

**Response (Asynchronous):**
```json
{
  "job_id": "abc-123-def-456",
  "status": "started",
  "message": "PRD story sync for epic EPIC-100 queued",
  "status_url": "/jobs/abc-123-def-456"
}
```

**PRD Table Format:**
The endpoint expects a table in the PRD document with the following structure:
- **Section heading**: "Story Ticket List", "Story Tickets", "Story List", or similar variations
- **Table columns**: Title (or Summary/Name), Description, Acceptance Criteria
- **Column detection**: Headers are auto-detected and normalized (case-insensitive)
- **Missing columns**: Handled gracefully - title is required, description defaults to title if missing
- **Acceptance criteria parsing**: Supports Given/When/Then format, bullet points, or plain text

**PRD Table Updates:**
- **Dry Run Mode**: Generates temporary UUIDs for stories to be created and adds them as placeholders in the PRD table
- **Actual Creation**: When stories are created, the PRD table is automatically updated with clickable JIRA links
- **UUID Matching**: Uses UUID for exact row matching (eliminates need for fuzzy matching)
- **Column Creation**: Automatically creates "JIRA Ticket" column if it doesn't exist
- **Link Formatting**: Formats links as proper HTML anchor tags for Confluence compatibility
- **Update Flow**: When `existing_ticket_action="update"`, existing stories also get their PRD table rows updated

**Example:**
```bash
# Synchronous mode
curl -X POST "http://localhost:8000/plan/stories/sync-from-prd" \
  -H "Content-Type: application/json" \
  -d '{
    "epic_key": "EPIC-100",
    "dry_run": false,
    "async_mode": false,
    "existing_ticket_action": "skip"
  }'

# Asynchronous mode
curl -X POST "http://localhost:8000/plan/stories/sync-from-prd" \
  -H "Content-Type: application/json" \
  -d '{
    "epic_key": "EPIC-100",
    "dry_run": false,
    "async_mode": true,
    "existing_ticket_action": "skip"
  }'
```

### Task Generation

#### `POST /plan/tasks/generate`
Generate tasks for stories using epic context

**Request Body:**
```json
{
  "story_keys": ["STORY-123", "STORY-124"],
  "epic_key": "EPIC-100",
  "dry_run": true,
  "llm_provider": "openai",
  "llm_model": "gpt-5-mini"
}
```

**Response:** Returns comprehensive task details including descriptions, dependencies, estimates, and test cases.

#### `POST /plan/tasks/team-based`
Generate team-separated tasks (Backend/Frontend/QA) for stories

**Request Body:**
```json
{
  "story_keys": ["STORY-123"],
  "epic_key": "EPIC-100",
  "dry_run": true,
  "llm_provider": "anthropic",
  "llm_model": "claude-sonnet-4-5"
}
```

**Response:** Returns tasks organized by team with dependencies and blocking relationships.

### JIRA Operations

#### `POST /jira/update-ticket`
Update a JIRA ticket with partial updates: summary, description, test cases, mandays estimation, and issue links.

**Request Body:**
```json
{
  "ticket_key": "PROJ-123",
  "summary": "Updated summary",
  "description": "Updated description",
  "test_cases": "Test case content",
  "mandays": 3.5,
  "links": [
    {
      "link_type": "Blocks",
      "target_key": "PROJ-456",
      "direction": "outward"
    }
  ],
  "update_jira": false
}
```

**Parameters:**
- `ticket_key` (required): JIRA ticket key to update
- `summary` (optional): New ticket summary/title
- `description` (optional): New ticket description
- `test_cases` (optional): Test cases content for custom field
- `mandays` (optional): Mandays estimation value (float)
- `links` (optional): List of issue links to create
- `update_jira` (default: false): Set to true to actually update JIRA

**Response:**
```json
{
  "success": true,
  "ticket_key": "PROJ-123",
  "updated_in_jira": false,
  "updates_applied": {
    "summary": true,
    "mandays": true
  },
  "links_created": [],
  "preview": {
    "ticket_key": "PROJ-123",
    "current_summary": "Old summary",
    "new_summary": "Updated summary",
    "new_mandays": 3.5
  },
  "message": "Preview: Ticket PROJ-123 would be updated. Set update_jira=true to commit."
}
```

**Example:**
```bash
# Preview mode (default)
curl -X POST "http://localhost:8000/jira/update-ticket" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123",
    "mandays": 3.5
  }'

# Actually update JIRA
curl -X POST "http://localhost:8000/jira/update-ticket" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123",
    "mandays": 3.5,
    "update_jira": true
  }'
```

#### `POST /jira/create-ticket`
Create a new JIRA Task ticket with automatic linking and mandays estimation.

**Request Body:**
```json
{
  "parent_key": "EPIC-100",
  "summary": "Implement user authentication",
  "description": "Add login functionality with email and password",
  "story_key": "STORY-123",
  "test_cases": "Test case content",
  "blocks": ["PROJ-456"],
  "create_ticket": false
}
```

**Parameters:**
- `parent_key` (required): Parent epic ticket key
- `summary` (required): Task summary/title
- `description` (required): Task description
- `story_key` (required): Story ticket key to link via split-from relationship
- `test_cases` (optional): Test cases content for custom field
- `blocks` (optional): List of ticket keys that this task blocks
- `create_ticket` (default: false): Set to true to actually create ticket in JIRA

**Response:**
```json
{
  "success": true,
  "ticket_key": "PROJ-789",
  "created_in_jira": true,
  "links_created": [
    {
      "link_type": "Work item split",
      "source_key": "STORY-123",
      "target_key": "PROJ-789",
      "status": "created"
    }
  ],
  "message": "Successfully created task PROJ-789"
}
```

**Note:** Mandays estimation is automatically set from the task's cycle time estimate when the ticket is created. The mandays custom field must be configured in your JIRA instance.

**PRD Table Updates:** If the story matches a PRD table row (by UUID or fuzzy matching), the PRD table is automatically updated with a clickable JIRA link. The "JIRA Ticket" column is created automatically if it doesn't exist.

**Example:**
```bash
# Preview mode (default)
curl -X POST "http://localhost:8000/jira/create-ticket" \
  -H "Content-Type: application/json" \
  -d '{
    "parent_key": "EPIC-100",
    "summary": "Implement user authentication",
    "description": "Add login functionality",
    "story_key": "STORY-123"
  }'

# Actually create ticket
curl -X POST "http://localhost:8000/jira/create-ticket" \
  -H "Content-Type: application/json" \
  -d '{
    "parent_key": "EPIC-100",
    "summary": "Implement user authentication",
    "description": "Add login functionality",
    "story_key": "STORY-123",
    "create_ticket": true
  }'
```

#### `POST /jira/update-story-ticket`
Update an existing story ticket. Only works on Story tickets - will return an error if you try to update a different ticket type. You can update the title, description, test cases, parent epic, or add links. By default, this shows you what would change without actually updating anything. Set update_jira=true when you're ready to make the changes.

**PRD Table Updates:** Automatically updates the PRD table with a JIRA link if the story matches a PRD table row (by fuzzy matching on story title). The "JIRA Ticket" column is created automatically if it doesn't exist.

**Request Body:**
```json
{
  "story_key": "STORY-123",
  "summary": "Updated story title",
  "description": "Updated story description",
  "test_cases": "Updated test cases",
  "parent_key": "EPIC-200",
  "links": [
    {
      "link_type": "Blocks",
      "target_key": "STORY-456",
      "direction": "outward"
    }
  ],
  "update_jira": false
}
```

**Parameters:**
- `story_key` (required): The story ticket key you want to update
- `summary` (optional): Update the story title. Leave empty to keep current title.
- `description` (optional): Update the story description. Leave empty to keep current description.
- `test_cases` (optional): Update test cases for this story. Leave empty to keep current test cases.
- `parent_key` (optional): Change the parent epic. Leave empty to keep current parent.
- `links` (optional): Create links to other tickets. Leave empty if you don't need to add links.
- `update_jira` (default: false): Set to true to actually update the ticket. Default is false (preview mode).

**Response:**
```json
{
  "success": true,
  "ticket_key": "STORY-123",
  "updated_in_jira": false,
  "updates_applied": {
    "summary": true,
    "description": true
  },
  "links_created": [],
  "preview": {
    "story_key": "STORY-123",
    "current_summary": "Old story title",
    "new_summary": "Updated story title",
    "current_description": "Old description",
    "new_description": "Updated story description"
  },
  "message": "Preview: Story ticket STORY-123 would be updated. Set update_jira=true to commit."
}
```

**Example:**
```bash
# Preview mode (default)
curl -X POST "http://localhost:8000/jira/update-story-ticket" \
  -H "Content-Type: application/json" \
  -d '{
    "story_key": "STORY-123",
    "summary": "Updated story title"
  }'

# Actually update the story
curl -X POST "http://localhost:8000/jira/update-story-ticket" \
  -H "Content-Type: application/json" \
  -d '{
    "story_key": "STORY-123",
    "summary": "Updated story title",
    "description": "Updated description",
    "update_jira": true
  }'
```

#### `POST /jira/bulk-update-stories`
Bulk update multiple story tickets in a single request. Each story can have different update values for summary, description, test_cases, parent_epic, and links. Supports preview mode and asynchronous processing.

**PRD Table Updates:** Automatically updates PRD tables with JIRA links for each updated story that matches a PRD table row (by fuzzy matching on story title). The "JIRA Ticket" column is created automatically if it doesn't exist.

**Request Body:**
```json
{
  "stories": [
    {
      "story_key": "STORY-123",
      "summary": "Updated Story 1 Title",
      "description": "New description for story 1"
    },
    {
      "story_key": "STORY-456",
      "description": "Updated description for story 2",
      "test_cases": "New test cases",
      "parent_key": "EPIC-100"
    },
    {
      "story_key": "STORY-789",
      "summary": "Updated Story 3",
      "links": [
        {
          "link_type": "Blocks",
          "target_key": "STORY-999",
          "direction": "outward"
        }
      ]
    }
  ],
  "dry_run": true,
  "async_mode": false
}
```

**Parameters:**
- `stories` (required): List of story update requests. Each story can have different update values. Maximum 100 stories per request.
  - `story_key` (required): JIRA story ticket key to update
  - `summary` (optional): Update the story title. Leave empty to keep current title.
  - `description` (optional): Update the story description. Leave empty to keep current description.
  - `test_cases` (optional): Update test cases for this story. Leave empty to keep current test cases.
  - `parent_key` (optional): Change the parent epic. Leave empty to keep current parent.
  - `links` (optional): Create links to other tickets. Leave empty if you don't need to add links.
- `dry_run` (default: true): Preview mode - show what would be updated without actually updating JIRA
- `async_mode` (default: false): Process in background (returns job_id for status tracking)

**Response (Synchronous Mode):**
```json
{
  "total_stories": 3,
  "successful": 2,
  "failed": 1,
  "results": [
    {
      "story_key": "STORY-123",
      "success": true,
      "updated_in_jira": false,
      "updates_applied": {
        "summary": true,
        "description": true
      },
      "links_created": [],
      "error": null,
      "preview": {
        "story_key": "STORY-123",
        "current_summary": "Old Story 1 Title",
        "new_summary": "Updated Story 1 Title",
        "current_description": "Old description",
        "new_description": "New description for story 1"
      }
    },
    {
      "story_key": "STORY-456",
      "success": true,
      "updated_in_jira": false,
      "updates_applied": {
        "description": true,
        "test_cases": true,
        "parent_key": true
      },
      "links_created": [],
      "error": null
    },
    {
      "story_key": "STORY-789",
      "success": false,
      "updated_in_jira": false,
      "updates_applied": {},
      "links_created": [],
      "error": "Ticket STORY-789 not found"
    }
  ],
  "job_id": null,
  "status_url": null,
  "message": "Bulk update completed: 2 successful, 1 failed (preview mode - no JIRA changes made)"
}
```

**Response (Async Mode):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "started",
  "message": "Bulk story update queued for 3 stories",
  "status_url": "/jobs/550e8400-e29b-41d4-a716-446655440000",
  "jql": "",
  "max_results": 3,
  "update_jira": false,
  "safety_note": "JIRA will only be updated if dry_run is false"
}
```

**Error Handling:**
- Invalid story keys: Skipped, marked as failed, processing continues
- Non-story tickets: Error returned for that specific story, others continue
- JIRA API errors: Logged and marked as failed, processing continues
- Partial failures: Returns successful/failed counts with individual results

**Example:**
```bash
# Preview mode (synchronous)
curl -X POST "http://localhost:8000/jira/bulk-update-stories" \
  -H "Content-Type: application/json" \
  -d '{
    "stories": [
      {
        "story_key": "STORY-123",
        "summary": "Updated Title"
      },
      {
        "story_key": "STORY-456",
        "description": "Updated description"
      }
    ],
    "dry_run": true,
    "async_mode": false
  }'

# Actually update stories (synchronous)
curl -X POST "http://localhost:8000/jira/bulk-update-stories" \
  -H "Content-Type: application/json" \
  -d '{
    "stories": [
      {
        "story_key": "STORY-123",
        "summary": "Updated Title"
      }
    ],
    "dry_run": false,
    "async_mode": false
  }'

# Async mode (background processing)
curl -X POST "http://localhost:8000/jira/bulk-update-stories" \
  -H "Content-Type: application/json" \
  -d '{
    "stories": [
      {
        "story_key": "STORY-123",
        "summary": "Updated Title"
      }
    ],
    "dry_run": false,
    "async_mode": true
  }'

# Check job status
curl "http://localhost:8000/jobs/{job_id}"
```

**Notes:**
- Maximum 100 stories per request
- Each story update is independent - failures don't affect other stories
- Preview mode shows what would be updated for each story
- Async mode is recommended for large batches (>10 stories)
- All story keys are validated before processing begins

#### `POST /jira/bulk-create-tasks`
Bulk create multiple task tickets in a single request. All tickets are created first, then all links are created to ensure referenced tickets exist. Supports preview mode.

**Request Body:**
```json
{
  "tasks": [
    {
      "parent_key": "EPIC-100",
      "summary": "Implement user authentication",
      "description": "Add login functionality with email and password",
      "story_key": "STORY-123",
      "test_cases": "Test case content",
      "mandays": 2.0,
      "blocks": ["TASK-456", "TASK-789"]
    },
    {
      "parent_key": "EPIC-100",
      "summary": "Implement password reset",
      "description": "Add password reset functionality",
      "story_key": "STORY-123",
      "mandays": 1.5
    }
  ],
  "create_tickets": false
}
```

**Parameters:**
- `tasks` (required): List of task creation requests. Maximum 50 tasks per request.
  - `parent_key` (required): Parent epic ticket key
  - `summary` (required): Task summary/title
  - `description` (required): Task description
  - `story_key` (required): Story ticket key to link via split-from relationship
  - `test_cases` (optional): Test cases content for custom field
  - `mandays` (optional): Mandays estimation value (float)
  - `blocks` (optional): List of ticket keys that this task blocks
- `create_tickets` (default: false): Set to true to actually create tickets in JIRA

**Response:**
```json
{
  "total_tasks": 2,
  "successful": 2,
  "failed": 0,
  "results": [
    {
      "index": 0,
      "success": true,
      "ticket_key": "TASK-101",
      "error": null,
      "links_created": [
        {
          "link_type": "Work item split",
          "source_key": "STORY-123",
          "target_key": "TASK-101",
          "status": "created"
        },
        {
          "link_type": "Blocks",
          "source_key": "TASK-101",
          "target_key": "TASK-456",
          "status": "created"
        }
      ]
    },
    {
      "index": 1,
      "success": true,
      "ticket_key": "TASK-102",
      "error": null,
      "links_created": [
        {
          "link_type": "Work item split",
          "source_key": "STORY-123",
          "target_key": "TASK-102",
          "status": "created"
        }
      ]
    }
  ],
  "created_tickets": ["TASK-101", "TASK-102"],
  "message": "Bulk creation completed: 2 successful, 0 failed"
}
```

**Important:** This endpoint follows a two-phase approach:
1. **Phase 1**: All tickets are created first using JIRA's bulk create API
2. **Phase 2**: All links are created after all tickets exist (prevents linking to non-existent tickets)

**Example:**
```bash
# Preview mode (default)
curl -X POST "http://localhost:8000/jira/bulk-create-tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "tasks": [
      {
        "parent_key": "EPIC-100",
        "summary": "Implement user authentication",
        "description": "Add login functionality",
        "story_key": "STORY-123"
      }
    ],
    "create_tickets": false
  }'

# Actually create tickets
curl -X POST "http://localhost:8000/jira/bulk-create-tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "tasks": [
      {
        "parent_key": "EPIC-100",
        "summary": "Implement user authentication",
        "description": "Add login functionality",
        "story_key": "STORY-123",
        "mandays": 2.0
      }
    ],
    "create_tickets": true
  }'
```

**Notes:**
- Maximum 50 tasks per request
- All tickets are created first, then all links are created
- If a ticket creation fails, links for that ticket are skipped
- Preview mode shows what would be created without actually creating tickets

#### `POST /jira/bulk-create-stories`
Bulk create multiple story tickets in a single request. All tickets are created first, then all links are created to ensure referenced tickets exist. Supports preview mode.

**PRD Table Updates:** Automatically updates PRD tables with JIRA links for each created story that matches a PRD table row (by UUID if provided, or fuzzy matching on story title). The "JIRA Ticket" column is created automatically if it doesn't exist.

**Request Body:**
```json
{
  "stories": [
    {
      "parent_key": "EPIC-100",
      "summary": "User authentication feature",
      "description": "As a user, I want to authenticate with email and password so that I can access my account",
      "test_cases": "Test case content"
    },
    {
      "parent_key": "EPIC-100",
      "summary": "Password reset feature",
      "description": "As a user, I want to reset my password so that I can regain access to my account"
    }
  ],
  "create_tickets": false
}
```

**Parameters:**
- `stories` (required): List of story creation requests. Maximum 50 stories per request.
  - `parent_key` (required): Parent epic ticket key
  - `summary` (required): Story summary/title
  - `description` (required): Story description/context
  - `test_cases` (optional): Test cases content for custom field
- `create_tickets` (default: false): Set to true to actually create tickets in JIRA

**Response:**
```json
{
  "total_stories": 2,
  "successful": 2,
  "failed": 0,
  "results": [
    {
      "index": 0,
      "success": true,
      "ticket_key": "STORY-101",
      "error": null,
      "links_created": []
    },
    {
      "index": 1,
      "success": true,
      "ticket_key": "STORY-102",
      "error": null,
      "links_created": []
    }
  ],
  "created_tickets": ["STORY-101", "STORY-102"],
  "message": "Bulk creation completed: 2 successful, 0 failed"
}
```

**Important:** This endpoint follows a two-phase approach:
1. **Phase 1**: All tickets are created first using JIRA's bulk create API
2. **Phase 2**: All links are created after all tickets exist (currently stories only link to epics, which are set during creation)

**Example:**
```bash
# Preview mode (default)
curl -X POST "http://localhost:8000/jira/bulk-create-stories" \
  -H "Content-Type: application/json" \
  -d '{
    "stories": [
      {
        "parent_key": "EPIC-100",
        "summary": "User authentication feature",
        "description": "As a user, I want to authenticate"
      }
    ],
    "create_tickets": false
  }'

# Actually create tickets
curl -X POST "http://localhost:8000/jira/bulk-create-stories" \
  -H "Content-Type: application/json" \
  -d '{
    "stories": [
      {
        "parent_key": "EPIC-100",
        "summary": "User authentication feature",
        "description": "As a user, I want to authenticate",
        "test_cases": "Test cases here"
      }
    ],
    "create_tickets": true
  }'
```

**Notes:**
- Maximum 50 stories per request
- All tickets are created first, then all links are created
- Stories are automatically linked to their parent epic during creation
- Preview mode shows what would be created without actually creating tickets

### Bulk Creation (Planning-Based)

Bulk creation endpoints allow you to generate and create multiple JIRA tickets (stories and tasks) in a single operation. All endpoints support `async_mode` for background processing of long-running operations.

#### `POST /plan/epic/create`

Execute complete planning workflow and optionally create JIRA tickets. This endpoint performs gap analysis, story generation, task breakdown, and ticket creation in one operation.

**Request Body:**
```json
{
  "epic_key": "EPIC-100",
  "create_tickets": false,
  "operation_mode": "hybrid",
  "async_mode": false
}
```

**Parameters:**
- `epic_key` (required): JIRA epic key to plan and create tickets for
- `create_tickets` (default: false): Set to true to actually create tickets in JIRA
- `operation_mode` (default: "hybrid"): Planning mode - "documentation", "planning", or "hybrid"
- `async_mode` (default: false): Process in background. If true, returns job_id for status tracking

**Response (Synchronous):**
```json
{
  "epic_key": "EPIC-100",
  "create_tickets": false,
  "success": true,
  "planning_results": {...},
  "creation_results": {
    "created_tickets": {
      "stories": ["STORY-1", "STORY-2"],
      "tasks": ["TASK-1", "TASK-2", "TASK-3"]
    },
    "success": true
  },
  "errors": [],
  "execution_time_seconds": 45.2
}
```

**Response (Asynchronous):**
```json
{
  "job_id": "abc-123-def-456",
  "status": "started",
  "message": "Epic planning and creation queued for EPIC-100",
  "status_url": "/jobs/abc-123-def-456",
  "update_jira": false
}
```

**Notes:**
- Preview mode by default (`create_tickets=false`)
- Includes validation and error recovery
- Created ticket keys are available in `job.results.creation_results.created_tickets` when job completes
- Async mode recommended for large epics (>5 stories)

#### `POST /plan/stories/create`

Generate and optionally create story tickets for an epic with acceptance criteria.

**Request Body:**
```json
{
  "epic_key": "EPIC-100",
  "story_count": 5,
  "create_tickets": false,
  "async_mode": false
}
```

**Parameters:**
- `epic_key` (required): Parent epic key
- `story_count` (default: 5): Number of stories to generate
- `create_tickets` (default: false): Set to true to create tickets in JIRA
- `async_mode` (default: false): Process in background

**Response (Synchronous):**
```json
{
  "epic_key": "EPIC-100",
  "planning_results": {...},
  "creation_results": {
    "created_tickets": {
      "stories": ["STORY-1", "STORY-2", "STORY-3"]
    },
    "success": true
  },
  "success": true
}
```

**Response (Asynchronous):**
```json
{
  "job_id": "abc-123-def-456",
  "status": "started",
  "message": "Story creation queued for epic EPIC-100",
  "status_url": "/jobs/abc-123-def-456",
  "epic_key": "EPIC-100"
}
```

#### `POST /plan/tasks/create`

Generate and optionally create task tickets for stories with cycle time estimates. Validates cycle time constraints.

**Request Body:**
```json
{
  "story_keys": ["STORY-1", "STORY-2", "STORY-3"],
  "tasks_per_story": 3,
  "create_tickets": false,
  "async_mode": false
}
```

**Parameters:**
- `story_keys` (required): List of story keys to create tasks for
- `tasks_per_story` (default: 3): Number of tasks to generate per story
- `create_tickets` (default: false): Set to true to create tickets in JIRA
- `async_mode` (default: false): Process in background

**Response (Synchronous):**
```json
{
  "story_keys": ["STORY-1", "STORY-2", "STORY-3"],
  "planning_results": {...},
  "creation_results": {
    "created_tickets": {
      "tasks": ["TASK-1", "TASK-2", "TASK-3", "TASK-4", "TASK-5"]
    },
    "success": true
  },
  "success": true
}
```

**Response (Asynchronous):**
```json
{
  "job_id": "abc-123-def-456",
  "status": "started",
  "message": "Task creation queued for 3 stories",
  "status_url": "/jobs/abc-123-def-456",
  "story_keys": ["STORY-1", "STORY-2", "STORY-3"]
}
```

**Notes:**
- All bulk creation endpoints support async_mode for long-running operations
- Created JIRA ticket keys are returned in `job.results.creation_results.created_tickets` when jobs complete
- Duplicate prevention: checks for active jobs before starting new ones
- Preview mode by default - set `create_tickets=true` to actually create tickets

### Test Generation

#### `POST /plan/tests/comprehensive`
Generate comprehensive test suites for an entire epic

**Request Body:**
```json
{
  "epic_key": "EPIC-100",
  "coverage_level": "standard",
  "llm_provider": "openai",
  "llm_model": "gpt-5-mini"
}
```

**Coverage Levels:**
- **Minimal**: Basic happy path tests only (1-2 tests per item)
- **Basic**: Happy path + basic error scenarios (2-4 tests per item)
- **Standard**: Comprehensive coverage with edge cases (3-6 tests per item) *(Default)*
- **Comprehensive**: Full coverage including performance and security tests (5-10 tests per item)

#### `POST /plan/tests/story`
Generate targeted test cases for a specific story

**Request Body:**
```json
{
  "story_key": "STORY-123",
  "coverage_level": "basic",
  "llm_provider": "claude",
  "llm_model": "claude-sonnet-4-5"
}
```

#### `POST /plan/tests/task`
Generate technical test cases for a specific task

**Request Body:**
```json
{
  "task_key": "TASK-456", 
  "coverage_level": "standard",
  "llm_provider": "gemini",
  "llm_model": "gemini-2.5-flash"
}
```

**Generated Test Types:**
- Unit, Integration, Acceptance, E2E, Performance, Security, UI

---

## Usage Examples

### Example 1: Preview Descriptions (Read-Only)

```bash
# Start a batch job to preview descriptions
curl -X POST "http://localhost:8000/generate/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "jql": "project = MYPROJ AND description is EMPTY",
    "max_results": 20,
    "update_jira": false
  }'

# Check job status
curl http://localhost:8000/jobs/{job_id}
```

### Example 2: Update JIRA Tickets

```bash
curl -X POST "http://localhost:8000/generate/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "jql": "key in (PROJ-123, PROJ-124, PROJ-125)",
    "update_jira": true
  }'
```

### Example 3: Generate Team-Based Tasks

```bash
curl -X POST "http://localhost:8000/plan/tasks/team-based" \
  -H "Content-Type: application/json" \
  -d '{
    "story_keys": ["STORY-123"],
    "epic_key": "EPIC-100",
    "dry_run": true,
    "llm_provider": "openai",
    "llm_model": "gpt-5-mini"
  }'
```

### Example 4: Python Client

```python
import requests
import time

# Start batch processing
response = requests.post("http://localhost:8000/generate/batch", json={
    "jql": "project = MYPROJ AND description is EMPTY",
    "max_results": 50,
    "update_jira": False
})

job_id = response.json()["job_id"]

# Poll for completion
while True:
    status_response = requests.get(f"http://localhost:8000/jobs/{job_id}")
    status_data = status_response.json()
    
    if status_data["status"] == "completed":
        print("Job completed!")
        print(f"Results: {status_data['result']}")
        break
    elif status_data["status"] == "failed":
        print("Job failed!")
        break
    
    time.sleep(5)
```

### Common JQL Queries

```bash
# Empty descriptions
"description is EMPTY"

# Specific project
"project = MYPROJ AND description is EMPTY"

# Recent tickets
"created >= -7d AND description is EMPTY"

# Specific issue types
"issueType = Story AND description is EMPTY"
```

### Sprint Planning

#### `GET /sprint/board/{board_id}/sprints`
List sprints for a board

**Parameters:**
- `board_id` (path): JIRA board ID
- `state` (query, optional): Sprint state filter (active, closed, future)

**Response:**
```json
[
  {
    "id": 123,
    "name": "Sprint 1",
    "state": "active",
    "start_date": "2025-01-15",
    "end_date": "2025-01-29",
    "board_id": 1,
    "goal": "Complete epic planning features"
  }
]
```

#### `GET /sprint/{sprint_id}`
Get sprint details

**Response:**
```json
{
  "id": 123,
  "name": "Sprint 1",
  "state": "active",
  "start_date": "2025-01-15",
  "end_date": "2025-01-29",
  "board_id": 1,
  "goal": "Complete epic planning features"
}
```

#### `POST /sprint/create`
Create a new sprint

**Request Body:**
```json
{
  "name": "Sprint 1",
  "board_id": 1,
  "start_date": "2025-01-15",
  "end_date": "2025-01-29"
}
```

#### `PUT /sprint/{sprint_id}`
Update sprint

**Request Body:**
```json
{
  "name": "Updated Sprint Name",
  "start_date": "2025-01-16",
  "end_date": "2025-01-30",
  "state": "active"
}
```

#### `POST /sprint/{sprint_id}/assign`
Assign tickets to sprint

**Request Body:**
```json
{
  "sprint_id": 123,
  "issue_keys": ["TASK-1", "TASK-2", "TASK-3"],
  "dry_run": true
}
```

**Response:**
```json
{
  "success": true,
  "sprint_id": 123,
  "issue_keys": ["TASK-1", "TASK-2", "TASK-3"],
  "assigned_in_jira": false,
  "message": "Preview: Tickets would be assigned. Set dry_run=false to commit."
}
```

#### `POST /sprint/plan/epic`
Plan epic tasks to sprints based on capacity and dependencies

**SAFETY FIRST**: By default operates in PREVIEW MODE (dry_run=true). Must explicitly set `dry_run: false` to create/assign sprints in JIRA.

**Request Body:**
```json
{
  "epic_key": "EPIC-100",
  "board_id": 1,
  "sprint_capacity_days": 10.0,
  "start_date": "2025-01-15",
  "sprint_duration_days": 14,
  "team_id": 1,
  "auto_create_sprints": false,
  "dry_run": true,
  "async_mode": false
}
```

**Parameters:**
- `dry_run` (default: true): Set to false to actually create/assign sprints in JIRA
- `async_mode` (default: false): Run in background. If true, returns job_id for status tracking

**Response (Synchronous):**
```json
{
  "epic_key": "EPIC-100",
  "board_id": 1,
  "success": true,
  "assignments": [
    {
      "task_key": "TASK-1",
      "task_summary": "Implement feature X",
      "sprint_id": 123,
      "sprint_name": "Sprint 1",
      "estimated_days": 3.0,
      "team": "Backend"
    }
  ],
  "sprints_created": [],
  "total_tasks": 5,
  "total_sprints": 2,
  "capacity_utilization": {
    "123": 0.8,
    "124": 0.6
  },
  "errors": [],
  "warnings": []
}
```

**Response (Async Mode):**
```json
{
  "job_id": "abc-123-def-456",
  "status": "started",
  "message": "Sprint planning for epic EPIC-100 queued",
  "status_url": "/jobs/abc-123-def-456",
  "update_jira": false,
  "safety_note": "JIRA will only be updated if dry_run is false"
}
```

#### `POST /sprint/timeline`
Create timeline schedule for epic

**SAFETY FIRST**: By default operates in PREVIEW MODE (dry_run=true). Must explicitly set `dry_run: false` to create/assign sprints in JIRA.

**Request Body:**
```json
{
  "epic_key": "EPIC-100",
  "board_id": 1,
  "start_date": "2025-01-15",
  "sprint_duration_days": 14,
  "team_capacity_days": 10.0,
  "team_id": 1,
  "dry_run": true,
  "async_mode": false
}
```

**Parameters:**
- `dry_run` (default: true): Set to false to actually create/assign sprints in JIRA
- `async_mode` (default: false): Run in background. If true, returns job_id for status tracking

**Response (Async Mode):**
```json
{
  "job_id": "abc-123-def-456",
  "status": "started",
  "message": "Timeline planning for epic EPIC-100 queued",
  "status_url": "/jobs/abc-123-def-456",
  "update_jira": false,
  "safety_note": "JIRA will only be updated if dry_run is false"
}
```

**Response:**
```json
{
  "epic_key": "EPIC-100",
  "board_id": 1,
  "start_date": "2025-01-15",
  "sprint_duration_days": 14,
  "sprints": [
    {
      "sprint_id": 123,
      "sprint_name": "Sprint 1",
      "start_date": "2025-01-15",
      "end_date": "2025-01-29",
      "tasks": [...],
      "total_estimated_days": 8.0,
      "capacity_days": 10.0,
      "utilization_percent": 80.0
    }
  ],
  "total_sprints": 2,
  "total_tasks": 5,
  "estimated_completion_date": "2025-02-12",
  "errors": [],
  "warnings": []
}
```

#### `GET /sprint/{sprint_id}/issues`
Get all issues in a sprint

**Response:**
```json
{
  "sprint_id": 123,
  "total_issues": 5,
  "issues": [...]
}
```

---

## Troubleshooting

### Common Issues

1. **Connection Errors**: Check `config.yaml` and test with `/health` endpoint
2. **Job Stuck**: Check if background worker (`run_worker.py`) is running. Jobs are stored in Redis and persist across server restarts.
3. **Large Batches**: For very large batches, consider processing in smaller chunks or use async mode
4. **Redis Connection Errors**: Verify Redis is running (`redis-cli ping`) and check `REDIS_HOST`, `REDIS_PORT` in `.env`
5. **Background Jobs Not Processing**: Ensure `run_worker.py` is running in a separate terminal
6. **Jobs Processing Slowly**: Increase `WORKER_MAX_JOBS` to allow more concurrent jobs, or run multiple worker instances
7. **Job Timeouts**: Increase `WORKER_JOB_TIMEOUT` if jobs are timing out before completion
8. **Authentication Issues**: Verify password hash was generated correctly and environment variables are set
9. **Model Selection Errors**: Check `/models` endpoint for available models and verify API keys are set

### Error Responses

The API uses standard HTTP status codes:
- **200**: Success
- **404**: Resource not found (ticket, job, file)
- **422**: Validation error (invalid request parameters)
- **500**: Internal server error

### Verification Steps

1. **Check configuration:**
   ```bash
   curl http://localhost:8000/
   ```

2. **Test health endpoint:**
   ```bash
   curl http://localhost:8000/health
   ```

3. **Check available models:**
   ```bash
   curl http://localhost:8000/models
   ```

### Logs

Check server logs for detailed error information. The API uses Python's logging module with INFO level by default.

---

## Production Deployment

For production deployment, consider:

1. **Environment Variables**: Move sensitive config to environment variables
2. **Authentication**: Enable HTTP Basic Authentication or implement API key authentication
3. **Rate Limiting**: Implement request rate limiting
4. **HTTPS**: Use HTTPS in production
5. **Monitoring**: Add proper logging and monitoring
6. **Background Jobs**: Uses ARQ with Redis for background job processing
7. **Job Persistence**: Jobs are stored in Redis and persist across restarts
8. **Worker Process**: Run `run_worker.py` as a systemd service or in a container
9. **Redis High Availability**: Use Redis Sentinel or Cluster for production
10. **Scaling**: Run multiple worker processes for parallel job processing. Configure `max_jobs` per worker to control concurrency. Total capacity = `max_jobs × number_of_workers`

---

## Safety Reminders

- **Default behavior**: Preview mode (no JIRA updates)
- **To update JIRA**: Must explicitly set `"update_jira": true`
- **Always test first**: Run in preview mode before updating
- **Check results**: Review generated descriptions before applying
