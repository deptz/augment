"""
Tests for planning models and functionality
"""
import pytest
from datetime import datetime
from typing import List

from src.planning_models import (
    OperationMode, CycleTimeEstimate, TestCase, AcceptanceCriteria,
    TaskScope, TaskPlan, StoryPlan, EpicPlan, GapAnalysis,
    PlanningContext, PlanningResult
)


class TestCycleTimeEstimate:
    """Test cycle time estimation functionality"""
    
    def test_cycle_time_calculation(self):
        """Test basic cycle time calculation"""
        estimate = CycleTimeEstimate(
            development_days=2.0,
            testing_days=0.5,
            review_days=0.5,
            deployment_days=0.25,
            total_days=3.25
        )
        
        assert estimate.total_days == 3.25
        assert estimate.exceeds_limit is True  # > 3.0 days
        
    def test_cycle_time_within_limit(self):
        """Test cycle time within limit"""
        estimate = CycleTimeEstimate(
            development_days=1.5,
            testing_days=0.5,
            review_days=0.5,
            deployment_days=0.25,
            total_days=2.75
        )
        
        assert estimate.exceeds_limit is False  # <= 3.0 days
    
    def test_cycle_time_to_dict(self):
        """Test conversion to dictionary"""
        estimate = CycleTimeEstimate(
            development_days=1.0,
            testing_days=0.5,
            review_days=0.25,
            deployment_days=0.25,
            total_days=2.0,
            confidence_level=0.8
        )
        
        result = estimate.to_dict()
        expected = {
            "development": 1.0,
            "testing": 0.5,
            "review": 0.25,
            "deployment": 0.25,
            "total": 2.0,
            "confidence": 0.8
        }
        
        assert result == expected


class TestTaskPlan:
    """Test task planning functionality"""
    
    def test_task_plan_creation(self):
        """Test basic task plan creation"""
        scope = TaskScope(
            description="Implement user authentication",
            complexity="medium",
            deliverable="Working authentication system"
        )
        
        estimate = CycleTimeEstimate(
            development_days=2.0,
            testing_days=0.5,
            review_days=0.5,
            deployment_days=0.25,
            total_days=3.25
        )
        
        task = TaskPlan(
            summary="Implement user authentication system",
            purpose="Enable secure user access to the application",
            scopes=[scope],
            expected_outcomes=["Users can log in securely", "Authentication tokens are managed"],
            cycle_time_estimate=estimate,
            epic_key="EPIC-123"
        )
        
        assert task.summary == "Implement user authentication system"
        assert len(task.scopes) == 1
        assert task.epic_key == "EPIC-123"
        assert task.cycle_time_estimate.exceeds_limit is True
    
    def test_task_description_formatting(self):
        """Test task description formatting for JIRA"""
        scope = TaskScope(
            description="Create login form",
            complexity="low",
            deliverable="Login UI component"
        )
        
        task = TaskPlan(
            summary="Create login form",
            purpose="Allow users to enter credentials",
            scopes=[scope],
            expected_outcomes=["Login form is functional", "Form validation works"]
        )
        
        description = task.format_description()
        
        assert "**Purpose:**" in description
        assert "Allow users to enter credentials" in description
        assert "**Scopes:**" in description
        assert "Create login form" in description
        assert "**Expected Outcome:**" in description
        assert "Login form is functional" in description


class TestStoryPlan:
    """Test story planning functionality"""
    
    def test_story_plan_creation(self):
        """Test basic story plan creation"""
        criteria = AcceptanceCriteria(
            scenario="User login with valid credentials",
            given="a user has valid username and password",
            when="they attempt to log in",
            then="they should be successfully authenticated"
        )
        
        story = StoryPlan(
            summary="User authentication",
            description="As a user, I need to log in securely",
            acceptance_criteria=[criteria],
            epic_key="EPIC-123"
        )
        
        assert story.summary == "User authentication"
        assert len(story.acceptance_criteria) == 1
        assert story.epic_key == "EPIC-123"
    
    def test_acceptance_criteria_formatting(self):
        """Test acceptance criteria formatting"""
        criteria = AcceptanceCriteria(
            scenario="Successful login",
            given="valid credentials are provided",
            when="user clicks login button",
            then="user should be redirected to dashboard"
        )
        
        formatted = criteria.format_gwt()
        
        assert "**Scenario: Successful login**" in formatted
        assert "**Given** valid credentials are provided" in formatted
        assert "**When** user clicks login button" in formatted
        assert "**Then** user should be redirected to dashboard" in formatted


class TestGapAnalysis:
    """Test gap analysis functionality"""
    
    def test_gap_analysis_needs_assessment(self):
        """Test gap analysis needs assessment"""
        gap = GapAnalysis(
            epic_key="EPIC-123",
            existing_stories=["STORY-1", "STORY-2"],
            missing_stories=["User Authentication", "Data Validation"],
            incomplete_stories=["STORY-1"],
            orphaned_tasks=["TASK-99"]
        )
        
        assert gap.needs_stories is True  # has missing stories
        assert gap.needs_tasks is True   # has incomplete stories
        assert gap.is_complete is False  # has gaps
    
    def test_gap_analysis_complete(self):
        """Test complete gap analysis"""
        gap = GapAnalysis(
            epic_key="EPIC-123",
            existing_stories=["STORY-1", "STORY-2"],
            missing_stories=[],
            incomplete_stories=[],
            orphaned_tasks=[]
        )
        
        assert gap.needs_stories is False
        assert gap.needs_tasks is False
        assert gap.is_complete is True


class TestEpicPlan:
    """Test epic planning functionality"""
    
    def test_epic_plan_creation(self):
        """Test basic epic plan creation"""
        # Create a simple story with tasks
        task_scope = TaskScope(
            description="Implement login logic",
            complexity="medium",
            deliverable="Working login function"
        )
        
        cycle_estimate = CycleTimeEstimate(
            development_days=1.5,
            testing_days=0.5,
            review_days=0.25,
            deployment_days=0.25,
            total_days=2.5
        )
        
        task = TaskPlan(
            summary="Implement login",
            purpose="Enable user authentication",
            scopes=[task_scope],
            expected_outcomes=["Login works"],
            cycle_time_estimate=cycle_estimate
        )
        
        criteria = AcceptanceCriteria(
            scenario="User login",
            given="valid credentials",
            when="user logs in",
            then="access is granted"
        )
        
        story = StoryPlan(
            summary="User authentication",
            description="User login story",
            acceptance_criteria=[criteria],
            tasks=[task]
        )
        
        epic = EpicPlan(
            epic_key="EPIC-123",
            epic_title="Authentication Epic",
            stories=[story]
        )
        
        assert epic.epic_key == "EPIC-123"
        assert len(epic.stories) == 1
        assert len(epic.get_all_tasks()) == 1
    
    def test_epic_summary_stats(self):
        """Test epic summary statistics"""
        # Create epic with multiple stories and tasks
        cycle_estimate1 = CycleTimeEstimate(
            development_days=1.0,
            testing_days=0.5,
            review_days=0.25,
            deployment_days=0.25,
            total_days=2.0
        )
        
        cycle_estimate2 = CycleTimeEstimate(
            development_days=2.5,
            testing_days=1.0,
            review_days=0.5,
            deployment_days=0.5,
            total_days=4.5  # Exceeds limit
        )
        
        task1 = TaskPlan(
            summary="Task 1",
            purpose="Test purpose",
            scopes=[],
            expected_outcomes=[],
            cycle_time_estimate=cycle_estimate1
        )
        
        task2 = TaskPlan(
            summary="Task 2",
            purpose="Test purpose",
            scopes=[],
            expected_outcomes=[],
            cycle_time_estimate=cycle_estimate2
        )
        
        story1 = StoryPlan(
            summary="Story 1",
            description="Test story",
            acceptance_criteria=[],
            tasks=[task1]
        )
        
        story2 = StoryPlan(
            summary="Story 2",
            description="Test story",
            acceptance_criteria=[],
            tasks=[task2]
        )
        
        epic = EpicPlan(
            epic_key="EPIC-123",
            epic_title="Test Epic",
            stories=[story1, story2]
        )
        
        stats = epic.get_summary_stats()
        
        assert stats["total_stories"] == 2
        assert stats["total_tasks"] == 2
        assert stats["estimated_total_days"] == 6.5  # 2.0 + 4.5
        assert stats["tasks_exceeding_limit"] == 1   # task2 exceeds 3.0 days
        assert stats["average_task_days"] == 3.25    # 6.5 / 2


class TestPlanningContext:
    """Test planning context"""
    
    def test_planning_context_creation(self):
        """Test planning context creation with defaults"""
        context = PlanningContext(
            mode=OperationMode.PLANNING,
            epic_key="EPIC-123"
        )
        
        assert context.mode == OperationMode.PLANNING
        assert context.epic_key == "EPIC-123"
        assert context.max_task_cycle_days == 3.0  # default
        assert context.split_oversized_tasks is True  # default
        assert context.dry_run is True  # default
    
    def test_planning_context_custom_options(self):
        """Test planning context with custom options"""
        context = PlanningContext(
            mode=OperationMode.HYBRID,
            epic_key="EPIC-456",
            max_task_cycle_days=2.0,
            split_oversized_tasks=False,
            dry_run=False
        )
        
        assert context.mode == OperationMode.HYBRID
        assert context.max_task_cycle_days == 2.0
        assert context.split_oversized_tasks is False
        assert context.dry_run is False


class TestPlanningResult:
    """Test planning result"""
    
    def test_planning_result_success(self):
        """Test successful planning result"""
        result = PlanningResult(
            epic_key="EPIC-123",
            mode=OperationMode.PLANNING,
            success=True,
            created_tickets={"stories": ["STORY-1"], "tasks": ["TASK-1", "TASK-2"]},
            execution_time_seconds=15.5
        )
        
        assert result.success is True
        assert result.epic_key == "EPIC-123"
        assert len(result.created_tickets["stories"]) == 1
        assert len(result.created_tickets["tasks"]) == 2
        assert result.execution_time_seconds == 15.5
    
    def test_planning_result_failure(self):
        """Test failed planning result"""
        result = PlanningResult(
            epic_key="EPIC-123",
            mode=OperationMode.PLANNING,
            success=False,
            errors=["JIRA connection failed", "Invalid epic key"],
            execution_time_seconds=2.1
        )
        
        assert result.success is False
        assert len(result.errors) == 2
        assert "JIRA connection failed" in result.errors


if __name__ == "__main__":
    pytest.main([__file__])
