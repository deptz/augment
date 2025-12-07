"""
Test bulk ticket creation functionality
"""
import pytest
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.bulk_ticket_creator import BulkTicketCreator
from src.jira_client import JiraClient
from src.planning_models import (
    EpicPlan, StoryPlan, TaskPlan, CycleTimeEstimate, 
    AcceptanceCriteria, TestCase, TaskScope
)
from unittest.mock import Mock, patch


class TestBulkTicketCreator:
    """Test bulk ticket creation operations"""
    
    @pytest.fixture
    def mock_jira_client(self):
        """Mock JIRA client"""
        client = Mock(spec=JiraClient)
        client.get_project_key_from_epic.return_value = "TEST"
        client.create_story_ticket.return_value = "STORY-123"
        client.create_task_ticket.return_value = "TASK-456"
        client.create_issue_link.return_value = True
        client.validate_ticket_relationships.return_value = {
            "valid": True,
            "issues": []
        }
        return client
    
    @pytest.fixture
    def bulk_creator(self, mock_jira_client):
        """Bulk ticket creator instance"""
        return BulkTicketCreator(mock_jira_client)
    
    @pytest.fixture
    def sample_epic_plan(self):
        """Sample epic plan for testing"""
        task1 = TaskPlan(
            summary="Implement user authentication",
            purpose="Enable secure user access to the system",
            scopes=[
                TaskScope(
                    description="Create JWT token-based authentication system",
                    complexity="medium",
                    dependencies=["User database setup"],
                    deliverable="Working JWT authentication service"
                )
            ],
            expected_outcomes=["Users can securely log in and out of the system"],
            cycle_time_estimate=CycleTimeEstimate(
                development_days=2.0,
                testing_days=1.0,
                review_days=0.5,
                deployment_days=0.5,
                total_days=4.0,
                confidence_level=0.8
            ),
            test_cases=[
                TestCase(
                    title="Test successful login",
                    type="integration",
                    description="Verify user can login with valid credentials",
                    expected_result="User redirected to dashboard"
                )
            ]
        )
        
        task2 = TaskPlan(
            summary="Design user interface",
            purpose="Create intuitive user experience",
            scopes=[
                TaskScope(
                    description="Design login and dashboard screens",
                    complexity="low",
                    dependencies=["UX research"],
                    deliverable="UI mockups and prototypes"
                )
            ],
            expected_outcomes=["Intuitive and accessible user interface"],
            cycle_time_estimate=CycleTimeEstimate(
                development_days=1.5,
                testing_days=0.5,
                review_days=0.5,
                deployment_days=0.5,
                total_days=3.0,
                confidence_level=0.9
            )
        )
        
        story1 = StoryPlan(
            summary="User Authentication System",
            description="As a user, I want to login securely",
            story_points=5,
            acceptance_criteria=[
                AcceptanceCriteria(
                    scenario="User Login Authentication",
                    given="User has valid credentials",
                    when="User submits login form",
                    then="User is authenticated and redirected"
                )
            ],
            test_cases=[
                TestCase(
                    title="Test authentication flow",
                    type="e2e",
                    description="End-to-end authentication testing",
                    expected_result="Complete login process works"
                )
            ],
            tasks=[task1],
            cycle_time_estimate=CycleTimeEstimate(
                development_days=4.0,
                testing_days=2.0,
                review_days=1.0,
                deployment_days=1.0,
                total_days=8.0,
                confidence_level=0.8
            )
        )
        
        return EpicPlan(
            epic_key="TEST-100",
            epic_title="User Management Epic",
            epic_description="Complete user management system",
            stories=[story1],
            total_estimated_days=8.0
        )
    
    def test_dry_run_epic_creation(self, bulk_creator, sample_epic_plan):
        """Test dry run epic creation"""
        result = bulk_creator.create_epic_structure(sample_epic_plan, dry_run=True)
        
        assert result["success"] is True
        assert result["dry_run"] is True
        assert result["epic_key"] == "TEST-100"
        assert len(result["created_tickets"]["stories"]) == 1
        assert len(result["created_tickets"]["tasks"]) == 1
        assert len(result["relationships_created"]) == 1
        assert result["execution_time_seconds"] > 0
    
    def test_real_epic_creation(self, bulk_creator, sample_epic_plan, mock_jira_client):
        """Test actual epic creation"""
        result = bulk_creator.create_epic_structure(sample_epic_plan, dry_run=False)
        
        assert result["success"] is True
        assert result["dry_run"] is False
        assert result["epic_key"] == "TEST-100"
        assert len(result["created_tickets"]["stories"]) == 1
        assert len(result["created_tickets"]["tasks"]) == 1
        
        # Verify JIRA client methods were called
        mock_jira_client.get_project_key_from_epic.assert_called_with("TEST-100")
        mock_jira_client.create_story_ticket.assert_called_once()
        mock_jira_client.create_task_ticket.assert_called_once()
        mock_jira_client.validate_ticket_relationships.assert_called_with("TEST-100")
    
    def test_story_creation_only(self, bulk_creator, sample_epic_plan):
        """Test creating only stories"""
        result = bulk_creator.create_stories_only(
            "TEST-100", 
            sample_epic_plan.stories, 
            dry_run=True
        )
        
        assert result["success"] is True
        assert result["epic_key"] == "TEST-100"
        assert len(result["created_tickets"]["stories"]) == 1
        assert "tasks" not in result["created_tickets"]
    
    def test_task_creation_only(self, bulk_creator, sample_epic_plan):
        """Test creating only tasks"""
        all_tasks = []
        for story in sample_epic_plan.stories:
            all_tasks.extend(story.tasks)
        
        result = bulk_creator.create_tasks_only(
            all_tasks, 
            ["STORY-123"], 
            dry_run=True
        )
        
        assert result["success"] is True
        assert len(result["created_tickets"]["tasks"]) == 1
        assert "stories" not in result["created_tickets"]
    
    def test_creation_with_jira_failure(self, bulk_creator, sample_epic_plan, mock_jira_client):
        """Test handling JIRA creation failures"""
        # Mock JIRA failure
        mock_jira_client.create_story_ticket.return_value = None
        
        result = bulk_creator.create_epic_structure(sample_epic_plan, dry_run=False)
        
        assert result["success"] is False
        assert len(result["failed_creations"]) > 0
        assert result["failed_creations"][0]["type"] == "story"
    
    def test_creation_with_project_key_failure(self, bulk_creator, sample_epic_plan, mock_jira_client):
        """Test handling project key extraction failure"""
        mock_jira_client.get_project_key_from_epic.return_value = None
        
        result = bulk_creator.create_epic_structure(sample_epic_plan, dry_run=False)
        
        assert result["success"] is False
        assert len(result["errors"]) > 0
        assert "Could not extract project key" in result["errors"][0]
    
    def test_validation_failure_handling(self, bulk_creator, sample_epic_plan, mock_jira_client):
        """Test handling validation failures"""
        mock_jira_client.validate_ticket_relationships.return_value = {
            "valid": False,
            "issues": ["Story not linked to epic"]
        }
        
        result = bulk_creator.create_epic_structure(sample_epic_plan, dry_run=False)
        
        # Should still succeed but log validation issues
        assert result["success"] is True
        assert len(result["errors"]) > 0
    
    def test_rollback_creation(self, bulk_creator):
        """Test rollback functionality"""
        created_tickets = {
            "stories": ["STORY-123", "STORY-124"],
            "tasks": ["TASK-456", "TASK-457"]
        }
        
        result = bulk_creator.rollback_creation(created_tickets)
        
        assert result["success"] is True
        assert len(result["deleted_tickets"]) == 4
        assert "STORY-123" in result["deleted_tickets"]
        assert "TASK-456" in result["deleted_tickets"]


class TestBulkCreatorIntegration:
    """Integration tests for bulk creator with planning service"""
    
    @pytest.fixture
    def mock_planning_service(self):
        """Mock planning service"""
        from src.planning_service import PlanningService
        service = Mock(spec=PlanningService)
        service.bulk_creator = Mock(spec=BulkTicketCreator)
        return service
    
    @pytest.fixture
    def integration_epic_plan(self):
        """Sample epic plan for integration testing"""
        task1 = TaskPlan(
            summary="Integration test task",
            purpose="Test integration",
            scopes=[
                TaskScope(
                    description="Basic integration test",
                    complexity="low",
                    dependencies=[],
                    deliverable="Test results"
                )
            ],
            expected_outcomes=["Integration works correctly"],
            cycle_time_estimate=CycleTimeEstimate(
                development_days=1.0,
                testing_days=0.5,
                review_days=0.5,
                deployment_days=0.0,
                total_days=2.0,
                confidence_level=0.9
            )
        )
        
        story1 = StoryPlan(
            summary="Integration Test Story",
            description="Story for integration testing",
            story_points=3,
            acceptance_criteria=[
                AcceptanceCriteria(
                    scenario="Integration Testing",
                    given="System is configured",
                    when="Integration test runs",
                    then="All components work together"
                )
            ],
            tasks=[task1],
            cycle_time_estimate=CycleTimeEstimate(
                development_days=2.0,
                testing_days=1.0,
                review_days=0.5,
                deployment_days=0.5,
                total_days=4.0,
                confidence_level=0.8
            )
        )
        
        return EpicPlan(
            epic_key="INT-100",
            epic_title="Integration Test Epic",
            stories=[story1],
            total_estimated_days=4.0
        )
    
    def test_planning_service_integration(self, mock_planning_service, integration_epic_plan):
        """Test planning service integration with bulk creator"""
        # Mock the bulk creator methods
        mock_planning_service.bulk_creator.create_epic_structure.return_value = {
            "success": True,
            "created_tickets": {"stories": ["STORY-123"], "tasks": ["TASK-456"]},
            "errors": []
        }
        
        # Test the integration
        result = mock_planning_service.bulk_creator.create_epic_structure(integration_epic_plan, dry_run=False)
        
        assert result["success"] is True
        assert len(result["created_tickets"]["stories"]) == 1
        assert len(result["created_tickets"]["tasks"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
