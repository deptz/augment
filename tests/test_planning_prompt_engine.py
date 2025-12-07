"""
Tests for Planning Prompt Engine
"""
import pytest
from unittest.mock import Mock, patch

from src.planning_prompt_engine import (
    PlanningPromptEngine, DocumentType, GenerationContext, PromptContext
)


class TestPlanningPromptEngine:
    """Test cases for the planning prompt engine"""
    
    @pytest.fixture
    def prompt_engine(self):
        """Fixture providing a prompt engine instance"""
        return PlanningPromptEngine()
    
    def test_epic_analysis_prompt_prd_context(self, prompt_engine):
        """Test epic analysis prompt generation with PRD context"""
        epic_key = "PROJ-123"
        epic_description = "User management system"
        prd_content = "User stories: 1. As a user I want to login..."
        
        prompt = prompt_engine.generate_epic_analysis_prompt(
            epic_key=epic_key,
            epic_description=epic_description,
            prd_content=prd_content
        )
        
        # Verify prompt contains key elements
        assert epic_key in prompt
        assert epic_description in prompt
        assert "PRD CONTEXT" in prompt
        assert "Product Manager" in prompt
        assert "business requirement" in prompt.lower()
        assert "QUALITY REQUIREMENTS" in prompt
    
    def test_epic_analysis_prompt_rfc_context(self, prompt_engine):
        """Test epic analysis prompt generation with RFC context"""
        epic_key = "PROJ-123"
        epic_description = "Authentication service"
        rfc_content = "Technical requirements: JWT tokens, OAuth2..."
        
        prompt = prompt_engine.generate_epic_analysis_prompt(
            epic_key=epic_key,
            epic_description=epic_description,
            rfc_content=rfc_content
        )
        
        # Verify prompt contains key elements
        assert epic_key in prompt
        assert "RFC CONTEXT" in prompt
        assert "Technical Lead" in prompt
        assert "technical requirement" in prompt.lower()
    
    def test_epic_analysis_prompt_hybrid_context(self, prompt_engine):
        """Test epic analysis prompt generation with both PRD and RFC"""
        epic_key = "PROJ-123"
        epic_description = "Complete user system"
        prd_content = "User stories..."
        rfc_content = "Technical specs..."
        existing_stories = [
            {"key": "PROJ-124", "summary": "User login"},
            {"key": "PROJ-125", "summary": "User registration"}
        ]
        
        prompt = prompt_engine.generate_epic_analysis_prompt(
            epic_key=epic_key,
            epic_description=epic_description,
            prd_content=prd_content,
            rfc_content=rfc_content,
            existing_stories=existing_stories
        )
        
        # Verify hybrid context
        assert "PRD CONTEXT" in prompt
        assert "RFC CONTEXT" in prompt
        assert "EXISTING STORIES" in prompt
        assert "Project Manager" in prompt
        assert "PROJ-124" in prompt
        assert "User login" in prompt
    
    def test_story_creation_prompt_prd_focused(self, prompt_engine):
        """Test story creation prompt for PRD-focused generation"""
        epic_context = "User management epic with authentication needs"
        missing_areas = ["User registration", "Password reset"]
        
        prompt = prompt_engine.generate_story_creation_prompt(
            epic_context=epic_context,
            missing_areas=missing_areas,
            doc_type=DocumentType.PRD
        )
        
        # Verify story prompt structure
        assert epic_context in prompt
        assert "User registration" in prompt
        assert "Password reset" in prompt
        assert "Product Manager" in prompt
        assert "Given" in prompt and "When" in prompt and "Then" in prompt
        assert "ACCEPTANCE CRITERIA FORMAT" in prompt
        assert "business value" in prompt.lower()
    
    def test_story_creation_prompt_rfc_focused(self, prompt_engine):
        """Test story creation prompt for RFC-focused generation"""
        epic_context = "Authentication service implementation"
        missing_areas = ["JWT token service", "OAuth integration"]
        
        prompt = prompt_engine.generate_story_creation_prompt(
            epic_context=epic_context,
            missing_areas=missing_areas,
            doc_type=DocumentType.RFC,
            complexity_hint="high"
        )
        
        # Verify technical focus
        assert "Technical Lead" in prompt
        assert "JWT token service" in prompt
        assert "technical implementation" in prompt.lower()
        assert "COMPLEXITY GUIDANCE" in prompt
        assert "high" in prompt
    
    def test_task_breakdown_prompt_generation(self, prompt_engine):
        """Test task breakdown prompt generation"""
        story_summary = "User authentication system"
        story_description = "Implement secure user login functionality"
        acceptance_criteria = [
            "Given valid credentials, when user logs in, then access granted",
            "Given invalid credentials, when user logs in, then access denied"
        ]
        
        prompt = prompt_engine.generate_task_breakdown_prompt(
            story_summary=story_summary,
            story_description=story_description,
            acceptance_criteria=acceptance_criteria,
            max_cycle_days=3,
            technical_context="JWT-based authentication"
        )
        
        # Verify task prompt structure
        assert story_summary in prompt
        assert story_description in prompt
        assert "valid credentials" in prompt
        assert "3 days maximum" in prompt
        assert "JWT-based authentication" in prompt
        assert "Purpose" in prompt and "Scopes" in prompt and "Expected Outcomes" in prompt
        assert "Development Lead" in prompt
    
    def test_test_case_prompt_story_level(self, prompt_engine):
        """Test test case generation prompt for stories"""
        story_summary = "User login functionality"
        story_description = "Users can authenticate with credentials"
        acceptance_criteria = ["User can login with valid credentials"]
        
        prompt = prompt_engine.generate_test_case_prompt(
            item_type="story",
            item_summary=story_summary,
            item_description=story_description,
            acceptance_criteria=acceptance_criteria
        )
        
        # Verify test case prompt
        assert story_summary in prompt
        assert "STORY INFORMATION" in prompt
        assert "acceptance test" in prompt.lower()
        assert "integration" in prompt
        assert "TEST CASE FORMAT" in prompt
        assert "Title" in prompt and "Type" in prompt and "Expected Result" in prompt
    
    def test_test_case_prompt_task_level(self, prompt_engine):
        """Test test case generation prompt for tasks"""
        task_summary = "Implement JWT token validation"
        task_description = "Create service to validate JWT tokens"
        
        prompt = prompt_engine.generate_test_case_prompt(
            item_type="task",
            item_summary=task_summary,
            item_description=task_description
        )
        
        # Verify task test focus
        assert task_summary in prompt
        assert "TASK INFORMATION" in prompt
        assert "unit test" in prompt.lower()
        assert "technical validation" in prompt.lower()
    
    def test_effort_estimation_prompt(self, prompt_engine):
        """Test effort estimation prompt generation"""
        task_summary = "Create user authentication API"
        task_scopes = [
            "Design API endpoints for login/logout",
            "Implement JWT token generation",
            "Add password validation logic"
        ]
        complexity_indicators = {
            "api_endpoints": 3,
            "database_interactions": True,
            "external_dependencies": ["JWT library"]
        }
        
        prompt = prompt_engine.generate_effort_estimation_prompt(
            task_summary=task_summary,
            task_scopes=task_scopes,
            complexity_indicators=complexity_indicators
        )
        
        # Verify estimation prompt
        assert task_summary in prompt
        assert "Design API endpoints" in prompt
        assert "JWT token generation" in prompt
        assert "api_endpoints" in prompt
        assert "Development Days" in prompt
        assert "3-DAY RULE" in prompt
        assert "CONFIDENCE LEVELS" in prompt
    
    def test_document_type_determination(self, prompt_engine):
        """Test document type determination logic"""
        # Test PRD only
        doc_type = prompt_engine._determine_document_type("PRD content", None)
        assert doc_type == DocumentType.PRD
        
        # Test RFC only
        doc_type = prompt_engine._determine_document_type(None, "RFC content")
        assert doc_type == DocumentType.RFC
        
        # Test both (hybrid)
        doc_type = prompt_engine._determine_document_type("PRD content", "RFC content")
        assert doc_type == DocumentType.HYBRID
        
        # Test neither (epic description)
        doc_type = prompt_engine._determine_document_type(None, None)
        assert doc_type == DocumentType.EPIC_DESCRIPTION
    
    def test_content_truncation(self, prompt_engine):
        """Test content truncation for long inputs"""
        long_content = "A" * 5000
        truncated = prompt_engine._truncate_content(long_content, 1000)
        
        assert len(truncated) <= 1000
        assert "Content truncated" in truncated
        
        # Test short content (no truncation)
        short_content = "Short content"
        result = prompt_engine._truncate_content(short_content, 1000)
        assert result == short_content
    
    def test_quality_directives_inclusion(self, prompt_engine):
        """Test that quality directives are included in prompts"""
        prompt = prompt_engine.generate_story_creation_prompt(
            epic_context="Test context",
            missing_areas=["Test area"]
        )
        
        assert "QUALITY REQUIREMENTS" in prompt
        assert "acceptance criteria" in prompt.lower()
        assert "story point" in prompt.lower()
    
    def test_prompt_template_initialization(self, prompt_engine):
        """Test that prompt templates are properly initialized"""
        # Verify all required templates exist
        assert "epic_analysis" in prompt_engine.prompt_templates
        assert "story_generation" in prompt_engine.prompt_templates
        assert "task_breakdown" in prompt_engine.prompt_templates
        assert "test_case_generation" in prompt_engine.prompt_templates
        assert "effort_estimation" in prompt_engine.prompt_templates
        
        # Verify document type variations
        assert "prd" in prompt_engine.prompt_templates["epic_analysis"]
        assert "rfc" in prompt_engine.prompt_templates["epic_analysis"]
        assert "hybrid" in prompt_engine.prompt_templates["epic_analysis"]
    
    def test_context_modifiers_exist(self, prompt_engine):
        """Test that context modifiers are available"""
        assert hasattr(prompt_engine, 'context_modifiers')
        assert isinstance(prompt_engine.context_modifiers, dict)
        assert len(prompt_engine.context_modifiers) > 0
    
    def test_quality_validators_exist(self, prompt_engine):
        """Test that quality validators are available"""
        assert hasattr(prompt_engine, 'quality_validators')
        assert isinstance(prompt_engine.quality_validators, dict)
        assert "epic_analysis" in prompt_engine.quality_validators
        assert "story_generation" in prompt_engine.quality_validators


class TestPromptEngineIntegration:
    """Integration tests for prompt engine with planning service"""
    
    def test_prompt_length_constraints(self):
        """Test that generated prompts don't exceed reasonable length limits"""
        engine = PlanningPromptEngine()
        
        # Test with very long inputs
        long_epic_desc = "A" * 10000
        long_prd = "B" * 20000
        long_rfc = "C" * 15000
        
        prompt = engine.generate_epic_analysis_prompt(
            epic_key="TEST-123",
            epic_description=long_epic_desc,
            prd_content=long_prd,
            rfc_content=long_rfc
        )
        
        # Prompt should be reasonable length (adjust as needed)
        assert len(prompt) < 10000
        assert "Content truncated" in prompt
    
    def test_prompt_consistency(self):
        """Test that prompts are consistent across multiple generations"""
        engine = PlanningPromptEngine()
        
        # Generate same prompt multiple times
        prompt1 = engine.generate_story_creation_prompt(
            epic_context="Test context",
            missing_areas=["Area 1", "Area 2"]
        )
        
        prompt2 = engine.generate_story_creation_prompt(
            epic_context="Test context",
            missing_areas=["Area 1", "Area 2"]
        )
        
        # Should be identical
        assert prompt1 == prompt2
