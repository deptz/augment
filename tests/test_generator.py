import pytest
from unittest.mock import Mock, patch
from src.generator import DescriptionGenerator
from src.models import TicketInfo, PRDContent, GenerationContext
from src.jira_client import JiraClient
from src.llm_client import LLMClient


@pytest.fixture
def mock_jira_client():
    client = Mock(spec=JiraClient)
    client.should_update_ticket.return_value = True
    client.update_ticket_description.return_value = True
    client.extract_prd_url.return_value = "https://confluence.example.com/page/123"
    client.extract_rfc_url.return_value = None  # No RFC URL by default
    client.find_story_tickets.return_value = []  # No story tickets by default
    return client


@pytest.fixture
def mock_llm_client():
    client = Mock(spec=LLMClient)
    
    # Mock the provider
    mock_provider = Mock()
    mock_provider.generate_description.return_value = """**Purpose:**
This task implements user authentication to improve application security.

**Scopes:**
- Added login controller
- Integrated JWT library
- Created token validation middleware

**Expected Outcome:**
- Users can securely authenticate using JWT tokens
- Application supports stateless authentication"""
    mock_provider.api_key = "test-key"
    mock_provider.model = "gpt-4o"
    mock_provider.system_prompt = "Test system prompt"
    mock_provider.temperature = 0.7
    
    client.provider = mock_provider
    client.provider_name = "openai"
    client.generate_description.return_value = mock_provider.generate_description.return_value
    
    return client


@pytest.fixture
def sample_ticket_data():
    return {
        'key': 'TEST-123',
        'fields': {
            'summary': 'Implement JWT Authentication',
            'description': None,
            'status': {'name': 'Done'},
            'parent': {
                'key': 'STORY-456',
                'fields': {'summary': 'User Authentication Epic'}
            },
            'customfield_10001': 'https://confluence.example.com/page/123',
            'created': '2023-08-15T10:30:00.000+0000',
            'updated': '2023-08-16T15:45:00.000+0000'
        }
    }


@pytest.fixture
def sample_prd_content():
    return PRDContent(
        title="Authentication RFC",
        url="https://confluence.example.com/page/123",
        summary="Implement JWT-based authentication to replace session-based auth",
        goals="Improve scalability and security of user authentication",
        content="Full content of the authentication RFC..."
    )


@pytest.fixture
def description_generator(mock_jira_client, mock_llm_client):
    return DescriptionGenerator(
        jira_client=mock_jira_client,
        bitbucket_client=None,
        confluence_client=None,
        llm_client=mock_llm_client,
        prompt_template="Test template: {{ticket_key}} - {{ticket_title}}"
    )


class TestDescriptionGenerator:
    
    def test_process_ticket_success(self, description_generator, mock_jira_client, sample_ticket_data):
        """Test successful ticket processing"""
        mock_jira_client.get_ticket.return_value = sample_ticket_data
        
        result = description_generator.process_ticket('TEST-123', dry_run=True)
        
        assert result.success is True
        assert result.ticket_key == 'TEST-123'
        assert result.description is not None
        assert "Purpose" in result.description.description
        assert "Scopes" in result.description.description
        assert "Expected Outcome" in result.description.description
    
    def test_process_ticket_no_data(self, description_generator, mock_jira_client):
        """Test handling when ticket data cannot be fetched"""
        mock_jira_client.get_ticket.return_value = None
        
        result = description_generator.process_ticket('TEST-123', dry_run=True)
        
        assert result.success is False
        assert result.error == "Failed to fetch ticket data"
    
    def test_process_ticket_should_not_update(self, description_generator, mock_jira_client, sample_ticket_data):
        """Test skipping tickets that should not be updated"""
        mock_jira_client.get_ticket.return_value = sample_ticket_data
        mock_jira_client.should_update_ticket.return_value = False
        
        result = description_generator.process_ticket('TEST-123', dry_run=True)
        
        assert result.success is False
        assert result.skipped_reason == "Ticket already has description"
    
    def test_build_context(self, description_generator, sample_ticket_data):
        """Test context building from ticket data"""
        context = description_generator._build_context(sample_ticket_data)
        
        assert isinstance(context, GenerationContext)
        assert context.ticket.key == 'TEST-123'
        assert context.ticket.title == 'Implement JWT Authentication'
        assert context.ticket.parent_key == 'STORY-456'
        assert context.ticket.parent_summary == 'User Authentication Epic'
    
    def test_build_prompt(self, description_generator):
        """Test prompt building with template variables"""
        ticket = TicketInfo(
            key='TEST-123',
            title='Test Ticket',
            status='Done'
        )
        
        context = GenerationContext(ticket=ticket)
        prompt = description_generator._build_prompt(context)
        
        assert 'TEST-123' in prompt
        assert 'Test Ticket' in prompt
    
    def test_format_pull_request_titles(self, description_generator):
        """Test formatting of pull request titles"""
        from src.models import PullRequest
        
        pull_requests = [
            PullRequest(id='1', title='Feature: Add authentication', source_branch='feature/auth', destination_branch='main', state='MERGED'),
            PullRequest(id='2', title='Fix: Authentication bug', source_branch='fix/auth-bug', destination_branch='main', state='MERGED')
        ]
        
        formatted = description_generator._format_pull_request_titles(pull_requests)
        
        assert '- Feature: Add authentication' in formatted
        assert '- Fix: Authentication bug' in formatted
    
    def test_format_commit_messages(self, description_generator):
        """Test formatting of commit messages"""
        from src.models import Commit
        
        commits = [
            Commit(hash='abc123', message='feat: add login controller\n\nDetailed description', author='developer@example.com'),
            Commit(hash='def456', message='fix: handle edge case in authentication', author='developer@example.com')
        ]
        
        formatted = description_generator._format_commit_messages(commits)
        
        assert '- feat: add login controller' in formatted
        assert '- fix: handle edge case in authentication' in formatted
        # Should only include first line of commit message
        assert 'Detailed description' not in formatted


if __name__ == '__main__':
    pytest.main([__file__])
