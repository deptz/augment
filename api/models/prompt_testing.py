"""
Prompt Testing Models
Request and response models for prompt resubmission (A/B testing) endpoints
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class PromptResubmitRequest(BaseModel):
    """Request to resubmit a prompt with modifications for A/B testing"""
    operation_type: str = Field(
        ..., 
        description="Type of operation to resubmit: 'generate_single', 'plan_tasks', or 'analyze_coverage'",
        example="generate_single"
    )
    original_request: Dict[str, Any] = Field(
        ...,
        description="Original request parameters (as JSON object)",
        example={"ticket_key": "PROJ-123", "update_jira": False}
    )
    modified_system_prompt: Optional[str] = Field(
        None,
        description="Modified system prompt (optional, uses original if not provided)"
    )
    modified_user_prompt: str = Field(
        ...,
        description="Modified user prompt"
    )
    llm_provider: Optional[str] = Field(
        None,
        description="LLM provider override"
    )
    llm_model: Optional[str] = Field(
        None,
        description="LLM model override"
    )


class PromptResubmitResponse(BaseModel):
    """Response for prompt resubmission with A/B comparison"""
    success: bool = Field(..., description="Whether resubmission was successful")
    operation_type: str = Field(..., description="Type of operation that was resubmitted")
    original_result: Optional[Dict[str, Any]] = Field(
        None,
        description="Original generation result (for comparison)"
    )
    new_result: Dict[str, Any] = Field(
        ...,
        description="New generation result with modified prompt"
    )
    prompts_used: Dict[str, Any] = Field(
        ...,
        description="Prompts used for both original and new generation",
        example={
            "original_system_prompt": "...",
            "original_user_prompt": "...",
            "modified_system_prompt": "...",
            "modified_user_prompt": "..."
        }
    )
    comparison_notes: Optional[str] = Field(
        None,
        description="Auto-generated comparison notes"
    )
    error: Optional[str] = Field(
        None,
        description="Error message if resubmission failed"
    )

