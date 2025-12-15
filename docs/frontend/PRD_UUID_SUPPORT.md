# Frontend Update: PRD Story Sync UUID Support

## Overview
The PRD story sync API now supports UUID-based row matching. UUIDs are generated during dry run and can be used for exact PRD table row matching when creating stories.

## API Changes

### 1. PRD Sync Response (`POST /plan/stories/sync-from-prd`)
The `story_details` array now includes an optional `prd_row_uuid` field:

```typescript
interface StoryDetail {
  // ... existing fields
  prd_row_uuid?: string; // UUID for matching PRD table row (from dry run)
}
```

**When present:**
- UUID is generated during dry run mode
- UUID is stored in PRD table as placeholder: `[TEMP-{uuid}](placeholder)`
- UUID should be preserved and used when creating the story

### 2. Create Story Request (`POST /jira/create-story-ticket`)
New optional field added:

```typescript
interface CreateStoryTicketRequest {
  // ... existing fields
  prd_row_uuid?: string; // Optional UUID for exact PRD row matching
}
```

### 3. Bulk Create Stories Request (`POST /jira/bulk-create-stories`)
Each story item now supports UUID:

```typescript
interface BulkCreateStoryItem {
  // ... existing fields
  prd_row_uuid?: string; // Optional UUID for exact PRD row matching
}
```

## Frontend Implementation Requirements

### 1. Display UUID in PRD Sync Results
- Show `prd_row_uuid` in story details UI (optional, for debugging/transparency)
- UUID is only present for stories that will be created (not for existing stories)

### 2. Preserve UUID in Story Creation Flow
When user creates a story after PRD sync:
- If story has `prd_row_uuid` from sync response, include it in the create request
- This ensures exact row matching in PRD table (no fuzzy matching needed)

### 3. Workflow Support
**Recommended flow:**
1. User runs PRD sync in dry run mode → receives stories with UUIDs
2. User reviews stories
3. User creates stories → UUIDs automatically included from sync response
4. PRD table is updated with exact row matches using UUIDs

### 4. UI Considerations
- UUID field is optional - don't require user input
- UUID should be automatically passed from sync response to creation request
- Consider showing UUID in story details for transparency (optional)

## Example Flow

```typescript
// 1. PRD Sync (dry run)
const syncResponse = await syncStoriesFromPRD({ epic_key, dry_run: true });
// Response includes: story_details[].prd_row_uuid

// 2. Create Story (use UUID from sync)
const story = syncResponse.story_details[0];
await createStoryTicket({
  parent_key: epic_key,
  summary: story.summary,
  description: story.description,
  prd_row_uuid: story.prd_row_uuid // Pass UUID for exact matching
});
```

## Notes
- UUID is only generated during dry run mode
- UUID is only present for stories that need to be created (not existing stories)
- If UUID is not provided, system falls back to fuzzy matching
- UUID format: standard UUID v4 (e.g., "550e8400-e29b-41d4-a716-446655440000")

