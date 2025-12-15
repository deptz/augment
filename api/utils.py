"""
Utility Functions
Helper functions for LLM client creation and data extraction
"""
from typing import Optional, Dict, Any, List
from src.llm_client import LLMClient
from .dependencies import get_config, get_generator
from .models.test_generation import TestCaseModel
from .models.planning import TaskDetail, StoryDetail
import logging

logger = logging.getLogger(__name__)


def create_custom_llm_client(provider: Optional[str] = None, model: Optional[str] = None) -> LLMClient:
    """Create a custom LLM client with specified provider and model"""
    config = get_config()
    try:
        # Use the config method that properly handles provider/model selection
        llm_config = config.get_llm_config(provider, model)
        logger.info(f"Using custom LLM configuration: provider={llm_config.get('provider')}, model={llm_config.get('model')}")
        
        return LLMClient(llm_config)
    except Exception as e:
        logger.error(f"Failed to create custom LLM client: {e}")
        # Fallback to default client
        return LLMClient(config.get_llm_config())


def create_custom_llm_client_with_prompts(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: float = 0.7
) -> LLMClient:
    """
    Create a custom LLM client with specified provider, model, and system prompt
    
    Args:
        provider: LLM provider (e.g., 'openai', 'claude', 'gemini')
        model: Model name
        system_prompt: Custom system prompt (if None, uses default from config)
        temperature: Temperature for generation
        
    Returns:
        Configured LLMClient instance
    """
    config = get_config()
    try:
        # Get base config
        llm_config = config.get_llm_config(provider, model)
        
        # Override system prompt if provided
        if system_prompt:
            llm_config['system_prompt'] = system_prompt
            logger.info("Using custom system prompt for LLM client")
        
        # Override temperature
        llm_config['temperature'] = temperature
        
        logger.info(f"Creating custom LLM client: provider={llm_config.get('provider')}, model={llm_config.get('model')}")
        
        return LLMClient(llm_config)
    except Exception as e:
        logger.error(f"Failed to create custom LLM client with prompts: {e}")
        raise


def extract_task_details_with_tests(planning_result) -> List[TaskDetail]:
    """Helper function to extract task details with test cases from planning result"""
    task_details = []
    generator = get_generator()
    
    if hasattr(planning_result, 'epic_plan') and planning_result.epic_plan:
        all_tasks = planning_result.epic_plan.get_all_tasks()
        
        for task in all_tasks:
            try:
                # Generate test cases for the task
                task_test_cases = []
                if hasattr(task, 'test_cases') and task.test_cases:
                    task_test_cases = [
                        TestCaseModel(
                            title=getattr(tc, 'title', 'Untitled Test'),
                            type=getattr(tc, 'type', 'unit'),
                            description=getattr(tc, 'description', ''),
                            expected_result=getattr(tc, 'expected_result', ''),
                            priority=getattr(tc, 'priority', None),
                            traceability=getattr(tc, 'traceability', None),
                            precondition=getattr(tc, 'precondition', None),
                            test_steps='\n'.join(tc.steps) if hasattr(tc, 'steps') and tc.steps else None,
                            source=getattr(tc, 'source', None)
                        )
                        for tc in task.test_cases
                    ]
                elif generator and hasattr(generator, 'planning_service') and hasattr(task, 'key') and task.key:
                    # Generate test cases if not already present (only for existing JIRA tasks)
                    try:
                        from src.enhanced_test_generator import TestCoverageLevel
                        test_results = generator.planning_service.generate_task_tests(
                            task_key=task.key,
                            coverage_level=TestCoverageLevel.STANDARD
                        )
                        if test_results.get("success"):
                            task_test_cases = [
                                TestCaseModel(
                                    title=tc["title"],
                                    type=tc["type"], 
                                    description=tc["description"],
                                    expected_result=tc["expected_result"],
                                    priority=tc.get("priority"),
                                    traceability=tc.get("traceability"),
                                    precondition=tc.get("precondition"),
                                    test_steps=tc.get("test_steps"),
                                    source=tc.get("source")
                                )
                                for tc in test_results["test_cases"]
                            ]
                    except Exception as e:
                        logger.warning(f"Failed to generate test cases for task '{task.summary}': {e}")
                
                task_detail = TaskDetail(
                    task_id=getattr(task, 'task_id', None),  # Include task_id for stable dependency resolution
                    summary=task.summary,
                    description=task.format_description(),
                    team=task.team.value,
                    depends_on_tasks=task.depends_on_tasks,
                    estimated_days=task.cycle_time_estimate.total_days if task.cycle_time_estimate else None,
                    test_cases=task_test_cases,
                    jira_key=getattr(task, 'key', None)
                )
                task_details.append(task_detail)
            except Exception as e:
                logger.error(f"Error processing task '{task.summary}': {str(e)}")
                
    return task_details


def extract_story_details_with_tests(planning_result) -> List[StoryDetail]:
    """Helper function to extract story details with test cases from planning result"""
    story_details = []
    generator = get_generator()
    
    # Debug logging
    has_epic_plan = hasattr(planning_result, 'epic_plan')
    if has_epic_plan:
        epic_plan = planning_result.epic_plan
        has_stories = epic_plan and hasattr(epic_plan, 'stories')
        story_count = len(epic_plan.stories) if has_stories and epic_plan.stories else 0
        logger.debug(f"extract_story_details_with_tests: has_epic_plan={has_epic_plan}, has_stories={has_stories}, story_count={story_count}")
    
    if hasattr(planning_result, 'epic_plan') and planning_result.epic_plan:
        stories_list = planning_result.epic_plan.stories if hasattr(planning_result.epic_plan, 'stories') else []
        logger.debug(f"Processing {len(stories_list)} stories from epic_plan")
        for story in stories_list:
            try:
                # Generate test cases for the story
                story_test_cases = []
                if hasattr(story, 'test_cases') and story.test_cases:
                    story_test_cases = [
                        TestCaseModel(
                            title=getattr(tc, 'title', 'Untitled Test'),
                            type=getattr(tc, 'type', 'acceptance'),
                            description=getattr(tc, 'description', ''),
                            expected_result=getattr(tc, 'expected_result', ''),
                            priority=getattr(tc, 'priority', None),
                            traceability=getattr(tc, 'traceability', None),
                            precondition=getattr(tc, 'precondition', None),
                            test_steps='\n'.join(tc.steps) if hasattr(tc, 'steps') and tc.steps else None,
                            source=getattr(tc, 'source', None)
                        )
                        for tc in story.test_cases
                    ]
                elif generator and hasattr(generator, 'planning_service') and hasattr(story, 'key') and story.key:
                    # Generate test cases if not already present (only for existing JIRA stories)
                    try:
                        from src.enhanced_test_generator import TestCoverageLevel
                        test_results = generator.planning_service.generate_story_tests(
                            story_key=story.key,
                            coverage_level=TestCoverageLevel.STANDARD
                        )
                        if test_results.get("success"):
                            story_test_cases = [
                                TestCaseModel(
                                    title=tc["title"],
                                    type=tc["type"],
                                    description=tc["description"],
                                    expected_result=tc["expected_result"],
                                    priority=tc.get("priority"),
                                    traceability=tc.get("traceability"),
                                    precondition=tc.get("precondition"),
                                    test_steps=tc.get("test_steps"),
                                    source=tc.get("source")
                                )
                                for tc in test_results["test_cases"]
                            ]
                    except Exception as e:
                        logger.warning(f"Failed to generate test cases for story '{story.summary}': {e}")
                
                # Extract tasks for this story with test cases
                story_tasks = []
                for task in story.tasks:
                    try:
                        # Generate test cases for the task
                        task_test_cases = []
                        if hasattr(task, 'test_cases') and task.test_cases:
                            task_test_cases = [
                                TestCaseModel(
                                    title=getattr(tc, 'title', 'Untitled Test'),
                                    type=getattr(tc, 'type', 'unit'),
                                    description=getattr(tc, 'description', ''),
                                    expected_result=getattr(tc, 'expected_result', ''),
                                    priority=getattr(tc, 'priority', None),
                                    traceability=getattr(tc, 'traceability', None),
                                    precondition=getattr(tc, 'precondition', None),
                                    test_steps='\n'.join(tc.steps) if hasattr(tc, 'steps') and tc.steps else None,
                                    source=getattr(tc, 'source', None)
                                )
                                for tc in task.test_cases
                            ]
                        elif generator and hasattr(generator, 'planning_service'):
                            # Generate test cases if not already present
                            try:
                                from src.enhanced_test_generator import TestCoverageLevel
                                test_results = generator.planning_service.generate_task_tests(
                                    task_key=getattr(task, 'key', task.summary),
                                    coverage_level=TestCoverageLevel.STANDARD
                                )
                                if test_results.get("success"):
                                    task_test_cases = [
                                        TestCaseModel(
                                            title=tc["title"],
                                            type=tc["type"],
                                            description=tc["description"],
                                            expected_result=tc["expected_result"],
                                            priority=tc.get("priority"),
                                            traceability=tc.get("traceability"),
                                            precondition=tc.get("precondition"),
                                            test_steps=tc.get("test_steps"),
                                            source=tc.get("source")
                                        )
                                        for tc in test_results["test_cases"]
                                    ]
                            except Exception as e:
                                logger.warning(f"Failed to generate test cases for task '{task.summary}': {e}")
                        
                        story_task = TaskDetail(
                            task_id=getattr(task, 'task_id', None),  # Include task_id for stable dependency resolution
                            summary=task.summary,
                            description=task.format_description(),
                            team=task.team.value,
                            depends_on_tasks=task.depends_on_tasks,
                            estimated_days=task.cycle_time_estimate.total_days if task.cycle_time_estimate else None,
                            test_cases=task_test_cases,
                            jira_key=getattr(task, 'key', None)
                        )
                        story_tasks.append(story_task)
                    except Exception as e:
                        logger.error(f"Error processing task '{task.summary}': {str(e)}")
                
                # Get story metadata if available
                story_key = getattr(story, 'key', None)
                story_meta = None
                if story_key and hasattr(planning_result, 'story_metadata') and planning_result.story_metadata:
                    story_meta = planning_result.story_metadata.get(story_key)
                
                # Build JIRA URL if we have a key
                jira_url = None
                if story_key:
                    try:
                        from ..dependencies import get_jira_client
                        jira_client = get_jira_client()
                        if jira_client:
                            jira_url = f"{jira_client.server_url.rstrip('/')}/browse/{story_key}"
                    except:
                        pass
                
                # Use metadata if available, otherwise use defaults
                ticket_source = story_meta.get('source') if story_meta else None
                action_taken = story_meta.get('action_taken') if story_meta else None
                was_updated = story_meta.get('was_updated') if story_meta else None
                metadata_jira_url = story_meta.get('jira_url') if story_meta else None
                
                # If story has a key but no metadata, infer it was found in PRD (most common case)
                if story_key and not ticket_source:
                    # Story has JIRA key but no metadata - likely parsed from PRD table
                    # This can happen in edge cases or if metadata wasn't populated
                    ticket_source = 'prd_table'  # Most likely source if key exists but no metadata
                
                # Acceptance criteria is now embedded in description, so set to empty list
                story_detail = StoryDetail(
                    summary=story.summary,
                    description=story.format_description() if hasattr(story, 'format_description') else getattr(story, 'description', ''),
                    acceptance_criteria=[],  # Empty since it's now in description
                    test_cases=story_test_cases,
                    tasks=story_tasks,
                    jira_key=story_key,
                    jira_url=metadata_jira_url or jira_url,
                    ticket_source=ticket_source,
                    action_taken=action_taken,
                    was_updated=was_updated,
                    prd_row_uuid=getattr(story, 'prd_row_uuid', None)  # Include UUID if available
                )
                story_details.append(story_detail)
                
            except Exception as e:
                logger.error(f"Error processing story '{story.summary}': {str(e)}")
                
    return story_details


# Keep old function for backward compatibility
def extract_task_details(planning_result) -> List[TaskDetail]:
    """Legacy function for backward compatibility - now includes test cases"""
    return extract_task_details_with_tests(planning_result)

