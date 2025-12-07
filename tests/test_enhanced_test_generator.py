"""
Tests for Enhanced Test Case Generation Engine
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from typing import List, Dict, Any

from src.enhanced_test_generator import (
    EnhancedTestGenerator, TestType, TestCoverageLevel, TestDataType
)
from src.planning_models import StoryPlan, TaskPlan, TaskScope, AcceptanceCriteria, TestCase
from src.planning_prompt_engine import PlanningPromptEngine
from src.llm_client import LLMClient


class TestEnhancedTestGenerator(unittest.TestCase):
    """Test cases for Enhanced Test Generator"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_llm_client = Mock(spec=LLMClient)
        self.mock_prompt_engine = Mock(spec=PlanningPromptEngine)
        self.test_generator = EnhancedTestGenerator(
            llm_client=self.mock_llm_client,
            prompt_engine=self.mock_prompt_engine
        )
        
        # Sample test data
        self.sample_story = StoryPlan(
            summary="User login functionality",
            description="As a user, I want to log in to access my account",
            acceptance_criteria=[
                AcceptanceCriteria(
                    scenario="Valid login",
                    given="User has valid credentials",
                    when="User submits login form",
                    then="User is authenticated and redirected"
                ),
                AcceptanceCriteria(
                    scenario="Invalid login",
                    given="User has invalid credentials", 
                    when="User submits login form",
                    then="Error message is displayed"
                )
            ],
            story_points=3
        )
        
        self.sample_task = TaskPlan(
            summary="Implement user authentication API",
            purpose="Create secure authentication endpoint",
            scopes=[
                TaskScope(
                    description="JWT token generation",
                    deliverable="Authentication service",
                    category="implementation"
                ),
                TaskScope(
                    description="Password validation",
                    deliverable="Validation middleware",
                    category="implementation"
                )
            ],
            expected_outcomes=["Secure authentication", "Token management"],
            estimated_hours=16
        )

    def test_generate_story_test_cases_basic_coverage(self):
        """Test story test case generation with basic coverage"""
        # Mock AI response
        ai_response = """
Test Case: Valid User Login
Type: acceptance
Description: Test successful login with valid credentials
Expected Result: User is authenticated and redirected to dashboard

Test Case: Invalid Credentials Error
Type: integration  
Description: Test error handling for invalid credentials
Expected Result: Error message displayed, no authentication
"""
        
        self.mock_llm_client.generate_content.return_value = ai_response
        self.mock_prompt_engine.generate_test_case_prompt.return_value = "Mock prompt"
        
        # Generate test cases
        test_cases = self.test_generator.generate_story_test_cases(
            story=self.sample_story,
            coverage_level=TestCoverageLevel.BASIC
        )
        
        # Verify results
        self.assertGreaterEqual(len(test_cases), 2)
        self.assertTrue(any(tc.type == "acceptance" for tc in test_cases))
        self.assertTrue(any("login" in tc.title.lower() for tc in test_cases))
        
        # Verify LLM was called
        self.mock_llm_client.generate_content.assert_called_once()
        self.mock_prompt_engine.generate_test_case_prompt.assert_called_once()

    def test_generate_story_test_cases_comprehensive_coverage(self):
        """Test story test case generation with comprehensive coverage"""
        # Mock AI response
        ai_response = """
Test Case: User Authentication Flow
Type: acceptance
Description: Complete user authentication journey
Expected Result: User successfully logs in and accesses features

Test Case: Authentication Security
Type: security
Description: Test authentication against various attacks
Expected Result: System resists security vulnerabilities
"""
        
        self.mock_llm_client.generate_content.return_value = ai_response
        self.mock_prompt_engine.generate_test_case_prompt.return_value = "Mock prompt"
        
        # Generate test cases
        test_cases = self.test_generator.generate_story_test_cases(
            story=self.sample_story,
            coverage_level=TestCoverageLevel.COMPREHENSIVE,
            domain_context="security"
        )
        
        # Verify comprehensive coverage
        self.assertGreaterEqual(len(test_cases), 3)
        
        # Check for required test types in comprehensive coverage
        test_types = {tc.type for tc in test_cases}
        self.assertIn("acceptance", test_types)
        
        # Verify domain context was considered
        call_args = self.mock_llm_client.generate_content.call_args
        self.assertIn("security", call_args[1]["prompt"])

    def test_generate_task_test_cases_standard_coverage(self):
        """Test task test case generation with standard coverage"""
        # Mock AI response
        ai_response = """
Test Case: JWT Token Generation
Type: unit
Description: Test JWT token creation with valid user data
Expected Result: Valid JWT token is generated with correct claims

Test Case: Authentication API Integration
Type: integration
Description: Test authentication API endpoint functionality
Expected Result: API returns correct authentication response
"""
        
        self.mock_llm_client.generate_content.return_value = ai_response
        self.mock_prompt_engine.generate_test_case_prompt.return_value = "Mock prompt"
        
        # Generate test cases
        test_cases = self.test_generator.generate_task_test_cases(
            task=self.sample_task,
            coverage_level=TestCoverageLevel.STANDARD,
            technical_context="API"
        )
        
        # Verify results
        self.assertGreaterEqual(len(test_cases), 2)
        test_types = {tc.type for tc in test_cases}
        self.assertIn("unit", test_types)
        self.assertTrue(any("JWT" in tc.title for tc in test_cases))

    def test_generate_test_data_valid_input(self):
        """Test test data generation for valid inputs"""
        test_case = TestCase(
            title="Test user login",
            type="unit",
            description="Test login functionality",
            expected_result="User is authenticated"
        )
        
        # Mock AI response for test data
        ai_response = """
{
    "valid_input": [
        {"description": "Valid username/password", "value": {"username": "testuser", "password": "Test123!"}},
        {"description": "Valid email/password", "value": {"username": "test@example.com", "password": "Test123!"}}
    ],
    "invalid_input": [
        {"description": "Empty password", "value": {"username": "testuser", "password": ""}},
        {"description": "Invalid email format", "value": {"username": "invalid-email", "password": "Test123!"}}
    ]
}
"""
        
        self.mock_llm_client.generate_content.return_value = ai_response
        
        # Generate test data
        data_types = [TestDataType.VALID_INPUT, TestDataType.INVALID_INPUT]
        test_data = self.test_generator.generate_test_data(
            test_case=test_case,
            data_types=data_types,
            context={"domain": "authentication"}
        )
        
        # Verify test data structure
        self.assertIn("valid_input", test_data)
        self.assertIn("invalid_input", test_data)
        self.assertIsInstance(test_data["valid_input"], list)
        self.assertIsInstance(test_data["invalid_input"], list)

    def test_ai_generation_fallback_handling(self):
        """Test fallback handling when AI generation fails"""
        # Mock LLM failure
        self.mock_llm_client.generate_content.side_effect = Exception("LLM API error")
        self.mock_prompt_engine.generate_test_case_prompt.return_value = "Mock prompt"
        
        # Generate test cases (should use fallback)
        test_cases = self.test_generator.generate_story_test_cases(
            story=self.sample_story,
            coverage_level=TestCoverageLevel.BASIC
        )
        
        # Verify fallback worked
        self.assertGreater(len(test_cases), 0)
        self.assertTrue(any("Acceptance Test" in tc.title for tc in test_cases))

    def test_test_case_deduplication(self):
        """Test that duplicate test cases are removed"""
        # Create test cases with duplicates
        test_cases = [
            TestCase(title="Test Login", type="unit", description="Test 1", expected_result="Pass"),
            TestCase(title="Test Login", type="unit", description="Test 2", expected_result="Pass"),  # Duplicate title
            TestCase(title="Test Registration", type="unit", description="Test 3", expected_result="Pass")
        ]
        
        # Test deduplication
        unique_tests = self.test_generator._deduplicate_tests(test_cases)
        
        # Verify duplicates removed
        self.assertEqual(len(unique_tests), 2)
        titles = [tc.title for tc in unique_tests]
        self.assertIn("Test Login", titles)
        self.assertIn("Test Registration", titles)

    def test_coverage_level_enforcement_minimal(self):
        """Test that minimal coverage requirements are enforced"""
        test_cases = []  # Start with no tests
        
        # Ensure minimal coverage
        final_tests = self.test_generator._ensure_story_coverage(
            tests=test_cases,
            story=self.sample_story,
            coverage_level=TestCoverageLevel.MINIMAL
        )
        
        # Verify minimal requirements met
        self.assertGreater(len(final_tests), 0)
        test_types = {tc.type for tc in final_tests}
        self.assertIn("acceptance", test_types)

    def test_coverage_level_enforcement_comprehensive(self):
        """Test that comprehensive coverage requirements are enforced"""
        # Start with basic tests
        test_cases = [
            TestCase(title="Basic Test", type="acceptance", description="Basic", expected_result="Pass")
        ]
        
        # Ensure comprehensive coverage
        final_tests = self.test_generator._ensure_story_coverage(
            tests=test_cases,
            story=self.sample_story,
            coverage_level=TestCoverageLevel.COMPREHENSIVE
        )
        
        # Verify comprehensive requirements met
        test_types = {tc.type for tc in final_tests}
        required_types = ["acceptance", "integration", "e2e", "performance", "security"]
        
        # Should have most required types for comprehensive coverage
        self.assertGreaterEqual(len(test_types.intersection(required_types)), 3)

    def test_domain_specific_guidance(self):
        """Test domain-specific test guidance"""
        # Test financial domain guidance
        financial_guidance = self.test_generator._get_domain_specific_guidance("financial", "story")
        self.assertIn("monetary", financial_guidance.lower())
        self.assertIn("compliance", financial_guidance.lower())
        
        # Test healthcare domain guidance
        healthcare_guidance = self.test_generator._get_domain_specific_guidance("healthcare", "story")
        self.assertIn("hipaa", healthcare_guidance.lower())
        self.assertIn("privacy", healthcare_guidance.lower())

    def test_technical_specific_guidance(self):
        """Test technical context-specific guidance"""
        # Test API technical guidance
        api_guidance = self.test_generator._get_technical_specific_guidance("api")
        self.assertIn("endpoint", api_guidance.lower())
        self.assertIn("validation", api_guidance.lower())
        
        # Test database technical guidance
        db_guidance = self.test_generator._get_technical_specific_guidance("database")
        self.assertIn("integrity", db_guidance.lower())
        self.assertIn("transaction", db_guidance.lower())

    def test_test_pattern_initialization(self):
        """Test that test patterns are properly initialized"""
        patterns = self.test_generator._initialize_test_patterns()
        
        # Verify pattern structure
        self.assertIn("story_patterns", patterns)
        self.assertIn("task_patterns", patterns)
        
        # Verify story patterns
        story_patterns = patterns["story_patterns"]
        self.assertIn("user_journey", story_patterns)
        self.assertIn("error_handling", story_patterns)
        
        # Verify task patterns
        task_patterns = patterns["task_patterns"]
        self.assertIn("unit_functionality", task_patterns)
        self.assertIn("integration_points", task_patterns)

    def test_coverage_template_initialization(self):
        """Test that coverage templates are properly initialized"""
        templates = self.test_generator._initialize_coverage_templates()
        
        # Verify all coverage levels exist
        expected_levels = ["minimal", "basic", "standard", "comprehensive"]
        for level in expected_levels:
            self.assertIn(level, templates)
            
            # Verify each level has required fields
            template = templates[level]
            self.assertIn("story_types", template)
            self.assertIn("task_types", template)
            self.assertIn("story_guidance", template)
            self.assertIn("task_guidance", template)

    def test_pattern_based_test_generation_stories(self):
        """Test pattern-based test generation for stories"""
        # Generate pattern tests
        pattern_tests = self.test_generator._generate_pattern_story_tests(
            story=self.sample_story,
            coverage_level=TestCoverageLevel.STANDARD
        )
        
        # Verify pattern tests generated
        self.assertGreater(len(pattern_tests), 0)
        
        # Should have acceptance tests for each acceptance criterion
        acceptance_tests = [tc for tc in pattern_tests if tc.type == "acceptance"]
        self.assertGreaterEqual(len(acceptance_tests), len(self.sample_story.acceptance_criteria))

    def test_pattern_based_test_generation_tasks(self):
        """Test pattern-based test generation for tasks"""
        # Generate pattern tests
        pattern_tests = self.test_generator._generate_pattern_task_tests(
            task=self.sample_task,
            coverage_level=TestCoverageLevel.STANDARD
        )
        
        # Verify pattern tests generated
        self.assertGreater(len(pattern_tests), 0)
        
        # Should have unit tests for each scope
        unit_tests = [tc for tc in pattern_tests if tc.type == "unit"]
        self.assertGreaterEqual(len(unit_tests), len(self.sample_task.scopes))

    def test_test_data_type_enum(self):
        """Test TestDataType enum values"""
        # Verify all expected data types exist
        expected_types = [
            "valid_input", "invalid_input", "boundary_values", 
            "edge_cases", "security_payloads", "performance_data"
        ]
        
        for expected_type in expected_types:
            # Should be able to create enum from string
            data_type = TestDataType(expected_type)
            self.assertEqual(data_type.value, expected_type)

    def test_test_coverage_level_enum(self):
        """Test TestCoverageLevel enum values"""
        # Verify all expected coverage levels exist
        expected_levels = ["minimal", "basic", "standard", "comprehensive"]
        
        for expected_level in expected_levels:
            # Should be able to create enum from string
            coverage_level = TestCoverageLevel(expected_level)
            self.assertEqual(coverage_level.value, expected_level)

    def test_test_type_enum(self):
        """Test TestType enum values"""
        # Verify all expected test types exist
        expected_types = [
            "unit", "integration", "e2e", "acceptance", 
            "performance", "security", "regression", "smoke"
        ]
        
        for expected_type in expected_types:
            # Should be able to create enum from string
            test_type = TestType(expected_type)
            self.assertEqual(test_type.value, expected_type)


if __name__ == '__main__':
    unittest.main()
