"""
Modifiers
Context modifiers and quality validators for prompts.
"""

from typing import Dict


class ModifiersPrompts:
    """Context modifiers and quality validators"""
    
    @staticmethod
    def get_context_modifiers() -> Dict[str, str]:
        """Get context modification templates"""
        return {
            "team_velocity_high": "This team has high velocity - can handle complex tasks efficiently.",
            "team_velocity_low": "This team prefers smaller, well-defined tasks with clear instructions.",
            "domain_financial": "Consider financial domain regulations and compliance requirements.",
            "domain_healthcare": "Consider healthcare privacy (HIPAA) and safety requirements.",
            "domain_ecommerce": "Consider scalability, payment processing, and user experience.",
        }
    
    @staticmethod
    def get_quality_validators() -> Dict[str, str]:
        """Get quality validation directives"""
        return {
            "epic_analysis": """
**QUALITY REQUIREMENTS:**
- Identify at least 3-5 major coverage areas
- Provide specific gap analysis with examples
- Include risk assessment for missing areas
- Suggest prioritization for gap coverage""",

            "story_generation": """
**QUALITY REQUIREMENTS:**
- Each story must have 2-3 acceptance criteria minimum
- Stories must be independent and deliverable
- Include story point estimation (1,2,3,5,8)
- Ensure stories align with epic goals""",

            "task_breakdown": """
**QUALITY REQUIREMENTS:**
- Each task must be completable in 3 days or less
- Tasks must have clear, measurable deliverables
- Include proper dependency identification
- Provide confidence levels for estimates""",

            "test_case_generation": """
**QUALITY REQUIREMENTS:**
- Generate 3-6 comprehensive test cases per item (covering positive, negative, edge cases)
- Each test case must follow strict Gherkin format with embedded test data
- Cover happy path, unhappy path, and boundary/edge case scenarios
- Include specific, verifiable expected results with measurable outcomes
- Ensure test cases are self-contained with complete preconditions
- Consider diverse user personas and real-world usage scenarios
- Address security, performance, and accessibility concerns where applicable
- Write test steps that are executable by someone unfamiliar with the system""",

            "effort_estimation": """
**QUALITY REQUIREMENTS:**
- Provide estimates in quarter-day increments
- Include confidence level (0.0-1.0)
- If >3 days total, provide split recommendations
- Consider complexity, dependencies, and unknowns"""
        }

