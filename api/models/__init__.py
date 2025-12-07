"""
Models Package
Export all API models for easy imports
"""
# Generation models
from .generation import (
    JQLRequest,
    SingleTicketRequest,
    TicketResponse,
    BatchResponse,
    JobStatus
)

# Planning models
from .planning import (
    EpicPlanRequest,
    StoryGenerationRequest,
    TaskGenerationRequest,
    EpicAnalysisResponse,
    TaskDetail,
    StoryDetail,
    PlanningResultResponse,
    CycleTimeEstimateResponse
)

# Test generation models
from .test_generation import (
    TestGenerationRequest,
    TestCaseModel,
    TestGenerationResponse,
    ComprehensiveTestSuiteResponse
)

# Story analysis models
from .story_analysis import (
    StoryCoverageRequest,
    TaskSummaryModel,
    CoverageGap,
    UpdateTaskSuggestion,
    NewTaskSuggestion,
    StoryCoverageResponse,
    UpdateTaskRequest,
    CreateTaskRequest,
    UpdateTaskResponse,
    CreateTaskResponse
)

# JIRA operations models
from .jira_operations import (
    IssueLinkRequest,
    UpdateTicketRequest,
    UpdateTicketResponse,
    CreateTicketRequest,
    CreateTicketResponse
)

# Bulk creation models
from .bulk_creation import (
    BulkTicketCreationRequest,
    BulkCreationResponse,
    StoryCreationRequest,
    TaskCreationRequest
)

__all__ = [
    # Generation
    "JQLRequest",
    "SingleTicketRequest",
    "TicketResponse",
    "BatchResponse",
    "JobStatus",
    # Planning
    "EpicPlanRequest",
    "StoryGenerationRequest",
    "TaskGenerationRequest",
    "EpicAnalysisResponse",
    "TaskDetail",
    "StoryDetail",
    "PlanningResultResponse",
    "CycleTimeEstimateResponse",
    # Test generation
    "TestGenerationRequest",
    "TestCaseModel",
    "TestGenerationResponse",
    "ComprehensiveTestSuiteResponse",
    # Story analysis
    "StoryCoverageRequest",
    "TaskSummaryModel",
    "CoverageGap",
    "UpdateTaskSuggestion",
    "NewTaskSuggestion",
    "StoryCoverageResponse",
    "UpdateTaskRequest",
    "CreateTaskRequest",
    "UpdateTaskResponse",
    "CreateTaskResponse",
    # JIRA operations
    "IssueLinkRequest",
    "UpdateTicketRequest",
    "UpdateTicketResponse",
    "CreateTicketRequest",
    "CreateTicketResponse",
    # Bulk creation
    "BulkTicketCreationRequest",
    "BulkCreationResponse",
    "StoryCreationRequest",
    "TaskCreationRequest",
    # Prompt testing
    "PromptResubmitRequest",
    "PromptResubmitResponse",
]

