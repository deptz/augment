"""
Tests for OpenCode Integration
Tests for workspace management, OpenCode runner, and prompts
"""
import pytest
import json
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path
import tempfile
import shutil

from api.models.opencode import (
    RepoSpec,
    validate_repos_list,
    normalize_repo_input
)
from src.opencode_schemas import (
    validate_opencode_result,
    validate_result_content,
    TICKET_DESCRIPTION_SCHEMA,
    TASK_BREAKDOWN_SCHEMA,
    COVERAGE_CHECK_SCHEMA
)


class TestRepoSpec:
    """Tests for RepoSpec model"""
    
    def test_valid_https_url(self):
        """Test valid HTTPS git URL"""
        spec = RepoSpec(url="https://github.com/org/repo.git")
        assert spec.url == "https://github.com/org/repo.git"
        assert spec.branch is None
    
    def test_valid_ssh_url(self):
        """Test valid SSH git URL"""
        spec = RepoSpec(url="git@github.com:org/repo.git")
        assert spec.url == "git@github.com:org/repo.git"
    
    def test_valid_url_with_branch(self):
        """Test URL with branch specified"""
        spec = RepoSpec(url="https://github.com/org/repo.git", branch="develop")
        assert spec.url == "https://github.com/org/repo.git"
        assert spec.branch == "develop"
    
    def test_invalid_file_url(self):
        """Test that file:// URLs are rejected"""
        with pytest.raises(ValueError, match="Only HTTPS"):
            RepoSpec(url="file:///path/to/repo")
    
    def test_invalid_ftp_url(self):
        """Test that ftp:// URLs are rejected"""
        with pytest.raises(ValueError, match="Only HTTPS"):
            RepoSpec(url="ftp://server/repo.git")
    
    def test_dangerous_patterns_blocked(self):
        """Test that dangerous URL patterns are blocked"""
        with pytest.raises(ValueError, match="localhost"):
            RepoSpec(url="https://localhost/repo.git")
        
        with pytest.raises(ValueError, match="127.0.0.1"):
            RepoSpec(url="https://127.0.0.1/repo.git")
    
    def test_branch_sanitization(self):
        """Test branch name sanitization"""
        # Valid branch names
        spec = RepoSpec(url="https://github.com/org/repo.git", branch="feature/new-feature")
        assert spec.branch == "feature/new-feature"
        
        spec = RepoSpec(url="https://github.com/org/repo.git", branch="release-1.0.0")
        assert spec.branch == "release-1.0.0"
    
    def test_branch_path_traversal_blocked(self):
        """Test that .. in branch names is blocked"""
        with pytest.raises(ValueError, match="cannot contain"):
            RepoSpec(url="https://github.com/org/repo.git", branch="../etc/passwd")
    
    def test_invalid_branch_characters(self):
        """Test that invalid branch characters are rejected"""
        with pytest.raises(ValueError, match="Invalid branch name"):
            RepoSpec(url="https://github.com/org/repo.git", branch="branch;rm -rf /")


class TestValidateReposList:
    """Tests for validate_repos_list function"""
    
    def test_empty_list(self):
        """Test empty list returns None"""
        assert validate_repos_list([]) is None
        assert validate_repos_list(None) is None
    
    def test_string_urls(self):
        """Test list of string URLs"""
        repos = validate_repos_list(["https://github.com/org/repo1.git", "https://github.com/org/repo2.git"])
        assert len(repos) == 2
        assert all(isinstance(r, RepoSpec) for r in repos)
    
    def test_dict_specs(self):
        """Test list of dict specs"""
        repos = validate_repos_list([
            {"url": "https://github.com/org/repo1.git", "branch": "main"},
            {"url": "https://github.com/org/repo2.git"}
        ])
        assert len(repos) == 2
        assert repos[0].branch == "main"
        assert repos[1].branch is None
    
    def test_mixed_input(self):
        """Test mixed string and dict input"""
        repos = validate_repos_list([
            "https://github.com/org/repo1.git",
            {"url": "https://github.com/org/repo2.git", "branch": "develop"}
        ])
        assert len(repos) == 2
    
    def test_max_repos_limit(self):
        """Test maximum repos limit"""
        urls = [f"https://github.com/org/repo{i}.git" for i in range(10)]
        with pytest.raises(ValueError, match="Too many repositories"):
            validate_repos_list(urls, max_repos=5)
    
    def test_invalid_url_in_list(self):
        """Test that invalid URL in list raises error"""
        with pytest.raises(ValueError, match="Invalid repository"):
            validate_repos_list(["https://github.com/org/repo.git", "invalid-url"])


class TestOpenCodeSchemas:
    """Tests for OpenCode JSON schemas"""
    
    def test_ticket_description_valid(self):
        """Test valid ticket description result"""
        result = {
            "description": "This is a valid description that is long enough to pass validation.",
            "impacted_files": ["src/main.py", "tests/test_main.py"],
            "components": ["backend", "api"],
            "acceptance_criteria": ["AC1", "AC2"],
            "confidence": "high"
        }
        # Should not raise
        validate_opencode_result(result, "ticket_description")
    
    def test_ticket_description_minimal(self):
        """Test minimal valid ticket description"""
        result = {
            "description": "Minimal description"
        }
        validate_opencode_result(result, "ticket_description")
    
    def test_ticket_description_missing_required(self):
        """Test ticket description missing required field"""
        result = {
            "impacted_files": ["src/main.py"]
        }
        from jsonschema import ValidationError
        with pytest.raises(ValidationError):
            validate_opencode_result(result, "ticket_description")
    
    def test_task_breakdown_valid(self):
        """Test valid task breakdown result"""
        result = {
            "tasks": [
                {
                    "summary": "Implement API endpoint",
                    "description": "Create the REST endpoint for user management",
                    "files_to_modify": ["src/api/users.py"],
                    "estimated_effort": "medium",
                    "dependencies": []
                },
                {
                    "summary": "Add tests",
                    "description": "Write unit tests for the new endpoint",
                    "files_to_modify": ["tests/test_users.py"],
                    "estimated_effort": "small",
                    "dependencies": ["Implement API endpoint"]
                }
            ],
            "warnings": ["Large scope - consider splitting further"]
        }
        validate_opencode_result(result, "task_breakdown")
    
    def test_task_breakdown_empty_tasks(self):
        """Test task breakdown with empty tasks is valid schema but fails content check"""
        result = {"tasks": []}
        # Schema validation passes
        validate_opencode_result(result, "task_breakdown")
        # Content validation fails
        assert not validate_result_content(result, "task_breakdown")
    
    def test_coverage_check_valid(self):
        """Test valid coverage check result"""
        result = {
            "coverage_percentage": 75.5,
            "covered_requirements": [
                {
                    "requirement": "User authentication",
                    "tasks": ["TASK-1", "TASK-2"],
                    "files": ["src/auth.py"]
                }
            ],
            "gaps": [
                {
                    "requirement": "Password reset",
                    "missing_tasks": "No task covers password reset flow",
                    "affected_files": ["src/auth.py", "src/email.py"],
                    "severity": "important"
                }
            ],
            "risks": ["Authentication implementation not fully tested"]
        }
        validate_opencode_result(result, "coverage_check")
    
    def test_coverage_check_out_of_range(self):
        """Test coverage percentage out of range"""
        result = {"coverage_percentage": 150}  # Invalid: > 100
        from jsonschema import ValidationError
        with pytest.raises(ValidationError):
            validate_opencode_result(result, "coverage_check")
    
    def test_invalid_job_type(self):
        """Test invalid job type raises error"""
        with pytest.raises(ValueError, match="Unknown job type"):
            validate_opencode_result({}, "invalid_job_type")


class TestValidateResultContent:
    """Tests for semantic content validation"""
    
    def test_ticket_description_too_short(self):
        """Test ticket description too short fails content check"""
        result = {"description": "Too short"}
        assert not validate_result_content(result, "ticket_description")
    
    def test_ticket_description_valid_length(self):
        """Test ticket description with valid length passes"""
        result = {"description": "A" * 60}  # > 50 chars
        assert validate_result_content(result, "ticket_description")
    
    def test_task_breakdown_empty_description(self):
        """Test task with empty description fails"""
        result = {"tasks": [{"summary": "Task", "description": ""}]}
        assert not validate_result_content(result, "task_breakdown")
    
    def test_coverage_check_invalid_percentage(self):
        """Test coverage with non-numeric percentage fails"""
        result = {"coverage_percentage": "high"}  # Should be number
        assert not validate_result_content(result, "coverage_check")


class TestWorkspaceManager:
    """Tests for WorkspaceManager"""
    
    @pytest.fixture
    def workspace_manager(self):
        """Create a workspace manager for testing"""
        from src.workspace_manager import WorkspaceManager
        return WorkspaceManager(
            git_username="test",
            git_password="test",
            clone_timeout_seconds=30,
            shallow_clone=True
        )
    
    def test_get_workspace_path(self, workspace_manager):
        """Test workspace path generation"""
        path = workspace_manager.get_workspace_path("job-123")
        assert "job-123" in str(path)
    
    def test_add_auth_to_https_url(self, workspace_manager):
        """Test adding auth to HTTPS URL"""
        url = workspace_manager._add_auth_to_url("https://github.com/org/repo.git")
        assert "test:test@github.com" in url
    
    def test_ssh_url_unchanged(self, workspace_manager):
        """Test SSH URLs are not modified"""
        url = workspace_manager._add_auth_to_url("git@github.com:org/repo.git")
        assert url == "git@github.com:org/repo.git"
    
    def test_get_repo_name(self, workspace_manager):
        """Test repo name extraction"""
        assert workspace_manager._get_repo_name("https://github.com/org/repo.git") == "repo"
        assert workspace_manager._get_repo_name("https://github.com/org/repo") == "repo"


class TestOpenCodeRunner:
    """Tests for OpenCodeRunner"""
    
    @pytest.fixture
    def runner(self):
        """Create an OpenCode runner for testing"""
        from src.opencode_runner import OpenCodeRunner
        return OpenCodeRunner(
            docker_image="test-image",
            job_timeout_minutes=5,
            max_result_size_mb=10
        )
    
    def test_extract_json_plain(self, runner):
        """Test extracting plain JSON"""
        content = '{"key": "value"}'
        result = runner._extract_json(content)
        assert result == '{"key": "value"}'
    
    def test_extract_json_from_markdown(self, runner):
        """Test extracting JSON from markdown code block"""
        content = '''Here is the result:
```json
{"key": "value"}
```
'''
        result = runner._extract_json(content)
        assert '{"key": "value"}' in result
    
    @patch('src.opencode_runner.docker')
    def test_is_docker_available_success(self, mock_docker, runner):
        """Test Docker availability check success"""
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_docker.from_env.return_value = mock_client
        
        assert runner.is_docker_available() is True
    
    @patch('src.opencode_runner.docker')
    def test_is_docker_available_failure(self, mock_docker, runner):
        """Test Docker availability check failure"""
        mock_docker.from_env.side_effect = Exception("Docker not found")
        
        assert runner.is_docker_available() is False


class TestOpenCodePrompts:
    """Tests for OpenCode prompts"""
    
    def test_ticket_description_prompt(self):
        """Test ticket description prompt generation"""
        from src.prompts.opencode import ticket_description_prompt
        
        prompt = ticket_description_prompt(
            ticket_data={
                'key': 'TEST-123',
                'summary': 'Test ticket',
                'description': 'Existing description',
                'parent_summary': 'Parent epic'
            },
            repos=['repo1', 'repo2'],
            additional_context='Additional context here'
        )
        
        assert 'TEST-123' in prompt
        assert 'Test ticket' in prompt
        assert 'repo1' in prompt
        assert 'repo2' in prompt
        assert 'Additional context here' in prompt
        assert 'result.json' in prompt
    
    def test_task_breakdown_prompt(self):
        """Test task breakdown prompt generation"""
        from src.prompts.opencode import task_breakdown_prompt
        
        prompt = task_breakdown_prompt(
            story_data={
                'key': 'STORY-456',
                'summary': 'User story',
                'description': 'Story description',
                'acceptance_criteria': ['AC1', 'AC2']
            },
            repos=['backend-repo'],
            additional_context=None,
            max_tasks=5
        )
        
        assert 'STORY-456' in prompt
        assert 'User story' in prompt
        assert 'backend-repo' in prompt
        assert '5' in prompt  # max_tasks
        assert 'result.json' in prompt
    
    def test_coverage_check_prompt(self):
        """Test coverage check prompt generation"""
        from src.prompts.opencode import coverage_check_prompt
        
        prompt = coverage_check_prompt(
            story_data={
                'key': 'STORY-789',
                'summary': 'Coverage story',
                'description': 'Story to check'
            },
            tasks=[
                {'key': 'TASK-1', 'summary': 'Task 1', 'description': 'Task desc'}
            ],
            repos=['api-repo', 'frontend-repo'],
            additional_context='Check all coverage'
        )
        
        assert 'STORY-789' in prompt
        assert 'TASK-1' in prompt
        assert 'api-repo' in prompt
        assert 'frontend-repo' in prompt
        assert 'Check all coverage' in prompt
        assert 'result.json' in prompt
    
    def test_get_prompt_for_job_type(self):
        """Test get_prompt_for_job_type dispatcher"""
        from src.prompts.opencode import get_prompt_for_job_type
        
        # Test all job types
        for job_type in ['ticket_description', 'task_breakdown', 'coverage_check']:
            prompt = get_prompt_for_job_type(
                job_type=job_type,
                data={'key': 'TEST-1', 'summary': 'Test'},
                repos=['repo'],
                additional_context=None
            )
            assert 'result.json' in prompt
    
    def test_get_prompt_invalid_job_type(self):
        """Test invalid job type raises error"""
        from src.prompts.opencode import get_prompt_for_job_type
        
        with pytest.raises(ValueError, match="Unknown job type"):
            get_prompt_for_job_type(
                job_type="invalid",
                data={},
                repos=[],
                additional_context=None
            )


class TestOpenCodeRunnerAdvanced:
    """Advanced tests for OpenCodeRunner"""
    
    @pytest.fixture
    def runner(self):
        """Create an OpenCode runner for testing"""
        from src.opencode_runner import OpenCodeRunner
        return OpenCodeRunner(
            docker_image="test-image",
            job_timeout_minutes=5,
            max_result_size_mb=10,
            llm_config={
                'openai_api_key': 'test-key',
                'provider': 'openai',
                'openai_model': 'gpt-4o-mini'
            }
        )
    
    def test_build_container_environment(self, runner):
        """Test container environment includes LLM keys"""
        env = runner._build_container_environment()
        
        assert 'OPENCODE_WORKSPACE' in env
        assert env['OPENCODE_WORKSPACE'] == '/workspace'
        assert 'OPENAI_API_KEY' in env
        assert env['OPENAI_API_KEY'] == 'test-key'
        assert 'LLM_PROVIDER' in env
        assert env['LLM_PROVIDER'] == 'openai'
    
    def test_build_container_environment_from_env(self, runner):
        """Test container environment falls back to env vars"""
        import os
        runner.llm_config = {}  # Clear config
        
        # Mock environment
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'env-anthropic-key'}):
            env = runner._build_container_environment()
            assert 'ANTHROPIC_API_KEY' in env
            assert env['ANTHROPIC_API_KEY'] == 'env-anthropic-key'
    
    def test_set_llm_config(self, runner):
        """Test setting LLM config"""
        new_config = {'anthropic_api_key': 'new-key', 'provider': 'anthropic'}
        runner.set_llm_config(new_config)
        
        assert runner.llm_config == new_config
    
    @pytest.mark.asyncio
    async def test_cancellation_event(self, runner):
        """Test that cancellation event stops execution"""
        import asyncio
        from src.opencode_runner import OpenCodeRunner
        
        cancellation_event = asyncio.Event()
        cancellation_event.set()  # Set immediately
        
        with pytest.raises(asyncio.CancelledError):
            await runner._execute_internal(
                job_id="test-job",
                workspace_path=Path("/tmp/test"),
                prompt="test prompt",
                job_type="ticket_description",
                cancellation_event=cancellation_event
            )


class TestCoverageSchemaWithSuggestions:
    """Tests for coverage schema with suggestions fields"""
    
    def test_coverage_with_suggestions_valid(self):
        """Test coverage result with suggestions is valid"""
        result = {
            "coverage_percentage": 75.0,
            "gaps": [
                {"requirement": "Test requirement", "missing_tasks": "Need tests"}
            ],
            "suggestions_for_updates": [
                {
                    "task_key": "TASK-1",
                    "current_description": "Old desc",
                    "suggested_description": "New desc",
                    "ready_to_submit": {"description": "New desc"}
                }
            ],
            "suggestions_for_new_tasks": [
                {
                    "summary": "New task",
                    "description": "Task description",
                    "gap_addressed": "Test requirement",
                    "ready_to_submit": {"summary": "New task"}
                }
            ]
        }
        # Should not raise
        validate_opencode_result(result, "coverage_check")
    
    def test_coverage_prompt_includes_suggestions(self):
        """Test coverage prompt includes instructions for suggestions"""
        from src.prompts.opencode import coverage_check_prompt
        
        prompt = coverage_check_prompt(
            story_data={'key': 'STORY-1', 'summary': 'Test', 'description': 'Test desc'},
            tasks=[],
            repos=['repo1'],
            additional_context=None
        )
        
        assert 'suggestions_for_updates' in prompt
        assert 'suggestions_for_new_tasks' in prompt
        assert 'ready_to_submit' in prompt


class TestImagePullError:
    """Tests for ImagePullError exception"""
    
    def test_image_pull_error_is_container_error(self):
        """Test ImagePullError inherits from ContainerError"""
        from src.opencode_runner import ImagePullError, ContainerError
        
        error = ImagePullError("Image not found")
        assert isinstance(error, ContainerError)
        assert str(error) == "Image not found"


class TestSSERetryBehavior:
    """Tests for SSE retry behavior"""
    
    @pytest.mark.asyncio
    async def test_sse_retry_on_connection_error(self):
        """Test SSE retries on connection errors"""
        from src.opencode_runner import OpenCodeRunner, ContainerError, SSE_MAX_RETRIES
        
        runner = OpenCodeRunner(docker_image="test")
        
        with patch('src.opencode_runner.httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post.side_effect = \
                httpx.ConnectError("Connection refused")
            
            with pytest.raises(ContainerError) as exc_info:
                await runner._send_prompt_and_stream(
                    port=4096,
                    session_id="test-session",
                    prompt="test",
                    job_id="test-job"
                )
            
            assert f"after {SSE_MAX_RETRIES} attempts" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_sse_cancellation_during_retry(self):
        """Test cancellation is checked during SSE retry loop"""
        import asyncio
        from src.opencode_runner import OpenCodeRunner
        
        runner = OpenCodeRunner(docker_image="test")
        cancellation_event = asyncio.Event()
        cancellation_event.set()
        
        with pytest.raises(asyncio.CancelledError):
            await runner._send_prompt_and_stream(
                port=4096,
                session_id="test-session",
                prompt="test",
                job_id="test-job",
                cancellation_event=cancellation_event
            )
