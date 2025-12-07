"""
System Prompts
System prompts for different LLM operations and contexts.
"""


class SystemPrompts:
    """System prompts for LLM providers"""
    
    @staticmethod
    def get_default_system_prompt() -> str:
        """Get default system prompt for LLM"""
        return "You are a technical documentation assistant specializing in creating structured Jira ticket descriptions from historical development artifacts."
    
    @staticmethod
    def get_team_task_system_prompt() -> str:
        """Get system prompt for team task generation"""
        return "You are an expert development lead who understands team responsibilities. Break down stories into Backend, Frontend, and QA tasks with clear team ownership."
    
    @staticmethod
    def get_unified_task_test_system_prompt() -> str:
        """Get system prompt for unified task+test generation"""
        return "You are a senior technical lead who generates complete implementation plans with embedded test cases. Generate tasks with proper team ownership and comprehensive test coverage."
    
    @staticmethod
    def get_coverage_analysis_system_prompt() -> str:
        """Get system prompt for coverage analysis"""
        return "You are an expert QA analyst who analyzes story coverage by tasks and identifies gaps in requirements coverage."
    
    @staticmethod
    def get_planning_system_prompt() -> str:
        """Get system prompt for planning operations"""
        return "You are an expert agile planning specialist who generates comprehensive user stories and task breakdowns from product requirements and technical specifications."
    
    @staticmethod
    def get_test_data_generation_system_prompt() -> str:
        """Get system prompt for test data generation"""
        return "You are a world-class test data engineer with expertise in creating realistic, comprehensive test datasets. Generate varied test data that covers edge cases, boundary conditions, security vulnerabilities, and real-world scenarios with specific, actionable data values."
    
    @staticmethod
    def get_story_test_generation_system_prompt() -> str:
        """Get system prompt for story test case generation"""
        return "You are an expert test engineer. Generate comprehensive, executable test cases following industry best practices and Gherkin format. Return ONLY valid JSON array."
    
    @staticmethod
    def get_task_test_generation_system_prompt() -> str:
        """Get system prompt for task test case generation"""
        return "You are a QA Engineer. Generate test cases in valid JSON format only. Each test case MUST include the test_steps field with Gherkin format (Given/When/Then). Return a JSON array of test case objects with the exact structure specified."
    
    @staticmethod
    def get_enhanced_task_test_system_prompt() -> str:
        """Get system prompt for enhanced task test generation"""
        return "You are a world-class Senior QA Engineer specializing in technical testing. Generate thorough test cases using strict Gherkin format covering unit tests, integration tests, error conditions, and edge cases. Focus on technical robustness, security, and performance validation."
    
    @staticmethod
    def get_full_context_test_system_prompt() -> str:
        """Get system prompt for full context test generation"""
        return "You are a world-class Senior QA Engineer with expertise in context-aware testing. Generate comprehensive test cases using strict Gherkin format that validate both technical implementation and business requirements. Consider user story context, business rules, and technical constraints."

