"""
Test Generation Models
Request and response models for test generation endpoints
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any


class TestGenerationRequest(BaseModel):
    """Request model for test case generation operations"""
    epic_key: Optional[str] = Field(None, description="Epic key for comprehensive test generation")
    story_key: Optional[str] = Field(None, description="Story key for story-specific test generation") 
    task_key: Optional[str] = Field(None, description="Task key for task-specific test generation")
    coverage_level: str = Field(
        "standard", 
        description="Test coverage level: minimal, basic, standard, comprehensive",
        pattern="^(minimal|basic|standard|comprehensive)$"
    )
    async_mode: bool = Field(
        False,
        description="Process in background (returns job_id for status tracking)",
        example=False
    )
    domain_context: Optional[str] = Field(None, description="Domain context (financial, healthcare, ecommerce, security)")
    technical_context: Optional[str] = Field(None, description="Technical context (api, database, ui, microservice)")
    include_documents: bool = Field(True, description="Include PRD/RFC document context in test generation")
    llm_provider: Optional[str] = Field(
        default=None,
        description="LLM provider: openai, claude, gemini, or kimi (uses default if not specified)",
        example="openai"
    )
    llm_model: Optional[str] = Field(
        default=None,
        description="LLM model to use (uses default for provider if not specified)",
        example="gpt-5-mini"
    )

    @validator('epic_key', 'story_key', 'task_key')
    def validate_at_least_one_key(cls, v, values):
        keys = [values.get('epic_key'), values.get('story_key'), values.get('task_key'), v]
        if not any(key for key in keys if key):
            raise ValueError('At least one of epic_key, story_key, or task_key must be provided')
        return v


class TestCaseModel(BaseModel):
    """Model for individual test cases"""
    title: str = Field(..., description="Test case title")
    type: str = Field(..., description="Test type (unit/integration/e2e/acceptance/performance/security)")
    description: str = Field(..., description="Test description and steps")
    expected_result: str = Field(..., description="Expected test result")
    priority: Optional[str] = Field(None, description="Test priority (P0/P1/P2)")
    traceability: Optional[str] = Field(None, description="Requirement or story ID this test validates")
    precondition: Optional[str] = Field(None, description="System state required before test execution")
    test_steps: Optional[str] = Field(None, description="Detailed test steps in Gherkin format")
    source: Optional[str] = Field(None, description="Source of test generation: llm_ai, llm_fallback, pattern, fallback")


class TestGenerationResponse(BaseModel):
    """Response model for test generation operations"""
    success: bool = Field(..., description="Whether test generation was successful")
    coverage_level: str = Field(..., description="Coverage level used")
    epic_key: Optional[str] = Field(None, description="Epic key if epic-level generation")
    story_key: Optional[str] = Field(None, description="Story key if story-level generation")
    task_key: Optional[str] = Field(None, description="Task key if task-level generation")
    test_cases: List[TestCaseModel] = Field(default_factory=list, description="Generated test cases")
    test_count: int = Field(..., description="Total number of test cases generated")
    domain_context: Optional[str] = Field(None, description="Detected or provided domain context")
    technical_context: Optional[str] = Field(None, description="Detected or provided technical context")
    story_context: Optional[Dict[str, Any]] = Field(None, description="Parent story context information")
    document_context: Optional[Dict[str, Any]] = Field(None, description="PRD/RFC document context")
    context_sources: List[str] = Field(default_factory=list, description="Sources of context used")
    errors: List[str] = Field(default_factory=list, description="Any errors encountered")
    execution_time_seconds: float = Field(..., description="Time taken for test generation")


class ComprehensiveTestSuiteResponse(BaseModel):
    """Response model for comprehensive test suite generation"""
    success: bool = Field(..., description="Whether test generation was successful")
    epic_key: str = Field(..., description="Epic key for the test suite")
    coverage_level: str = Field(..., description="Coverage level used")
    story_tests: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="Test cases by story")
    task_tests: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="Test cases by task")
    total_test_cases: int = Field(..., description="Total number of test cases generated")
    test_statistics: Dict[str, Any] = Field(default_factory=dict, description="Test generation statistics")
    errors: List[str] = Field(default_factory=list, description="Any errors encountered")
    execution_time_seconds: float = Field(..., description="Time taken for test generation")

