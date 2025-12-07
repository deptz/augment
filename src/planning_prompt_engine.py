"""
Advanced Prompt Engineering for Planning Mode
Provides context-aware, document-specific prompts for enhanced planning generation
"""
import logging
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass

from .planning_models import OperationMode, EpicPlan, StoryPlan, TaskPlan
from .prompts import Prompts

logger = logging.getLogger(__name__)


class DocumentType(str, Enum):
    """Type of source document for context-aware prompts"""
    PRD = "prd"
    RFC = "rfc"
    EPIC_DESCRIPTION = "epic_description"
    HYBRID = "hybrid"


class GenerationContext(str, Enum):
    """Context for different types of generation"""
    EPIC_ANALYSIS = "epic_analysis"
    STORY_GENERATION = "story_generation"
    TASK_BREAKDOWN = "task_breakdown"
    TEST_CASE_CREATION = "test_case_creation"
    EFFORT_ESTIMATION = "effort_estimation"
    GAP_ANALYSIS = "gap_analysis"


@dataclass
class PromptContext:
    """Context information for prompt generation"""
    document_type: DocumentType
    generation_context: GenerationContext
    team_preferences: Optional[Dict[str, Any]] = None
    historical_data: Optional[Dict[str, Any]] = None
    complexity_level: Optional[str] = None
    domain_specific: Optional[str] = None


class PlanningPromptEngine:
    """
    Advanced prompt engineering engine for planning mode operations
    """
    
    def __init__(self):
        self.prompt_templates = self._initialize_prompt_templates()
        self.context_modifiers = self._initialize_context_modifiers()
        self.quality_validators = self._initialize_quality_validators()
    
    def generate_epic_analysis_prompt(self, 
                                    epic_key: str,
                                    epic_description: str,
                                    prd_content: Optional[str] = None,
                                    rfc_content: Optional[str] = None,
                                    existing_stories: Optional[List[Dict]] = None) -> str:
        """
        Generate context-aware prompt for epic analysis
        
        Args:
            epic_key: JIRA epic key
            epic_description: Epic description text
            prd_content: PRD document content if available
            rfc_content: RFC document content if available
            existing_stories: List of existing stories under epic
            
        Returns:
            Optimized prompt for epic analysis
        """
        logger.info(f"Generating epic analysis prompt for {epic_key}")
        
        # Determine document context
        doc_type = self._determine_document_type(prd_content, rfc_content)
        
        # Build base prompt
        base_prompt = self.prompt_templates["epic_analysis"][doc_type.value]
        
        # Add context-specific sections
        context_sections = []
        
        # Epic information section
        context_sections.append(f"""
**EPIC INFORMATION:**
- Epic Key: {epic_key}
- Epic Description: {epic_description}
""")
        
        # Document-specific context
        if prd_content:
            context_sections.append(f"""
**PRD CONTEXT:**
Extract user stories, acceptance criteria, and business requirements from:
{self._truncate_content(prd_content, 2000)}
""")
        
        if rfc_content:
            context_sections.append(f"""
**RFC CONTEXT:**
Extract technical requirements, architecture decisions, and implementation details from:
{self._truncate_content(rfc_content, 2000)}
""")
        
        # Existing work context
        if existing_stories:
            stories_summary = "\n".join([f"- {story.get('key', 'N/A')}: {story.get('summary', 'N/A')}" 
                                       for story in existing_stories[:10]])
            context_sections.append(f"""
**EXISTING STORIES:**
Consider these existing stories to avoid duplication:
{stories_summary}
""")
        
        # Combine all sections
        full_prompt = base_prompt + "\n".join(context_sections)
        
        # Add quality directives
        full_prompt += self._get_quality_directives("epic_analysis")
        
        return full_prompt
    
    def generate_story_creation_prompt(self,
                                     epic_context: str,
                                     missing_areas: List[str],
                                     doc_type: DocumentType = DocumentType.HYBRID,
                                     complexity_hint: Optional[str] = None) -> str:
        """
        Generate optimized prompt for story creation
        
        Args:
            epic_context: Context about the epic
            missing_areas: Areas that need story coverage
            doc_type: Type of source document
            complexity_hint: Complexity level hint
            
        Returns:
            Optimized story generation prompt
        """
        logger.info(f"Generating story creation prompt for {len(missing_areas)} missing areas")
        
        base_prompt = self.prompt_templates["story_generation"][doc_type.value]
        
        context_sections = [f"""
**EPIC CONTEXT:**
{epic_context}

**MISSING COVERAGE AREAS:**
Generate stories to cover these specific areas:
{chr(10).join([f"- {area}" for area in missing_areas])}
"""]
        
        if complexity_hint:
            context_sections.append(f"""
**COMPLEXITY GUIDANCE:**
Target complexity level: {complexity_hint}
Adjust story scope and granularity accordingly.
""")
        
        # Add Given/When/Then guidance from centralized prompts
        gwt_guidance = Prompts.get_story_generation_gwt_guidance_template()
        
        full_prompt = base_prompt + "\n".join(context_sections) + gwt_guidance
        full_prompt += self._get_quality_directives("story_generation")
        
        return full_prompt
    
    def generate_task_breakdown_prompt(self,
                                     story_summary: str,
                                     story_description: str,
                                     acceptance_criteria: List[str],
                                     max_cycle_days: int = 3,
                                     technical_context: Optional[str] = None) -> str:
        """
        Generate optimized prompt for task breakdown
        
        Args:
            story_summary: Story title/summary
            story_description: Full story description
            acceptance_criteria: List of acceptance criteria
            max_cycle_days: Maximum cycle time constraint
            technical_context: Technical implementation context
            
        Returns:
            Optimized task breakdown prompt
        """
        logger.info(f"Generating task breakdown prompt for story: {story_summary}")
        
        base_prompt = self.prompt_templates["task_breakdown"]["default"]
        
        context_sections = [f"""
**STORY INFORMATION:**
- Summary: {story_summary}
- Description: {story_description}

**ACCEPTANCE CRITERIA:**
{chr(10).join([f"- {criteria}" for criteria in acceptance_criteria])}

**CYCLE TIME CONSTRAINT:**
Each task must be completable within {max_cycle_days} days maximum.
If a logical task would exceed this, break it into smaller tasks.
"""]
        
        if technical_context:
            context_sections.append(f"""
**TECHNICAL CONTEXT:**
{technical_context}
""")
        
        # Add Purpose/Scopes/Outcome guidance from centralized prompts
        pso_guidance = Prompts.get_task_breakdown_pso_guidance_template()
        
        full_prompt = base_prompt + "\n".join(context_sections) + pso_guidance
        full_prompt += self._get_quality_directives("task_breakdown")
        
        return full_prompt
    
    def generate_test_case_prompt(self,
                                item_type: str,  # "story" or "task"
                                item_summary: str,
                                item_description: str,
                                acceptance_criteria: Optional[List[str]] = None) -> str:
        """
        Generate optimized prompt for test case creation using enhanced quality standards
        """
        logger.info(f"Generating test case prompt for {item_type}: {item_summary}")
        
        if item_type.lower() == "story":
            return self._generate_enhanced_story_test_prompt(item_summary, item_description, acceptance_criteria)
        else:
            return self._generate_enhanced_task_test_prompt(item_summary, item_description)
    
    def _generate_enhanced_story_test_prompt(self, summary: str, description: str, acceptance_criteria: Optional[List[str]]) -> str:
        """Generate enhanced story test prompt based on EnhancedTestGenerator standards"""
        # Use centralized template
        template = Prompts.get_enhanced_story_test_prompt_template()
        
        # Build acceptance criteria section
        acceptance_criteria_section = ""
        if acceptance_criteria:
            acceptance_criteria_section = f"""
**Acceptance Criteria:**
{chr(10).join([f"- {ac}" for ac in acceptance_criteria])}"""
        
        prompt = template.format(
            story_summary=summary,
            story_description=description,
            acceptance_criteria_section=acceptance_criteria_section
        )
        
        return prompt
    
    def _generate_enhanced_task_test_prompt(self, summary: str, description: str) -> str:
        """Generate enhanced task test prompt based on EnhancedTestGenerator standards"""
        # Use centralized template
        template = Prompts.get_enhanced_task_test_prompt_template()
        
        prompt = template.format(
            task_summary=summary,
            task_description=description
        )
        
        return prompt
    
    def generate_effort_estimation_prompt(self,
                                        task_summary: str,
                                        task_scopes: List[str],
                                        complexity_indicators: Optional[Dict[str, Any]] = None) -> str:
        """
        Generate prompt for effort estimation
        
        Args:
            task_summary: Task summary
            task_scopes: List of task scopes
            complexity_indicators: Additional complexity information
            
        Returns:
            Effort estimation prompt
        """
        logger.info(f"Generating effort estimation prompt for task: {task_summary}")
        
        base_prompt = self.prompt_templates["effort_estimation"]["default"]
        
        context_sections = [f"""
**TASK INFORMATION:**
- Summary: {task_summary}
- Scopes:
{chr(10).join([f"  - {scope}" for scope in task_scopes])}
"""]
        
        if complexity_indicators:
            context_sections.append(f"""
**COMPLEXITY INDICATORS:**
{chr(10).join([f"- {key}: {value}" for key, value in complexity_indicators.items()])}
""")
        
        # Add estimation guidance from centralized prompts
        estimation_guidance = Prompts.get_effort_estimation_guidance_template()
        
        full_prompt = base_prompt + "\n".join(context_sections) + estimation_guidance
        full_prompt += self._get_quality_directives("effort_estimation")
        
        return full_prompt
    
    def _initialize_prompt_templates(self) -> Dict[str, Dict[str, str]]:
        """Initialize base prompt templates for different contexts (now uses centralized prompts)"""
        return {
            "epic_analysis": {
                "prd": Prompts.get_epic_analysis_prompt("prd"),
                "rfc": Prompts.get_epic_analysis_prompt("rfc"),
                "hybrid": Prompts.get_epic_analysis_prompt("hybrid")
            },
            
            "story_generation": {
                "prd": Prompts.get_story_generation_prompt("prd"),
                "rfc": Prompts.get_story_generation_prompt("rfc"),
                "hybrid": Prompts.get_story_generation_prompt("hybrid")
            },
            
            "task_breakdown": {
                "default": Prompts.get_task_breakdown_prompt()
            },
            
            "test_case_generation": {
                "story": Prompts.get_test_case_generation_prompt("story"),
                "task": Prompts.get_test_case_generation_prompt("task")
            },
            
            "effort_estimation": {
                "default": Prompts.get_effort_estimation_prompt()
            }
        }
    
    def _initialize_context_modifiers(self) -> Dict[str, str]:
        """Initialize context modification templates"""
        return Prompts.get_context_modifiers()
    
    def _initialize_quality_validators(self) -> Dict[str, str]:
        """Initialize quality validation directives"""
        return Prompts.get_quality_validators()
    
    def _determine_document_type(self, prd_content: Optional[str], rfc_content: Optional[str]) -> DocumentType:
        """Determine the primary document type for context-aware prompting"""
        if prd_content and rfc_content:
            return DocumentType.HYBRID
        elif prd_content:
            return DocumentType.PRD
        elif rfc_content:
            return DocumentType.RFC
        else:
            return DocumentType.EPIC_DESCRIPTION
    
    def _truncate_content(self, content: str, max_length: int) -> str:
        """Truncate content to fit within prompt length limits"""
        if len(content) <= max_length:
            return content
        
        truncated = content[:max_length - 100]
        return truncated + "\n... [Content truncated for length] ..."
    
    def _get_quality_directives(self, context: str) -> str:
        """Get quality directives for specific generation context"""
        return self.quality_validators.get(context, "")
