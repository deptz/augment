# Features Documentation

This document provides comprehensive documentation for all features in the Augment system.

## Table of Contents

1. [Test Case Generation](#test-case-generation)
2. [Team-Based Task Generation](#team-based-task-generation)
3. [Task Dependency Management](#task-dependency-management)
4. [AI Dependency Enhancement](#ai-dependency-enhancement)
5. [Enhanced Test Generator Integration](#enhanced-test-generator-integration)
6. [Background Job Processing](#background-job-processing)
7. [Sprint Planning & Capacity Management](#sprint-planning--capacity-management)
8. [PRD to Story Ticket Sync](#prd-to-story-ticket-sync)
9. [Draft PR Orchestrator](#draft-pr-orchestrator)
10. [OpenCode Integration](#opencode-integration)

---

## Test Case Generation

### Overview

Augment includes comprehensive AI-powered test case generation capabilities. This feature automatically creates detailed test cases for stories, tasks, and entire epics with multiple coverage levels and domain-aware scenarios.

### Key Features

- **AI-Powered Generation**: Leverages LLM for intelligent test scenario creation
- **Multiple Coverage Levels**: Minimal, Basic, Standard, and Comprehensive coverage options
- **Context-Aware**: Adapts tests based on domain (financial, healthcare, etc.) and technical context (API, database, UI)
- **Fallback Mechanisms**: Robust pattern-based generation when AI is unavailable
- **Test Deduplication**: Advanced algorithms to eliminate duplicate test cases
- **Real-time Generation**: Live test case creation with execution time tracking

### Test Types Generated

- **Unit**: Individual function and method tests
- **Integration**: Component and service interaction tests
- **Acceptance**: User story validation tests
- **E2E**: Complete user journey tests
- **Performance**: Load, stress, and scalability tests
- **Security**: Authentication, authorization, and vulnerability tests
- **UI**: User interface and interaction tests

### Coverage Levels

| Level | Description | Tests Per Item |
|-------|-------------|----------------|
| **Minimal** | Basic happy path tests only | 1-2 tests |
| **Basic** | Happy path + basic error scenarios | 2-4 tests |
| **Standard** | Comprehensive coverage with edge cases | 3-6 tests |
| **Comprehensive** | Full coverage including performance and security | 5-10 tests |

### API Endpoints

- `POST /plan/tests/comprehensive` - Generate complete test suites for epics
- `POST /plan/tests/story` - Generate targeted test cases for specific stories
- `POST /plan/tests/task` - Generate technical test cases for specific tasks

### Domain-Aware Testing

The system automatically detects domain context and adapts test scenarios:
- **Financial**: Monetary calculations, compliance, audit trails
- **Healthcare**: HIPAA compliance, patient data privacy
- **eCommerce**: Payment processing, inventory management
- **Security**: Authentication, authorization, encryption

### Technical Context Awareness

Tests are tailored for specific technical contexts:
- **API**: Endpoint testing, request/response validation, error codes
- **Database**: Data integrity, transactions, performance queries
- **UI**: User interactions, accessibility, browser compatibility
- **Microservice**: Service communication, fault tolerance, distributed behavior

---

## Team-Based Task Generation

### Overview

Intelligent team-based task generation that automatically separates user stories into appropriate Backend, Frontend, and QA tasks with proper team assignment, dependency management, and cycle time optimization.

### Key Features

- **Team Separation Logic**: Intelligent classification of tasks by team responsibility
- **AI-Powered Analysis**: Story type detection and complexity assessment
- **Cycle Time Optimization**: Team-specific estimation and task splitting
- **Dependency Analysis**: Automatic identification of task relationships
- **JIRA Integration**: Creates actual JIRA tickets with proper relationships

### Team Responsibilities

**Backend Tasks:**
- API development and endpoints
- Database design and implementation
- Business logic and data processing
- Service integrations and external APIs
- Security and authentication implementation

**Frontend Tasks:**
- User interface components and pages
- User experience and interactions
- Client-side logic and state management
- UI/UX implementation
- Responsive design and accessibility

**QA Tasks:**
- Test plan creation and test case design
- Manual testing and exploratory testing
- Automated test implementation
- Integration testing coordination
- Performance and security testing

### Story Type Analysis

The system automatically detects story types:
- **API-focused**: API, endpoint, service, backend, database patterns
- **UI-focused**: UI, interface, component, page, view, frontend patterns
- **Data-focused**: Analytics, processing pipeline, data processing, migration patterns
- **Integration patterns**: Integration, connect, sync, third-party, external patterns

### API Endpoint

`POST /plan/tasks/team-based`

**Request:**
```json
{
  "story_keys": ["STORY-123"],
  "epic_key": "EPIC-100",
  "dry_run": true,
  "llm_provider": "openai",
  "llm_model": "gpt-5-mini"
}
```

**Response:** Returns tasks organized by team with dependencies, estimates, and test cases.

### Task Splitting

The system automatically splits oversized tasks to maintain cycle time constraints:
- Tasks exceeding `max_task_cycle_days` are split into smaller subtasks
- Maintains logical work boundaries
- Preserves team assignments and dependencies

---

## Task Dependency Management

### Overview

Enhanced task generation system that automatically creates "is blocked by" relationships between tasks across different teams. This ensures proper workflow dependencies where Frontend tasks depend on Backend tasks, and QA tasks depend on implementation completion.

### Key Features

- **Intelligent Dependency Analysis**: Automatically analyzes task relationships based on team assignments
- **JIRA Integration**: Creates "Blocks" issue links in JIRA
- **Team-Aware Workflow**: Supports Backend → Frontend → QA dependency flow
- **Complex Dependencies**: Supports multi-team dependencies and infrastructure tasks

### Dependency Flow

**Typical Workflow:**
```
Backend API → Frontend UI → QA Testing
```

**Complex Feature:**
```
Database Setup → API Implementation → UI Implementation → QA Testing
```

### Team Blocking Relationships

- **Backend tasks** can depend on other Backend infrastructure tasks
- **Frontend tasks** are blocked by Backend API/service tasks
- **QA tasks** are blocked by implementation tasks from both teams

### JIRA Integration

The system creates "Blocks" relationships in JIRA:
- Maintains proper relationship direction (blocker blocks dependent)
- Supports bulk relationship creation with error handling
- Provides detailed logging of relationship creation

### API Response

Enhanced response includes dependency information:
```json
{
  "task_details": [
    {
      "summary": "Implement API endpoints",
      "team": "backend",
      "depends_on_tasks": [],
      "blocked_by_teams": []
    },
    {
      "summary": "Create UI components",
      "team": "frontend",
      "depends_on_tasks": ["Implement API endpoints"],
      "blocked_by_teams": ["backend"]
    }
  ],
  "relationships_created": [
    {
      "from": "TASK-101",
      "to": "TASK-102",
      "type": "Blocks",
      "blocking_team": "backend",
      "dependent_team": "frontend"
    }
  ]
}
```

### Benefits

1. **Workflow Clarity**: Clear visual dependencies in JIRA
2. **Project Management**: Better sprint planning with dependency awareness
3. **Team Coordination**: Automatic notification when blocking tasks complete

---

## AI Dependency Enhancement

### Overview

Enhanced AI-powered dependency detection that intelligently identifies task relationships and creates proper blocking relationships in JIRA.

### Key Features

- **AI-Powered Analysis**: Uses LLM to analyze task relationships
- **Intelligent Detection**: Identifies logical dependencies between tasks
- **Automatic Link Creation**: Creates JIRA "Blocks" relationships automatically
- **Error Handling**: Graceful fallback when dependency creation fails

### Implementation

The system analyzes:
- Task descriptions and summaries
- Team assignments
- Technical context
- Story relationships

Based on this analysis, it determines:
- Which tasks block others
- Dependency direction
- Team blocking relationships

### Benefits

- **Reduced Manual Work**: No need to manually create dependency links
- **Accurate Dependencies**: AI ensures logical dependency relationships
- **Better Planning**: Clear dependency visualization for sprint planning

---

## Enhanced Test Generator Integration

### PRD/RFC Integration

The test generator integrates with PRD and RFC documents to create context-aware test cases:

- **PRD Context**: Extracts user stories, acceptance criteria, and business requirements
- **RFC Context**: Extracts technical design, architecture, and implementation details
- **Combined Context**: Uses both PRD and RFC information for comprehensive test coverage

### System Integration

The test generator is fully integrated with:

- **Task Generation**: Automatically includes test cases in task generation responses
- **Team-Based Planning**: Generates team-specific test cases (Backend, Frontend, QA)
- **Epic Analysis**: Creates comprehensive test suites for entire epics
- **Story Analysis**: Generates acceptance and integration tests for stories

### Test Case Structure

Each generated test case includes:
- **Title**: Descriptive test case name
- **Type**: Unit, integration, e2e, acceptance, performance, security, UI
- **Description**: Detailed test scenario and steps
- **Expected Result**: Clear success criteria

### Integration Points

1. **Task Generation Endpoints**: Test cases included in task details
2. **Dedicated Test Endpoints**: Standalone test generation endpoints
3. **Batch Processing**: Can generate tests for multiple stories/tasks
4. **Model Selection**: Supports custom LLM provider/model selection

---

## Background Job Processing

### Overview

All generation endpoints support asynchronous background processing using ARQ (async Redis queue), allowing long-running operations to be processed without blocking the API.

### Key Features

- **Job Tracking**: Monitor job progress in real-time via `GET /jobs/{job_id}`
- **Ticket-Based Status**: Query job status by ticket key via `GET /jobs/ticket/{ticket_key}`
- **Duplicate Prevention**: Automatically rejects duplicate requests for tickets already being processed
- **Job Cancellation**: Cancel running jobs via `DELETE /jobs/{job_id}`
- **Job Persistence**: Jobs survive server restarts (stored in Redis)
- **Multiple Job Types**: Supports batch, single, story generation, task generation, test generation, sprint planning, and PRD story sync

### Supported Endpoints

All these endpoints support `async_mode: true` parameter:

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

### Job Types

- `batch`: Batch ticket processing
- `single`: Single ticket generation
- `story_generation`: Story generation for epics
- `prd_story_sync`: PRD story sync operations
- `task_generation`: Task generation for stories
- `test_generation`: Test case generation
- `epic_creation`: Epic planning and ticket creation
- `story_creation`: Story creation for epics
- `task_creation`: Task creation for stories
- `sprint_planning`: Sprint planning for epic tasks
- `timeline_planning`: Timeline schedule creation

### Duplicate Prevention

The system automatically prevents duplicate processing:
- Checks for active jobs before starting new ones
- Returns `409 Conflict` with existing job ID if duplicate detected
- Supports ticket-based job lookup for status pages
- Automatically unregisters jobs on completion or failure

### Usage Example

```bash
# Start async job
curl -X POST "http://localhost:8000/generate/single" \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_key": "PROJ-123",
    "async_mode": true
  }'

# Check status by job ID
curl "http://localhost:8000/jobs/{job_id}"

# Check status by ticket key
curl "http://localhost:8000/jobs/ticket/PROJ-123"
```

---

## Sprint Planning & Capacity Management

### Overview

Comprehensive sprint planning capabilities with capacity-based task assignment, dependency awareness, and timeline scheduling.

### Key Features

- **Capacity-Based Planning**: Automatically assigns tasks to sprints based on team capacity and task estimates
- **Dependency Awareness**: Respects task dependencies when assigning to sprints
- **Team Integration**: Uses team member data for accurate capacity calculations
- **Timeline Scheduling**: Creates timeline views showing when tasks will be completed
- **Dry Run Mode**: All endpoints default to `dry_run=true` for safe preview
- **Async Support**: Long-running operations support `async_mode=true` for background processing

### Sprint Planning Features

**Capacity Calculation:**
- Uses team member capacity data from SQLite database (auto-created at `data/team_members.db`)
- Supports per-sprint capacity override
- Calculates capacity utilization per sprint
- Handles team-based capacity when `team_id` is provided

**Dependency Handling:**
- Topological sort ensures dependencies are respected
- Tasks are assigned to sprints only after dependencies are satisfied
- Supports complex multi-level dependencies

**Sprint Assignment:**
- Automatically finds or creates sprints as needed
- Assigns tasks to sprints based on capacity and dependencies
- Provides capacity utilization metrics
- Supports manual sprint assignment via `/sprint/{sprint_id}/assign`

### API Endpoints

- `POST /sprint/plan/epic` - Plan epic tasks to sprints (capacity-based, dry_run=true, async_mode supported)
- `POST /sprint/timeline` - Create timeline schedule for epic (dry_run=true, async_mode supported)
- `GET /sprint/timeline/{epic_key}` - Get timeline for epic
- `POST /sprint/{sprint_id}/assign` - Assign tickets to sprint (dry_run=true by default)
- `GET /sprint/board/{board_id}/sprints` - List sprints for a board

### Team Member Integration

The sprint planning system integrates with team member management:
- Uses `capacity_days_per_sprint` from team member records
- Supports team-based capacity calculation via `team_id`
- Can override capacity with `sprint_capacity_days` parameter

### Usage Example

```bash
# Plan epic to sprints (preview mode)
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

# Create timeline (async mode)
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
```

---

## PRD to Story Ticket Sync

### Overview

Automatically syncs story tickets from PRD (Product Requirements Document) table format to JIRA, creating story tickets with proper descriptions and acceptance criteria. The system also automatically updates the PRD table with JIRA ticket links when stories are created or updated.

### Key Features

- **Table Parsing**: Automatically detects and parses story tables from PRD documents
- **Flexible Table Format**: Supports various table structures and column names
- **Acceptance Criteria Parsing**: Intelligently parses Given/When/Then format, bullet points, or plain text
- **Existing Ticket Handling**: Supports skip, update, or error actions for existing tickets
- **Async Support**: Supports both synchronous and asynchronous processing
- **Dry Run Mode**: Defaults to `dry_run=true` for safe preview
- **Automatic PRD Table Updates**: Automatically updates PRD table with JIRA links when stories are created or updated
- **UUID-Based Row Matching**: Uses temporary UUIDs for exact row matching during sync (eliminates need for fuzzy matching)
- **Automatic Column Creation**: Creates "JIRA Ticket" column in PRD table if it doesn't exist
- **HTML Link Formatting**: Formats JIRA links as proper HTML anchor tags for Confluence compatibility

### PRD Table Format

The endpoint expects a table in the PRD document with:

**Section Heading:**
- "Story Ticket List", "Story Tickets", "Story List", or similar variations
- Auto-detected by section ID or heading text

**Table Columns:**
- **Title** (required): Story title/summary (also accepts "Summary" or "Name")
- **Description** (optional): Story description (defaults to title if missing)
- **Acceptance Criteria** (optional): Acceptance criteria in various formats

**Column Detection:**
- Headers are auto-detected and normalized (case-insensitive)
- Missing columns are handled gracefully
- Supports various column name variations

### Acceptance Criteria Parsing

The system intelligently parses acceptance criteria in multiple formats:

1. **Given/When/Then Format:**
   ```
   Given: the user is logged in
   When: they click the submit button
   Then: the form is submitted
   ```

2. **Bullet Points:**
   ```
   - User can submit form
   - Validation errors are shown
   ```

3. **Plain Text:**
   ```
   The form should validate input and show errors
   ```

### Existing Ticket Actions

When a story ticket already exists, you can choose:

- **`skip`** (default): Don't create, log and continue
- **`update`**: Update existing ticket description/acceptance criteria
- **`error`**: Return error and stop processing

### API Endpoint

`POST /plan/stories/sync-from-prd`

**Request:**
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
- `async_mode` (default: false): Run in background (async mode).
- `existing_ticket_action` (default: "skip"): Action when story ticket already exists.

### Usage Example

```bash
# Synchronous mode (preview)
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
    "dry_run": false,
    "async_mode": true,
    "existing_ticket_action": "update"
  }'

# Check job status
curl "http://localhost:8000/jobs/{job_id}"
```

### PRD Table Updates

When stories are created or updated, the system automatically updates the PRD table:

**Automatic Column Creation:**
- Creates a "JIRA Ticket" column in the PRD table if it doesn't exist
- Adds missing cells to rows that are too short
- Handles all table structures gracefully

**UUID-Based Row Matching:**
- During dry run mode, generates temporary UUIDs for each story to be created
- Stores UUIDs as placeholders in PRD table: `[TEMP-{uuid}](placeholder)`
- When story is created, uses UUID for exact row matching (no fuzzy matching needed)
- Falls back to fuzzy matching by story title if UUID is not available

**Link Formatting:**
- Formats JIRA links as proper HTML anchor tags (`<a href="...">...</a>`)
- Ensures links are clickable in Confluence
- Replaces UUID placeholders with actual JIRA links

**Update Flows:**
- **Story Creation**: Single and bulk story creation endpoints automatically update PRD table
- **Story Updates**: Single and bulk story update endpoints automatically update PRD table
- **PRD Sync**: PRD sync flow updates table for both new and existing stories (when `existing_ticket_action="update"`)

### Integration

The PRD story sync integrates with:
- **Confluence**: Fetches PRD documents from Confluence and updates PRD tables
- **JIRA**: Creates story tickets under the specified epic
- **Planning Service**: Uses planning service for ticket creation and PRD updates
- **Background Jobs**: Supports async processing for large PRDs

---

## Dynamic Additional Context Management

### Overview

Augment includes intelligent dynamic token-based management for `additional_context` parameters. Instead of using a fixed character limit, the system automatically calculates the optimal limit based on actual token usage and available budget, maximizing context utilization while respecting LLM token constraints.

### Key Features

- **Token-Based Calculation**: Dynamically calculates character limits based on actual token usage
- **No Hard Caps**: Removes arbitrary character limits, trusting the dynamic calculation
- **Provider-Aware**: Adapts to different LLM provider token limits (OpenAI: 2k-16k, Claude: 8k, Gemini: 8k, Kimi: 8k)
- **Smart Budget Allocation**: Reserves 30% of tokens for response generation, allocates remaining to additional context
- **Automatic Fallback**: Falls back to 1000 characters if token information is unavailable

### How It Works

1. **Token Counting**: System counts tokens used by base prompt (system prompt + user prompt without additional_context)
2. **Budget Calculation**: Calculates remaining budget after reserving 30% for response generation
3. **Character Conversion**: Converts remaining tokens to characters (3.5 chars per token, conservative estimate)
4. **Dynamic Truncation**: Truncates additional_context to fit calculated limit with smart sentence boundaries

### Token Calculation Formula

```
1. Get max_tokens (from config or provider default)
2. Build base prompt without additional_context
3. Count tokens: system_prompt + base_prompt
4. Reserve 30% of max_tokens for response generation
5. Calculate: remaining = (max_tokens - 30%) - tokens_used - 100 buffer
6. Convert to chars: char_limit = remaining * 3.5
7. Truncate additional_context to char_limit
```

### Examples

**Large Token Budget (20k tokens):**
- System prompt: ~500 tokens
- Base prompt: ~3,000 tokens
- Response reserve (30%): 6,000 tokens
- Available for prompt: 14,000 tokens
- Remaining for additional_context: ~10,400 tokens
- **Character limit: ~36,400 characters**

**Medium Token Budget (8k tokens):**
- System prompt: ~500 tokens
- Base prompt: ~2,000 tokens
- Response reserve (30%): 2,400 tokens
- Available for prompt: 5,600 tokens
- Remaining for additional_context: ~3,000 tokens
- **Character limit: ~10,500 characters**

**Small Token Budget (2k tokens with large prompt):**
- System prompt: ~500 tokens
- Base prompt: ~1,000 tokens
- Response reserve (30%): 600 tokens
- Available for prompt: 1,400 tokens
- Remaining for additional_context: 0 tokens (no room)
- **Character limit: 0 characters** (gracefully handles no space)

### Where It's Applied

This dynamic limit calculation is applied to:
- **Single Ticket Description Generation** (`POST /generate/single`)
- **Task Breakdown Prompts** (`POST /plan/tasks/team-based`)
- **Unified Task/Test Generation** (internal task generation with test cases)

### Benefits

1. **Maximizes Context**: Uses all available token budget for additional context
2. **Prevents Overflow**: Automatically prevents token limit violations
3. **Provider Flexibility**: Adapts to different LLM provider capabilities
4. **No Manual Tuning**: Automatically adjusts based on prompt size and token budget

### Configuration

The system uses your configured `LLM_MAX_TOKENS` setting or provider defaults:
- If `LLM_MAX_TOKENS` is set, uses that value
- If not set, uses provider-specific defaults (OpenAI: 2000/16000 for GPT-5, Claude: 8000, Gemini: 8192, Kimi: 8000)
- Falls back to 1000 characters if token information is unavailable

---

## Draft PR Orchestrator

### Overview

The Draft PR Orchestrator converts ambiguous stories into safe, code-scoped, reality-verified Draft PRs through a complete pipeline: **PLAN → APPROVAL → APPLY → VERIFY → PACKAGE → DRAFT_PR**. It enforces CI-grade rigor for the *intent → change* workflow with human-in-the-loop approval, safety guards, and comprehensive artifact persistence.

### Key Features

- **Structured Planning**: AI-generated plans with scope, tests, failure modes, and rollback procedures
- **Human-in-the-Loop**: Approval workflow ensures no code changes without human consent
- **Plan Iteration**: Revise plans based on feedback with version comparison
- **Safety Guards**: Plan-apply guards verify changes match approved plans
- **Git Transaction Safety**: Atomic changes with rollback on failure
- **Verification Gates**: Automatic test, lint, and build execution before PR creation
- **Artifact Persistence**: All plans, diffs, logs, and PR metadata stored for auditability
- **YOLO Mode**: Policy-based auto-approval for low-risk changes

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
- Policy checks: file count, LOC delta, path restrictions
- Falls back to normal mode if policy not compliant
- Use for low-risk changes (docs, scripts, tools)

### Plan Specification

Plans are structured artifacts with:
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

### Plan Iteration

Users can iterate on plans:
1. Review generated plan
2. Submit feedback with concerns and change requests
3. System generates revised plan version
4. Compare versions to see changes
5. Approve when satisfied

**Features:**
- Immutable plan versions (never modified)
- Feedback history tracked per version
- Version comparison highlights changes
- Previous approval invalidated on revision

### Safety Mechanisms

1. **Plan Hash Binding**: Approval cryptographically bound to plan hash
2. **Plan-Apply Guards**: Verifies actual changes match approved plan
3. **Git Transaction Safety**: Atomic operations with rollback on failure
4. **Verification Gates**: PR only created if tests/lint/build pass
5. **Artifact Persistence**: All evidence stored for auditability
6. **Workspace Fingerprinting**: Reproducible workspace state

### API Endpoints

- `POST /draft-pr/create` - Create new Draft PR job
- `GET /draft-pr/jobs/{job_id}` - Get job status
- `GET /draft-pr/jobs/{job_id}/plan` - Get latest plan
- `GET /draft-pr/jobs/{job_id}/plans` - List all plan versions with metadata
- `GET /draft-pr/jobs/{job_id}/plans/{version}` - Get specific plan version
- `POST /draft-pr/jobs/{job_id}/revise-plan` - Submit feedback and revise plan
- `GET /draft-pr/jobs/{job_id}/plans/compare` - Compare plan versions
- `POST /draft-pr/jobs/{job_id}/approve` - Approve plan to proceed
- `GET /draft-pr/jobs/{job_id}/artifacts` - List all artifacts
- `GET /draft-pr/jobs/{job_id}/artifacts/{artifact_type}` - Get specific artifact

### Configuration

```yaml
draft_pr:
  yolo_policy:
    max_files: 5
    max_loc_delta: 200
    allow_paths: ["docs/**", "scripts/**"]
    deny_paths: ["auth/**", "billing/**"]
    require_tests: false
  
  verification:
    test_command: "pytest"
    lint_command: "ruff check"
    build_command: ""
  
  protected_paths:
    billing/**:
      require: finance_team
```

### Usage Example

```bash
# 1. Create Draft PR job
POST /draft-pr/create
{
  "story_key": "STORY-123",
  "repos": [{"url": "https://bitbucket.org/workspace/repo.git"}],
  "mode": "normal"
}

# 2. Review plan
GET /draft-pr/jobs/{job_id}/plan

# 3. Approve plan
POST /draft-pr/jobs/{job_id}/approve
{
  "plan_hash": "abc123..."
}

# 4. Monitor progress
GET /draft-pr/jobs/{job_id}
# Pipeline continues: APPLY → VERIFY → PACKAGE → DRAFT_PR
```

### Related Documentation

- [Draft PR Orchestrator Guide](DRAFT_PR_ORCHESTRATOR.md) - Complete guide with examples
- [API Documentation](../api/API_DOCUMENTATION.md#draft-pr-orchestrator) - API reference
- [Product Requirements Document](../../opencode_coder.md) - PRD specification

---

## OpenCode Integration

### Overview

OpenCode is a code-aware execution engine that analyzes repositories to generate task breakdowns and ticket descriptions. When OpenCode is enabled and the `repos` parameter is provided in API requests, Augment uses OpenCode containers instead of direct LLM calls.

### Key Features

- **Code-Aware Generation**: Analyzes actual repository contents for context-aware task breakdowns
- **File Path References**: Generates content that references actual file paths and code structure
- **Impact Analysis**: Identifies impacted files for changes
- **Implementation-Specific**: Creates implementation-specific task breakdowns based on codebase patterns
- **Docker-Based**: Runs in isolated Docker containers for security and reproducibility

### LLM Configuration for OpenCode

**IMPORTANT**: OpenCode requires **separate, OpenCode-specific LLM configuration**. It does **NOT** use the main LLM configuration. This ensures OpenCode uses separate API keys from the main application.

#### How It Works

1. **Separate Configuration**: OpenCode uses its own set of environment variables prefixed with `OPENCODE_`. These are completely independent from the main LLM configuration.

2. **Environment Variable Mapping**: OpenCodeRunner maps OpenCode-specific configuration to the following environment variables inside containers:
   - `OPENAI_API_KEY` (from `OPENCODE_OPENAI_API_KEY`)
   - `ANTHROPIC_API_KEY` (from `OPENCODE_ANTHROPIC_API_KEY`)
   - `GOOGLE_API_KEY` (from `OPENCODE_GOOGLE_API_KEY`)
   - `MOONSHOT_API_KEY` (from `OPENCODE_MOONSHOT_API_KEY`)
   - `LLM_PROVIDER` (from `OPENCODE_LLM_PROVIDER`)
   - `LLM_MODEL` (from `OPENCODE_*_MODEL` based on provider)

3. **No Fallback**: OpenCode does **NOT** fall back to main LLM configuration. All required OpenCode-specific variables must be set.

### Setup Instructions

#### 1. Enable OpenCode

Enable OpenCode in your `.env` file:

```bash
OPENCODE_ENABLED=true
```

#### 2. Configure OpenCode-Specific LLM Provider (REQUIRED)

**IMPORTANT**: OpenCode requires its own provider configuration. It does NOT use the main `LLM_PROVIDER`.

Set the OpenCode-specific provider:

```bash
OPENCODE_LLM_PROVIDER=claude  # Options: openai, claude, gemini, kimi
```

#### 3. Set OpenCode-Specific API Key and Model (REQUIRED)

Set the API key and model for your chosen provider. These are **separate** from the main LLM configuration:

**For OpenAI:**
```bash
OPENCODE_OPENAI_API_KEY=sk-...
OPENCODE_OPENAI_MODEL=gpt-5-mini
```

**For Anthropic (Claude):**
```bash
OPENCODE_ANTHROPIC_API_KEY=sk-ant-api03-...
OPENCODE_ANTHROPIC_MODEL=claude-haiku-4-5
```

**For Google (Gemini):**
```bash
OPENCODE_GOOGLE_API_KEY=...
OPENCODE_GOOGLE_MODEL=gemini-2.5-flash
```

**For Moonshot AI (KIMI):**
```bash
OPENCODE_MOONSHOT_API_KEY=...
OPENCODE_MOONSHOT_MODEL=moonshot-v1-8k
```

#### 4. Configure OpenCode Settings (Optional)

These settings control OpenCode container behavior, resource limits, and repository handling:

```bash
# Docker Configuration
OPENCODE_DOCKER_IMAGE=ghcr.io/anomalyco/opencode  # Docker image for OpenCode containers (default: ghcr.io/anomalyco/opencode)

# Concurrency and Resource Limits
OPENCODE_MAX_CONCURRENT=2  # Maximum number of concurrent OpenCode containers (default: 2). Prevents resource exhaustion.
OPENCODE_MAX_REPOS=5  # Maximum number of repositories allowed per job (default: 5). Validates repository count in API requests.
OPENCODE_TIMEOUT=20  # Job timeout in minutes (default: 20). Maximum execution time for OpenCode jobs.
OPENCODE_CLONE_TIMEOUT=300  # Git clone timeout in seconds (default: 300). Timeout for repository cloning operations.
OPENCODE_SHALLOW_CLONE=true  # Use shallow clone with --depth 1 (default: true). Faster cloning, only latest commit.
OPENCODE_MAX_RESULT_SIZE=10  # Maximum result file size in MB (default: 10). Prevents oversized result files.
```

**Configuration Details:**
- **OPENCODE_DOCKER_IMAGE**: Specifies which Docker image to use. The default image is automatically pulled on worker startup.
- **OPENCODE_MAX_CONCURRENT**: Limits how many OpenCode containers can run simultaneously. Increase if you have more resources.
- **OPENCODE_MAX_REPOS**: Validates the number of repositories in API requests. Prevents jobs from processing too many repos at once.
- **OPENCODE_TIMEOUT**: Maximum time a job can run before being terminated. Increase for large repositories or complex analysis.
- **OPENCODE_CLONE_TIMEOUT**: Time limit for git clone operations. Increase for large repositories or slow network connections.
- **OPENCODE_SHALLOW_CLONE**: When `true`, only clones the latest commit (faster). Set to `false` for full history (slower but more complete).
- **OPENCODE_MAX_RESULT_SIZE**: Maximum size of result files in MB. Prevents memory issues from oversized results.

#### 5. Set Git Credentials (Required for Private Repos, Optional for Public)

Git credentials are required when cloning private repositories via HTTPS. For public repositories, these can be left empty.

```bash
# Git Credentials (Required for Private Repositories, Optional for Public)
GIT_USERNAME=your-username  # Git username or email (required for private repos)
GIT_PASSWORD=your-token-or-password  # Git password, personal access token, or app password (required for private repos)
```

**Git Credential Details:**
- **GIT_USERNAME**: Your Git username or email address
- **GIT_PASSWORD**: Your Git password, personal access token, or app password
- **For Bitbucket**: Use App Password (create at: https://bitbucket.org/account/settings/app-passwords/)
- **For GitHub**: Use Personal Access Token (create at: https://github.com/settings/tokens)
- **For GitLab**: Use Personal Access Token (create at: https://gitlab.com/-/profile/personal_access_tokens)
- **Note**: SSH URLs (`git@...`) use SSH keys, not these credentials

#### 6. Optional: OpenCode-Specific Temperature and Max Tokens

```bash
OPENCODE_LLM_TEMPERATURE=0.7  # Optional, defaults to 0.7
OPENCODE_LLM_MAX_TOKENS=      # Optional, uses provider defaults if not set
```

### Prerequisites

- **Docker**: Must be installed and running
- **Git credentials**: For cloning private repositories
- **OpenCode-Specific LLM Configuration**: All required OpenCode-specific variables must be set:
  - `OPENCODE_LLM_PROVIDER` (REQUIRED)
  - `OPENCODE_*_API_KEY` for your provider (REQUIRED)
  - `OPENCODE_*_MODEL` for your provider (REQUIRED)

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

### Agents.md Distribution

When OpenCode containers are created with the `repos` parameter, the system automatically distributes `Agents.md` files to guide OpenCode agents on MCP usage:

**Automatic Distribution:**
- `Agents.md` files are created in each cloned repository root directory
- Also created at workspace root level for easy reference
- Happens automatically after repositories are cloned

**Smart Content Merging:**
- **If `Agents.md` exists**: OpenCode MCP integration section is appended (existing content preserved)
- **If `Agents.md` doesn't exist**: New file is created with OpenCode MCP instructions
- **Idempotent**: Safe to run multiple times (prevents duplicate content)

**Content Includes:**
- Available MCP servers (Bitbucket and Atlassian)
- When to use each MCP (code vs documentation vs tickets)
- Read-only constraints and safety rules
- Best practices for data fetching (always fetch real data, minimize calls)
- Reference to `/app/opencode.json` for MCP configuration

**Safety Features:**
- Path sanitization prevents security issues
- File size limits (10MB max for existing files)
- Encoding error handling (UTF-8 with fallback)
- Atomic file writes (prevents corruption)
- Idempotency checks (prevents duplicate appends)

### Repository Specification

The `repos` parameter accepts an array of repository specifications:

**String format** (simple):
```json
"repos": ["https://github.com/org/repo.git"]
```

**Object format** (with branch):
```json
"repos": [
  {"url": "https://github.com/org/repo.git", "branch": "main"}
]
```

### Troubleshooting

#### OpenCode containers can't access LLM

**Problem**: OpenCode containers fail with authentication errors (401).

**Solution**: 
- Verify your **OpenCode-specific** API key is correct (e.g., `OPENCODE_ANTHROPIC_API_KEY`, not `ANTHROPIC_API_KEY`)
- Check that `OPENCODE_LLM_PROVIDER` matches your API key provider
- Ensure all required OpenCode-specific variables are set:
  - `OPENCODE_LLM_PROVIDER` (REQUIRED)
  - `OPENCODE_*_API_KEY` for your provider (REQUIRED)
  - `OPENCODE_*_MODEL` for your provider (REQUIRED)
- Ensure Docker has access to environment variables (restart Docker if needed)

#### Wrong LLM model being used

**Problem**: OpenCode uses a different model than expected.

**Solution**:
- Verify `OPENCODE_LLM_PROVIDER` is set correctly
- Check that the OpenCode-specific model environment variable is set (e.g., `OPENCODE_ANTHROPIC_MODEL`, not `ANTHROPIC_MODEL`)
- Remember: OpenCode uses `OPENCODE_*` prefixed variables, not the main LLM variables

#### OpenCode not using configured LLM

**Problem**: OpenCode seems to use default settings or fails with "Missing API key" errors.

**Solution**:
- Ensure `.env` file is loaded (check `load_dotenv()` is called)
- Verify **OpenCode-specific** environment variables are set (prefixed with `OPENCODE_`)
- OpenCode does NOT use main LLM configuration - you must set OpenCode-specific variables
- Check OpenCodeRunner logs for which environment variables are being passed
- Look for error messages indicating which variable is missing

#### Docker-related issues

**Problem**: "Docker is not available" or "Image pull failed"

**Solution**:
- Ensure Docker daemon is running (`docker ps`)
- Check network connectivity for image pulling
- Verify Docker has access to environment variables
- The OpenCode Docker image is automatically pulled on worker startup

#### Clone timeout

**Problem**: Repository cloning times out

**Solution**:
- Increase `OPENCODE_CLONE_TIMEOUT` (default: 300 seconds)
- Check repository access and credentials
- Verify Git credentials are correct for private repositories
- Consider using `OPENCODE_SHALLOW_CLONE=true` for faster cloning

#### Job timeout

**Problem**: OpenCode jobs timeout before completion

**Solution**:
- Increase `OPENCODE_TIMEOUT` (default: 20 minutes)
- Reduce number of repositories per job (`OPENCODE_MAX_REPOS`)
- Check repository size and complexity

### Example Configuration

```bash
# Main LLM Configuration (for direct LLM calls, not used by OpenCode)
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-api03-...
ANTHROPIC_MODEL=claude-sonnet-4-5
LLM_TEMPERATURE=0.7

# OpenCode Configuration (REQUIRED - separate from main LLM config)
OPENCODE_ENABLED=true
OPENCODE_LLM_PROVIDER=claude  # REQUIRED: OpenCode-specific provider
OPENCODE_ANTHROPIC_API_KEY=sk-ant-api03-...  # REQUIRED: OpenCode-specific API key
OPENCODE_ANTHROPIC_MODEL=claude-haiku-4-5  # REQUIRED: OpenCode-specific model
OPENCODE_LLM_TEMPERATURE=0.7  # Optional: defaults to 0.7

# OpenCode Docker Settings
OPENCODE_DOCKER_IMAGE=ghcr.io/anomalyco/opencode
OPENCODE_MAX_CONCURRENT=2
OPENCODE_MAX_REPOS=5
OPENCODE_TIMEOUT=20
OPENCODE_CLONE_TIMEOUT=300
OPENCODE_SHALLOW_CLONE=true

# Git Credentials (for private repos)
GIT_USERNAME=your-username
GIT_PASSWORD=your-token
```

**Important Notes:**
- OpenCode uses `OPENCODE_*` prefixed variables, which are **separate** from main LLM configuration
- You can use different providers/models for OpenCode vs main LLM calls
- All OpenCode-specific variables (`OPENCODE_LLM_PROVIDER`, `OPENCODE_*_API_KEY`, `OPENCODE_*_MODEL`) are **REQUIRED**

### MCP Server Integration

OpenCode containers can access external data sources (Bitbucket, Jira, Confluence) via MCP (Model Context Protocol) servers. MCP servers run as persistent services separate from OpenCode containers.

**Benefits:**
- **Real Data Access**: OpenCode can fetch actual Jira issues, Confluence pages, and Bitbucket files/PRs
- **Read-Only Safety**: All MCP servers are configured for read-only operations
- **Network Isolation**: MCP servers run on isolated Docker network for security
- **Automatic Connection**: OpenCode containers automatically connect to MCP network when available

**Setup:**
1. Start MCP servers: `python main.py mcp start` (automatically generates `docker-compose.mcp.yml` based on workspaces)
2. OpenCode containers automatically get dynamically generated `opencode.json` with appropriate MCP URLs based on repos being analyzed (no manual configuration needed)
3. Ensure MCP servers are running before using OpenCode with `repos` parameter

**MCP Servers:**
- **Bitbucket MCP**: One instance per workspace (automatically created based on `BITBUCKET_WORKSPACES`)
  - Provides access to repositories, files, PRs, and commits
  - Each workspace gets its own MCP instance with unique port and hostname (`bitbucket-mcp-{workspace}`)
- **Atlassian MCP**: Single instance providing access to Jira issues and Confluence pages

**Configuration:**
**IMPORTANT**: MCP servers use the **SAME environment variables as the main application**. No duplicate variables needed!

MCP servers automatically use:
- `JIRA_SERVER_URL`, `JIRA_USERNAME`, `JIRA_API_TOKEN` (from main app configuration)
- `CONFLUENCE_SERVER_URL`, `CONFLUENCE_USERNAME`, `CONFLUENCE_API_TOKEN` (from main app configuration)
- `BITBUCKET_EMAIL`, `BITBUCKET_API_TOKEN`, `BITBUCKET_WORKSPACES` (from main app configuration)

**Multi-Workspace Support:**
If `BITBUCKET_WORKSPACES` contains multiple workspaces (comma-separated), the system automatically creates one Bitbucket MCP instance per workspace with unique ports (7001, 7002, 7003...) and hostnames.

The generated `opencode.json` always uses `bitbucket-{workspace}` format for all workspaces (single or multiple), ensuring consistent behavior and full access to all configured workspaces.

For detailed MCP setup instructions, see [MCP Setup Guide](../technical/MCP_SETUP.md).

### Debug Conversation Logging

OpenCode includes an optional debug mode that captures and stores full conversation logs for troubleshooting and analysis.

#### Overview

When enabled, debug conversation logging:
- **Captures full SSE events**: Records complete event data (not truncated) from OpenCode conversations
- **Saves dual-format logs**: Creates both JSON (structured) and text (human-readable) files
- **Preserves on errors**: Logs are saved even if jobs fail or are cancelled
- **Zero performance impact when disabled**: Debug mode is off by default

#### Configuration

Enable debug conversation logging in your `.env` file:

```bash
# Enable debug conversation logging
OPENCODE_DEBUG_LOGGING=true

# Optional: Custom log directory (defaults to logs/opencode)
OPENCODE_LOG_DIR=logs/opencode
```

Or in `config.yaml`:

```yaml
opencode:
  debug_conversation_logging: true
  conversation_log_dir: logs/opencode  # Optional, defaults to logs/opencode
```

#### Log Files

When debug mode is enabled, two files are created for each OpenCode job:

1. **`{job_id}.json`** - Structured JSON format with:
   - Job metadata (job_id, start_time, end_time, duration)
   - Full prompt text
   - Complete event log with timestamps, event types, and data

2. **`{job_id}.log`** - Human-readable text format with:
   - Job summary (start time, end time, duration)
   - Full prompt text
   - Chronological event log with formatted timestamps

**Example JSON structure:**
```json
{
  "job_id": "abc123",
  "start_time": "2024-01-01T12:00:00.000Z",
  "end_time": "2024-01-01T12:05:30.123Z",
  "duration_seconds": 330.123,
  "prompt": "Generate task breakdown for...",
  "events": [
    {
      "timestamp": 1704110400.123,
      "event_type": "message",
      "data": "Event data...",
      "raw_event": {...}
    }
  ]
}
```

**Example text format:**
```
OpenCode Conversation Log - Job: abc123
Started: 2024-01-01T12:00:00.000Z
Ended: 2024-01-01T12:05:30.123Z
Duration: 330.123s

================================================================================
PROMPT
================================================================================
Generate task breakdown for...

================================================================================
EVENTS
================================================================================
[2024-01-01 12:00:00.123] [message] Event data...
[2024-01-01 12:00:01.456] [done]
```

#### Use Cases

Debug conversation logging is useful for:
- **Troubleshooting**: Understanding why OpenCode generated unexpected results
- **Prompt optimization**: Analyzing how prompts are processed and responded to
- **Performance analysis**: Reviewing conversation flow and timing
- **Debugging errors**: Inspecting full event sequences when jobs fail
- **Audit trails**: Maintaining records of AI-generated content

#### Important Notes

- **Disabled by default**: Debug logging is off by default to avoid unnecessary I/O
- **Error resilient**: Log failures don't impact job execution (warnings logged, job continues)
- **Automatic directory creation**: Log directory is created automatically if it doesn't exist
- **Per-job files**: Each job gets its own log files, identified by `job_id`
- **Full event capture**: All SSE events are captured, including errors and completion events

### Technical Details

#### Configuration Flow

1. `Config.get_opencode_llm_config()` returns a dict with:
   - `provider`: The LLM provider name (from `OPENCODE_LLM_PROVIDER`)
   - `api_key`: The API key (from `OPENCODE_*_API_KEY`)
   - `model`: The model name (from `OPENCODE_*_MODEL`)
   - Other settings (temperature, max_tokens, etc.)

2. `OpenCodeRunner._build_container_environment()` transforms this to:
   - Provider-specific API key environment variables
   - `LLM_PROVIDER` environment variable
   - `LLM_MODEL` environment variable

3. These environment variables are passed to the Docker container when it starts.

#### Supported Providers

- **OpenAI**: `openai` → Uses `OPENCODE_OPENAI_API_KEY` and `OPENCODE_OPENAI_MODEL`
- **Anthropic**: `claude` → Uses `OPENCODE_ANTHROPIC_API_KEY` and `OPENCODE_ANTHROPIC_MODEL`
- **Google**: `gemini` → Uses `OPENCODE_GOOGLE_API_KEY` and `OPENCODE_GOOGLE_MODEL`
- **Moonshot**: `kimi` → Uses `OPENCODE_MOONSHOT_API_KEY` and `OPENCODE_MOONSHOT_MODEL`

### Session Completion & Execution Flow

#### How Session Completion is Detected

OpenCode uses an **event-driven architecture** rather than polling:

- **No Polling**: The system does not poll for completion status. Instead, it uses Server-Sent Events (SSE) streaming for real-time communication with OpenCode containers.

- **Completion Detection Methods**:
  1. **SSE "done" event**: For streaming responses, the system listens for a "done" event from OpenCode via SSE. When this event is received, the session is considered complete.
  2. **JSON response**: For non-streaming responses, OpenCode may return a JSON response immediately, which indicates completion.

- **Post-Completion Steps**:
  1. After streaming completes (via "done" event or JSON response), there's a brief 1-second delay to allow file system writes to complete.
  2. The system then reads the result file (`result.json`) from the workspace.
  3. The result is validated against expected schemas and returned.

- **Timeout Protection**: The overall job timeout (`OPENCODE_TIMEOUT`, default: 20 minutes) applies to the entire operation, ensuring jobs don't hang indefinitely if OpenCode fails to send completion signals.

#### Execution Flow

1. **Container Spawn**: OpenCode container is started with workspace mounted
2. **Session Creation**: HTTP POST to `/session` endpoint creates a session and returns `session_id`
3. **Prompt Submission**: HTTP POST to `/session/{session_id}/message` with prompt
4. **Streaming Response**: 
   - If response is `text/event-stream`, system streams SSE events until "done" event
   - If response is `application/json`, completion is immediate
5. **Result Extraction**: After completion, reads `result.json` from workspace
6. **Container Cleanup**: Container is stopped and removed

This event-driven approach is more efficient than polling and provides real-time feedback during execution.

---

## Related Documentation

- [API Documentation](../api/API_DOCUMENTATION.md) - Complete API reference
- [Technical Documentation](../technical/TECHNICAL.md) - Technical implementation details

