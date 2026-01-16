"""
Draft PR Orchestrator Models
Pydantic models for plan specifications, versions, feedback, approvals, and workspace fingerprints
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class FeedbackType(str, Enum):
    """Types of feedback that can be provided on a plan"""
    GENERAL = "general"
    SCOPE = "scope"
    TESTS = "tests"
    SAFETY = "safety"
    OTHER = "other"


class PlanFeedback(BaseModel):
    """User feedback on a plan version"""
    feedback_text: str = Field(..., description="Free-form feedback text")
    specific_concerns: List[str] = Field(default_factory=list, description="List of specific issues (e.g., 'scope too broad', 'missing edge case')")
    requested_changes: Optional[str] = Field(None, description="Structured change requests")
    feedback_type: FeedbackType = Field(default=FeedbackType.GENERAL, description="Type of feedback")
    provided_by: Optional[str] = Field(None, description="User who provided the feedback")
    provided_at: datetime = Field(default_factory=datetime.now, description="When feedback was provided")


class PlanSpec(BaseModel):
    """Structured plan specification following PRD requirements"""
    summary: str = Field(..., description="High-level summary of the plan")
    scope: Dict[str, Any] = Field(..., description="Scope of changes including files to modify")
    happy_paths: List[str] = Field(default_factory=list, description="Happy path scenarios")
    edge_cases: List[str] = Field(default_factory=list, description="Edge cases to handle")
    failure_modes: List[Dict[str, str]] = Field(default_factory=list, description="Failure modes with trigger, impact, and mitigation")
    assumptions: List[str] = Field(default_factory=list, description="Assumptions made in the plan")
    unknowns: List[str] = Field(default_factory=list, description="Unknowns or uncertainties")
    tests: List[Dict[str, str]] = Field(default_factory=list, description="Tests to run (type: unit|integration|e2e, target: ...)")
    rollback: List[str] = Field(default_factory=list, description="Rollback procedures")
    cross_repo_impacts: List[Dict[str, str]] = Field(default_factory=list, description="Cross-repo impacts (repo, reason)")


class PlanVersion(BaseModel):
    """Immutable plan version with version number, hash, and feedback history"""
    version: int = Field(..., description="Plan version number (1, 2, 3, ...)")
    plan_spec: PlanSpec = Field(..., description="The plan specification")
    plan_hash: str = Field(..., description="SHA256 hash of the canonical plan JSON")
    created_at: datetime = Field(default_factory=datetime.now, description="When this version was created")
    feedback_history: List[PlanFeedback] = Field(default_factory=list, description="Feedback that led to this version (empty for v1)")
    previous_version_hash: Optional[str] = Field(None, description="Hash of previous version (None for v1)")
    generated_by: Optional[str] = Field(None, description="Who/what generated this version (e.g., 'opencode', 'llm')")


class Approval(BaseModel):
    """Approval record binding job_id, plan_hash, and approver"""
    job_id: str = Field(..., description="Job identifier")
    plan_hash: str = Field(..., description="Hash of the approved plan")
    approver: str = Field(..., description="User who approved the plan")
    approved_at: datetime = Field(default_factory=datetime.now, description="When approval was given")
    notes: Optional[str] = Field(None, description="Optional approval notes")


class WorkspaceFingerprint(BaseModel):
    """Fingerprint of workspace state for reproducibility"""
    repos: List[Dict[str, str]] = Field(..., description="List of repos with URL and ref/branch")
    selected_paths: Optional[List[str]] = Field(None, description="Selected file paths from plan scope")
    fingerprint_hash: str = Field(..., description="SHA256 hash of repos + refs + paths")
    created_at: datetime = Field(default_factory=datetime.now, description="When fingerprint was created")


class PlanComparison(BaseModel):
    """Comparison between two plan versions"""
    from_version: int = Field(..., description="Source version number")
    to_version: int = Field(..., description="Target version number")
    changes: Dict[str, Any] = Field(..., description="Structured changes (added, removed, modified)")
    summary: str = Field(..., description="Human-readable summary of changes")
    changed_sections: List[str] = Field(default_factory=list, description="List of sections that changed")
