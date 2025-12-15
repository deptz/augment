# Technical Documentation

This document provides technical implementation details, architecture decisions, and deep-dive information about the Augment system.

## Table of Contents

1. [Ticket Linking Strategy](#ticket-linking-strategy)
2. [Confluence Content Extraction](#confluence-content-extraction)
3. [PRD/RFC Document Processing](#prdrfc-document-processing)
4. [RFC Integration](#rfc-integration)
5. [Team Member Database](#team-member-database)

---

## Ticket Linking Strategy

### Overview

The system uses JIRA issue links to establish relationships between tickets. This document explains the linking strategy, supported link types, and how relationships are created.

### JIRA Hierarchy Requirements

This system works with JIRA instances that have the following hierarchy:
- **Epic** (hierarchyLevel: 1) → **Story** (hierarchyLevel: 0) 
- **Epic** (hierarchyLevel: 1) → **Task** (hierarchyLevel: 0)
- **Story** and **Task** are siblings under Epic (Tasks cannot be children of Stories)

### Supported Link Types

The system automatically detects available link types in your JIRA instance. Common link types used:

#### Work Item Split
- **Purpose**: Parent-child relationships between stories and tasks
- **Inward**: "split from" - Task is split from Story
- **Outward**: "split to" - Story is split to Task
- **Usage**: Links tasks to their parent stories

#### Blocks / Blocked By
- **Purpose**: Task dependency relationships
- **Inward**: "is blocked by" - Task is blocked by another task
- **Outward**: "blocks" - Task blocks another task
- **Usage**: Creates dependency relationships between tasks

#### Relates To
- **Purpose**: General relationships (used as fallback)
- **Inward**: "relates to"
- **Outward**: "relates to"
- **Usage**: Fallback when preferred link types fail

### Link Type Discovery

The system includes automatic link type discovery:
- Queries JIRA instance for available link types via `/rest/api/3/issueLinkType`
- Provides detailed debugging when preferred link types are not available
- Falls back to alternative link types when needed
- Logs all available link types for troubleshooting

### Link Creation Logic

#### Story-Task Relationships

Tasks are created under epics (not stories) to comply with JIRA hierarchy rules. Story-task relationships are created via "Work item split" links:

```python
# Task -> Story (inward: "split from")
create_issue_link(task_key, story_key, "Work item split", direction="inward")

# Story -> Task (outward: "split to")  
create_issue_link(story_key, task_key, "Work item split", direction="outward")
```

#### Task Dependencies

Tasks that depend on others create "Blocks" relationships:

```python
# Blocking task blocks dependent task
create_issue_link(blocking_task_key, dependent_task_key, "Blocks")
```

### Smart Split Detection

The API includes "smart split detection" where if `link_type` contains "split", it automatically determines the direction:
- **Inward** (Task -> Story): Task is split from Story
- **Outward** (Story -> Task): Story is split to Task

Direction is determined based on ticket types.

### Error Handling

- **Link Type Not Found**: System queries available link types and suggests alternatives
- **Duplicate Prevention**: Checks for existing links before creation
- **Fallback Mechanisms**: Falls back to "Relates to" if preferred link types fail
- **Comprehensive Logging**: Detailed debug logging

### Debug and Monitoring

- **Enhanced Logging**: Comprehensive debug logging
- **Relationship Tracking**: Detailed logging of all relationship creation attempts
- **Error Context**: Rich error messages with ticket keys and relationship types
- **Link Type Discovery**: Automatic querying and logging of available link types

---

## Confluence Content Extraction

### Overview

The system uses BeautifulSoup for robust Confluence content extraction, supporting both PRD and RFC document formats with enhanced section detection.

**Key Features:**
- **Structured Macros**: Properly extracts content from `<ac:structured-macro>` elements
- **Complex Nesting**: Handles deeply nested HTML structures
- **Macro Intelligence**: Converts Confluence-specific elements (code, info, warning, note) into readable text
- **Smart Section Detection**: Multiple fallback strategies for finding content sections

### PRD/RFC Section Extraction

**Core PRD Sections Extracted:**
- Target Population
- User Value
- Business Value
- Proposed Solution
- Success Criteria
- Constraints & Limitations
- Supporting Documents
- User Stories

**Core RFC Sections Extracted:**
- Overview
- Technical Design
- High Availability & Security
- Backwards Compatibility & Rollout Plan
- Concerns, Questions, or Known Limitations
- Alternatives Considered
- Risks & Mitigations
- Testing Strategy
- Timeline

**Enhanced Processing Features:**
- Pattern-based section detection using heading IDs and text patterns
- Prioritized content extraction for key business context
- Improved text extraction with content length validation
- Template-specific patterns for Confluence document structure

---

## PRD/RFC Document Processing

### Overview

The system processes both PRD (Product Requirements Documents) and RFC (Request for Comments) documents from Confluence, extracting structured sections for use in task and test generation.

### Document Context Flow

```
Epic Ticket → PRD/RFC Custom Field → Confluence Page → Section Extraction → Task/Test Generation
```

### Extraction Strategies

The system uses multiple extraction strategies:
1. **ID-Based Matching**: Matches section IDs from Confluence
2. **Text Pattern Matching**: Falls back to heading text patterns
3. **Hierarchical Parsing**: Extracts content until next heading
4. **Content Validation**: Ensures meaningful content extraction

### Integration with Task Generation

PRD/RFC documents provide context for:
- **Epic Analysis**: Business and technical context for epics
- **Task Generation**: Technical and business requirements for tasks
- **Test Generation**: Test scenarios based on requirements and design

---

## RFC Integration Summary

### Overview

Complete integration of RFC (Request for Comments) document support into the system.

### RFC Sections Supported

- **Overview**: Success criteria, scope, assumptions, dependencies
- **Technical Design**: Architecture, tech stack, APIs, database models
- **High Availability & Security**: HA requirements, security implications
- **Backwards Compatibility & Rollout Plan**: Compatibility, rollout strategy
- **Concerns, Questions, or Known Limitations**: Risk identification
- **Alternatives Considered**: Decision rationale
- **Risks & Mitigations**: Risk management
- **Testing Strategy**: Test approach
- **Timeline**: Implementation timeline

### Integration Benefits

- **Technical Context**: Rich technical design information
- **Architecture Awareness**: System architecture and design decisions
- **Risk Management**: Identified risks and mitigations
- **Implementation Guidance**: Technical implementation details

---

## Team Member Database

### Overview

The system uses a SQLite database to store team member, team, and board information for sprint planning and capacity management.

### Database Configuration

**Location:**
- Default: `data/team_members.db` (relative to project root)
- Configurable via `TEAM_MEMBER_DB_PATH` environment variable
- Supports both absolute and relative paths

**Auto-Initialization:**
- Database is automatically created on first use
- Schema is initialized automatically when the module is imported
- Parent directories are created if they don't exist
- No manual database setup required

**Startup Verification:**
- Database readiness is checked during API server startup
- Verifies: accessibility, required tables exist, write permissions
- Automatically attempts initialization if database is missing or incomplete
- Logs clear error messages if database cannot be made ready

**Health Check Integration:**
- Database status included in `/health` endpoint
- Returns `"ready"` if healthy, or detailed error message if not
- Overall health status set to `"degraded"` if database is unavailable

### Database Schema

The database includes the following tables:
- `members` - Team member information (name, email, level, capacity)
- `teams` - Team definitions (name, description)
- `boards` - JIRA board information (board ID, name, project key)
- `member_teams` - Many-to-many relationship between members and teams
- `team_boards` - Many-to-many relationship between teams and boards

### Implementation Details

**File:** `src/team_member_db.py`

**Key Functions:**
- `get_db_path()` - Resolves database path from environment or default
- `get_db_connection()` - Creates database connection, ensuring directory exists
- `init_database()` - Initializes database schema with all tables and indexes
- `check_database_ready()` - Verifies database is accessible and properly initialized
- `ensure_database_ready()` - Ensures database is ready, initializing if necessary

**Startup Integration:**
- Called during FastAPI startup event (`api/main.py`)
- Runs before service initialization
- Non-blocking: logs warnings but continues startup if check fails

---

## PRD Table Updates

### Overview

The system automatically updates PRD (Product Requirements Document) tables in Confluence with JIRA ticket links when stories are created or updated. This ensures PRD documents stay synchronized with JIRA tickets.

### Key Features

- **Automatic Column Creation**: Creates "JIRA Ticket" column in PRD table if it doesn't exist
- **UUID-Based Row Matching**: Uses temporary UUIDs for exact row matching during PRD sync
- **Fuzzy Matching Fallback**: Falls back to fuzzy matching by story title if UUID is not available
- **HTML Link Formatting**: Formats JIRA links as proper HTML anchor tags for Confluence compatibility
- **Cell Management**: Automatically adds missing cells to rows that are too short

### Implementation Details

**File:** `src/prd_table_updater.py`

**Key Functions:**
- `_add_jira_ticket_column()`: Creates "JIRA Ticket" column if missing (uses `soup.new_tag()` for HTML tag creation)
- `add_uuid_placeholder_to_row()`: Adds temporary UUID placeholder to PRD table row during dry run
- `find_row_by_uuid()`: Locates PRD table row by UUID placeholder
- `replace_uuid_with_jira_link()`: Replaces UUID placeholder with actual JIRA link
- `update_story_row_with_jira_link()`: Updates PRD table row with JIRA link using fuzzy matching

**File:** `src/planning_service.py`

**Key Functions:**
- `_update_prd_table_for_story()`: Reusable method for single-story PRD updates
- `_update_prd_table_with_story_links_uuid()`: Handles PRD updates for multiple stories with UUID support
- `sync_stories_from_prd_table()`: PRD sync flow that generates UUIDs during dry run and updates table during creation

### UUID-Based Matching Flow

1. **Dry Run Mode:**
   - System generates UUID for each story to be created
   - UUID is stored in `StoryPlan.prd_row_uuid`
   - UUID placeholder is added to PRD table: `[TEMP-{uuid}](placeholder)`
   - PRD page is saved with UUID placeholders

2. **Actual Creation:**
   - When story is created, `prd_row_uuid` is passed to PRD update function
   - System finds PRD row by UUID using `find_row_by_uuid()`
   - UUID placeholder is replaced with actual JIRA link using `replace_uuid_with_jira_link()`

3. **Fallback:**
   - If UUID is not available (e.g., manual story creation), system uses fuzzy matching
   - Fuzzy matching compares story title/summary with PRD table row titles
   - Uses `update_story_row_with_jira_link()` for fuzzy matching

### HTML Link Formatting

Confluence expects HTML anchor tags for clickable links, not markdown. The system creates proper HTML:

```python
jira_cell.clear()
link_tag = soup.new_tag("a", href=jira_url)
link_tag.string = jira_key
jira_cell.append(link_tag)
```

This ensures links are clickable in Confluence pages.

### Column Creation

The system automatically creates the "JIRA Ticket" column if it doesn't exist:

1. Checks if column exists by searching for header text
2. If missing, creates new `<th>` header cell using `soup.new_tag("th")`
3. Adds column to all existing rows
4. Handles edge cases where rows have different cell counts

**Important:** The `soup` object (BeautifulSoup root) must be used for `new_tag()`, not the `table` object. The system traverses the table's parent chain to find the BeautifulSoup root if not provided.

### Update Flows

**Story Creation:**
- `POST /jira/create-story-ticket`: Updates PRD table after story creation
- `POST /jira/bulk-create-stories`: Updates PRD table for each created story

**Story Updates:**
- `POST /jira/update-story-ticket`: Updates PRD table after story update
- `POST /jira/bulk-update-stories`: Updates PRD table for each updated story

**PRD Sync:**
- `POST /plan/stories/sync-from-prd`: Updates PRD table for both new and existing stories (when `existing_ticket_action="update"`)

### Error Handling

- PRD updates are non-blocking: failures don't prevent story creation/updates
- Errors are logged as warnings, not errors
- System gracefully handles missing PRD documents, missing rows, or Confluence API failures
- Column creation failures are logged but don't stop the update process

---

## Related Documentation

- [API Documentation](../api/API_DOCUMENTATION.md) - API reference
- [Features Documentation](../features/FEATURES.md) - Feature documentation

