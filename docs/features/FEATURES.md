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

## Related Documentation

- [API Documentation](../api/API_DOCUMENTATION.md) - Complete API reference
- [Technical Documentation](../technical/TECHNICAL.md) - Technical implementation details

