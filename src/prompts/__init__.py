"""
Centralized Prompt Templates
All LLM prompts are defined here for better maintainability and consistency.

This module aggregates prompts from category-specific modules while maintaining
backward compatibility with the original Prompts class interface.
"""
from typing import Dict, Optional

from .generation import GenerationPrompts
from .analysis import AnalysisPrompts
from .planning import PlanningPrompts
from .team_tasks import TeamTasksPrompts
from .system import SystemPrompts
from .test_generation import TestGenerationPrompts
from .utility import UtilityPrompts
from .modifiers import ModifiersPrompts


class Prompts:
    """Centralized prompt templates organized by category"""
    
    # ==========================================
    # GENERATION PROMPTS
    # ==========================================
    
    @staticmethod
    def get_description_template() -> str:
        """Get the template for generating ticket descriptions"""
        return GenerationPrompts.get_description_template()
    
    # ==========================================
    # ANALYSIS PROMPTS
    # ==========================================
    
    @staticmethod
    def get_story_coverage_analysis_template() -> str:
        """Get the template for story coverage analysis"""
        return AnalysisPrompts.get_story_coverage_analysis_template()
    
    # ==========================================
    # PLANNING PROMPTS
    # ==========================================
    
    @staticmethod
    def get_epic_analysis_prompt(document_type: str = "prd") -> str:
        """Get epic analysis prompt based on document type"""
        return PlanningPrompts.get_epic_analysis_prompt(document_type)
    
    @staticmethod
    def get_story_generation_prompt(document_type: str = "prd") -> str:
        """Get story generation prompt based on document type"""
        return PlanningPrompts.get_story_generation_prompt(document_type)
    
    @staticmethod
    def get_task_breakdown_prompt() -> str:
        """Get task breakdown prompt"""
        return PlanningPrompts.get_task_breakdown_prompt()
    
    @staticmethod
    def get_test_case_generation_prompt(context: str = "story") -> str:
        """Get test case generation prompt"""
        return PlanningPrompts.get_test_case_generation_prompt(context)
    
    @staticmethod
    def get_effort_estimation_prompt() -> str:
        """Get effort estimation prompt"""
        return PlanningPrompts.get_effort_estimation_prompt()
    
    # ==========================================
    # TEAM TASK GENERATION PROMPTS
    # ==========================================
    
    @staticmethod
    def get_team_separation_prompt_template() -> str:
        """Get the template for team-separated task generation"""
        return TeamTasksPrompts.get_team_separation_prompt_template()
    
    @staticmethod
    def get_unified_task_test_prompt_template() -> str:
        """Get the template for unified task+test generation"""
        return TeamTasksPrompts.get_unified_task_test_prompt_template()
    
    # ==========================================
    # SYSTEM PROMPTS
    # ==========================================
    
    @staticmethod
    def get_default_system_prompt() -> str:
        """Get default system prompt for LLM"""
        return SystemPrompts.get_default_system_prompt()
    
    @staticmethod
    def get_team_task_system_prompt() -> str:
        """Get system prompt for team task generation"""
        return SystemPrompts.get_team_task_system_prompt()
    
    @staticmethod
    def get_unified_task_test_system_prompt() -> str:
        """Get system prompt for unified task+test generation"""
        return SystemPrompts.get_unified_task_test_system_prompt()
    
    @staticmethod
    def get_coverage_analysis_system_prompt() -> str:
        """Get system prompt for coverage analysis"""
        return SystemPrompts.get_coverage_analysis_system_prompt()
    
    @staticmethod
    def get_planning_system_prompt() -> str:
        """Get system prompt for planning operations"""
        return SystemPrompts.get_planning_system_prompt()
    
    @staticmethod
    def get_test_data_generation_system_prompt() -> str:
        """Get system prompt for test data generation"""
        return SystemPrompts.get_test_data_generation_system_prompt()
    
    @staticmethod
    def get_story_test_generation_system_prompt() -> str:
        """Get system prompt for story test case generation"""
        return SystemPrompts.get_story_test_generation_system_prompt()
    
    @staticmethod
    def get_task_test_generation_system_prompt() -> str:
        """Get system prompt for task test case generation"""
        return SystemPrompts.get_task_test_generation_system_prompt()
    
    @staticmethod
    def get_enhanced_task_test_system_prompt() -> str:
        """Get system prompt for enhanced task test generation"""
        return SystemPrompts.get_enhanced_task_test_system_prompt()
    
    @staticmethod
    def get_full_context_test_system_prompt() -> str:
        """Get system prompt for full context test generation"""
        return SystemPrompts.get_full_context_test_system_prompt()
    
    # ==========================================
    # TEST GENERATION PROMPTS
    # ==========================================
    
    @staticmethod
    def get_test_data_prompt_template() -> str:
        """Get template for test data generation prompt"""
        return TestGenerationPrompts.get_test_data_prompt_template()
    
    @staticmethod
    def get_story_test_generation_prompt_template() -> str:
        """Get template for story test case generation"""
        return TestGenerationPrompts.get_story_test_generation_prompt_template()
    
    @staticmethod
    def get_task_test_generation_prompt_template() -> str:
        """Get template for task test case generation"""
        return TestGenerationPrompts.get_task_test_generation_prompt_template()
    
    @staticmethod
    def get_enhanced_story_test_prompt_template() -> str:
        """Get enhanced template for story test case generation (detailed version)"""
        return TestGenerationPrompts.get_enhanced_story_test_prompt_template()
    
    @staticmethod
    def get_enhanced_task_test_prompt_template() -> str:
        """Get enhanced template for task test case generation (detailed version)"""
        return TestGenerationPrompts.get_enhanced_task_test_prompt_template()
    
    @staticmethod
    def get_enhanced_task_prompt_template() -> str:
        """Get enhanced template for task test case generation (optimized version)"""
        return TestGenerationPrompts.get_enhanced_task_prompt_template()
    
    # ==========================================
    # UTILITY PROMPTS
    # ==========================================
    
    @staticmethod
    def get_summarization_prompt_template() -> str:
        """Get template for text summarization"""
        return UtilityPrompts.get_summarization_prompt_template()
    
    @staticmethod
    def get_effort_estimation_guidance_template() -> str:
        """Get template for effort estimation guidance"""
        return UtilityPrompts.get_effort_estimation_guidance_template()
    
    @staticmethod
    def get_legacy_build_prompt_template() -> str:
        """Get template for legacy prompt building (deprecated - use centralized templates)"""
        return UtilityPrompts.get_legacy_build_prompt_template()
    
    @staticmethod
    def get_story_generation_gwt_guidance_template() -> str:
        """Get Given/When/Then guidance template for story generation"""
        return UtilityPrompts.get_story_generation_gwt_guidance_template()
    
    @staticmethod
    def get_task_breakdown_pso_guidance_template() -> str:
        """Get Purpose/Scopes/Outcome guidance template for task breakdown"""
        return UtilityPrompts.get_task_breakdown_pso_guidance_template()
    
    @staticmethod
    def get_json_response_instruction() -> str:
        """Get standard JSON response instruction"""
        return UtilityPrompts.get_json_response_instruction()
    
    @staticmethod
    def get_claude_json_response_instruction() -> str:
        """Get Claude-specific JSON response instruction (more forceful for prompt-based generation)"""
        return UtilityPrompts.get_claude_json_response_instruction()
    
    @staticmethod
    def get_comprehensive_task_prompt_context_template() -> str:
        """Get template for comprehensive task prompt context additions"""
        return UtilityPrompts.get_comprehensive_task_prompt_context_template()
    
    @staticmethod
    def get_prd_context_section_template() -> str:
        """Get template for PRD context section"""
        return UtilityPrompts.get_prd_context_section_template()
    
    @staticmethod
    def get_rfc_context_section_template() -> str:
        """Get template for RFC context section"""
        return UtilityPrompts.get_rfc_context_section_template()
    
    @staticmethod
    def get_testing_focus_template() -> str:
        """Get template for testing focus guidance"""
        return UtilityPrompts.get_testing_focus_template()
    
    @staticmethod
    def get_story_context_addition_template() -> str:
        """Get template for adding story context to prompts"""
        return UtilityPrompts.get_story_context_addition_template()
    
    @staticmethod
    def get_prd_usage_guidance() -> str:
        """Get PRD usage guidance text"""
        return UtilityPrompts.get_prd_usage_guidance()
    
    @staticmethod
    def get_rfc_usage_guidance() -> str:
        """Get RFC usage guidance text"""
        return UtilityPrompts.get_rfc_usage_guidance()
    
    @staticmethod
    def get_testing_focus_messages() -> Dict[str, str]:
        """Get testing focus messages for different context scenarios"""
        return UtilityPrompts.get_testing_focus_messages()
    
    # ==========================================
    # MODIFIERS
    # ==========================================
    
    @staticmethod
    def get_context_modifiers() -> Dict[str, str]:
        """Get context modification templates"""
        return ModifiersPrompts.get_context_modifiers()
    
    @staticmethod
    def get_quality_validators() -> Dict[str, str]:
        """Get quality validation directives"""
        return ModifiersPrompts.get_quality_validators()


# ==========================================
# CONVENIENCE FUNCTIONS
# ==========================================

def get_prompt(category: str, prompt_name: str, **kwargs) -> str:
    """
    Get a prompt by category and name with optional formatting
    
    Args:
        category: Prompt category (generation, analysis, planning, team_tasks, system)
        prompt_name: Name of the prompt
        **kwargs: Formatting parameters for the prompt
    
    Returns:
        Formatted prompt string
    """
    prompts = Prompts()
    
    # Map category to method
    prompt_map = {
        "generation": {
            "description_template": prompts.get_description_template
        },
        "analysis": {
            "story_coverage": prompts.get_story_coverage_analysis_template
        },
        "planning": {
            "epic_analysis": lambda doc_type="prd": prompts.get_epic_analysis_prompt(doc_type),
            "story_generation": lambda doc_type="prd": prompts.get_story_generation_prompt(doc_type),
            "task_breakdown": prompts.get_task_breakdown_prompt,
            "test_case_generation": lambda context="story": prompts.get_test_case_generation_prompt(context),
            "effort_estimation": prompts.get_effort_estimation_prompt
        },
        "team_tasks": {
            "team_separation": prompts.get_team_separation_prompt_template,
            "unified_task_test": prompts.get_unified_task_test_prompt_template
        },
        "system": {
            "default": prompts.get_default_system_prompt,
            "team_task": prompts.get_team_task_system_prompt,
            "unified_task_test": prompts.get_unified_task_test_system_prompt,
            "coverage_analysis": prompts.get_coverage_analysis_system_prompt,
            "planning": prompts.get_planning_system_prompt,
            "test_data_generation": prompts.get_test_data_generation_system_prompt,
            "story_test_generation": prompts.get_story_test_generation_system_prompt,
            "task_test_generation": prompts.get_task_test_generation_system_prompt,
            "enhanced_task_test": prompts.get_enhanced_task_test_system_prompt,
            "full_context_test": prompts.get_full_context_test_system_prompt,
            "story_generation": prompts.get_story_generation_prompt
        },
        "test_generation": {
            "test_data": prompts.get_test_data_prompt_template,
            "story_test": prompts.get_story_test_generation_prompt_template,
            "task_test": prompts.get_task_test_generation_prompt_template,
            "enhanced_story_test": prompts.get_enhanced_story_test_prompt_template,
            "enhanced_task_test": prompts.get_enhanced_task_test_prompt_template
        },
        "utility": {
            "summarization": prompts.get_summarization_prompt_template,
            "effort_estimation_guidance": prompts.get_effort_estimation_guidance_template,
            "legacy_build_prompt": prompts.get_legacy_build_prompt_template,
            "story_generation_gwt_guidance": prompts.get_story_generation_gwt_guidance_template,
            "task_breakdown_pso_guidance": prompts.get_task_breakdown_pso_guidance_template,
            "json_response_instruction": prompts.get_json_response_instruction
        },
        "modifiers": {
            "context": prompts.get_context_modifiers,
            "quality": prompts.get_quality_validators
        }
    }
    
    if category not in prompt_map:
        raise ValueError(f"Unknown prompt category: {category}")
    
    if prompt_name not in prompt_map[category]:
        raise ValueError(f"Unknown prompt '{prompt_name}' in category '{category}'")
    
    prompt_func = prompt_map[category][prompt_name]
    prompt_text = prompt_func()
    
    # Apply formatting if kwargs provided
    if kwargs:
        try:
            prompt_text = prompt_text.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"Missing format parameter: {e}")
    
    return prompt_text

