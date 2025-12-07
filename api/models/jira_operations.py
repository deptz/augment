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

