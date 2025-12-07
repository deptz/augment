from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class StoryInfo(BaseModel):
    """Story ticket information"""
    key: str
    title: str
    description: Optional[str] = None


class TicketInfo(BaseModel):
    """Jira ticket information"""
    key: str
    title: str
    description: Optional[str] = None
    status: str
    parent_key: Optional[str] = None
    parent_summary: Optional[str] = None
    stories: List[StoryInfo] = []
    prd_url: Optional[str] = None
    rfc_url: Optional[str] = None
    created: Optional[datetime] = None
    updated: Optional[datetime] = None


class PRDContent(BaseModel):
    """PRD document content"""
    title: str
    url: str
    summary: Optional[str] = None
    goals: Optional[str] = None
    content: Optional[str] = None


class RFCContent(BaseModel):
    """Model for RFC document content with comprehensive field coverage"""
    # Metadata
    status: Optional[str] = None
    owner: Optional[str] = None
    authors: Optional[str] = None
    
    # 1. Overview section
    overview: Optional[str] = None
    success_criteria: Optional[str] = None
    out_of_scope: Optional[str] = None
    related_documents: Optional[str] = None
    assumptions: Optional[str] = None
    dependencies: Optional[str] = None
    
    # 2. Technical Design section
    technical_design: Optional[str] = None
    architecture_tech_stack: Optional[str] = None
    sequence: Optional[str] = None
    database_model: Optional[str] = None
    apis: Optional[str] = None
    
    # 3. High-Availability & Security section
    high_availability_security: Optional[str] = None
    performance_requirement: Optional[str] = None
    monitoring_alerting: Optional[str] = None
    logging: Optional[str] = None
    security_implications: Optional[str] = None
    
    # 4. Backwards Compatibility and Rollout Plan section
    backwards_compatibility_rollout: Optional[str] = None
    compatibility: Optional[str] = None
    rollout_strategy: Optional[str] = None
    
    # 5. Concern, Questions, or Known Limitations section
    concerns_questions_limitations: Optional[str] = None
    
    # Additional common sections
    alternatives_considered: Optional[str] = None
    risks_and_mitigations: Optional[str] = None
    testing_strategy: Optional[str] = None
    timeline: Optional[str] = None
    
    def get_technical_summary(self) -> str:
        """Get a comprehensive technical summary of the RFC"""
        summary_parts = []
        
        if self.overview:
            summary_parts.append(f"Overview: {self.overview[:300]}...")
        
        if self.technical_design:
            summary_parts.append(f"Technical Design: {self.technical_design[:300]}...")
        
        if self.architecture_tech_stack:
            summary_parts.append(f"Architecture & Tech Stack: {self.architecture_tech_stack[:200]}...")
        
        if self.apis:
            summary_parts.append(f"APIs: {self.apis[:200]}...")
        
        if self.database_model:
            summary_parts.append(f"Database Model: {self.database_model[:200]}...")
        
        return "\n\n".join(summary_parts) if summary_parts else "No technical content available"
    
    def get_implementation_summary(self) -> str:
        """Get implementation-focused summary for development tasks"""
        impl_parts = []
        
        if self.sequence:
            impl_parts.append(f"Sequence Design: {self.sequence[:200]}...")
        
        if self.rollout_strategy:
            impl_parts.append(f"Rollout Strategy: {self.rollout_strategy[:200]}...")
        
        if self.compatibility:
            impl_parts.append(f"Compatibility Considerations: {self.compatibility[:200]}...")
        
        if self.testing_strategy:
            impl_parts.append(f"Testing Strategy: {self.testing_strategy[:200]}...")
        
        if self.monitoring_alerting:
            impl_parts.append(f"Monitoring & Alerting: {self.monitoring_alerting[:200]}...")
        
        return "\n\n".join(impl_parts) if impl_parts else "No implementation details available"
    
    def get_security_and_performance_summary(self) -> str:
        """Get security and performance related summary"""
        security_parts = []
        
        if self.high_availability_security:
            security_parts.append(f"High-Availability & Security: {self.high_availability_security[:200]}...")
        
        if self.security_implications:
            security_parts.append(f"Security Implications: {self.security_implications[:200]}...")
        
        if self.performance_requirement:
            security_parts.append(f"Performance Requirements: {self.performance_requirement[:200]}...")
        
        if self.logging:
            security_parts.append(f"Logging Requirements: {self.logging[:200]}...")
        
        return "\n\n".join(security_parts) if security_parts else "No security/performance details available"


class PullRequest(BaseModel):
    """Pull request information"""
    id: str
    title: str
    description: Optional[str] = None
    source_branch: str
    destination_branch: str
    state: str
    created_on: Optional[datetime] = None
    diff: Optional[str] = None
    code_changes: Optional[Dict[str, Any]] = None


class Commit(BaseModel):
    """Commit information"""
    hash: str
    message: str
    author: str
    date: Optional[datetime] = None
    diff: Optional[str] = None
    code_changes: Optional[Dict[str, Any]] = None


class GenerationContext(BaseModel):
    """Complete context for description generation"""
    ticket: TicketInfo
    prd: Optional[PRDContent] = None
    rfc: Optional[RFCContent] = None
    pull_requests: List[PullRequest] = Field(default_factory=list)
    commits: List[Commit] = Field(default_factory=list)
    additional_context: Optional[str] = None


class GeneratedDescription(BaseModel):
    """Generated ticket description"""
    ticket_key: str
    description: str
    confidence_score: Optional[float] = None
    sources_used: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None


class ProcessingResult(BaseModel):
    """Result of processing a single ticket"""
    ticket_key: str
    success: bool
    description: Optional[GeneratedDescription] = None
    error: Optional[str] = None
    skipped_reason: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
