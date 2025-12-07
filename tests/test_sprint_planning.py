"""
Tests for Sprint Planning functionality
"""
import pytest
import os
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from src.jira_client import JiraClient
from src.sprint_planning_service import SprintPlanningService
from src.team_member_service import TeamMemberService
from src.planning_models import TaskPlan, TaskScope, CycleTimeEstimate, TaskTeam


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Setup and teardown test database for each test"""
    # Create temporary directory for test database
    test_db_dir = tempfile.mkdtemp()
    test_db_file = Path(test_db_dir) / "team_members.db"
    
    # Patch the database path
    import src.team_member_db as team_db_module
    monkeypatch.setattr(team_db_module, 'DB_FILE', test_db_file)
    
    # Initialize database
    team_db_module.init_database()
    
    yield
    
    # Cleanup
    if test_db_file.exists():
        test_db_file.unlink()
    if Path(test_db_dir).exists():
        shutil.rmtree(test_db_dir)


class TestJiraClientSprintMethods:
    """Tests for JiraClient sprint API methods"""
    
    @pytest.fixture
    def jira_client(self):
        return JiraClient(
            server_url="https://test.atlassian.net",
            username="test@example.com",
            api_token="test-token",
            prd_custom_field="customfield_10001"
        )
    
    @patch('src.jira_client.requests.Session.get')
    def test_get_board_sprints(self, mock_get, jira_client):
        """Test getting sprints for a board"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'values': [
                {
                    'id': 123,
                    'name': 'Sprint 1',
                    'state': 'active',
                    'startDate': '2025-01-15',
                    'endDate': '2025-01-29',
                    'originBoardId': 1
                }
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        sprints = jira_client.get_board_sprints(1, state="active")
        
        assert len(sprints) == 1
        assert sprints[0]['id'] == 123
        assert sprints[0]['name'] == 'Sprint 1'
        mock_get.assert_called_once()
    
    @patch('src.jira_client.requests.Session.get')
    def test_get_sprint(self, mock_get, jira_client):
        """Test getting sprint details"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'id': 123,
            'name': 'Sprint 1',
            'state': 'active',
            'startDate': '2025-01-15',
            'endDate': '2025-01-29'
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        sprint = jira_client.get_sprint(123)
        
        assert sprint['id'] == 123
        assert sprint['name'] == 'Sprint 1'
        mock_get.assert_called_once()
    
    @patch('src.jira_client.requests.Session.post')
    def test_create_sprint(self, mock_post, jira_client):
        """Test creating a sprint"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'id': 123,
            'name': 'New Sprint',
            'state': 'future'
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        sprint = jira_client.create_sprint(
            name="New Sprint",
            board_id=1,
            start_date="2025-01-15",
            end_date="2025-01-29"
        )
        
        assert sprint['id'] == 123
        assert sprint['name'] == 'New Sprint'
        mock_post.assert_called_once()
    
    @patch('src.jira_client.requests.Session.post')
    def test_add_issues_to_sprint(self, mock_post, jira_client):
        """Test adding issues to sprint"""
        mock_response = Mock()
        mock_response.status_code = 204
        mock_post.return_value = mock_response
        
        result = jira_client.add_issues_to_sprint(123, ["TASK-1", "TASK-2"])
        
        assert result is True
        mock_post.assert_called_once()
    
    @patch('src.jira_client.requests.Session.get')
    def test_get_sprint_issues(self, mock_get, jira_client):
        """Test getting sprint issues"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'issues': [
                {'key': 'TASK-1', 'fields': {'summary': 'Task 1'}},
                {'key': 'TASK-2', 'fields': {'summary': 'Task 2'}}
            ],
            'isLast': True
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        issues = jira_client.get_sprint_issues(123)
        
        assert len(issues) == 2
        assert issues[0]['key'] == 'TASK-1'
        mock_get.assert_called_once()
    
    @patch('src.jira_client.requests.Session.get')
    def test_get_board_id(self, mock_get, jira_client):
        """Test getting board ID for project"""
        mock_response = Mock()
        mock_response.json.return_value = {
            'values': [
                {'id': 1, 'name': 'Project Board'}
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        board_id = jira_client.get_board_id("PROJ")
        
        assert board_id == 1
        mock_get.assert_called_once()


class TestSprintPlanningService:
    """Tests for SprintPlanningService"""
    
    @pytest.fixture
    def mock_jira_client(self):
        client = Mock(spec=JiraClient)
        client.get_ticket.return_value = {
            'fields': {'summary': 'Test Epic'}
        }
        client.get_board_sprints.return_value = []
        return client
    
    @pytest.fixture
    def mock_team_service(self):
        service = Mock(spec=TeamMemberService)
        service.get_team_capacity.return_value = 10.0
        return service
    
    @pytest.fixture
    def sprint_service(self, mock_jira_client, mock_team_service):
        return SprintPlanningService(mock_jira_client, mock_team_service)
    
    def test_plan_epic_to_sprints_dry_run(self, sprint_service, mock_jira_client):
        """Test planning epic to sprints in dry run mode"""
        result = sprint_service.plan_epic_to_sprints(
            epic_key="EPIC-100",
            board_id=1,
            sprint_capacity_days=10.0,
            dry_run=True
        )
        
        assert result['epic_key'] == "EPIC-100"
        assert result['board_id'] == 1
        assert result['success'] is True
        mock_jira_client.get_ticket.assert_called_once_with("EPIC-100")
    
    def test_optimize_sprint_assignments(self, sprint_service):
        """Test optimizing sprint assignments"""
        tasks = [
            TaskPlan(
                key="TASK-1",
                summary="Task 1",
                purpose="Purpose 1",
                scopes=[TaskScope(description="Scope 1", complexity="medium", deliverable="Deliverable 1")],
                expected_outcomes=["Outcome 1"],
                cycle_time_estimate=CycleTimeEstimate(
                    development_days=2.0,
                    testing_days=1.0,
                    review_days=0.5,
                    deployment_days=0.0,
                    total_days=3.5,
                    confidence_level=0.8
                )
            ),
            TaskPlan(
                key="TASK-2",
                summary="Task 2",
                purpose="Purpose 2",
                scopes=[TaskScope(description="Scope 2", complexity="medium", deliverable="Deliverable 2")],
                expected_outcomes=["Outcome 2"],
                depends_on_tasks=["TASK-1"],
                cycle_time_estimate=CycleTimeEstimate(
                    development_days=1.0,
                    testing_days=0.5,
                    review_days=0.5,
                    deployment_days=0.0,
                    total_days=2.0,
                    confidence_level=0.8
                )
            )
        ]
        
        sprints = [
            {'id': 123, 'name': 'Sprint 1'},
            {'id': 124, 'name': 'Sprint 2'}
        ]
        
        assignments = sprint_service.optimize_sprint_assignments(tasks, sprints, 10.0)
        
        assert len(assignments) > 0
        # TASK-2 should be in same or later sprint than TASK-1 due to dependency
        task1_sprint = next((a['sprint_id'] for a in assignments if a['task_key'] == 'TASK-1'), None)
        task2_sprint = next((a['sprint_id'] for a in assignments if a['task_key'] == 'TASK-2'), None)
        
        if task1_sprint and task2_sprint:
            assert task2_sprint >= task1_sprint
    
    def test_topological_sort(self, sprint_service):
        """Test topological sort respects dependencies"""
        tasks = [
            TaskPlan(
                key="TASK-1",
                summary="Task 1",
                purpose="Purpose 1",
                scopes=[TaskScope(description="Scope 1", complexity="medium", deliverable="Deliverable 1")],
                expected_outcomes=["Outcome 1"]
            ),
            TaskPlan(
                key="TASK-2",
                summary="Task 2",
                purpose="Purpose 2",
                scopes=[TaskScope(description="Scope 2", complexity="medium", deliverable="Deliverable 2")],
                expected_outcomes=["Outcome 2"],
                depends_on_tasks=["TASK-1"]
            ),
            TaskPlan(
                key="TASK-3",
                summary="Task 3",
                purpose="Purpose 3",
                scopes=[TaskScope(description="Scope 3", complexity="medium", deliverable="Deliverable 3")],
                expected_outcomes=["Outcome 3"],
                depends_on_tasks=["TASK-2"]
            )
        ]
        
        dependency_graph = {
            "TASK-1": [],
            "TASK-2": ["TASK-1"],
            "TASK-3": ["TASK-2"]
        }
        
        sorted_tasks = sprint_service._topological_sort(tasks, dependency_graph)
        
        # TASK-1 should come before TASK-2, TASK-2 before TASK-3
        task1_idx = next((i for i, t in enumerate(sorted_tasks) if (t.key or t.summary) == "TASK-1"), -1)
        task2_idx = next((i for i, t in enumerate(sorted_tasks) if (t.key or t.summary) == "TASK-2"), -1)
        task3_idx = next((i for i, t in enumerate(sorted_tasks) if (t.key or t.summary) == "TASK-3"), -1)
        
        assert task1_idx < task2_idx
        assert task2_idx < task3_idx


class TestTeamMemberService:
    """Tests for TeamMemberService"""
    
    @pytest.fixture
    def team_service(self):
        return TeamMemberService()
    
    def test_create_member(self, team_service):
        """Test creating a team member"""
        member = team_service.create_member(
            name="John Doe",
            email="john@example.com",
            level="Senior",
            capacity_days_per_sprint=8.0,
            team_ids=[]
        )
        
        assert member['name'] == "John Doe"
        assert member['email'] == "john@example.com"
        assert member['level'] == "Senior"
        assert member['capacity_days_per_sprint'] == 8.0
    
    def test_get_members(self, team_service):
        """Test getting members"""
        # Create a test member first
        team_service.create_member(
            name="Test User",
            email="test@example.com",
            level="Mid",
            capacity_days_per_sprint=5.0,
            team_ids=[]
        )
        
        members = team_service.get_members(active_only=True)
        
        assert len(members) > 0
        assert any(m['email'] == "test@example.com" for m in members)
    
    def test_get_all_levels(self, team_service):
        """Test getting all career levels"""
        # Create members with different levels
        team_service.create_member(
            name="Junior Dev",
            email="junior@example.com",
            level="Junior",
            capacity_days_per_sprint=3.0,
            team_ids=[]
        )
        team_service.create_member(
            name="Senior Dev",
            email="senior@example.com",
            level="Senior",
            capacity_days_per_sprint=8.0,
            team_ids=[]
        )
        
        levels = team_service.get_all_levels()
        
        assert "Junior" in levels
        assert "Senior" in levels

