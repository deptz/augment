"""
Tests for Team-Based Task Generator
"""
import pytest
from unittest.mock import Mock, patch
from typing import List

from src.team_based_task_generator import TeamBasedTaskGenerator, StoryType
from src.planning_models import (
    StoryPlan, TaskPlan, TaskTeam, AcceptanceCriteria, 
    CycleTimeEstimate, TestCase, TaskScope
)
from src.llm_client import LLMClient
from src.planning_prompt_engine import PlanningPromptEngine


class TestTeamBasedTaskGenerator:
    """Test cases for TeamBasedTaskGenerator"""

    @pytest.fixture
    def mock_llm_client(self):
        """Mock LLM client for testing"""
        mock = Mock(spec=LLMClient)
        mock.generate_content.return_value = """
**Team:** Backend
**Task Title:** API implementation for user authentication
**Purpose:** Implement backend authentication services
**Scope:** Create user authentication endpoints and session management
**Expected Outcome:** Working authentication API
**Dependencies:** Database setup

**Team:** Frontend
**Task Title:** Login interface for user authentication
**Purpose:** Create user interface for authentication
**Scope:** Implement login form and user feedback
**Expected Outcome:** Working login interface
**Dependencies:** API implementation

**Team:** QA
**Task Title:** Authentication testing
**Purpose:** Validate authentication functionality
**Scope:** Test login flows and security measures
**Expected Outcome:** Complete test coverage
**Dependencies:** Login interface
        """
        return mock

    @pytest.fixture
    def mock_prompt_engine(self):
        """Mock prompt engine for testing"""
        return Mock(spec=PlanningPromptEngine)

    @pytest.fixture
    def task_generator(self, mock_llm_client, mock_prompt_engine):
        """Create task generator instance"""
        return TeamBasedTaskGenerator(mock_llm_client, mock_prompt_engine)

    @pytest.fixture
    def sample_story(self):
        """Sample story for testing"""
        return StoryPlan(
            summary="Implement user authentication system",
            description="Create a secure user authentication system with login and logout functionality",
            acceptance_criteria=[
                AcceptanceCriteria(
                    scenario="User login with valid credentials",
                    given="User has valid credentials",
                    when="User attempts to login",
                    then="User is authenticated and redirected to dashboard"
                ),
                AcceptanceCriteria(
                    scenario="User logout",
                    given="User is logged in",
                    when="User clicks logout",
                    then="User session is terminated and redirected to login page"
                )
            ],
            test_cases=[],
            epic_key="AUTH-100"
        )

    def test_story_type_analysis_api_feature(self, task_generator, sample_story):
        """Test story type analysis for API features"""
        # Test API-focused story (without data processing to avoid confusion)
        api_story = StoryPlan(
            summary="Create REST API endpoints for user management",
            description="Implement backend API endpoints for user management operations",
            acceptance_criteria=[],
            test_cases=[],
            epic_key="API-100"
        )
        
        story_type = task_generator._analyze_story_type(api_story)
        assert story_type == StoryType.API_FEATURE

    def test_story_type_analysis_ui_feature(self, task_generator):
        """Test story type analysis for UI features"""
        ui_story = StoryPlan(
            summary="Design responsive user interface for dashboard",
            description="Create modern UI components and responsive layout for user dashboard",
            acceptance_criteria=[],
            test_cases=[],
            epic_key="UI-100"
        )
        
        story_type = task_generator._analyze_story_type(ui_story)
        assert story_type == StoryType.UI_FEATURE

    def test_story_type_analysis_data_feature(self, task_generator):
        """Test story type analysis for data features"""
        data_story = StoryPlan(
            summary="Implement data analytics processing pipeline",
            description="Create data processing pipeline for analytics and reporting",
            acceptance_criteria=[],
            test_cases=[],
            epic_key="DATA-100"
        )
        
        story_type = task_generator._analyze_story_type(data_story)
        assert story_type == StoryType.DATA_FEATURE

    def test_complexity_analysis(self, task_generator, sample_story):
        """Test story complexity analysis"""
        complexity_analysis = task_generator._analyze_story_complexity(sample_story)
        
        assert "ui_complexity" in complexity_analysis
        assert "backend_complexity" in complexity_analysis
        assert "qa_complexity" in complexity_analysis
        assert "overall_complexity" in complexity_analysis
        
        # Should be medium complexity with 2 acceptance criteria
        assert complexity_analysis["qa_complexity"] == "medium"

    def test_ai_team_task_generation(self, task_generator, sample_story, mock_llm_client):
        """Test AI-powered team task generation"""
        tasks = task_generator._generate_ai_team_tasks(
            story=sample_story,
            story_type=StoryType.USER_WORKFLOW,
            max_cycle_days=3
        )
        
        # Should generate tasks from AI response
        assert len(tasks) > 0
        
        # Should have different teams represented
        teams = {task.team for task in tasks}
        assert TaskTeam.BACKEND in teams
        assert TaskTeam.FRONTEND in teams
        assert TaskTeam.QA in teams
        
        # Verify LLM was called
        mock_llm_client.generate_content.assert_called_once()

    def test_team_separation_prompt_creation(self, task_generator, sample_story):
        """Test creation of team separation prompt"""
        prompt = task_generator._create_team_separation_prompt(
            story=sample_story,
            story_type=StoryType.USER_WORKFLOW,
            max_cycle_days=3
        )
        
        assert "Backend" in prompt
        assert "Frontend" in prompt
        assert "QA" in prompt
        assert sample_story.summary in prompt
        assert "3 days" in prompt

    def test_ai_response_parsing(self, task_generator, sample_story):
        """Test parsing of AI response into tasks"""
        ai_response = """
**Team:** Backend
**Task Title:** Backend API implementation
**Purpose:** Create backend services
**Scope:** Implement API endpoints and business logic
**Expected Outcome:** Working backend API
**Dependencies:** Database setup

**Team:** Frontend
**Task Title:** Frontend UI implementation
**Purpose:** Create user interface
**Scope:** Implement UI components and user interactions
**Expected Outcome:** Working frontend interface
**Dependencies:** Backend API

**Team:** QA
**Task Title:** Quality assurance testing
**Purpose:** Validate functionality
**Scope:** Create and execute test cases
**Expected Outcome:** Quality validated
**Dependencies:** Frontend implementation
        """
        
        tasks = task_generator._parse_team_task_response(ai_response, sample_story)
        
        assert len(tasks) == 3
        
        # Check team assignments
        backend_tasks = [t for t in tasks if t.team == TaskTeam.BACKEND]
        frontend_tasks = [t for t in tasks if t.team == TaskTeam.FRONTEND]
        qa_tasks = [t for t in tasks if t.team == TaskTeam.QA]
        
        assert len(backend_tasks) == 1
        assert len(frontend_tasks) == 1
        assert len(qa_tasks) == 1
        
        # Check task content
        backend_task = backend_tasks[0]
        assert "API" in backend_task.summary
        assert backend_task.purpose == "Create backend services"

    def test_pattern_based_task_generation(self, task_generator, sample_story):
        """Test pattern-based task generation"""
        complexity_analysis = {
            "ui_complexity": "medium",
            "backend_complexity": "medium", 
            "qa_complexity": "medium",
            "overall_complexity": "medium"
        }
        
        tasks = task_generator._generate_pattern_team_tasks(
            story=sample_story,
            story_type=StoryType.USER_WORKFLOW,
            complexity_analysis=complexity_analysis
        )
        
        assert len(tasks) > 0
        
        # Should have different teams
        teams = {task.team for task in tasks}
        assert TaskTeam.BACKEND in teams
        assert TaskTeam.FRONTEND in teams
        assert TaskTeam.QA in teams

    def test_cycle_time_estimation_by_team(self, task_generator):
        """Test cycle time estimation by team"""
        # Test backend estimation
        backend_estimate = task_generator._estimate_cycle_time_by_team(
            TaskTeam.BACKEND, 
            "Implement complex database integration"
        )
        assert backend_estimate.development_days > 0
        assert backend_estimate.total_days > 0
        assert backend_estimate.total_days > backend_estimate.development_days
        
        # Test frontend estimation
        frontend_estimate = task_generator._estimate_cycle_time_by_team(
            TaskTeam.FRONTEND,
            "Create simple UI component"
        )
        assert frontend_estimate.development_days > 0
        
        # Test QA estimation
        qa_estimate = task_generator._estimate_cycle_time_by_team(
            TaskTeam.QA,
            "Execute comprehensive test suite"
        )
        assert qa_estimate.testing_days > qa_estimate.development_days

    def test_team_test_case_generation(self, task_generator):
        """Test test case generation by team"""
        # Backend test cases
        backend_tests = task_generator._generate_team_test_cases(
            TaskTeam.BACKEND, 
            "API implementation"
        )
        assert len(backend_tests) >= 1
        assert any("unit" in test.type for test in backend_tests)
        
        # Frontend test cases
        frontend_tests = task_generator._generate_team_test_cases(
            TaskTeam.FRONTEND,
            "UI component"
        )
        assert len(frontend_tests) >= 1
        assert any("UI" in test.title for test in frontend_tests)
        
        # QA test cases
        qa_tests = task_generator._generate_team_test_cases(
            TaskTeam.QA,
            "Feature testing"
        )
        assert len(qa_tests) >= 1
        assert any("test plan" in test.title.lower() for test in qa_tests)

    def test_team_separation_enforcement(self, task_generator, sample_story):
        """Test enforcement of team separation"""
        # Create tasks with missing teams
        incomplete_tasks = [
            TaskPlan(
                summary="Backend task",
                purpose="Backend work",
                scopes=[TaskScope(description="Backend implementation", complexity="medium", dependencies=[], deliverable="Backend")],
                expected_outcomes=["Backend complete"],
                team=TaskTeam.BACKEND,
                test_cases=[],
                cycle_time_estimate=CycleTimeEstimate(
                    development_days=1.0,
                    testing_days=0.5,
                    review_days=0.5,
                    deployment_days=0.5,
                    total_days=2.5,
                    confidence_level=0.7
                ),
                epic_key=sample_story.epic_key
            )
        ]
        
        completed_tasks = task_generator._ensure_team_separation(
            incomplete_tasks,
            sample_story,
            StoryType.USER_WORKFLOW
        )
        
        # Should add missing teams
        teams = {task.team for task in completed_tasks}
        assert TaskTeam.BACKEND in teams
        assert TaskTeam.FRONTEND in teams
        assert TaskTeam.QA in teams

    def test_task_splitting_for_oversized_tasks(self, task_generator):
        """Test splitting of oversized tasks"""
        oversized_task = TaskPlan(
            summary="Large task",
            purpose="Complete large feature",
            scopes=[
                TaskScope(description="Part 1", complexity="high", dependencies=[], deliverable="Part 1"),
                TaskScope(description="Part 2", complexity="high", dependencies=[], deliverable="Part 2")
            ],
            expected_outcomes=["Feature complete"],
            team=TaskTeam.BACKEND,
            test_cases=[TestCase(
                title="Test",
                type="unit", 
                description="Test the feature",
                expected_result="Works"
            )],
            cycle_time_estimate=CycleTimeEstimate(
                development_days=5.0,
                testing_days=1.0,
                review_days=1.0,
                deployment_days=1.0,
                total_days=8.0,
                confidence_level=0.7
            ),
            epic_key="TEST-100"
        )
        
        split_tasks = task_generator._split_oversized_task(oversized_task, 3)
        
        # Should split into multiple tasks
        assert len(split_tasks) > 1
        
        # Each split task should be under or at limit (allowing small buffer for splitting algorithm)
        for task in split_tasks:
            if task.cycle_time_estimate:
                assert task.cycle_time_estimate.total_days <= 3.5  # Allow small buffer for split tasks

    def test_fallback_task_generation(self, task_generator, sample_story):
        """Test fallback task generation when AI fails"""
        fallback_tasks = task_generator._generate_fallback_team_tasks(sample_story)
        
        assert len(fallback_tasks) == 3  # Backend, Frontend, QA
        
        teams = {task.team for task in fallback_tasks}
        assert TaskTeam.BACKEND in teams
        assert TaskTeam.FRONTEND in teams
        assert TaskTeam.QA in teams
        
        # Each task should have proper structure
        for task in fallback_tasks:
            assert task.summary
            assert task.purpose
            assert len(task.scopes) > 0
            assert len(task.expected_outcomes) > 0
            assert task.cycle_time_estimate
            assert len(task.test_cases) > 0

    def test_complete_team_task_generation_workflow(self, task_generator, sample_story, mock_llm_client):
        """Test complete workflow of team-separated task generation"""
        tasks = task_generator.generate_team_separated_tasks(
            story=sample_story,
            max_cycle_days=3,
            force_separation=True
        )
        
        assert len(tasks) > 0
        
        # Should have proper team separation
        teams = {task.team for task in tasks}
        assert len(teams) >= 2  # At least 2 different teams
        
        # All tasks should be under cycle limit
        for task in tasks:
            if task.cycle_time_estimate:
                assert task.cycle_time_estimate.total_days <= 3
        
        # All tasks should have required fields
        for task in tasks:
            assert task.summary
            assert task.purpose
            assert task.team in [TaskTeam.BACKEND, TaskTeam.FRONTEND, TaskTeam.QA, TaskTeam.DEVOPS, TaskTeam.FULLSTACK]
            assert len(task.scopes) > 0
            assert len(task.expected_outcomes) > 0

    def test_task_patterns_initialization(self, task_generator):
        """Test task patterns are properly initialized"""
        patterns = task_generator.task_patterns
        
        assert StoryType.API_FEATURE in patterns
        assert StoryType.UI_FEATURE in patterns
        assert StoryType.USER_WORKFLOW in patterns
        
        # Each pattern should have proper structure
        for story_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                assert 'team' in pattern
                assert 'summary' in pattern
                assert 'purpose' in pattern
                assert pattern['team'] in [TaskTeam.BACKEND, TaskTeam.FRONTEND, TaskTeam.QA]

    def test_team_responsibilities_initialization(self, task_generator):
        """Test team responsibilities are properly defined"""
        responsibilities = task_generator.team_responsibilities
        
        assert TaskTeam.BACKEND in responsibilities
        assert TaskTeam.FRONTEND in responsibilities
        assert TaskTeam.QA in responsibilities
        
        # Each team should have defined responsibilities
        for team, resp_list in responsibilities.items():
            assert len(resp_list) > 0
            assert all(isinstance(resp, str) for resp in resp_list)

    @patch('src.team_based_task_generator.logger')
    def test_error_handling_in_ai_generation(self, mock_logger, task_generator, sample_story, mock_llm_client):
        """Test error handling when AI generation fails"""
        # Make LLM client raise an exception
        mock_llm_client.generate_content.side_effect = Exception("LLM error")
        
        tasks = task_generator._generate_ai_team_tasks(
            story=sample_story,
            story_type=StoryType.USER_WORKFLOW,
            max_cycle_days=3
        )
        
        # Should return empty list on error
        assert tasks == []
        
        # Should log the warning
        mock_logger.warning.assert_called()

    def test_task_generation_with_different_story_types(self, task_generator, mock_llm_client):
        """Test task generation adapts to different story types"""
        # API-focused story
        api_story = StoryPlan(
            summary="Create user management API",
            description="Implement REST API for user management operations",
            acceptance_criteria=[],
            test_cases=[],
            epic_key="API-100"
        )
        
        api_tasks = task_generator.generate_team_separated_tasks(
            story=api_story,
            max_cycle_days=3
        )
        
        # Should include backend tasks for API story
        backend_tasks = [t for t in api_tasks if t.team == TaskTeam.BACKEND]
        assert len(backend_tasks) > 0
        
        # UI-focused story
        ui_story = StoryPlan(
            summary="Design user profile interface",
            description="Create responsive user interface for profile management",
            acceptance_criteria=[],
            test_cases=[],
            epic_key="UI-100"
        )
        
        ui_tasks = task_generator.generate_team_separated_tasks(
            story=ui_story,
            max_cycle_days=3
        )
        
        # Should include frontend tasks for UI story
        frontend_tasks = [t for t in ui_tasks if t.team == TaskTeam.FRONTEND]
        assert len(frontend_tasks) > 0

    def test_task_dependency_analysis(self, task_generator, mock_llm_client):
        """Test that task dependencies are properly analyzed and set up"""
        # Create a story that should generate backend -> frontend -> QA dependencies
        story = StoryPlan(
            summary="User profile management",
            description="Users can create and update their profiles",
            acceptance_criteria=[
                AcceptanceCriteria(
                    scenario="Profile creation",
                    given="User is logged in",
                    when="User creates profile",
                    then="Profile is saved"
                )
            ],
            epic_key="PROJ-123"
        )
        
        # Mock AI response with team-separated tasks
        mock_llm_client.generate_content.return_value = """
Team: Backend
Task Title: User profile API endpoints
Purpose: Create API for profile management
Scope: Implement CRUD operations for user profiles
Expected Outcome: Working profile API endpoints

Team: Frontend  
Task Title: User profile UI components
Purpose: Create user interface for profile management
Scope: Build profile forms and display components
Expected Outcome: Working profile UI

Team: QA
Task Title: Profile feature testing
Purpose: Test profile functionality end-to-end
Scope: Test profile creation, editing, and validation
Expected Outcome: Comprehensive test coverage
"""
        
        # Generate tasks with dependencies
        tasks = task_generator.generate_team_separated_tasks(story, max_cycle_days=3, force_separation=True)
        
        # Verify we have all three teams
        backend_tasks = [t for t in tasks if t.team == TaskTeam.BACKEND]
        frontend_tasks = [t for t in tasks if t.team == TaskTeam.FRONTEND] 
        qa_tasks = [t for t in tasks if t.team == TaskTeam.QA]
        
        assert len(backend_tasks) >= 1, "Should have backend tasks"
        assert len(frontend_tasks) >= 1, "Should have frontend tasks"
        assert len(qa_tasks) >= 1, "Should have QA tasks"
        
        # Verify dependency relationships
        frontend_task = frontend_tasks[0]
        qa_task = qa_tasks[0]
        
        # Frontend should be blocked by backend
        assert TaskTeam.BACKEND in frontend_task.blocked_by_teams, "Frontend should be blocked by backend"
        assert len(frontend_task.depends_on_tasks) > 0, "Frontend should have dependencies"
        
        # QA should be blocked by implementation teams
        assert len(qa_task.blocked_by_teams) > 0, "QA should be blocked by implementation teams"
        assert len(qa_task.depends_on_tasks) > 0, "QA should have dependencies"

    def test_bulk_creation_with_dependencies(self):
        """Test that bulk ticket creation handles task dependencies"""
        from src.bulk_ticket_creator import BulkTicketCreator
        from src.jira_client import JiraClient
        from unittest.mock import Mock
        from src.planning_models import EpicPlan
        
        # Mock JIRA client
        mock_jira = Mock(spec=JiraClient)
        mock_jira.get_project_key_from_epic.return_value = "PROJ"
        mock_jira.create_story_ticket.return_value = "PROJ-456"
        mock_jira.create_task_ticket.side_effect = ["PROJ-457", "PROJ-458", "PROJ-459"]
        mock_jira.create_issue_link.return_value = True
        mock_jira.validate_ticket_relationships.return_value = {"valid": True, "issues": []}
        
        creator = BulkTicketCreator(mock_jira)
        
        # Create tasks with dependencies
        backend_task = TaskPlan(
            summary="Backend API implementation",
            purpose="Create backend services",
            scopes=[TaskScope(description="Implement API", complexity="medium", dependencies=[], deliverable="Working API")],
            expected_outcomes=["API endpoints ready"],
            team=TaskTeam.BACKEND,
            epic_key="PROJ-123"
        )
        
        frontend_task = TaskPlan(
            summary="Frontend UI implementation", 
            purpose="Create user interface",
            scopes=[TaskScope(description="Build UI", complexity="medium", dependencies=[], deliverable="Working UI")],
            expected_outcomes=["UI components ready"],
            team=TaskTeam.FRONTEND,
            epic_key="PROJ-123",
            depends_on_tasks=["task_1"],  # Depends on backend task
            blocked_by_teams=[TaskTeam.BACKEND]
        )
        
        qa_task = TaskPlan(
            summary="QA testing",
            purpose="Test the feature",
            scopes=[TaskScope(description="Test functionality", complexity="medium", dependencies=[], deliverable="Test results")],
            expected_outcomes=["Feature tested"],
            team=TaskTeam.QA,
            epic_key="PROJ-123", 
            depends_on_tasks=["task_1", "task_2"],  # Depends on both implementation tasks
            blocked_by_teams=[TaskTeam.BACKEND, TaskTeam.FRONTEND]
        )
        
        story = StoryPlan(
            summary="Feature implementation",
            description="Implement a new feature",
            acceptance_criteria=[AcceptanceCriteria(
                scenario="Feature works",
                given="System is ready", 
                when="Feature is used",
                then="It works correctly"
            )],
            tasks=[backend_task, frontend_task, qa_task],
            epic_key="PROJ-123"
        )
        
        epic_plan = EpicPlan(
            epic_key="PROJ-123",
            epic_title="Feature epic",
            stories=[story]
        )
        
        # Test creation with dependencies (dry run)
        results = creator.create_epic_structure(epic_plan, dry_run=True)
        
        # Verify results
        assert results["success"], f"Creation should succeed: {results.get('errors', [])}"
        assert len(results["created_tickets"]["tasks"]) == 3, "Should create 3 tasks"
        
        # Check that dependency relationships were simulated
        blocking_relationships = [r for r in results["relationships_created"] if r["type"] == "Blocks"]
        assert len(blocking_relationships) > 0, "Should have blocking relationships"
