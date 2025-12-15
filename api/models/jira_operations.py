"""
JIRA Operations Models
Request and response models for JIRA operation endpoints
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class IssueLinkRequest(BaseModel):
    """Request to create a link between tickets"""
    link_type: str = Field(
        ...,
        description="Link type name (e.g., 'Blocks', 'Relates', 'Split')",
        example="Blocks"
    )
    target_key: str = Field(
        ...,
        description="Target ticket key to link to",
        example="PROJ-456"
    )
    direction: str = Field(
        default="outward",
        description="Link direction: 'outward' (source -> target) or 'inward' (target -> source)",
        example="outward"
    )


class UpdateTicketRequest(BaseModel):
    """Request to update a JIRA ticket with partial updates support"""
    ticket_key: str = Field(
        ...,
        description="JIRA ticket key to update",
        example="PROJ-123"
    )
    summary: Optional[str] = Field(
        None,
        description="New ticket summary/title (optional, only updated if provided)"
    )
    description: Optional[str] = Field(
        None,
        description="New ticket description (optional, only updated if provided)"
    )
    test_cases: Optional[str] = Field(
        None,
        description="Test cases content for custom field (optional, only updated if provided)"
    )
    mandays: Optional[float] = Field(
        None,
        description="Mandays estimation value (optional, only updated if provided)"
    )
    links: Optional[List[IssueLinkRequest]] = Field(
        None,
        description="List of issue links to create (optional)"
    )
    update_jira: bool = Field(
        default=False,
        description="Update JIRA (default: false for preview mode)"
    )


class UpdateTicketResponse(BaseModel):
    """Response from updating a JIRA ticket"""
    success: bool = Field(..., description="Whether the operation was successful")
    ticket_key: str = Field(..., description="Ticket key that was updated")
    updated_in_jira: bool = Field(..., description="Whether JIRA was actually updated")
    updates_applied: Dict[str, bool] = Field(
        default_factory=dict,
        description="Dictionary of field names and whether they were successfully updated"
    )
    links_created: List[Dict[str, str]] = Field(
        default_factory=list,
        description="List of links that were created with details"
    )
    preview: Optional[Dict[str, Any]] = Field(
        None,
        description="Preview of changes (when update_jira=false)"
    )
    message: str = Field(..., description="Status message")
    error: Optional[str] = Field(None, description="Error message if failed")


class CreateTicketRequest(BaseModel):
    """Request to create a new JIRA Task ticket"""
    parent_key: str = Field(
        ...,
        description="Parent epic ticket key",
        example="PROJ-100"
    )
    summary: str = Field(
        ...,
        description="Task summary/title",
        example="Implement user authentication"
    )
    description: str = Field(
        ...,
        description="Task description",
        example="Add login functionality with email and password"
    )
    story_key: str = Field(
        ...,
        description="Story ticket key to link via split-from relationship",
        example="PROJ-123"
    )
    test_cases: Optional[str] = Field(
        None,
        description="Test cases content for custom field (optional)"
    )
    mandays: Optional[float] = Field(
        None,
        description="Mandays estimation value (optional, will be set as total_days in cycle time estimate)",
        example=2.0
    )
    blocks: Optional[List[str]] = Field(
        None,
        description="List of ticket keys that this task blocks (optional)",
        example=["PROJ-456", "PROJ-789"]
    )
    create_ticket: bool = Field(
        default=False,
        description="Create ticket in JIRA (default: false for preview mode)"
    )


class CreateTicketResponse(BaseModel):
    """Response from creating a new JIRA ticket"""
    success: bool = Field(..., description="Whether the operation was successful")
    ticket_key: Optional[str] = Field(None, description="Created ticket key (if actually created)")
    created_in_jira: bool = Field(..., description="Whether ticket was actually created in JIRA")
    links_created: List[Dict[str, str]] = Field(
        default_factory=list,
        description="List of links that were created with details"
    )
    preview: Optional[Dict[str, Any]] = Field(
        None,
        description="Preview of ticket that would be created (when create_ticket=false)"
    )
    message: str = Field(..., description="Status message")
    error: Optional[str] = Field(None, description="Error message if failed")


class CreateStoryTicketRequest(BaseModel):
    """Request to create a new JIRA Story ticket"""
    parent_key: str = Field(
        ...,
        description="Parent epic ticket key",
        example="EPIC-100"
    )
    summary: str = Field(
        ...,
        description="Story summary/title",
        example="User authentication feature"
    )
    description: str = Field(
        ...,
        description="Story description/context",
        example="As a user, I want to authenticate with email and password so that I can access my account"
    )
    test_cases: Optional[str] = Field(
        None,
        description="Test cases content for custom field (optional)"
    )
    prd_row_uuid: Optional[str] = Field(
        None,
        description="Optional UUID for matching PRD table row (from dry run preview)"
    )
    create_ticket: bool = Field(
        default=False,
        description="Create ticket in JIRA (default: false for preview mode)"
    )


class UpdateStoryTicketRequest(BaseModel):
    """Request to update a JIRA Story ticket"""
    story_key: str = Field(
        ...,
        description="The story ticket key you want to update",
        example="STORY-123"
    )
    summary: Optional[str] = Field(
        None,
        description="Update the story title. Leave empty to keep current title."
    )
    description: Optional[str] = Field(
        None,
        description="Update the story description. Leave empty to keep current description."
    )
    test_cases: Optional[str] = Field(
        None,
        description="Update test cases for this story. Leave empty to keep current test cases."
    )
    parent_key: Optional[str] = Field(
        None,
        description="Change the parent epic. Leave empty to keep current parent."
    )
    links: Optional[List[IssueLinkRequest]] = Field(
        None,
        description="Create links to other tickets. Leave empty if you don't need to add links."
    )
    update_jira: bool = Field(
        default=False,
        description="Set to true to actually update the ticket. Default is false (preview mode)."
    )


class StoryUpdateItem(BaseModel):
    """Individual story update request for bulk operations"""
    story_key: str = Field(
        ...,
        description="JIRA story ticket key to update",
        example="STORY-123"
    )
    summary: Optional[str] = Field(
        None,
        description="Update the story title. Leave empty to keep current title."
    )
    description: Optional[str] = Field(
        None,
        description="Update the story description. Leave empty to keep current description."
    )
    test_cases: Optional[str] = Field(
        None,
        description="Update test cases for this story. Leave empty to keep current test cases."
    )
    parent_key: Optional[str] = Field(
        None,
        description="Change the parent epic. Leave empty to keep current parent."
    )
    links: Optional[List[IssueLinkRequest]] = Field(
        None,
        description="Create links to other tickets. Leave empty if you don't need to add links."
    )


class StoryUpdateResult(BaseModel):
    """Result for individual story update in bulk operation"""
    story_key: str = Field(..., description="Story ticket key that was processed")
    success: bool = Field(..., description="Whether the update was successful")
    updated_in_jira: bool = Field(..., description="Whether JIRA was actually updated")
    updates_applied: Dict[str, bool] = Field(
        default_factory=dict,
        description="Dictionary of field names and whether they were successfully updated"
    )
    links_created: List[Dict[str, str]] = Field(
        default_factory=list,
        description="List of links that were created with details"
    )
    error: Optional[str] = Field(None, description="Error message if update failed")
    preview: Optional[Dict[str, Any]] = Field(
        None,
        description="Preview of changes (when dry_run=true)"
    )


class BulkUpdateStoriesRequest(BaseModel):
    """Request to bulk update multiple story tickets"""
    stories: List[StoryUpdateItem] = Field(
        ...,
        description="List of story update requests. Each story can have different update values.",
        min_items=1,
        example=[
            {
                "story_key": "STORY-123",
                "summary": "Updated Story 1 Title",
                "description": "New description"
            },
            {
                "story_key": "STORY-456",
                "description": "Updated description",
                "test_cases": "New test cases"
            }
        ]
    )
    dry_run: bool = Field(
        default=True,
        description="Preview mode - show what would be updated without actually updating JIRA"
    )
    async_mode: bool = Field(
        default=False,
        description="Process in background (returns job_id for status tracking)"
    )


class BulkUpdateStoriesResponse(BaseModel):
    """Response from bulk story update operation"""
    total_stories: int = Field(..., description="Total number of stories in the request")
    successful: int = Field(..., description="Number of successfully updated stories")
    failed: int = Field(..., description="Number of failed story updates")
    results: List[StoryUpdateResult] = Field(
        ...,
        description="Individual results for each story update"
    )
    job_id: Optional[str] = Field(
        None,
        description="Job ID for async processing (only present if async_mode=true)"
    )
    status_url: Optional[str] = Field(
        None,
        description="URL to check job status (only present if async_mode=true)"
    )
    message: str = Field(..., description="Status message")


class BulkCreateTaskItem(BaseModel):
    """Individual task creation request for bulk operations"""
    task_id: Optional[str] = Field(
        None,
        description="Internal task ID (UUID) for dependency resolution within the batch. Used to resolve references in 'blocks' field.",
        example="b948a26f-5407-4eb6-9378-01a39115fab2"
    )
    parent_key: str = Field(
        ...,
        description="Parent epic ticket key",
        example="EPIC-100"
    )
    summary: str = Field(
        ...,
        description="Task summary/title",
        example="Implement user authentication"
    )
    description: str = Field(
        ...,
        description="Task description",
        example="Add login functionality with email and password"
    )
    story_key: str = Field(
        ...,
        description="Story ticket key to link via split-from relationship",
        example="STORY-123"
    )
    test_cases: Optional[str] = Field(
        None,
        description="Test cases content for custom field (optional)"
    )
    mandays: Optional[float] = Field(
        None,
        description="Mandays estimation value (optional)",
        example=2.0
    )
    blocks: Optional[List[str]] = Field(
        None,
        description="List of ticket keys OR task_ids (UUIDs) that this task blocks. UUIDs will be resolved to JIRA keys for tasks in the same batch.",
        example=["TASK-456", "b948a26f-5407-4eb6-9378-01a39115fab2"]
    )


class BulkCreateStoryItem(BaseModel):
    """Individual story creation request for bulk operations"""
    parent_key: str = Field(
        ...,
        description="Parent epic ticket key",
        example="EPIC-100"
    )
    summary: str = Field(
        ...,
        description="Story summary/title",
        example="User authentication feature"
    )
    description: str = Field(
        ...,
        description="Story description/context",
        example="As a user, I want to authenticate with email and password so that I can access my account"
    )
    test_cases: Optional[str] = Field(
        None,
        description="Test cases content for custom field (optional)"
    )
    prd_row_uuid: Optional[str] = Field(
        None,
        description="Optional UUID for matching PRD table row (from dry run preview)"
    )


class BulkCreateTasksRequest(BaseModel):
    """Request to bulk create multiple task tickets"""
    tasks: List[BulkCreateTaskItem] = Field(
        ...,
        description="List of task creation requests",
        min_items=1
    )
    create_tickets: bool = Field(
        default=False,
        description="Create tickets in JIRA (default: false for preview mode)"
    )
    async_mode: bool = Field(
        default=False,
        description="Process in background (returns job_id for status tracking)"
    )


class BulkCreateStoriesRequest(BaseModel):
    """Request to bulk create multiple story tickets"""
    stories: List[BulkCreateStoryItem] = Field(
        ...,
        description="List of story creation requests",
        min_items=1
    )
    create_tickets: bool = Field(
        default=False,
        description="Create tickets in JIRA (default: false for preview mode)"
    )
    async_mode: bool = Field(
        default=False,
        description="Process in background (returns job_id for status tracking)"
    )


class BulkCreateResult(BaseModel):
    """Result for individual ticket creation in bulk operation"""
    index: int = Field(..., description="Index of the ticket in the request")
    success: bool = Field(..., description="Whether the creation was successful")
    ticket_key: Optional[str] = Field(None, description="Created ticket key (if successful)")
    error: Optional[str] = Field(None, description="Error message if creation failed")
    links_created: List[Dict[str, str]] = Field(
        default_factory=list,
        description="List of links that were created for this ticket"
    )


class BulkCreateTasksResponse(BaseModel):
    """Response from bulk task creation operation"""
    total_tasks: int = Field(..., description="Total number of tasks in the request")
    successful: int = Field(..., description="Number of successfully created tasks")
    failed: int = Field(..., description="Number of failed task creations")
    results: List[BulkCreateResult] = Field(
        ...,
        description="Individual results for each task creation"
    )
    created_tickets: List[str] = Field(
        default_factory=list,
        description="List of successfully created ticket keys"
    )
    message: str = Field(..., description="Status message")


class BulkCreateStoriesResponse(BaseModel):
    """Response from bulk story creation operation"""
    total_stories: int = Field(..., description="Total number of stories in the request")
    successful: int = Field(..., description="Number of successfully created stories")
    failed: int = Field(..., description="Number of failed story creations")
    results: List[BulkCreateResult] = Field(
        ...,
        description="Individual results for each story creation"
    )
    created_tickets: List[str] = Field(
        default_factory=list,
        description="List of successfully created ticket keys"
    )
    message: str = Field(..., description="Status message")

