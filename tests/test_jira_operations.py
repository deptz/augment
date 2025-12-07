"""
Tests for JIRA Operations API Endpoints
Tests for update-ticket and create-ticket endpoints with mandays support
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient

from api.main import app
from src.jira_client import JiraClient


@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)


@pytest.fixture
def mock_jira_client():
    """Mock JIRA client"""
    jira_client = Mock(spec=JiraClient)
    jira_client.get_ticket.return_value = {
        'fields': {
            'summary': 'Test Ticket',
            'description': 'Test description'
        }
    }
    jira_client.update_ticket_summary.return_value = True
    jira_client.update_ticket_description.return_value = True
    jira_client.update_test_case_custom_field.return_value = True
    jira_client.update_mandays_custom_field.return_value = True
    jira_client.get_ticket_type.return_value = "Task"
    jira_client.create_issue_link_generic.return_value = True
    jira_client.get_project_key_from_epic.return_value = "PROJ"
    jira_client.create_task_ticket.return_value = "PROJ-789"
    jira_client.create_issue_link.return_value = True
    return jira_client


@pytest.fixture
def mock_jira_client_dependency(mock_jira_client):
    """Override JIRA client dependency"""
    with patch('api.routes.jira_operations.get_jira_client', return_value=mock_jira_client):
        with patch('api.dependencies.get_jira_client', return_value=mock_jira_client):
            yield mock_jira_client


class TestUpdateTicketEndpoint:
    """Tests for POST /jira/update-ticket endpoint"""
    
    def test_update_ticket_preview_mode(self, client, mock_jira_client_dependency):
        """Test update ticket in preview mode"""
        response = client.post(
            "/jira/update-ticket",
            json={
                "ticket_key": "PROJ-123",
                "summary": "New summary",
                "mandays": 3.5
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["updated_in_jira"] is False
        assert "preview" in data
        assert data["preview"]["new_summary"] == "New summary"
        assert data["preview"]["new_mandays"] == 3.5
    
    def test_update_ticket_with_mandays(self, client, mock_jira_client_dependency):
        """Test updating ticket with mandays"""
        response = client.post(
            "/jira/update-ticket",
            json={
                "ticket_key": "PROJ-123",
                "mandays": 5.0,
                "update_jira": True
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["updated_in_jira"] is True
        assert "mandays" in data["updates_applied"]
        mock_jira_client_dependency.update_mandays_custom_field.assert_called_once_with("PROJ-123", 5.0)
    
    def test_update_ticket_without_mandays(self, client, mock_jira_client_dependency):
        """Test updating ticket without mandays (should not call update_mandays)"""
        response = client.post(
            "/jira/update-ticket",
            json={
                "ticket_key": "PROJ-123",
                "summary": "New summary",
                "update_jira": True
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_jira_client_dependency.update_mandays_custom_field.assert_not_called()
    
    def test_update_ticket_mandays_none(self, client, mock_jira_client_dependency):
        """Test that mandays=None doesn't trigger update"""
        response = client.post(
            "/jira/update-ticket",
            json={
                "ticket_key": "PROJ-123",
                "mandays": None,
                "update_jira": True
            }
        )
        
        assert response.status_code == 200
        mock_jira_client_dependency.update_mandays_custom_field.assert_not_called()


class TestCreateTicketEndpoint:
    """Tests for POST /jira/create-ticket endpoint"""
    
    def test_create_ticket_preview_mode(self, client, mock_jira_client_dependency):
        """Test create ticket in preview mode"""
        response = client.post(
            "/jira/create-ticket",
            json={
                "parent_key": "EPIC-100",
                "summary": "Test task",
                "description": "Test description",
                "story_key": "STORY-123"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["created_in_jira"] is False
        assert "preview" in data
    
    def test_create_ticket_creates_with_mandays(self, client, mock_jira_client_dependency):
        """Test that create ticket sets mandays from cycle time estimate"""
        response = client.post(
            "/jira/create-ticket",
            json={
                "parent_key": "EPIC-100",
                "summary": "Test task",
                "description": "Test description",
                "story_key": "STORY-123",
                "create_ticket": True
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["created_in_jira"] is True
        assert data["ticket_key"] == "PROJ-789"
        
        # Verify create_task_ticket was called (which should set mandays)
        mock_jira_client_dependency.create_task_ticket.assert_called_once()
        call_args = mock_jira_client_dependency.create_task_ticket.call_args
        task_plan = call_args[0][0]
        assert task_plan.cycle_time_estimate is not None
        assert task_plan.cycle_time_estimate.total_days == 2.0


