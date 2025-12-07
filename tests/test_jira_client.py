import pytest
from unittest.mock import Mock, patch
from src.jira_client import JiraClient


class TestJiraClient:
    
    @pytest.fixture
    def jira_client(self):
        return JiraClient(
            server_url="https://test.atlassian.net",
            username="test@example.com",
            api_token="test-token",
            prd_custom_field="customfield_10001"
        )
    
    def test_should_update_ticket_empty_description(self, jira_client):
        """Test that tickets with empty descriptions should be updated"""
        ticket_data = {
            'fields': {
                'description': None
            }
        }
        
        assert jira_client.should_update_ticket(ticket_data) is True
    
    def test_should_update_ticket_placeholder_text(self, jira_client):
        """Test that tickets with placeholder text should be updated"""
        ticket_data = {
            'fields': {
                'description': 'TODO: Add description'
            }
        }
        
        assert jira_client.should_update_ticket(ticket_data) is True
    
    def test_should_not_update_ticket_with_content(self, jira_client):
        """Test that tickets with real content should not be updated"""
        ticket_data = {
            'fields': {
                'description': {
                    'type': 'doc',
                    'version': 1,
                    'content': [
                        {
                            'type': 'paragraph',
                            'content': [
                                {
                                    'type': 'text',
                                    'text': 'This is a real description with actual content.'
                                }
                            ]
                        }
                    ]
                }
            }
        }
        
        assert jira_client.should_update_ticket(ticket_data) is False
    
    def test_extract_prd_url_string_field(self, jira_client):
        """Test extracting PRD URL from string custom field"""
        ticket_data = {
            'fields': {
                'customfield_10001': 'https://confluence.example.com/page/123'
            }
        }
        
        url = jira_client.extract_prd_url(ticket_data)
        assert url == 'https://confluence.example.com/page/123'
    
    def test_extract_prd_url_dict_field(self, jira_client):
        """Test extracting PRD URL from dict custom field"""
        ticket_data = {
            'fields': {
                'customfield_10001': {
                    'value': 'https://confluence.example.com/page/123'
                }
            }
        }
        
        url = jira_client.extract_prd_url(ticket_data)
        assert url == 'https://confluence.example.com/page/123'
    
    def test_extract_prd_url_empty_field(self, jira_client):
        """Test handling empty PRD custom field"""
        ticket_data = {
            'fields': {
                'customfield_10001': None
            }
        }
        
        url = jira_client.extract_prd_url(ticket_data)
        assert url is None
    
    def test_extract_text_from_adf(self, jira_client):
        """Test extracting text from Atlassian Document Format"""
        adf_content = {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'paragraph',
                    'content': [
                        {
                            'type': 'text',
                            'text': 'Hello world'
                        }
                    ]
                },
                {
                    'type': 'paragraph',
                    'content': [
                        {
                            'type': 'text',
                            'text': 'Second paragraph'
                        }
                    ]
                }
            ]
        }
        
        text = jira_client._extract_text_from_adf(adf_content)
        assert 'Hello world' in text
        assert 'Second paragraph' in text

    def test_extract_rfc_url_string_field(self, jira_client):
        """Test extracting RFC URL from string custom field"""
        # Configure the client for RFC field
        jira_client.rfc_custom_field = "customfield_10002"
        
        ticket_data = {
            'fields': {
                'customfield_10002': 'https://confluence.example.com/rfc/456'
            }
        }
        
        url = jira_client.extract_rfc_url(ticket_data)
        assert url == 'https://confluence.example.com/rfc/456'
    
    def test_extract_rfc_url_dict_field(self, jira_client):
        """Test extracting RFC URL from dict custom field"""
        jira_client.rfc_custom_field = "customfield_10002"
        
        ticket_data = {
            'fields': {
                'customfield_10002': {
                    'content': 'Check RFC: https://confluence.example.com/rfc/789'
                }
            }
        }
        
        url = jira_client.extract_rfc_url(ticket_data)
        assert url == 'https://confluence.example.com/rfc/789'
    
    def test_extract_rfc_url_empty_field(self, jira_client):
        """Test extracting RFC URL when field is empty"""
        jira_client.rfc_custom_field = "customfield_10002"
        
        ticket_data = {
            'fields': {
                'customfield_10002': None
            }
        }
        
        url = jira_client.extract_rfc_url(ticket_data)
        assert url is None

    def test_get_fields_list_includes_mandays(self):
        """Test that _get_fields_list includes mandays field when configured"""
        jira_client = JiraClient(
            server_url="https://test.atlassian.net",
            username="test@example.com",
            api_token="test-token",
            prd_custom_field="customfield_10001",
            mandays_custom_field="customfield_10004"
        )
        
        fields_list = jira_client._get_fields_list()
        assert "customfield_10004" in fields_list

    def test_get_fields_list_excludes_mandays_when_not_configured(self, jira_client):
        """Test that _get_fields_list excludes mandays field when not configured"""
        fields_list = jira_client._get_fields_list()
        assert "customfield_10004" not in fields_list

    @patch('src.jira_client.requests.Session')
    def test_create_task_ticket_with_mandays(self, mock_session_class):
        """Test that create_task_ticket sets mandays field when configured"""
        from src.planning_models import TaskPlan, CycleTimeEstimate, TaskScope, TaskTeam
        
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {'key': 'PROJ-123'}
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        jira_client = JiraClient(
            server_url="https://test.atlassian.net",
            username="test@example.com",
            api_token="test-token",
            prd_custom_field="customfield_10001",
            mandays_custom_field="customfield_10004"
        )
        jira_client.session = mock_session
        
        cycle_estimate = CycleTimeEstimate(
            development_days=2.0,
            testing_days=0.5,
            review_days=0.5,
            deployment_days=0.5,
            total_days=3.5,
            confidence_level=0.8
        )
        
        task_plan = TaskPlan(
            summary="Test task",
            purpose="Test purpose",
            scopes=[TaskScope(description="Test scope", deliverable="Test deliverable")],
            expected_outcomes=["Test outcome"],
            team=TaskTeam.BACKEND,
            cycle_time_estimate=cycle_estimate,
            epic_key="EPIC-1"
        )
        
        result = jira_client.create_task_ticket(task_plan, "PROJ")
        
        assert result == "PROJ-123"
        call_args = mock_session.post.call_args
        assert call_args is not None
        issue_data = call_args[1]['json']
        assert issue_data['fields']['customfield_10004'] == 3.5

    @patch('src.jira_client.requests.Session')
    def test_create_task_ticket_without_mandays_field(self, mock_session_class):
        """Test that create_task_ticket works when mandays field is not configured"""
        from src.planning_models import TaskPlan, CycleTimeEstimate, TaskScope, TaskTeam
        
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {'key': 'PROJ-123'}
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        jira_client = JiraClient(
            server_url="https://test.atlassian.net",
            username="test@example.com",
            api_token="test-token",
            prd_custom_field="customfield_10001"
        )
        jira_client.session = mock_session
        
        cycle_estimate = CycleTimeEstimate(
            development_days=2.0,
            testing_days=0.5,
            review_days=0.5,
            deployment_days=0.5,
            total_days=3.5,
            confidence_level=0.8
        )
        
        task_plan = TaskPlan(
            summary="Test task",
            purpose="Test purpose",
            scopes=[TaskScope(description="Test scope", deliverable="Test deliverable")],
            expected_outcomes=["Test outcome"],
            team=TaskTeam.BACKEND,
            cycle_time_estimate=cycle_estimate,
            epic_key="EPIC-1"
        )
        
        result = jira_client.create_task_ticket(task_plan, "PROJ")
        
        assert result == "PROJ-123"
        call_args = mock_session.post.call_args
        assert call_args is not None
        issue_data = call_args[1]['json']
        assert 'customfield_10004' not in issue_data['fields']

    @patch('src.jira_client.requests.Session')
    def test_create_story_ticket_with_mandays_from_tasks(self, mock_session_class):
        """Test that create_story_ticket calculates mandays from child tasks"""
        from src.planning_models import StoryPlan, TaskPlan, CycleTimeEstimate, TaskScope, TaskTeam, AcceptanceCriteria
        
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {'key': 'STORY-123'}
        mock_session.post.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        jira_client = JiraClient(
            server_url="https://test.atlassian.net",
            username="test@example.com",
            api_token="test-token",
            prd_custom_field="customfield_10001",
            mandays_custom_field="customfield_10004"
        )
        jira_client.session = mock_session
        
        task1 = TaskPlan(
            summary="Task 1",
            purpose="Purpose 1",
            scopes=[TaskScope(description="Scope 1", deliverable="Deliverable 1")],
            expected_outcomes=["Outcome 1"],
            team=TaskTeam.BACKEND,
            cycle_time_estimate=CycleTimeEstimate(
                development_days=1.0,
                testing_days=0.5,
                review_days=0.5,
                deployment_days=0.0,
                total_days=2.0,
                confidence_level=0.8
            )
        )
        
        task2 = TaskPlan(
            summary="Task 2",
            purpose="Purpose 2",
            scopes=[TaskScope(description="Scope 2", deliverable="Deliverable 2")],
            expected_outcomes=["Outcome 2"],
            team=TaskTeam.FRONTEND,
            cycle_time_estimate=CycleTimeEstimate(
                development_days=1.5,
                testing_days=0.5,
                review_days=0.5,
                deployment_days=0.0,
                total_days=2.5,
                confidence_level=0.8
            )
        )
        
        story_plan = StoryPlan(
            summary="Test story",
            description="Test description",
            acceptance_criteria=[AcceptanceCriteria(
                scenario="Test scenario",
                given="Given condition",
                when="When action",
                then="Then result"
            )],
            tasks=[task1, task2],
            epic_key="EPIC-1"
        )
        
        result = jira_client.create_story_ticket(story_plan, "PROJ")
        
        assert result == "STORY-123"
        call_args = mock_session.post.call_args
        assert call_args is not None
        issue_data = call_args[1]['json']
        assert issue_data['fields']['customfield_10004'] == 4.5  # 2.0 + 2.5

    @patch('src.jira_client.requests.Session')
    def test_update_mandays_custom_field(self, mock_session_class):
        """Test update_mandays_custom_field method"""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 204
        mock_session.put.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        jira_client = JiraClient(
            server_url="https://test.atlassian.net",
            username="test@example.com",
            api_token="test-token",
            prd_custom_field="customfield_10001",
            mandays_custom_field="customfield_10004"
        )
        jira_client.session = mock_session
        
        result = jira_client.update_mandays_custom_field("PROJ-123", 3.5)
        
        assert result is True
        call_args = mock_session.put.call_args
        assert call_args is not None
        assert call_args[0][0] == "https://test.atlassian.net/rest/api/3/issue/PROJ-123"
        payload = call_args[1]['json']
        assert payload['fields']['customfield_10004'] == 3.5

    def test_update_mandays_custom_field_not_configured(self, jira_client):
        """Test update_mandays_custom_field returns False when field is not configured"""
        result = jira_client.update_mandays_custom_field("PROJ-123", 3.5)
        assert result is False


if __name__ == '__main__':
    pytest.main([__file__])
