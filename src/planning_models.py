"""
Planning-specific data models for top-down epic/story/task generation
"""
import uuid
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class OperationMode(str, Enum):
    """System operation modes"""
    DOCUMENTATION = "documentation"  # Bottom-up: generate descriptions from completed work
    PLANNING = "planning"            # Top-down: generate work breakdown from requirements
    HYBRID = "hybrid"               # Both: plan + track execution


class TaskTeam(str, Enum):
    """Team responsible for the task"""
    BACKEND = "backend"
    FRONTEND = "frontend" 
    QA = "qa"
    DEVOPS = "devops"
    FULLSTACK = "fullstack"


class CycleTimeEstimate(BaseModel):
    """Cycle time estimation for tasks"""
    development_days: float = Field(description="Estimated development time in days")
    testing_days: float = Field(description="Estimated testing time in days")
    review_days: float = Field(description="Estimated review time in days")
    deployment_days: float = Field(description="Estimated deployment time in days")
    total_days: float = Field(description="Total estimated cycle time in days")
    confidence_level: float = Field(default=0.7, description="Confidence in estimate (0-1)")
    
    @property
    def exceeds_limit(self) -> bool:
        """Check if estimate exceeds 3-day cycle time limit"""
        return self.total_days > 3.0
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "development": self.development_days,
            "testing": self.testing_days,
            "review": self.review_days,
            "deployment": self.deployment_days,
            "total": self.total_days,
            "confidence": self.confidence_level
        }


class TestCase(BaseModel):
    """Test case for stories and tasks"""
    title: str = Field(description="Test case title")
    type: str = Field(default="functional", description="Type: functional, unit, integration, etc.")
    description: str = Field(description="Test case description")
    steps: Optional[List[str]] = Field(default=None, description="Test execution steps")
    expected_result: Optional[str] = Field(default=None, description="Expected test outcome")
    priority: str = Field(default="medium", description="Priority: high, medium, low")
    source: Optional[str] = Field(default=None, description="Source of test generation: llm_ai, llm_fallback, pattern, fallback")
    
    def format_for_jira(self) -> str:
        """Format test case for JIRA test case field"""
        formatted = f"**{self.title}** ({self.type})\n{self.description}\n"
        
        if self.steps:
            formatted += "\n**Steps:**\n"
            # Preserve clean Given/When/Then format without any prefixes
            for step in self.steps:
                formatted += f"{step}\n"
        
        if self.expected_result:
            formatted += f"\n**Expected Result:** {self.expected_result}\n"
            
        return formatted


class AcceptanceCriteria(BaseModel):
    """Given/When/Then acceptance criteria for stories"""
    scenario: str = Field(description="Scenario description")
    given: str = Field(description="Initial condition/context")
    when: str = Field(description="Action/trigger")
    then: str = Field(description="Expected result/outcome")
    
    def format_gwt(self) -> str:
        """Format as Given/When/Then structure"""
        return f"**Scenario: {self.scenario}**\n- **Given** {self.given}\n- **When** {self.when}\n- **Then** {self.then}"


class TaskScope(BaseModel):
    """Individual scope item for a task"""
    description: str = Field(description="What needs to be done")
    complexity: str = Field(default="medium", description="Complexity: low, medium, high")
    dependencies: List[str] = Field(default_factory=list, description="Dependencies on other work")
    deliverable: str = Field(description="Concrete deliverable from this scope")


class TaskPlan(BaseModel):
    """Planned task with all required content"""
    key: Optional[str] = Field(default=None, description="JIRA task key")
    task_id: Optional[str] = Field(default=None, description="Temporary task ID (UUID) for dependency resolution before JIRA creation")
    summary: str = Field(description="Task title/summary")
    purpose: str = Field(description="Why this task is needed")
    scopes: List[TaskScope] = Field(description="What exactly needs to be done")
    expected_outcomes: List[str] = Field(description="Expected results when task is done")
    team: TaskTeam = Field(default=TaskTeam.BACKEND, description="Team responsible for the task")
    test_cases: List[TestCase] = Field(default_factory=list, description="Task-level test cases")
    cycle_time_estimate: Optional[CycleTimeEstimate] = Field(default=None, description="Effort estimation")
    epic_key: Optional[str] = Field(default=None, description="Parent epic JIRA key")
    story_key: Optional[str] = Field(default=None, description="Parent story JIRA key")
    depends_on_tasks: List[str] = Field(default_factory=list, description="Task IDs (task_id or summary) this task depends on. Prefer task_id when available.")
    blocked_by_teams: List[TaskTeam] = Field(default_factory=list, description="Teams this task is blocked by")
    sprint_id: Optional[int] = Field(default=None, description="Assigned sprint ID")
    scheduled_sprint: Optional[Dict[str, Any]] = Field(default=None, description="Scheduled sprint information")
    
    def format_description(self) -> str:
        """Format task description for JIRA (Markdown format - will be converted to ADF)"""
        description = f"**Team:** {self.team.value.title()}\n\n"
        description += f"**Purpose:**\n{self.purpose}\n\n"
        
        description += "**Scopes:**\n"
        for scope in self.scopes:
            description += f"- {scope.description}\n"
        
        description += "\n**Expected Outcome:**\n"
        for outcome in self.expected_outcomes:
            description += f"- {outcome}\n"
            
        return description
    
    def format_description_for_jira_adf(self) -> Dict[str, Any]:
        """Format task description as JIRA ADF (Atlassian Document Format)"""
        content = []
        
        # Team section
        content.append({
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Team: ", "marks": [{"type": "strong"}]},
                {"type": "text", "text": self.team.value.title()}
            ]
        })
        
        # Purpose section
        content.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": "Purpose:", "marks": [{"type": "strong"}]}]
        })
        content.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": self.purpose}]
        })
        
        # Scopes section
        content.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": "Scopes:", "marks": [{"type": "strong"}]}]
        })
        scope_items = []
        for scope in self.scopes:
            scope_items.append({
                "type": "listItem",
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": scope.description}]
                }]
            })
        if scope_items:
            content.append({
                "type": "bulletList",
                "content": scope_items
            })
        
        # Expected Outcome section
        content.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": "Expected Outcome:", "marks": [{"type": "strong"}]}]
        })
        outcome_items = []
        for outcome in self.expected_outcomes:
            outcome_items.append({
                "type": "listItem",
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": outcome}]
                }]
            })
        if outcome_items:
            content.append({
                "type": "bulletList",
                "content": outcome_items
            })
        
        return {
            "type": "doc",
            "version": 1,
            "content": content
        }
    
    def format_test_cases(self) -> str:
        """Format test cases for JIRA test case field"""
        if not self.test_cases:
            return ""
        
        formatted = ""
        for test_case in self.test_cases:
            formatted += test_case.format_for_jira() + "\n---\n"
        
        return formatted.rstrip("\n---\n")


class StoryPlan(BaseModel):
    """Planned story with all required content"""
    key: Optional[str] = Field(default=None, description="JIRA story key")
    summary: str = Field(description="Story title/summary")
    description: str = Field(description="Story description/context")
    acceptance_criteria: List[AcceptanceCriteria] = Field(description="Given/When/Then acceptance criteria")
    test_cases: List[TestCase] = Field(default_factory=list, description="Story-level test cases")
    tasks: List[TaskPlan] = Field(default_factory=list, description="Child tasks")
    epic_key: Optional[str] = Field(default=None, description="Parent epic JIRA key")
    priority: str = Field(default="medium", description="Story priority")
    prd_row_uuid: Optional[str] = Field(default=None, description="Temporary UUID for matching PRD table row during sync")
    
    def format_description(self) -> str:
        """Format story description for JIRA (Markdown format - will be converted to ADF)"""
        # If description already contains acceptance criteria (from PRD parsing), just return it
        # Otherwise, append acceptance criteria for backward compatibility
        if "**Acceptance Criteria:**" in self.description:
            return self.description
        
        description = f"{self.description}\n\n"
        
        # Only add acceptance criteria if not already in description
        if self.acceptance_criteria:
            description += "**Acceptance Criteria:**\n\n"
            for criteria in self.acceptance_criteria:
                description += criteria.format_gwt() + "\n\n"
            
        return description.rstrip()
    
    def format_description_for_jira_adf(self) -> Dict[str, Any]:
        """Format story description as JIRA ADF (Atlassian Document Format)"""
        # Check if description already contains acceptance criteria (from PRD parsing)
        # If so, we'll convert the markdown description to ADF without adding duplicate acceptance criteria
        description_lower = self.description.lower()
        description_has_acceptance_criteria = (
            "**acceptance criteria:**" in description_lower or 
            "acceptance criteria:" in description_lower or
            "acceptance criteria" in description_lower
        )
        
        # If description already has acceptance criteria, just convert the markdown to ADF
        # Otherwise, add acceptance criteria from the acceptance_criteria field
        if description_has_acceptance_criteria:
            # Description already contains acceptance criteria, return None to signal
            # that the caller should use markdown-to-ADF conversion instead
            return None
        else:
            # Description doesn't have acceptance criteria, build ADF with acceptance criteria
            content = []
            
            # Story description (convert markdown to ADF if needed)
            # For now, just add as paragraph - will be converted by JiraClient
            content.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": self.description}]
            })
            
            # Acceptance Criteria section (only if not already in description)
            if self.acceptance_criteria:
                content.append({
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Acceptance Criteria:", "marks": [{"type": "strong"}]}]
                })
                
                # Add each acceptance criteria
                for criteria in self.acceptance_criteria:
                    criteria_content = []
                    
                    # Given
                    criteria_content.append({
                        "type": "paragraph", 
                        "content": [
                            {"type": "text", "text": "Given: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": criteria.given}
                        ]
                    })
                    
                    # When
                    criteria_content.append({
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "When: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": criteria.when}
                        ]
                    })
                    
                    # Then
                    criteria_content.append({
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Then: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": criteria.then}
                        ]
                    })
                    
                    content.extend(criteria_content)
                    
                    # Add separator between criteria
                    if criteria != self.acceptance_criteria[-1]:
                        content.append({
                            "type": "paragraph",
                            "content": [{"type": "text", "text": ""}]
                        })
            
            return {
                "type": "doc",
                "version": 1,
                "content": content
            }
    
    def format_test_cases(self) -> str:
        """Format test cases for JIRA test case field"""
        if not self.test_cases:
            return ""
        
        formatted = ""
        for test_case in self.test_cases:
            formatted += test_case.format_for_jira() + "\n---\n"
        
        return formatted.rstrip("\n---\n")


class EpicPlan(BaseModel):
    """Complete epic planning structure"""
    epic_key: str = Field(description="JIRA epic key")
    epic_title: str = Field(description="Epic title")
    epic_description: Optional[str] = Field(default=None, description="Epic description")
    prd_url: Optional[str] = Field(default=None, description="Related PRD document URL")
    rfc_url: Optional[str] = Field(default=None, description="Related RFC document URL")
    stories: List[StoryPlan] = Field(default_factory=list, description="Planned stories")
    total_estimated_days: float = Field(default=0.0, description="Total effort estimate")
    sprint_assignments: Dict[str, int] = Field(default_factory=dict, description="Task key to sprint ID mapping")
    
    def get_all_tasks(self) -> List[TaskPlan]:
        """Get all tasks across all stories"""
        all_tasks = []
        for story in self.stories:
            all_tasks.extend(story.tasks)
        return all_tasks
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """Get planning summary statistics"""
        all_tasks = self.get_all_tasks()
        
        return {
            "total_stories": len(self.stories),
            "total_tasks": len(all_tasks),
            "estimated_total_days": sum(task.cycle_time_estimate.total_days for task in all_tasks if task.cycle_time_estimate),
            "tasks_exceeding_limit": len([task for task in all_tasks if task.cycle_time_estimate and task.cycle_time_estimate.exceeds_limit]),
            "average_task_days": sum(task.cycle_time_estimate.total_days for task in all_tasks if task.cycle_time_estimate) / len(all_tasks) if all_tasks else 0
        }


class GapAnalysis(BaseModel):
    """Analysis of what's missing in an epic structure"""
    epic_key: str = Field(description="JIRA epic key being analyzed")
    existing_stories: List[str] = Field(default_factory=list, description="Existing story keys")
    missing_stories: List[str] = Field(default_factory=list, description="Missing story requirements")
    incomplete_stories: List[str] = Field(default_factory=list, description="Stories without tasks")
    orphaned_tasks: List[str] = Field(default_factory=list, description="Tasks without parent stories")
    prd_requirements: List[str] = Field(default_factory=list, description="Requirements from PRD")
    rfc_requirements: List[str] = Field(default_factory=list, description="Requirements from RFC")
    
    @property
    def needs_stories(self) -> bool:
        """Check if stories need to be created"""
        return len(self.missing_stories) > 0
    
    @property
    def needs_tasks(self) -> bool:
        """Check if tasks need to be created"""
        return len(self.incomplete_stories) > 0
    
    @property
    def is_complete(self) -> bool:
        """Check if epic structure is complete"""
        return not (self.needs_stories or self.needs_tasks or self.orphaned_tasks)


class PlanningContext(BaseModel):
    """Context for planning operations"""
    mode: OperationMode = Field(description="Operation mode")
    epic_key: str = Field(description="Target epic key")
    gap_analysis: Optional[GapAnalysis] = Field(default=None, description="Gap analysis results")
    epic_plan: Optional[EpicPlan] = Field(default=None, description="Generated epic plan")
    options: Dict[str, Any] = Field(default_factory=dict, description="Planning options")
    
    # Planning options
    max_task_cycle_days: float = Field(default=3.0, description="Maximum task cycle time in days")
    max_tasks_per_story: int = Field(default=3, description="Maximum number of tasks per story")
    split_oversized_tasks: bool = Field(default=True, description="Automatically split large tasks")
    generate_test_cases: bool = Field(default=True, description="Generate test cases")
    create_missing_stories: bool = Field(default=True, description="Create missing stories")
    create_missing_tasks: bool = Field(default=True, description="Create missing tasks")
    dry_run: bool = Field(default=True, description="Don't actually create tickets")
    
    # Document context
    prd_content: Optional[Dict[str, Any]] = Field(default=None, description="PRD document content")
    rfc_content: Optional[Dict[str, Any]] = Field(default=None, description="RFC document content")
    additional_context: Optional[str] = Field(default=None, description="Custom additional context")


class PlanningResult(BaseModel):
    """Result of a planning operation"""
    epic_key: str = Field(description="Epic that was planned")
    mode: OperationMode = Field(description="Operation mode used")
    success: bool = Field(description="Whether planning was successful")
    created_tickets: Dict[str, List[str]] = Field(default_factory=dict, description="Created ticket keys by type")
    gap_analysis: Optional[GapAnalysis] = Field(default=None, description="Gap analysis performed")
    epic_plan: Optional[EpicPlan] = Field(default=None, description="Generated epic plan")
    summary_stats: Optional[Dict[str, Any]] = Field(default=None, description="Planning summary statistics")
    errors: List[str] = Field(default_factory=list, description="Any errors encountered")
    warnings: List[str] = Field(default_factory=list, description="Any warnings")
    execution_time_seconds: float = Field(default=0.0, description="Time taken for planning")
    system_prompt: Optional[str] = Field(default=None, description="System prompt sent to LLM")
    user_prompt: Optional[str] = Field(default=None, description="User prompt sent to LLM")
    story_metadata: Optional[Dict[str, Dict[str, Any]]] = Field(default=None, description="Metadata about stories: key -> {source, action_taken, was_updated, jira_url}")
