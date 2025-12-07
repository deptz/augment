"""
Planning Service for Epic Development Planning
"""
import logging
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from .planning_models import (
    EpicPlan, StoryPlan, TaskPlan, CycleTimeEstimate, AcceptanceCriteria,
    TestCase, PlanningResult, OperationMode, PlanningContext, GapAnalysis,
    TaskScope, TaskTeam
)
from .epic_analysis_engine import EpicAnalysisEngine
from .jira_client import JiraClient
from .llm_client import LLMClient
from .bulk_ticket_creator import BulkTicketCreator
from .confluence_client import ConfluenceClient
from .planning_prompt_engine import PlanningPromptEngine, DocumentType
from .enhanced_test_generator import EnhancedTestGenerator, TestCoverageLevel
from .team_based_task_generator import TeamBasedTaskGenerator

logger = logging.getLogger(__name__)


class PlanningService:
    """Core service for planning operations and ticket creation"""
    
    def __init__(
        self, 
        jira_client: JiraClient, 
        confluence_client: ConfluenceClient,
        llm_client: LLMClient
    ):
        self.jira_client = jira_client
        self.confluence_client = confluence_client
        self.llm_client = llm_client
        self.analysis_engine = EpicAnalysisEngine(jira_client, confluence_client)
        self.bulk_creator = BulkTicketCreator(jira_client)
        self.prompt_engine = PlanningPromptEngine()
        # Enhanced test generator with full context access
        self.test_generator = EnhancedTestGenerator(
            llm_client, 
            self.prompt_engine, 
            jira_client=jira_client, 
            confluence_client=confluence_client
        )
        self.team_task_generator = TeamBasedTaskGenerator(llm_client, self.prompt_engine)
        
        # Task relationship tracking
        self._task_summary_to_plan = {}
        self._task_summary_to_key = {}
    
    def plan_epic_complete(self, context: PlanningContext) -> PlanningResult:
        """
        Complete planning for an epic - generate all missing stories and tasks
        
        Args:
            context: Planning context with epic key and options
            
        Returns:
            PlanningResult with generated plan and execution details
        """
        start_time = time.time()
        logger.info(f"Starting complete epic planning for {context.epic_key}")
        
        try:
            # Step 1: Analyze current epic structure
            gap_analysis = self.analysis_engine.analyze_epic_structure(context.epic_key)
            context.gap_analysis = gap_analysis
            
            # Step 2: Generate complete epic plan
            epic_plan = self._generate_epic_plan(context)
            context.epic_plan = epic_plan
            
            # Step 3: Create tickets if not dry run
            created_tickets = {}
            if not context.dry_run:
                created_tickets = self._create_epic_tickets(epic_plan)
            
            # Step 4: Generate summary statistics
            summary_stats = epic_plan.get_summary_stats() if epic_plan else {}
            
            execution_time = time.time() - start_time
            
            result = PlanningResult(
                epic_key=context.epic_key,
                mode=context.mode,
                success=True,
                created_tickets=created_tickets,
                gap_analysis=gap_analysis,
                epic_plan=epic_plan,
                summary_stats=summary_stats,
                execution_time_seconds=execution_time
            )
            
            logger.info(f"Epic planning completed for {context.epic_key} in {execution_time:.2f}s")
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Error in epic planning for {context.epic_key}: {str(e)}")
            
            return PlanningResult(
                epic_key=context.epic_key,
                mode=context.mode,
                success=False,
                errors=[str(e)],
                execution_time_seconds=execution_time
            )
    
    def generate_stories_for_epic(self, context: PlanningContext) -> PlanningResult:
        """
        Generate only stories for an epic (without tasks)
        
        Args:
            context: Planning context
            
        Returns:
            PlanningResult with generated stories
        """
        start_time = time.time()
        logger.info(f"Generating stories for epic {context.epic_key}")
        
        try:
            # Get epic information
            epic_issue = self.jira_client.jira.issue(context.epic_key)
            epic_description_field = epic_issue.fields.description
            
            # Extract epic description text
            if isinstance(epic_description_field, dict):
                epic_description = self._extract_text_from_adf(epic_description_field)
            else:
                epic_description = epic_description_field or ''
            
            # Get PRD/RFC content
            prd_content = self._get_prd_content(epic_issue)
            rfc_content = self._get_rfc_content(epic_issue)
            
            # Analyze gaps
            gap_analysis = self.analysis_engine.analyze_epic_structure(context.epic_key)
            
            # Generate stories only
            stories = self._generate_stories_for_epic_plan(context.epic_key, epic_description, gap_analysis, prd_content, rfc_content)
            
            epic_plan = EpicPlan(
                epic_key=context.epic_key,
                epic_title=f"Epic {context.epic_key}",
                stories=stories
            )
            
            # Create story tickets if not dry run
            created_tickets = {}
            if not context.dry_run:
                created_tickets = self._create_story_tickets(stories)
            
            execution_time = time.time() - start_time
            
            return PlanningResult(
                epic_key=context.epic_key,
                mode=context.mode,
                success=True,
                created_tickets=created_tickets,
                gap_analysis=gap_analysis,
                epic_plan=epic_plan,
                execution_time_seconds=execution_time
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Error generating stories for {context.epic_key}: {str(e)}")
            
            return PlanningResult(
                epic_key=context.epic_key,
                mode=context.mode,
                success=False,
                errors=[str(e)],
                execution_time_seconds=execution_time
            )
    
    def generate_tasks_for_stories(self, story_keys: List[str], context: PlanningContext, custom_llm_client: Optional['LLMClient'] = None) -> PlanningResult:
        """
        Generate tasks for specific stories
        
        Args:
            story_keys: List of story keys to generate tasks for
            context: Planning context
            custom_llm_client: Optional custom LLM client to use for generation
            
        Returns:
            PlanningResult with generated tasks
        """
        start_time = time.time()
        logger.info(f"Generating tasks for {len(story_keys)} stories")
        
        try:
            all_tasks = []
            created_tickets = {"tasks": []}
            
            for story_key in story_keys:
                # Generate tasks for this story
                tasks = self._generate_tasks_for_story(story_key, context, custom_llm_client)
                all_tasks.extend(tasks)
                
                # Create task tickets if not dry run
                if not context.dry_run:
                    logger.info(f"Dry run is FALSE - will create {len(tasks)} JIRA tickets for story {story_key}")
                    task_tickets = self._create_task_tickets(tasks)
                    created_tickets["tasks"].extend(task_tickets)
                    logger.info(f"Created {len(task_tickets)} task tickets for story {story_key}: {task_tickets}")
                else:
                    logger.info(f"Dry run is TRUE - not creating actual JIRA tickets for story {story_key}")
                    # In dry run mode, include task summaries for preview
                    task_summaries = [f"[DRY_RUN] {task.summary}" for task in tasks]
                    created_tickets["tasks"].extend(task_summaries)
                    logger.debug(f"Dry run task summaries: {task_summaries}")
            
            # Create epic plan with stories containing the generated tasks
            stories_with_tasks = []
            tasks_by_story = {}
            
            # Group tasks by story
            for task in all_tasks:
                story_key = task.story_key or "unknown"
                if story_key not in tasks_by_story:
                    tasks_by_story[story_key] = []
                tasks_by_story[story_key].append(task)
            
            # Create StoryPlan objects with tasks
            for story_key, tasks in tasks_by_story.items():
                story_plan = StoryPlan(
                    summary=f"Story {story_key}",
                    description=f"Story for {story_key}",
                    acceptance_criteria=[],
                    tasks=tasks,
                    epic_key=context.epic_key
                )
                stories_with_tasks.append(story_plan)
            
            epic_plan = EpicPlan(
                epic_key=context.epic_key,
                epic_title=f"Epic {context.epic_key}",
                stories=stories_with_tasks  # Now contains tasks!
            )
            
            # Check if tasks already have test cases from unified generation
            # If they do, skip redundant test generation to avoid multiple LLM calls
            tasks_with_tests = [task for task in all_tasks if hasattr(task, 'test_cases') and task.test_cases]
            tasks_without_tests = [task for task in all_tasks if not (hasattr(task, 'test_cases') and task.test_cases)]
            
            if tasks_without_tests:
                # Only generate tests for tasks that don't already have them
                logger.info(f"Generating enhanced test cases for {len(tasks_without_tests)} tasks (skipping {len(tasks_with_tests)} tasks that already have tests)...")
                task_tests = self.generate_test_cases_for_tasks(
                    tasks=tasks_without_tests,
                    coverage_level=TestCoverageLevel.STANDARD,
                    include_in_task_objects=True,
                    custom_llm_client=custom_llm_client
                )
                logger.info(f"Enhanced test generation completed for {len(tasks_without_tests)} tasks")
            else:
                logger.info(f"All {len(all_tasks)} tasks already have test cases from unified generation - skipping redundant test generation")
            
            # ✅ CRITICAL: Update JIRA with test cases for all created tasks
            if not context.dry_run:
                logger.info("Updating JIRA tickets with test cases...")
                for task in all_tasks:
                    if hasattr(task, 'key') and task.key and hasattr(task, 'test_cases') and task.test_cases:
                        logger.info(f"Updating JIRA task {task.key} with {len(task.test_cases)} test cases")
                        try:
                            self._update_ticket_with_test_cases(task.key, task.test_cases)
                        except Exception as e:
                            logger.error(f"Failed to update JIRA task {task.key} with test cases: {str(e)}")
            
            execution_time = time.time() - start_time
            
            # Capture system prompt from LLM client
            llm_to_use = custom_llm_client if custom_llm_client else self.llm_client
            system_prompt = llm_to_use.get_system_prompt() if llm_to_use else None
            
            return PlanningResult(
                epic_key=context.epic_key,
                mode=context.mode,
                success=True,
                created_tickets=created_tickets,
                epic_plan=epic_plan,
                summary_stats={"total_tasks": len(all_tasks)},
                execution_time_seconds=execution_time,
                system_prompt=system_prompt,
                user_prompt="[Multiple prompts used for different stories - see task details]"
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Error generating tasks for stories: {str(e)}")
            
            return PlanningResult(
                epic_key=context.epic_key,
                mode=context.mode,
                success=False,
                errors=[str(e)],
                execution_time_seconds=execution_time
            )
    
    def _generate_epic_plan(self, context: PlanningContext) -> EpicPlan:
        """Generate complete epic plan with stories and tasks"""
        epic_key = context.epic_key
        gap_analysis = context.gap_analysis
        
        # Get epic details
        epic_issue = self.jira_client.get_ticket(epic_key)
        if not epic_issue:
            raise ValueError(f"Epic {epic_key} not found")
        epic_title = epic_issue.get('fields', {}).get('summary', '')
        
        # Handle structured description (Atlassian Document Format)
        epic_description_field = epic_issue.get('fields', {}).get('description', '')
        if isinstance(epic_description_field, dict):
            epic_description = self._extract_text_from_adf(epic_description_field)
        else:
            epic_description = epic_description_field or ''
        
        # Get PRD/RFC content
        prd_content = self._get_prd_content(epic_issue)
        rfc_content = self._get_rfc_content(epic_issue)
        
        # Generate stories (including missing ones)
        stories = self._generate_stories_for_epic_plan(epic_key, epic_description, gap_analysis, prd_content, rfc_content)
        
        # Generate tasks for each story
        for story in stories:
            story.tasks = self._generate_tasks_for_story_plan(story, context)
        
        # Calculate total estimated days
        total_days = sum(
            task.cycle_time_estimate.total_days 
            for story in stories 
            for task in story.tasks 
            if task.cycle_time_estimate
        )
        
        return EpicPlan(
            epic_key=epic_key,
            epic_title=epic_title,
            epic_description=epic_description,
            prd_url=self._get_custom_field_value(epic_issue, 'PRD'),
            rfc_url=self._get_custom_field_value(epic_issue, 'RFC'),
            stories=stories,
            total_estimated_days=total_days
        )
    
    def _generate_stories_for_epic_plan(
        self,
        epic_key: str,
        epic_description: str,
        gap_analysis: GapAnalysis,
        prd_content: Optional[Dict[str, Any]] = None,
        rfc_content: Optional[Dict[str, Any]] = None
    ) -> List[StoryPlan]:
        """Generate stories for an epic"""
        stories = []
        
        # Generate stories for missing areas
        for missing_area in gap_analysis.missing_stories:
            story = self._generate_story_from_area(missing_area, epic_key, prd_content, rfc_content)
            stories.append(story)
        
        return stories
    
    def _generate_story_from_area(
        self,
        area: str,
        epic_key: str,
        prd_content: Optional[Dict[str, Any]] = None,
        rfc_content: Optional[Dict[str, Any]] = None
    ) -> StoryPlan:
        """Generate a story for a specific functional area using enhanced AI prompting"""
        logger.info(f"Generating story for area: {area}")
        
        try:
            # Use enhanced prompt engine for story generation
            epic_context = f"Epic: {epic_key} - Area: {area}"
            doc_type = DocumentType.HYBRID
            
            if prd_content and not rfc_content:
                doc_type = DocumentType.PRD
            elif rfc_content and not prd_content:
                doc_type = DocumentType.RFC
            
            # Generate optimized prompt
            prompt = self.prompt_engine.generate_story_creation_prompt(
                epic_context=epic_context,
                missing_areas=[area],
                doc_type=doc_type
            )
            
            # Add context from documents
            if prd_content:
                prompt += f"\n\nPRD Content for context:\n{str(prd_content)[:1000]}"
            if rfc_content:
                prompt += f"\n\nRFC Content for context:\n{str(rfc_content)[:1000]}"
            
            # Generate story using LLM with centralized system prompt
            # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
            response = self.llm_client.generate_content(
                prompt=prompt,
                system_prompt=Prompts.get_story_generation_prompt(),
                max_tokens=None
            )
            
            # Parse the LLM response into structured story
            story = self._parse_story_response(response, area, epic_key)
            if story:
                logger.info(f"Successfully generated story for {area}: {story.summary}")
                return story
            
        except Exception as e:
            logger.warning(f"LLM story generation failed for {area}: {str(e)}, falling back to template")
        
        # Fallback to template-based generation
        return self._generate_story_from_template(area, epic_key, prd_content, rfc_content)
    
    def _parse_story_response(self, response: str, area: str, epic_key: str) -> Optional[StoryPlan]:
        """Parse LLM response into StoryPlan structure"""
        try:
            # This would be enhanced with more sophisticated parsing
            # For now, create a basic story structure
            
            # Extract key information from response
            lines = response.strip().split('\n')
            summary = area
            description = f"Generated story for {area}"
            
            # Look for story patterns in response
            for line in lines:
                if line.strip().startswith('Summary:') or line.strip().startswith('Title:'):
                    summary = line.split(':', 1)[1].strip()
                elif line.strip().startswith('Description:') or line.strip().startswith('As a'):
                    description = line.strip()
                    break
            
            # Create default acceptance criteria
            criteria = [
                AcceptanceCriteria(
                    scenario=f"{area} functionality",
                    given="the system is properly configured",
                    when=f"a user interacts with {area.lower()}",
                    then="the expected functionality works correctly"
                )
            ]
            
            # Create test cases
            test_cases = [
                TestCase(
                    title=f"Test {area} functionality",
                    type="integration",
                    description=f"Verify {area} works as expected",
                    expected_result="Feature functions correctly"
                )
            ]
            
            # Create cycle time estimate
            cycle_estimate = CycleTimeEstimate(
                development_days=3.0,
                testing_days=1.0,
                review_days=0.5,
                deployment_days=0.5,
                total_days=5.0,
                confidence_level=0.7
            )
            
            return StoryPlan(
                summary=summary,
                description=description,
                story_points=5,
                acceptance_criteria=criteria,
                test_cases=test_cases,
                tasks=[],  # Will be populated later
                cycle_time_estimate=cycle_estimate,
                epic_key=epic_key
            )
            
        except Exception as e:
            logger.error(f"Error parsing story response: {str(e)}")
            return None
    
    def _generate_story_from_template(
        self,
        area: str,
        epic_key: str,
        prd_content: Optional[Dict[str, Any]] = None,
        rfc_content: Optional[Dict[str, Any]] = None
    ) -> StoryPlan:
        """Generate a story using templates (fallback method)"""
        story_templates = {
            "User Authentication": {
                "summary": "Implement user authentication system",
                "description": "As a user, I need to be able to securely log in and out of the system so that my account and data are protected.",
                "acceptance_criteria": [
                    AcceptanceCriteria(
                        scenario="User login with valid credentials",
                        given="a user has valid username and password",
                        when="they attempt to log in",
                        then="they should be successfully authenticated and redirected to the dashboard"
                    ),
                    AcceptanceCriteria(
                        scenario="User login with invalid credentials",
                        given="a user has invalid username or password",
                        when="they attempt to log in",
                        then="they should see an error message and remain on the login page"
                    )
                ]
            },
            "API Integration": {
                "summary": "Implement API integration layer",
                "description": "As a developer, I need a robust API integration layer so that the system can communicate with external services reliably.",
                "acceptance_criteria": [
                    AcceptanceCriteria(
                        scenario="Successful API call",
                        given="the external API is available",
                        when="a request is made to the integration layer",
                        then="the response should be properly formatted and returned"
                    )
                ]
            }
        }
        
        template = story_templates.get(area, {
            "summary": f"Implement {area}",
            "description": f"As a user, I need {area.lower()} functionality implemented.",
            "acceptance_criteria": [
                AcceptanceCriteria(
                    scenario=f"{area} functionality works",
                    given="the system is running",
                    when=f"I use the {area.lower()} feature",
                    then="it should work as expected"
                )
            ]
        })
        
        # Generate test cases
        test_cases = [
            TestCase(
                title=f"Test {area} functionality",
                description=f"Verify that {area.lower()} works correctly",
                expected_result=f"{area} functions as designed"
            )
        ]
        
        return StoryPlan(
            summary=template["summary"],
            description=template["description"],
            acceptance_criteria=template["acceptance_criteria"],
            test_cases=test_cases,
            epic_key=epic_key
        )
    
    def _generate_tasks_for_story_plan(self, story: StoryPlan, context: PlanningContext, custom_llm_client: Optional['LLMClient'] = None) -> List[TaskPlan]:
        """Generate tasks with embedded test cases using unified generation approach"""
        logger.info(f"Generating unified tasks with tests for story: {story.summary}")
        
        try:
            # Create a custom team task generator if custom LLM client is provided
            if custom_llm_client:
                from .team_based_task_generator import TeamBasedTaskGenerator
                custom_team_generator = TeamBasedTaskGenerator(custom_llm_client, self.prompt_engine)
                task_generator = custom_team_generator
                logger.info("Using custom LLM client for unified task+test generation")
            else:
                task_generator = self.team_task_generator
            
            # ✅ Use unified generation: tasks WITH embedded test cases
            tasks = task_generator.generate_team_separated_tasks_with_tests(
                story=story,
                max_cycle_days=context.max_task_cycle_days,
                test_coverage_level=TestCoverageLevel.STANDARD,  # Could be configurable via context
                force_separation=True,
                prd_content=context.prd_content,
                rfc_content=context.rfc_content,
                additional_context=context.additional_context
            )
            
            # Limit number of tasks per story
            limited_tasks = tasks[:context.max_tasks_per_story]
            
            # Count test cases for logging
            total_tests = sum(len(task.test_cases) for task in limited_tasks)
            
            logger.info(f"Generated {len(limited_tasks)} unified tasks with {total_tests} embedded tests for story {story.summary}: "
                       f"Backend: {len([t for t in limited_tasks if t.team == TaskTeam.BACKEND])}, "
                       f"Frontend: {len([t for t in limited_tasks if t.team == TaskTeam.FRONTEND])}, "
                       f"QA: {len([t for t in limited_tasks if t.team == TaskTeam.QA])}")
            
            return limited_tasks
            
        except Exception as e:
            logger.error(f"Unified task+test generation failed for story {story.summary}: {str(e)}, using fallback")
            # Fallback to separate generation
            return self._generate_fallback_tasks_with_tests(story, context, custom_llm_client)
    
    def _generate_fallback_tasks_with_tests(self, story: StoryPlan, context: PlanningContext, custom_llm_client: Optional['LLMClient'] = None) -> List[TaskPlan]:
        """Fallback: Generate tasks first, then add test cases separately"""
        logger.info(f"Using fallback separate generation for story: {story.summary}")
        
        try:
            # Create task generator
            if custom_llm_client:
                from .team_based_task_generator import TeamBasedTaskGenerator
                task_generator = TeamBasedTaskGenerator(custom_llm_client, self.prompt_engine)
            else:
                task_generator = self.team_task_generator
            
            # Generate tasks using existing method
            tasks = task_generator.generate_team_separated_tasks(
                story=story,
                max_cycle_days=context.max_task_cycle_days,
                force_separation=True,
                prd_content=context.prd_content,
                rfc_content=context.rfc_content,
                additional_context=context.additional_context
            )
            
            # Add test cases separately using enhanced test generator
            for task in tasks:
                try:
                    task.test_cases = self.test_generator.generate_task_test_cases(
                        task=task,
                        coverage_level=TestCoverageLevel.STANDARD,
                        technical_context=None
                    )
                    logger.info(f"Added {len(task.test_cases)} test cases to task: {task.summary}")
                except Exception as test_e:
                    logger.warning(f"Failed to generate test cases for task {task.summary}: {test_e}")
                    # Use minimal fallback tests
                    task.test_cases = [
                        TestCase(
                            title=f"Basic Test: {task.summary}",
                            type="unit",
                            description="Basic functionality test",
                            expected_result="Basic functionality works",
                            source="minimal_fallback"
                        )
                    ]
            
            # Limit tasks
            limited_tasks = tasks[:context.max_tasks_per_story]
            total_tests = sum(len(task.test_cases) for task in limited_tasks)
            
            logger.info(f"Fallback generation completed: {len(limited_tasks)} tasks with {total_tests} test cases")
            return limited_tasks
            
        except Exception as e:
            logger.error(f"Fallback generation also failed: {str(e)}, using basic fallback")
            return self._generate_fallback_team_tasks(story, context)
    
    def _generate_fallback_team_tasks(self, story: StoryPlan, context: PlanningContext) -> List[TaskPlan]:
        """Generate basic team-separated tasks as fallback when AI generation fails"""
        tasks = []
        
        # Backend task
        backend_task = TaskPlan(
            summary=f"Backend implementation for {story.summary}",
            purpose="Implement backend logic and data handling",
            scopes=[TaskScope(
                description="Develop backend services, APIs, and data layer",
                complexity="medium",
                dependencies=[],
                deliverable="Working backend implementation"
            )],
            expected_outcomes=["Backend services implemented", "APIs functional", "Data layer working"],
            team=TaskTeam.BACKEND,
            test_cases=[
                TestCase(
                    title=f"Backend unit tests for {story.summary}",
                    type="unit",
                    description="Test backend components and business logic",
                    expected_result="All backend unit tests pass"
                ),
                TestCase(
                    title=f"API integration tests for {story.summary}",
                    type="integration",
                    description="Test API endpoints and data flow",
                    expected_result="API integration tests pass"
                )
            ],
            cycle_time_estimate=CycleTimeEstimate(
                development_days=2.0,
                testing_days=0.5,
                review_days=0.5,
                deployment_days=0.5,
                total_days=3.0,
                confidence_level=0.7,
                exceeds_limit=False
            ),
            epic_key=story.epic_key,
            story_key=getattr(story, 'key', None)
        )
        tasks.append(backend_task)
        
        # Frontend task
        frontend_task = TaskPlan(
            summary=f"Frontend implementation for {story.summary}",
            purpose="Implement user interface and user experience",
            scopes=[TaskScope(
                description="Develop UI components, user interactions, and client-side logic",
                complexity="medium",
                dependencies=["Backend implementation"],
                deliverable="Working frontend implementation"
            )],
            expected_outcomes=["UI components implemented", "User interactions functional", "Frontend integrated with backend"],
            team=TaskTeam.FRONTEND,
            test_cases=[
                TestCase(
                    title=f"UI component tests for {story.summary}",
                    type="unit",
                    description="Test UI components and user interface elements",
                    expected_result="UI component tests pass"
                ),
                TestCase(
                    title=f"User interaction tests for {story.summary}",
                    type="e2e",
                    description="Test end-to-end user interactions and workflows",
                    expected_result="User interaction tests pass"
                )
            ],
            cycle_time_estimate=CycleTimeEstimate(
                development_days=1.5,
                testing_days=0.5,
                review_days=0.5,
                deployment_days=0.25,
                total_days=2.75,
                confidence_level=0.7,
                exceeds_limit=False
            ),
            epic_key=story.epic_key,
            story_key=getattr(story, 'key', None)
        )
        tasks.append(frontend_task)
        
        # QA task
        qa_task = TaskPlan(
            summary=f"Quality assurance for {story.summary}",
            purpose="Ensure quality and validate functionality",
            scopes=[TaskScope(
                description="Create comprehensive test plan, execute test cases, and validate quality",
                complexity="medium",
                dependencies=["Frontend implementation"],
                deliverable="Quality validation and test results"
            )],
            expected_outcomes=["Test plan created", "All test cases executed", "Quality validated", "Bugs identified and tracked"],
            team=TaskTeam.QA,
            test_cases=[
                TestCase(
                    title=f"Test plan creation for {story.summary}",
                    type="acceptance",
                    description="Create comprehensive test plan covering all acceptance criteria",
                    expected_result="Complete test plan documented"
                ),
                TestCase(
                    title=f"End-to-end testing for {story.summary}",
                    type="e2e",
                    description="Execute complete end-to-end testing of the feature",
                    expected_result="All E2E tests pass successfully"
                )
            ],
            cycle_time_estimate=CycleTimeEstimate(
                development_days=0.5,
                testing_days=2.0,
                review_days=0.25,
                deployment_days=0.25,
                total_days=3.0,
                confidence_level=0.8,
                exceeds_limit=False
            ),
            epic_key=story.epic_key,
            story_key=getattr(story, 'key', None)
        )
        tasks.append(qa_task)
        
        # ✅ ADD: Generate enhanced test cases for fallback tasks too
        try:
            for task in tasks:
                enhanced_test_cases = self.test_generator.generate_task_test_cases(
                    task=task,
                    coverage_level=TestCoverageLevel.BASIC,  # Use basic level for fallback
                    technical_context=self._detect_technical_context(task)
                )
                # Replace the manually created test cases with enhanced ones
                if enhanced_test_cases:
                    task.test_cases = enhanced_test_cases
                    logger.info(f"Generated {len(enhanced_test_cases)} enhanced test cases for fallback task: {task.summary}")
        except Exception as e:
            logger.warning(f"Enhanced test generation failed for fallback tasks: {str(e)}")
            # Keep the manually created test cases as final fallback
        
        return tasks[:context.max_tasks_per_story]
    
    def _generate_tasks_for_story(self, story_key: str, context: PlanningContext, custom_llm_client: Optional['LLMClient'] = None) -> List[TaskPlan]:
        """Generate tasks for an existing story"""
        try:
            # Get story details
            story_issue = self.jira_client.get_ticket(story_key)
            if not story_issue:
                logger.error(f"Story {story_key} not found")
                return []
            story_summary = story_issue.get('fields', {}).get('summary', '')
            
            # Create a minimal story plan for task generation
            description_field = story_issue.get('fields', {}).get('description', '')
            # Handle structured description (Atlassian Document Format)
            if isinstance(description_field, dict):
                # Extract text from ADF structure
                description = self._extract_text_from_adf(description_field)
            else:
                description = description_field or ''
                
            story_plan = StoryPlan(
                key=story_key,  # ✅ Set the story key!
                summary=story_summary,
                description=description,
                acceptance_criteria=[],
                epic_key=context.epic_key
            )
            
            logger.debug(f"Created StoryPlan with key='{story_plan.key}' for story {story_key}")
            
            generated_tasks = self._generate_tasks_for_story_plan(story_plan, context, custom_llm_client)
            
            # Verify story_key is set in generated tasks
            for task in generated_tasks:
                logger.debug(f"Generated task '{task.summary}' with story_key='{task.story_key}'")
                if not task.story_key:
                    logger.warning(f"⚠️ Task '{task.summary}' missing story_key, setting manually")
                    task.story_key = story_key
            
            return generated_tasks
            
        except Exception as e:
            logger.error(f"Error generating tasks for story {story_key}: {str(e)}")
            return []
    
    def _get_prd_content(self, epic_issue) -> Optional[Dict[str, Any]]:
        """Extract PRD content from epic using enhanced section extraction"""
        try:
            prd_url = self._get_custom_field_value(epic_issue, 'PRD')
            if not prd_url:
                return None
            
            # Use the correct confluence client method to get enhanced PRD content
            page_data = self.confluence_client.get_page_content(prd_url)
            if not page_data:
                return None
            
            # Extract enhanced PRD sections for planning context
            prd_sections = page_data.get('prd_sections', {})
            
            # Return structured PRD data for planning
            return {
                'title': page_data['title'],
                'url': page_data['url'],
                'summary': page_data.get('summary'),
                'goals': page_data.get('goals'),
                'content': page_data.get('content', ''),
                'sections': prd_sections
            }
            
        except Exception as e:
            logger.warning(f"Failed to get PRD content from epic: {e}")
            return None
    
    def _get_rfc_content(self, epic_issue) -> Optional[Dict[str, Any]]:
        """Extract RFC content from epic using enhanced section extraction"""
        try:
            rfc_url = self._get_custom_field_value(epic_issue, 'RFC')
            if not rfc_url:
                return None
            
            # Use the correct confluence client method to get enhanced RFC content
            page_data = self.confluence_client.get_page_content(rfc_url)
            if not page_data:
                return None
            
            # Extract enhanced RFC sections for planning context
            rfc_sections = page_data.get('rfc_sections', {})
            
            # Return structured RFC data for planning
            return {
                'title': page_data['title'],
                'url': page_data['url'],
                'summary': page_data.get('summary'),
                'content': page_data.get('content', ''),
                'sections': rfc_sections
            }
            
        except Exception as e:
            logger.warning(f"Failed to get RFC content from epic: {e}")
            return None
    
    def _get_custom_field_value(self, issue, field_type: str) -> Optional[str]:
        """Get custom field value for PRD or RFC"""
        try:
            if field_type == 'PRD':
                field_id = self.jira_client.prd_custom_field
            elif field_type == 'RFC':
                field_id = self.jira_client.rfc_custom_field
            else:
                return None
            
            if not field_id:
                return None
                
            return issue.get('fields', {}).get(field_id, None)
        except Exception:
            return None
    
    def _create_epic_tickets(self, epic_plan: EpicPlan) -> Dict[str, List[str]]:
        """Create all tickets for an epic plan"""
        created_tickets = {"stories": [], "tasks": []}
        
        # Create stories
        for story in epic_plan.stories:
            story_key = self._create_story_ticket(story)
            if story_key:
                created_tickets["stories"].append(story_key)
                
                # Create tasks for this story
                for task in story.tasks:
                    task.story_key = story_key
                    task_key = self._create_task_ticket(task)
                    if task_key:
                        created_tickets["tasks"].append(task_key)
        
        return created_tickets
    
    def _create_story_tickets(self, stories: List[StoryPlan]) -> Dict[str, List[str]]:
        """Create story tickets"""
        created_tickets = {"stories": []}
        
        for story in stories:
            story_key = self._create_story_ticket(story)
            if story_key:
                created_tickets["stories"].append(story_key)
        
        return created_tickets
    
    def _create_task_tickets(self, tasks: List[TaskPlan]) -> List[str]:
        """Create task tickets and establish relationships"""
        logger.info(f"Creating {len(tasks)} task tickets in JIRA...")
        created_keys = []
        failed_count = 0
        
        # Build a mapping of task summaries to tasks for dependency resolution
        self._task_summary_to_plan = {task.summary: task for task in tasks}
        self._task_summary_to_key = {}
        
        # First pass: Create all tickets
        for i, task in enumerate(tasks, 1):
            logger.debug(f"Creating task {i}/{len(tasks)}: {task.summary}")
            task_key = self._create_task_ticket_only(task)
            if task_key:
                created_keys.append(task_key)
                self._task_summary_to_key[task.summary] = task_key
                logger.debug(f"Task {i} created successfully: {task_key}")
            else:
                failed_count += 1
                logger.warning(f"Task {i} creation failed: {task.summary}")
        
        # Second pass: Create relationships after all tickets exist
        logger.info(f"Creating relationships for {len(created_keys)} created tasks...")
        for task in tasks:
            if task.key:  # Only process successfully created tasks
                self._create_task_relationships(task, task.key)
        
        logger.info(f"Task creation completed: {len(created_keys)} succeeded, {failed_count} failed")
        return created_keys
    
    def _create_story_ticket(self, story: StoryPlan) -> Optional[str]:
        """Create a single story ticket"""
        try:
            logger.info(f"Creating JIRA story ticket: {story.summary}")
            logger.debug(f"Story details - Epic: {story.epic_key}, Priority: {story.priority}")
            
            # Use the project key from the story's epic
            project_key = None
            if story.epic_key:
                # Extract project key from epic key (e.g., "PROJ-5840" -> "PROJ")
                project_key = story.epic_key.split('-')[0]
            
            if not project_key:
                logger.error(f"Cannot determine project key for story: {story.summary}")
                return None
            
            logger.debug(f"Using project key: {project_key}")
            
            # Create the ticket using JIRA client
            # Pass Confluence server URL for image attachment support
            confluence_server_url = None
            if self.confluence_client:
                confluence_server_url = self.confluence_client.server_url
            
            story_key = self.jira_client.create_story_ticket(
                story_plan=story,
                project_key=project_key,
                confluence_server_url=confluence_server_url
            )
            
            if story_key:
                logger.info(f"✅ Successfully created story ticket: {story_key}")
                # Update the story with the created key
                story.key = story_key
                
                # ❌ SKIP: Don't write generic test cases during story creation  
                # Let enhanced test generation write proper test cases instead
                if hasattr(story, 'test_cases') and story.test_cases:
                    logger.info(f"Skipping generic test cases during story creation for {story_key} - enhanced test generation will provide better ones")
            else:
                logger.error(f"❌ Failed to create story ticket for: {story.summary}")
            
            return story_key
            
        except Exception as e:
            logger.error(f"❌ Error creating story ticket for '{story.summary}': {str(e)}")
            logger.exception("Full exception details:")
            return None
    
    def _create_task_ticket_only(self, task: TaskPlan) -> Optional[str]:
        """Create a single task ticket without relationships"""
        try:
            logger.info(f"Creating JIRA task ticket: {task.summary}")
            logger.debug(f"Task details - Team: {task.team}, Epic: {task.epic_key}, Story: {getattr(task, 'story_key', 'None')}")
            
            # Use the project key from the task's epic or story
            project_key = None
            if task.epic_key:
                # Extract project key from epic key (e.g., "PROJ-5840" -> "PROJ")
                project_key = task.epic_key.split('-')[0]
            elif hasattr(task, 'story_key') and task.story_key:
                # Extract project key from story key
                project_key = task.story_key.split('-')[0]
            
            if not project_key:
                logger.error(f"Cannot determine project key for task: {task.summary}")
                return None
            
            logger.debug(f"Using project key: {project_key}")
            
            # Create the ticket using JIRA client
            task_key = self.jira_client.create_task_ticket(
                task_plan=task,
                project_key=project_key,
                story_key=getattr(task, 'story_key', None)
            )
            
            if task_key:
                logger.info(f"✅ Successfully created task ticket: {task_key}")
                # Update the task with the created key
                task.key = task_key
                
                # ❌ SKIP: Don't write generic test cases during task creation
                # Let enhanced test generation write proper test cases instead
                if hasattr(task, 'test_cases') and task.test_cases:
                    logger.info(f"Skipping generic test cases during task creation for {task_key} - enhanced test generation will provide better ones")
            else:
                logger.error(f"❌ Failed to create task ticket for: {task.summary}")
            
            return task_key
            
        except Exception as e:
            logger.error(f"❌ Error creating task ticket for '{task.summary}': {str(e)}")
            logger.exception("Full exception details:")
            return None

    def _create_task_relationships(self, task: TaskPlan, task_key: str):
        """Create issue links for task relationships"""
        try:
            logger.debug(f"📋 Creating relationships for task {task_key}")
            logger.debug(f"   Task details: story_key='{task.story_key}', epic_key='{task.epic_key}', team={task.team.value}")
            
            relationships_created = 0
            
            # Handle "depends_on_tasks" relationships - create "Blocks" links
            if task.depends_on_tasks:
                logger.info(f"Creating dependency links for {task_key}: depends on {task.depends_on_tasks}")
                for dependency_summary in task.depends_on_tasks:
                    # Try to find the actual JIRA key for the dependency task
                    dependency_key = self._find_task_key_by_summary(dependency_summary)
                    if dependency_key:
                        # Create "Blocks" link: dependency blocks this task
                        # Try "Blocks" first, fallback to standard link types
                        success = self._create_dependency_link(dependency_key, task_key)
                        if success:
                            logger.info(f"✅ Created dependency link: {dependency_key} blocks {task_key}")
                            relationships_created += 1
                        else:
                            logger.warning(f"❌ Failed to create dependency link: {dependency_key} -> {task_key}")
                    else:
                        logger.warning(f"🔍 Could not find JIRA key for dependency task: {dependency_summary}")
            
            # Handle story relationship - create "Split from" link only to stories
            if task.story_key:
                logger.info(f"Creating story-task link: {task_key} split from story {task.story_key}")
                success, actual_link_type = self._create_parent_child_link(task.story_key, task_key)
                if success:
                    logger.info(f"✅ Created '{actual_link_type}' link: {task_key} linked to story {task.story_key}")
                    relationships_created += 1
                else:
                    logger.warning(f"❌ Failed to create any relationship link: story {task.story_key} -> {task_key}")
            
            # For tasks without story parent, JIRA client already created native parent relationship to epic
            elif task.epic_key:
                logger.info(f"ℹ️ Task {task_key} uses native JIRA parent relationship to epic {task.epic_key} (no custom link needed)")
            
            # Log when no parent relationship is available
            else:
                logger.warning(f"⚠️ Task {task_key} has no story_key or epic_key for parent relationship")
            
            # Log team blocking information (informational only, as we can't create links to teams)
            if task.blocked_by_teams:
                logger.info(f"🚫 Task {task_key} is blocked by teams: {[team.value for team in task.blocked_by_teams]}")
                logger.debug(f"   ℹ️ Team blocking info is included in task description, no JIRA links created")
            
            logger.debug(f"📊 Relationship creation summary for {task_key}: {relationships_created} custom links created")
            
        except Exception as e:
            logger.error(f"💥 Error creating relationships for task {task_key}: {str(e)}")
            logger.exception("Full exception details:")

    def _find_task_key_by_summary(self, task_summary: str) -> Optional[str]:
        """
        Find JIRA key for a task by its summary
        This is a helper method to resolve task dependencies
        """
        try:
            logger.debug(f"Looking for JIRA key for task summary: {task_summary}")
            
            # Check our mapping of summaries to keys built during creation
            if hasattr(self, '_task_summary_to_key') and task_summary in self._task_summary_to_key:
                task_key = self._task_summary_to_key[task_summary]
                logger.debug(f"Found task key in mapping: {task_summary} -> {task_key}")
                return task_key
            
            # If not found in mapping, try to search JIRA (fallback)
            logger.warning(f"Task key not found in mapping for: {task_summary}")
            
            # Note: JIRA search fallback could be implemented in the future
            # This would search for recently created tasks with matching summaries
            # For now, we rely on the mapping built during ticket creation
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding task key for summary '{task_summary}': {str(e)}")
            return None

    def _create_dependency_link(self, dependency_key: str, task_key: str) -> bool:
        """
        Create a dependency link between tasks with fallback options
        """
        try:
            # Try different link types in order of preference
            link_types_to_try = ["Blocks", "Depends", "Relates"]
            
            for link_type in link_types_to_try:
                logger.debug(f"Attempting to create {link_type} link: {dependency_key} -> {task_key}")
                success = self.jira_client.create_issue_link(
                    inward_key=dependency_key,
                    outward_key=task_key,
                    link_type=link_type
                )
                if success:
                    logger.info(f"✅ Created {link_type} link: {dependency_key} -> {task_key}")
                    return True
                else:
                    logger.warning(f"Failed to create {link_type} link, trying next option...")
            
            logger.error(f"❌ Failed to create any dependency link: {dependency_key} -> {task_key}")
            return False
            
        except Exception as e:
            logger.error(f"Error creating dependency link {dependency_key} -> {task_key}: {str(e)}")
            return False

    def _create_parent_child_link(self, parent_key: str, child_key: str) -> tuple[bool, str]:
        """
        Create a parent-child link with fallback options
        
        Returns:
            Tuple of (success, actual_link_type_used)
        """
        try:
            # Try different link types in order of preference
            # Note: "Work item split" is the correct JIRA link type name (not "Split from")
            link_types_to_try = ["Work item split", "Subtask", "Child", "Relates"]
            
            split_from_failed = False
            for i, link_type in enumerate(link_types_to_try):
                logger.debug(f"Attempting to create {link_type} link: {parent_key} -> {child_key}")
                success = self.jira_client.create_issue_link(
                    inward_key=parent_key,
                    outward_key=child_key,
                    link_type=link_type
                )
                if success:
                    logger.info(f"✅ Created {link_type} link: {parent_key} -> {child_key}")
                    return True, link_type
                else:
                    if link_type == "Work item split":
                        split_from_failed = True
                        logger.warning(f"🚨 Work item split link failed - checking available link types...")
                        # Get available link types for debugging
                        available_types = self.jira_client.get_available_link_types()
                        if available_types:
                            logger.info(f"🔍 Available link types check completed (see above)")
                        else:
                            logger.warning(f"⚠️ Could not retrieve available link types")
                    logger.warning(f"Failed to create {link_type} link, trying next option...")
            
            if split_from_failed:
                logger.error(f"💡 RECOMMENDATION: 'Work item split' link type failed.")
                logger.error(f"💡 Check JIRA Admin > System > Issue linking configuration")
            
            logger.error(f"❌ Failed to create any parent-child link: {parent_key} -> {child_key}")
            return False, "none"
            
        except Exception as e:
            logger.error(f"Error creating parent-child link {parent_key} -> {child_key}: {str(e)}")
            return False

    def _update_ticket_with_test_cases(self, ticket_key: str, test_cases: List[TestCase]):
        """Update JIRA ticket with test cases in description or custom field"""
        try:
            if not test_cases:
                return
            
            # Format test cases as plain text with clean Gherkin format
            test_cases_text = "TEST CASES\n" + "=" * 60 + "\n\n"
            
            for test_case in test_cases:
                test_cases_text += f"{test_case.title}\n"
                test_cases_text += "-" * len(test_case.title) + "\n\n"
                
                test_cases_text += f"Type: {test_case.type}\n\n"
                test_cases_text += f"Description:\n{test_case.description}\n\n"
                
                # Handle both 'steps' (legacy) and 'test_steps' (enhanced) fields
                steps_content = None
                if hasattr(test_case, 'test_steps') and test_case.test_steps:
                    steps_content = test_case.test_steps
                elif hasattr(test_case, 'steps') and test_case.steps:
                    steps_content = test_case.steps
                
                if steps_content:
                    test_cases_text += f"Test Steps:\n"
                    if isinstance(steps_content, list):
                        # Join list items as plain lines without numbering
                        for step in steps_content:
                            test_cases_text += f"{step}\n"
                    else:
                        # Format Gherkin steps without numbering - preserve clean format
                        lines = steps_content.split('\n')
                        for line in lines:
                            line = line.strip()
                            if line:
                                test_cases_text += f"{line}\n"
                    test_cases_text += "\n"
                
                test_cases_text += f"Expected Result:\n{test_case.expected_result}\n\n"
                
                if hasattr(test_case, 'priority') and test_case.priority:
                    test_cases_text += f"Priority: {test_case.priority}\n\n"
                
                if hasattr(test_case, 'source') and test_case.source:
                    test_cases_text += f"Source: {test_case.source}\n\n"
                
                test_cases_text += "=" * 60 + "\n\n"
            
            # Update the ticket using custom field (with fallback to description)
            success = self.jira_client.update_test_case_custom_field(ticket_key, test_cases_text)
            
            if success:
                logger.info(f"✅ Successfully updated {ticket_key} with test cases in custom field")
            else:
                logger.warning(f"⚠️ Failed to update {ticket_key} with test cases")
                
        except Exception as e:
            logger.error(f"Error updating ticket {ticket_key} with test cases: {str(e)}")

    def verify_test_case_integration(self, ticket_key: str) -> Dict[str, Any]:
        """Verify that test cases were properly added to a JIRA ticket"""
        try:
            ticket = self.jira_client.get_ticket(ticket_key)
            if not ticket:
                return {"success": False, "error": "Ticket not found"}
            
            fields = ticket.get('fields', {})
            
            # Check custom field first (preferred method)
            test_case_field_content = ""
            has_test_cases_in_custom_field = False
            
            if self.jira_client.test_case_custom_field:
                test_case_field_content = fields.get(self.jira_client.test_case_custom_field, '')
                if test_case_field_content:
                    has_test_cases_in_custom_field = "## Test Cases" in str(test_case_field_content)
            
            # Check description as fallback
            description = fields.get('description', '')
            description_text = ""
            has_test_cases_in_description = False
            
            if isinstance(description, dict):
                description_text = self._extract_text_from_adf(description)
            else:
                description_text = str(description) if description else ""
            
            has_test_cases_in_description = "## Test Cases" in description_text
            
            # Overall test case presence
            has_test_cases = has_test_cases_in_custom_field or has_test_cases_in_description
            
            return {
                "success": True,
                "ticket_key": ticket_key,
                "has_test_cases": has_test_cases,
                "test_cases_location": {
                    "custom_field": has_test_cases_in_custom_field,
                    "description": has_test_cases_in_description,
                    "custom_field_id": self.jira_client.test_case_custom_field
                },
                "custom_field_content_length": len(str(test_case_field_content)),
                "description_length": len(description_text),
                "custom_field_preview": str(test_case_field_content)[:200] if test_case_field_content else "",
                "description_preview": description_text[:200] if description_text else ""
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =============================================================================
    # BULK TICKET CREATION METHODS
    # =============================================================================
    
    def create_epic_structure(self, epic_plan: EpicPlan, dry_run: bool = True) -> Dict[str, Any]:
        """
        Create complete epic structure with stories and tasks
        
        Args:
            epic_plan: Complete epic plan with stories and tasks  
            dry_run: If True, simulate creation without actually creating tickets
            
        Returns:
            Creation results with ticket keys and any errors
        """
        logger.info(f"Creating epic structure for {epic_plan.epic_key} (dry_run={dry_run})")
        return self.bulk_creator.create_epic_structure(epic_plan, dry_run)
    
    def create_stories_for_epic(self, epic_key: str, stories: List[StoryPlan], dry_run: bool = True) -> Dict[str, Any]:
        """
        Create stories for an epic using bulk operations
        
        Args:
            epic_key: Parent epic key
            stories: List of story plans to create
            dry_run: If True, simulate creation
            
        Returns:
            Creation results
        """
        logger.info(f"Creating {len(stories)} stories for epic {epic_key} (dry_run={dry_run})")
        return self.bulk_creator.create_stories_only(epic_key, stories, dry_run)
    
    def create_tasks_for_stories(self, tasks: List[TaskPlan], story_keys: List[str], dry_run: bool = True) -> Dict[str, Any]:
        """
        Create tasks for existing stories using bulk operations
        
        Args:
            tasks: List of task plans to create
            story_keys: List of parent story keys
            dry_run: If True, simulate creation
            
        Returns:
            Creation results
        """
        logger.info(f"Creating {len(tasks)} tasks for {len(story_keys)} stories (dry_run={dry_run})")
        return self.bulk_creator.create_tasks_only(tasks, story_keys, dry_run)
    
    def execute_planning_with_creation(self, context: PlanningContext, create_tickets: bool = False) -> Dict[str, Any]:
        """
        Execute complete planning workflow and optionally create tickets
        
        Args:
            context: Planning context with epic key and options
            create_tickets: If True, actually create tickets in JIRA
            
        Returns:
            Combined planning and creation results
        """
        start_time = time.time()
        logger.info(f"Executing planning workflow for {context.epic_key} (create_tickets={create_tickets})")
        
        results = {
            "epic_key": context.epic_key,
            "create_tickets": create_tickets,
            "success": True,
            "planning_results": None,
            "creation_results": None,
            "errors": [],
            "execution_time_seconds": 0.0
        }
        
        try:
            # Step 1: Generate the epic plan
            planning_result = self.plan_epic_complete(context)
            results["planning_results"] = planning_result.dict()
            
            if not planning_result.success:
                results["success"] = False
                results["errors"].extend(planning_result.errors)
                return results
            
            # Step 2: Create tickets if requested
            if create_tickets and planning_result.epic_plan:
                creation_result = self.create_epic_structure(
                    planning_result.epic_plan, 
                    dry_run=not create_tickets
                )
                results["creation_results"] = creation_result
                
                if not creation_result["success"]:
                    results["success"] = False
                    results["errors"].extend(creation_result["errors"])
                    
                    # If creation failed, log rollback information
                    if creation_result.get("created_tickets"):
                        rollback_info = self.bulk_creator.rollback_creation(
                            creation_result["created_tickets"]
                        )
                        results["rollback_info"] = rollback_info
            
        except Exception as e:
            results["success"] = False
            results["errors"].append(f"Unexpected error in planning workflow: {str(e)}")
            logger.error(f"Error in planning workflow: {str(e)}")
        
        finally:
            results["execution_time_seconds"] = time.time() - start_time
            logger.info(f"Planning workflow completed in {results['execution_time_seconds']:.2f}s")
        
        return results
    
    def validate_epic_structure(self, epic_key: str) -> Dict[str, Any]:
        """
        Validate epic structure integrity
        
        Args:
            epic_key: Epic to validate
            
        Returns:
            Validation results
        """
        logger.info(f"Validating epic structure for {epic_key}")
        return self.jira_client.validate_ticket_relationships(epic_key)
    
    def generate_comprehensive_test_suite(self, epic_key: str, coverage_level: TestCoverageLevel = TestCoverageLevel.STANDARD) -> Dict[str, Any]:
        """
        Generate comprehensive test suites for all stories and tasks in an epic
        
        Args:
            epic_key: Epic to generate tests for
            coverage_level: Level of test coverage desired
            
        Returns:
            Test generation results with all test cases
        """
        logger.info(f"Generating comprehensive test suite for epic {epic_key} (coverage: {coverage_level.value})")
        
        start_time = time.time()
        results = {
            "success": False,
            "epic_key": epic_key,
            "coverage_level": coverage_level.value,
            "story_tests": {},
            "task_tests": {},
            "total_test_cases": 0,
            "test_statistics": {},
            "errors": [],
            "execution_time_seconds": 0
        }
        
        try:
            # Get epic structure
            epic_analysis = self.analysis_engine.analyze_epic_completeness(epic_key)
            
            if not epic_analysis["success"]:
                results["errors"].append("Failed to analyze epic structure")
                return results
            
            epic_info = epic_analysis["epic_info"]
            
            # Generate tests for stories
            story_tests = {}
            for story in epic_info.get("stories", []):
                try:
                    story_plan = self._convert_jira_story_to_plan(story)
                    if story_plan:
                        # Determine domain context from epic or story
                        domain_context = self._extract_domain_context(epic_info, story)
                        
                        test_cases = self.test_generator.generate_story_test_cases(
                            story=story_plan,
                            coverage_level=coverage_level,
                            domain_context=domain_context
                        )
                        
                        story_tests[story["key"]] = {
                            "story_summary": story.get("summary", ""),
                            "test_cases": [self._test_case_to_dict(tc) for tc in test_cases],
                            "test_count": len(test_cases),
                            "coverage_level": coverage_level.value
                        }
                        
                        logger.info(f"Generated {len(test_cases)} test cases for story {story['key']}")
                        
                except Exception as e:
                    logger.error(f"Error generating tests for story {story.get('key', 'unknown')}: {str(e)}")
                    results["errors"].append(f"Story {story.get('key', 'unknown')}: {str(e)}")
            
            # Generate tests for tasks
            task_tests = {}
            for story in epic_info.get("stories", []):
                for task in story.get("subtasks", []):
                    try:
                        task_plan = self._convert_jira_task_to_plan(task)
                        if task_plan:
                            # Determine technical context from task
                            technical_context = self._extract_technical_context(task)
                            
                            test_cases = self.test_generator.generate_task_test_cases(
                                task=task_plan,
                                coverage_level=coverage_level,
                                technical_context=technical_context
                            )
                            
                            task_tests[task["key"]] = {
                                "task_summary": task.get("summary", ""),
                                "parent_story": story["key"],
                                "test_cases": [self._test_case_to_dict(tc) for tc in test_cases],
                                "test_count": len(test_cases),
                                "coverage_level": coverage_level.value
                            }
                            
                            logger.info(f"Generated {len(test_cases)} test cases for task {task['key']}")
                            
                    except Exception as e:
                        logger.error(f"Error generating tests for task {task.get('key', 'unknown')}: {str(e)}")
                        results["errors"].append(f"Task {task.get('key', 'unknown')}: {str(e)}")
            
            # Calculate statistics
            total_story_tests = sum(data["test_count"] for data in story_tests.values())
            total_task_tests = sum(data["test_count"] for data in task_tests.values())
            total_tests = total_story_tests + total_task_tests
            
            # Compile results
            results.update({
                "success": True,
                "story_tests": story_tests,
                "task_tests": task_tests,
                "total_test_cases": total_tests,
                "test_statistics": {
                    "total_stories": len(story_tests),
                    "total_tasks": len(task_tests),
                    "total_story_tests": total_story_tests,
                    "total_task_tests": total_task_tests,
                    "average_tests_per_story": total_story_tests / len(story_tests) if story_tests else 0,
                    "average_tests_per_task": total_task_tests / len(task_tests) if task_tests else 0,
                    "coverage_level": coverage_level.value
                }
            })
            
            logger.info(f"Generated {total_tests} total test cases for epic {epic_key}")
            
        except Exception as e:
            results["success"] = False
            results["errors"].append(f"Unexpected error in test generation: {str(e)}")
            logger.error(f"Error in comprehensive test generation: {str(e)}")
        
        finally:
            results["execution_time_seconds"] = time.time() - start_time
            logger.info(f"Test generation completed in {results['execution_time_seconds']:.2f}s")
        
        return results
    
    def generate_story_tests(self, story_key: str, coverage_level: TestCoverageLevel = TestCoverageLevel.STANDARD) -> Dict[str, Any]:
        """
        Generate test cases for a specific story
        
        Args:
            story_key: JIRA story key
            coverage_level: Level of test coverage desired
            
        Returns:
            Test generation results for the story
        """
        logger.info(f"Generating tests for story {story_key} (coverage: {coverage_level.value})")
        
        start_time = time.time()
        results = {
            "success": False,
            "story_key": story_key,
            "coverage_level": coverage_level.value,
            "test_cases": [],
            "test_count": 0,
            "errors": [],
            "execution_time_seconds": 0
        }
        
        try:
            # Get story details from JIRA
            story_details = self.jira_client.get_ticket(story_key)
            
            if not story_details:
                results["errors"].append(f"Failed to retrieve story details: Story not found")
                return results
                
            # Wrap in expected format
            story_details = {"success": True, "issue": story_details}
            
            # Convert to story plan
            story_plan = self._convert_jira_story_to_plan(story_details["issue"])
            
            if not story_plan:
                results["errors"].append("Failed to convert JIRA story to story plan")
                return results
            
            # Determine domain context
            domain_context = self._extract_domain_context({}, story_details["issue"])
            
            # Generate test cases
            test_cases = self.test_generator.generate_story_test_cases(
                story=story_plan,
                coverage_level=coverage_level,
                domain_context=domain_context
            )
            
            # Compile results
            results.update({
                "success": True,
                "test_cases": [self._test_case_to_dict(tc) for tc in test_cases],
                "test_count": len(test_cases),
                "story_summary": story_plan.summary,
                "domain_context": domain_context
            })
            
            logger.info(f"Generated {len(test_cases)} test cases for story {story_key}")
            
            # ✅ CRITICAL: Update JIRA with the generated test cases
            if test_cases:
                logger.info(f"Updating JIRA story {story_key} with {len(test_cases)} generated test cases")
                self._update_ticket_with_test_cases(story_key, test_cases)
            
        except Exception as e:
            results["success"] = False
            results["errors"].append(f"Unexpected error: {str(e)}")
            logger.error(f"Error generating story tests: {str(e)}")
        
        finally:
            results["execution_time_seconds"] = time.time() - start_time
        
        return results
    
    def generate_task_tests(self, task_key: str, coverage_level: TestCoverageLevel = TestCoverageLevel.STANDARD) -> Dict[str, Any]:
        """
        Generate test cases for a specific task
        
        Args:
            task_key: JIRA task key
            coverage_level: Level of test coverage desired
            
        Returns:
            Test generation results for the task
        """
        logger.info(f"Generating tests for task {task_key} (coverage: {coverage_level.value})")
        
        start_time = time.time()
        results = {
            "success": False,
            "task_key": task_key,
            "coverage_level": coverage_level.value,
            "test_cases": [],
            "test_count": 0,
            "errors": [],
            "execution_time_seconds": 0
        }
        
        try:
            # Get task details from JIRA
            task_details = self.jira_client.get_ticket(task_key)
            
            if not task_details:
                results["errors"].append(f"Failed to retrieve task details: Task not found")
                return results
                
            # Wrap in expected format
            task_details = {"success": True, "issue": task_details}
            
            # Convert to task plan
            task_plan = self._convert_jira_task_to_plan(task_details["issue"])
            
            if not task_plan:
                results["errors"].append("Failed to convert JIRA task to task plan")
                return results
            
            # Determine technical context
            technical_context = self._extract_technical_context(task_details["issue"])
            
            # Generate test cases
            test_cases = self.test_generator.generate_task_test_cases(
                task=task_plan,
                coverage_level=coverage_level,
                technical_context=technical_context
            )
            
            # Compile results
            results.update({
                "success": True,
                "test_cases": [self._test_case_to_dict(tc) for tc in test_cases],
                "test_count": len(test_cases),
                "task_summary": task_plan.summary,
                "technical_context": technical_context
            })
            
            logger.info(f"Generated {len(test_cases)} test cases for task {task_key}")
            
            # ✅ CRITICAL: Update JIRA with the generated test cases
            if test_cases:
                logger.info(f"Updating JIRA task {task_key} with {len(test_cases)} generated test cases")
                self._update_ticket_with_test_cases(task_key, test_cases)
            
        except Exception as e:
            results["success"] = False
            results["errors"].append(f"Unexpected error: {str(e)}")
            logger.error(f"Error generating task tests: {str(e)}")
        
        finally:
            results["execution_time_seconds"] = time.time() - start_time
        
        return results
    
    def generate_context_aware_task_tests(self, 
                                        task_key: str, 
                                        coverage_level: TestCoverageLevel = TestCoverageLevel.STANDARD,
                                        technical_context: Optional[str] = None,
                                        include_documents: bool = True,
                                        custom_llm_client=None) -> Dict[str, Any]:
        """
        Generate context-aware test cases for a task with story and document context
        
        Args:
            task_key: JIRA task key
            coverage_level: Level of test coverage desired
            technical_context: Technical context for the task
            include_documents: Whether to include PRD/RFC context
            custom_llm_client: Custom LLM client if specified
            
        Returns:
            Enhanced test generation results with context information
        """
        logger.info(f"Generating context-aware tests for task {task_key} (coverage: {coverage_level.value})")
        
        start_time = time.time()
        results = {
            "success": False,
            "task_key": task_key,
            "coverage_level": coverage_level.value,
            "test_cases": [],
            "test_count": 0,
            "technical_context": technical_context,
            "story_context": None,
            "document_context": None,
            "context_sources": [],
            "errors": [],
            "execution_time_seconds": 0
        }
        
        try:
            # Create enhanced test generator with JIRA and Confluence clients
            from .enhanced_test_generator import EnhancedTestGenerator
            enhanced_generator = EnhancedTestGenerator(
                llm_client=custom_llm_client or self.llm_client,
                prompt_engine=self.prompt_engine,
                jira_client=self.jira_client,
                confluence_client=getattr(self, 'confluence_client', None)
            )
            
            # Generate context-aware test cases
            test_cases = enhanced_generator.generate_task_test_cases_with_story_context(
                task_key=task_key,
                coverage_level=coverage_level,
                technical_context=technical_context,
                include_documents=include_documents
            )
            
            # Get context information for response
            if hasattr(enhanced_generator, '_last_story_context'):
                results["story_context"] = enhanced_generator._last_story_context
                results["context_sources"].append("parent_story")
            
            if hasattr(enhanced_generator, '_last_document_context'):
                results["document_context"] = enhanced_generator._last_document_context
                if enhanced_generator._last_document_context and enhanced_generator._last_document_context.get('prd'):
                    results["context_sources"].append("prd")
                if enhanced_generator._last_document_context and enhanced_generator._last_document_context.get('rfc'):
                    results["context_sources"].append("rfc")
            
            # Compile results
            results.update({
                "success": True,
                "test_cases": [self._enhanced_test_case_to_dict(tc) for tc in test_cases],
                "test_count": len(test_cases)
            })
            
            logger.info(f"Generated {len(test_cases)} context-aware test cases for task {task_key}")
            
            # ✅ CRITICAL: Update JIRA with the generated test cases
            if test_cases:
                logger.info(f"Updating JIRA task {task_key} with {len(test_cases)} context-aware test cases")
                self._update_ticket_with_test_cases(task_key, test_cases)
            
        except Exception as e:
            results["success"] = False
            results["errors"].append(f"Context-aware test generation error: {str(e)}")
            logger.error(f"Error generating context-aware task tests: {str(e)}")
            
            # Fallback to regular task test generation
            try:
                logger.info("Falling back to regular task test generation")
                fallback_results = self.generate_task_tests(task_key, coverage_level)
                if fallback_results["success"]:
                    results.update({
                        "success": True,
                        "test_cases": fallback_results["test_cases"],
                        "test_count": fallback_results["test_count"],
                        "technical_context": fallback_results.get("technical_context")
                    })
                    results["context_sources"].append("fallback_generation")
                    results["errors"].append("Used fallback generation due to context retrieval issues")
            except Exception as fallback_e:
                results["errors"].append(f"Fallback generation also failed: {str(fallback_e)}")
        
        finally:
            results["execution_time_seconds"] = time.time() - start_time
        
        return results
    
    def _convert_jira_story_to_plan(self, jira_story: Dict[str, Any]) -> Optional[StoryPlan]:
        """Convert JIRA story data to StoryPlan object"""
        try:
            # Extract acceptance criteria from description or custom fields
            acceptance_criteria = self._extract_acceptance_criteria(jira_story)
            
            # Handle structured description (Atlassian Document Format)
            description_field = jira_story.get("description", "")
            if isinstance(description_field, dict):
                description = self._extract_text_from_adf(description_field)
            else:
                description = description_field or ''
            
            return StoryPlan(
                summary=jira_story.get("summary", ""),
                description=description,
                acceptance_criteria=acceptance_criteria,
                story_points=jira_story.get("story_points", 1)
            )
        except Exception as e:
            logger.error(f"Error converting JIRA story to plan: {str(e)}")
            return None
    
    def _convert_jira_task_to_plan(self, jira_task: Dict[str, Any]) -> Optional[TaskPlan]:
        """Convert JIRA task data to TaskPlan object"""
        try:
            # Extract task scopes from description
            scopes = self._extract_task_scopes(jira_task)
            
            return TaskPlan(
                summary=jira_task.get("summary", ""),
                purpose=jira_task.get("description", ""),
                scopes=scopes,
                expected_outcomes=[jira_task.get("summary", "")],
                estimated_hours=8  # Default estimate
            )
        except Exception as e:
            logger.error(f"Error converting JIRA task to plan: {str(e)}")
            return None
    
    def _extract_acceptance_criteria(self, jira_story: Dict[str, Any]) -> List[AcceptanceCriteria]:
        """Extract acceptance criteria from JIRA story"""
        try:
            description = jira_story.get("description", "")
            criteria = []
            
            # Look for Given/When/Then patterns in description
            lines = description.split('\n')
            current_criteria = {}
            
            for line in lines:
                line = line.strip()
                if line.lower().startswith("given"):
                    current_criteria["given"] = line[5:].strip()
                elif line.lower().startswith("when"):
                    current_criteria["when"] = line[4:].strip()
                elif line.lower().startswith("then"):
                    current_criteria["then"] = line[4:].strip()
                    
                    # Complete criteria found
                    if all(key in current_criteria for key in ["given", "when", "then"]):
                        criteria.append(AcceptanceCriteria(
                            scenario=f"Scenario {len(criteria) + 1}",
                            given=current_criteria["given"],
                            when=current_criteria["when"],
                            then=current_criteria["then"]
                        ))
                        current_criteria = {}
            
            # If no proper criteria found, create a default one
            if not criteria:
                criteria.append(AcceptanceCriteria(
                    scenario="Default scenario",
                    given="User accesses the system",
                    when="User performs the action",
                    then="Expected functionality works correctly"
                ))
            
            return criteria
            
        except Exception as e:
            logger.error(f"Error extracting acceptance criteria: {str(e)}")
            return []
    
    def _extract_task_scopes(self, jira_task: Dict[str, Any]) -> List[TaskScope]:
        """Extract task scopes from JIRA task"""
        try:
            description = jira_task.get("description", "")
            summary = jira_task.get("summary", "")
            
            # Create basic scope from summary
            scopes = [
                TaskScope(
                    description=summary,
                    deliverable=f"Implementation of {summary}",
                    category="implementation"
                )
            ]
            
            return scopes
            
        except Exception as e:
            logger.error(f"Error extracting task scopes: {str(e)}")
            return []
    
    def _extract_domain_context(self, epic_info: Dict[str, Any], story_info: Dict[str, Any]) -> Optional[str]:
        """Extract domain context from epic and story information"""
        try:
            # Look for domain keywords in epic and story descriptions
            text_to_analyze = f"{epic_info.get('summary', '')} {epic_info.get('description', '')} {story_info.get('summary', '')} {story_info.get('description', '')}"
            text_lower = text_to_analyze.lower()
            
            # Domain detection patterns
            domain_patterns = {
                "financial": ["payment", "money", "financial", "bank", "transaction", "billing"],
                "healthcare": ["health", "medical", "patient", "hipaa", "clinical"],
                "ecommerce": ["shop", "cart", "order", "product", "purchase", "ecommerce"],
                "security": ["auth", "security", "login", "permission", "encrypt"]
            }
            
            for domain, keywords in domain_patterns.items():
                if any(keyword in text_lower for keyword in keywords):
                    return domain
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting domain context: {str(e)}")
            return None
    
    def _extract_technical_context(self, task_info: Dict[str, Any]) -> Optional[str]:
        """Extract technical context from task information"""
        try:
            text_to_analyze = f"{task_info.get('summary', '')} {task_info.get('description', '')}"
            text_lower = text_to_analyze.lower()
            
            # Technical context detection patterns
            tech_patterns = {
                "api": ["api", "endpoint", "rest", "service", "request", "response"],
                "database": ["database", "sql", "table", "query", "data", "persistence"],
                "ui": ["ui", "interface", "frontend", "component", "view", "page"],
                "microservice": ["microservice", "service", "distributed", "communication"]
            }
            
            for tech_context, keywords in tech_patterns.items():
                if any(keyword in text_lower for keyword in keywords):
                    return tech_context
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting technical context: {str(e)}")
            return None
    
    def _test_case_to_dict(self, test_case: TestCase) -> Dict[str, Any]:
        """Convert TestCase object to dictionary"""
        return {
            "title": test_case.title,
            "type": test_case.type,
            "description": test_case.description,
            "expected_result": test_case.expected_result
        }
    
    def _enhanced_test_case_to_dict(self, test_case: TestCase) -> Dict[str, Any]:
        """Convert TestCase object to enhanced dictionary with all Gherkin fields"""
        result = {
            "title": test_case.title,
            "type": test_case.type,
            "description": test_case.description,
            "expected_result": test_case.expected_result
        }
        
        # Add optional fields if they exist
        if hasattr(test_case, 'priority') and test_case.priority:
            result["priority"] = test_case.priority
        else:
            result["priority"] = "P2"  # Default priority
            
        if hasattr(test_case, 'traceability') and test_case.traceability:
            result["traceability"] = test_case.traceability
        else:
            result["traceability"] = ""
            
        if hasattr(test_case, 'precondition') and test_case.precondition:
            result["precondition"] = test_case.precondition
        else:
            result["precondition"] = ""
            
        if hasattr(test_case, 'steps') and test_case.steps:
            # Convert steps list to formatted string
            if isinstance(test_case.steps, list):
                result["test_steps"] = '\n'.join(test_case.steps)
            else:
                result["test_steps"] = str(test_case.steps)
        else:
            # Try to extract Gherkin steps from description
            result["test_steps"] = self._extract_gherkin_steps(test_case.description)
        
        return result
    
    def _extract_gherkin_steps(self, description: str) -> str:
        """Extract or format Gherkin steps from test description"""
        try:
            # Look for existing Gherkin format
            if any(keyword in description.lower() for keyword in ['given', 'when', 'then', 'and']):
                return description
            
            # If no Gherkin format, create a simple one
            return f"Given the system is in the required state\nWhen {description}\nThen the expected result should be achieved"
        except Exception:
            return description
    
    def _extract_text_from_adf(self, adf_content: Dict[str, Any]) -> str:
        """Extract plain text from Atlassian Document Format (ADF) content"""
        try:
            if not isinstance(adf_content, dict):
                return str(adf_content)
            
            text_parts = []
            
            def extract_text_recursive(node):
                if isinstance(node, dict):
                    # Handle text nodes
                    if node.get('type') == 'text':
                        text_parts.append(node.get('text', ''))
                    # Handle other nodes with content
                    elif 'content' in node:
                        for child in node['content']:
                            extract_text_recursive(child)
                    # Handle nodes with text directly
                    elif 'text' in node:
                        text_parts.append(node['text'])
                elif isinstance(node, list):
                    for item in node:
                        extract_text_recursive(item)
                elif isinstance(node, str):
                    text_parts.append(node)
            
            extract_text_recursive(adf_content)
            return ' '.join(text_parts).strip()
            
        except Exception as e:
            logger.warning(f"Error extracting text from ADF content: {str(e)}")
            return str(adf_content)[:500]  # Fallback to truncated string representation
    
    # =============================================================================
    # ENHANCED TEST GENERATION INTEGRATION METHODS
    # =============================================================================
    
    def generate_test_cases_for_stories(self, 
                                      stories: List[StoryPlan], 
                                      coverage_level: TestCoverageLevel = TestCoverageLevel.STANDARD,
                                      include_in_story_objects: bool = True) -> Dict[str, List[TestCase]]:
        """
        Generate comprehensive test cases for a list of stories
        
        Args:
            stories: List of story plans to generate tests for
            coverage_level: Level of test coverage desired
            include_in_story_objects: Whether to add test cases directly to story objects
            
        Returns:
            Dictionary mapping story summaries to test cases
        """
        logger.info(f"Generating test cases for {len(stories)} stories (coverage: {coverage_level.value})")
        
        story_tests = {}
        
        for story in stories:
            try:
                # Generate test cases using enhanced test generator
                test_cases = self.test_generator.generate_story_test_cases(
                    story=story,
                    coverage_level=coverage_level,
                    domain_context=self._detect_domain_context(story)
                )
                
                story_tests[story.summary] = test_cases
                
                # Add test cases to story object if requested
                if include_in_story_objects:
                    story.test_cases = test_cases
                
                logger.info(f"Generated {len(test_cases)} test cases for story: {story.summary}")
                
            except Exception as e:
                logger.error(f"Error generating test cases for story {story.summary}: {str(e)}")
                story_tests[story.summary] = []
        
        return story_tests
    
    def generate_test_cases_for_tasks(self, 
                                    tasks: List[TaskPlan], 
                                    coverage_level: TestCoverageLevel = TestCoverageLevel.STANDARD,
                                    include_in_task_objects: bool = True,
                                    custom_llm_client: Optional['LLMClient'] = None) -> Dict[str, List[TestCase]]:
        """
        Generate comprehensive test cases for a list of tasks with enhanced context
        
        Args:
            tasks: List of task plans to generate tests for
            coverage_level: Level of test coverage desired
            include_in_task_objects: Whether to add test cases directly to task objects
            custom_llm_client: Optional custom LLM client to use for test generation
            
        Returns:
            Dictionary mapping task summaries to test cases
        """
        logger.info(f"Generating test cases for {len(tasks)} tasks (coverage: {coverage_level.value})")
        
        task_tests = {}
        
        for task in tasks:
            try:
                logger.info(f"Starting enhanced test generation for task: {task.summary}")
                
                # Use custom LLM client if provided, otherwise use default test generator
                if custom_llm_client:
                    logger.info(f"Using custom LLM client for test generation: {custom_llm_client}")
                    custom_test_generator = EnhancedTestGenerator(
                        custom_llm_client,
                        self.prompt_engine,
                        jira_client=self.jira_client,
                        confluence_client=self.confluence_client
                    )
                    test_cases = custom_test_generator.generate_task_test_cases(
                        task=task,
                        coverage_level=coverage_level,
                        technical_context=self._detect_technical_context(task)
                    )
                else:
                    # Generate test cases using default enhanced test generator with context
                    test_cases = self.test_generator.generate_task_test_cases(
                        task=task,
                        coverage_level=coverage_level,
                        technical_context=self._detect_technical_context(task)
                    )
                
                task_tests[task.summary] = test_cases
                
                # Add test cases to task object if requested
                if include_in_task_objects:
                    task.test_cases = test_cases
                    logger.info(f"Enhanced test cases set on task object for: {task.summary}")
                
                logger.info(f"Generated {len(test_cases)} enhanced test cases for task: {task.summary}")
                
            except Exception as e:
                import traceback
                logger.error(f"CRITICAL: Enhanced test generation failed for task {task.summary}: {str(e)}")
                logger.error(f"Full traceback: {traceback.format_exc()}")
                logger.error(f"Task will keep original basic test cases from TeamBasedTaskGenerator")
                # Don't modify task.test_cases on failure - keep original basic test cases
                task_tests[task.summary] = []
        
        return task_tests
    
    def generate_context_aware_task_tests(self,
                                        task_keys: List[str],
                                        coverage_level: TestCoverageLevel = TestCoverageLevel.STANDARD,
                                        include_documents: bool = True) -> Dict[str, Dict[str, Any]]:
        """
        Generate context-aware test cases for existing JIRA tasks using enhanced extraction
        
        Args:
            task_keys: List of JIRA task keys
            coverage_level: Level of test coverage desired
            include_documents: Whether to include PRD/RFC context
            
        Returns:
            Dictionary mapping task keys to test generation results
        """
        logger.info(f"Generating context-aware test cases for {len(task_keys)} tasks")
        
        results = {}
        
        for task_key in task_keys:
            try:
                # Use enhanced test generator with full story and document context
                test_cases = self.test_generator.generate_task_test_cases_with_story_context(
                    task_key=task_key,
                    coverage_level=coverage_level,
                    technical_context=None,  # Will be auto-detected
                    include_documents=include_documents
                )
                
                results[task_key] = {
                    "success": True,
                    "test_cases": test_cases,
                    "test_count": len(test_cases),
                    "coverage_level": coverage_level.value,
                    "has_document_context": include_documents
                }
                
                logger.info(f"Generated {len(test_cases)} context-aware test cases for task {task_key}")
                
            except Exception as e:
                logger.error(f"Error generating context-aware tests for task {task_key}: {str(e)}")
                results[task_key] = {
                    "success": False,
                    "error": str(e),
                    "test_cases": [],
                    "test_count": 0
                }
        
        return results
    
    def plan_epic_with_test_generation(self, 
                                     context: PlanningContext,
                                     generate_story_tests: bool = True,
                                     generate_task_tests: bool = True,
                                     test_coverage_level: TestCoverageLevel = TestCoverageLevel.STANDARD) -> PlanningResult:
        """
        Complete epic planning with automatic test case generation
        
        Args:
            context: Planning context with epic key and options
            generate_story_tests: Whether to generate test cases for stories
            generate_task_tests: Whether to generate test cases for tasks
            test_coverage_level: Level of test coverage for generated tests
            
        Returns:
            PlanningResult with generated plan including test cases
        """
        logger.info(f"Planning epic {context.epic_key} with test generation (stories: {generate_story_tests}, tasks: {generate_task_tests})")
        
        start_time = time.time()
        
        try:
            # Step 1: Generate basic epic plan
            basic_result = self.plan_epic_complete(context)
            
            if not basic_result.success or not basic_result.epic_plan:
                logger.error("Basic epic planning failed, cannot generate tests")
                return basic_result
            
            # Step 2: Generate test cases for stories if requested
            if generate_story_tests and basic_result.epic_plan.stories:
                logger.info("Generating test cases for stories...")
                story_tests = self.generate_test_cases_for_stories(
                    stories=basic_result.epic_plan.stories,
                    coverage_level=test_coverage_level,
                    include_in_story_objects=True
                )
                
                # Add test generation summary to result
                basic_result.summary_stats["story_tests"] = {
                    "total_stories_with_tests": len([s for s in story_tests.values() if s]),
                    "total_story_test_cases": sum(len(tests) for tests in story_tests.values()),
                    "coverage_level": test_coverage_level.value
                }
            
            # Step 3: Generate test cases for tasks if requested
            if generate_task_tests and basic_result.epic_plan.stories:
                logger.info("Generating test cases for tasks...")
                all_tasks = []
                for story in basic_result.epic_plan.stories:
                    all_tasks.extend(story.tasks or [])
                
                if all_tasks:
                    task_tests = self.generate_test_cases_for_tasks(
                        tasks=all_tasks,
                        coverage_level=test_coverage_level,
                        include_in_task_objects=True
                    )
                    
                    # Add test generation summary to result
                    basic_result.summary_stats["task_tests"] = {
                        "total_tasks_with_tests": len([t for t in task_tests.values() if t]),
                        "total_task_test_cases": sum(len(tests) for tests in task_tests.values()),
                        "coverage_level": test_coverage_level.value
                    }
            
            # Update execution time
            basic_result.execution_time_seconds = time.time() - start_time
            
            logger.info(f"Epic planning with test generation completed for {context.epic_key}")
            return basic_result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Error in epic planning with test generation: {str(e)}")
            
            return PlanningResult(
                epic_key=context.epic_key,
                mode=context.mode,
                success=False,
                errors=[f"Epic planning with test generation failed: {str(e)}"],
                execution_time_seconds=execution_time
            )
    
    def _detect_domain_context(self, story: StoryPlan) -> Optional[str]:
        """Detect domain context from story content"""
        try:
            text_to_analyze = f"{story.summary} {story.description}".lower()
            
            domain_patterns = {
                "financial": ["payment", "money", "financial", "bank", "transaction", "billing", "invoice"],
                "healthcare": ["health", "medical", "patient", "hipaa", "clinical", "treatment"],
                "ecommerce": ["shop", "cart", "order", "product", "purchase", "inventory", "catalog"],
                "security": ["auth", "security", "login", "permission", "encrypt", "access", "token"],
                "api": ["api", "endpoint", "service", "integration", "webhook", "rest"]
            }
            
            for domain, keywords in domain_patterns.items():
                if any(keyword in text_to_analyze for keyword in keywords):
                    return domain
            
            return None
            
        except Exception as e:
            logger.warning(f"Error detecting domain context: {str(e)}")
            return None
    
    def _detect_technical_context(self, task: TaskPlan) -> Optional[str]:
        """Detect technical context from task content"""
        try:
            text_to_analyze = f"{task.summary} {task.purpose}".lower()
            
            tech_patterns = {
                "api": ["api", "endpoint", "rest", "service", "request", "response", "integration"],
                "database": ["database", "sql", "table", "query", "data", "persistence", "migration"],
                "ui": ["ui", "frontend", "interface", "component", "view", "page", "react", "angular"],
                "backend": ["backend", "server", "business logic", "processing", "validation"],
                "microservice": ["microservice", "service", "distributed", "communication", "messaging"]
            }
            
            for tech_context, keywords in tech_patterns.items():
                if any(keyword in text_to_analyze for keyword in keywords):
                    return tech_context
            
            return None
            
        except Exception as e:
            logger.warning(f"Error detecting technical context: {str(e)}")
            return None
    
    def sync_stories_from_prd_table(self, epic_key: str, prd_content: Dict[str, Any],
                                    existing_ticket_action: str = "skip", dry_run: bool = False) -> 'PlanningResult':
        """
        Sync stories from PRD table to JIRA
        
        Args:
            epic_key: Epic key to associate stories with
            prd_content: PRD page data from Confluence
            existing_ticket_action: Action for existing tickets: "skip", "update", or "error"
            
        Returns:
            PlanningResult with synced stories
        """
        import time
        from .planning_models import PlanningResult, OperationMode, EpicPlan
        from .prd_story_parser import PRDStoryParser
        
        start_time = time.time()
        logger.info(f"Syncing stories from PRD table for epic {epic_key}")
        
        try:
            # Parse stories from PRD table
            parser = PRDStoryParser()
            stories = parser.parse_stories_from_prd_content(prd_content, epic_key)
            
            if not stories:
                logger.warning(f"No stories parsed from PRD content for epic {epic_key}")
                # Debug: Check if PRD content has body structure
                has_body = 'body' in prd_content
                has_storage = prd_content.get('body', {}).get('storage', {}) if has_body else {}
                has_value = 'value' in has_storage if has_storage else False
                logger.debug(f"PRD content structure - has_body: {has_body}, has_storage: {bool(has_storage)}, has_value: {has_value}")
                return PlanningResult(
                    epic_key=epic_key,
                    mode=OperationMode.PLANNING,
                    success=False,
                    errors=["No stories found in PRD table"],
                    execution_time_seconds=time.time() - start_time
                )
            
            logger.info(f"Parsed {len(stories)} stories from PRD table")
            
            # Check for existing tickets
            existing_stories = self._get_epic_stories(epic_key)
            existing_story_titles = {}
            
            if existing_stories:
                for story_key in existing_stories:
                    try:
                        story_data = self.jira_client.get_ticket(story_key)
                        if story_data:
                            title = story_data.get('fields', {}).get('summary', '')
                            existing_story_titles[title.lower()] = story_key
                    except Exception as e:
                        logger.warning(f"Error getting existing story {story_key}: {e}")
            
            # Filter stories based on existing_ticket_action
            stories_to_create = []
            stories_to_update = []
            skipped_stories = []
            
            for story in stories:
                story_title_lower = story.summary.lower()
                if story_title_lower in existing_story_titles:
                    existing_key = existing_story_titles[story_title_lower]
                    
                    if existing_ticket_action == "error":
                        return PlanningResult(
                            epic_key=epic_key,
                            mode=OperationMode.PLANNING,
                            success=False,
                            errors=[f"Story '{story.summary}' already exists as {existing_key}"],
                            execution_time_seconds=time.time() - start_time
                        )
                    elif existing_ticket_action == "update":
                        story.key = existing_key
                        stories_to_update.append(story)
                    else:  # skip
                        skipped_stories.append(story.summary)
                else:
                    stories_to_create.append(story)
            
            # Create/update stories (only if not dry run)
            created_tickets = {"stories": []}
            
            if not dry_run:
                if stories_to_create:
                    created = self._create_story_tickets(stories_to_create)
                    created_tickets["stories"].extend(created.get("stories", []))
                
                if stories_to_update:
                    for story in stories_to_update:
                        try:
                            self._update_story_ticket(story)
                            created_tickets["stories"].append(story.key)
                        except Exception as e:
                            logger.error(f"Error updating story {story.key}: {e}")
            
            # Build epic plan with all stories (including skipped ones for display)
            # The 'stories' variable contains all parsed stories, regardless of whether they're created/updated/skipped
            # This ensures story_details will show all stories from the PRD
            logger.info(f"Building epic plan with {len(stories)} stories (total parsed: {len(stories_to_create)} to create, {len(stories_to_update)} to update, {len(skipped_stories)} skipped)")
            
            # Ensure we're using the original stories list (all parsed stories)
            if not stories:
                logger.warning(f"No stories available for epic plan, but {len(stories_to_create) + len(stories_to_update) + len(skipped_stories)} were processed")
            
            epic_plan = EpicPlan(
                epic_key=epic_key,
                epic_title=f"Epic {epic_key}",
                stories=stories  # All parsed stories, regardless of action taken
            )
            
            # Verify epic_plan was created with stories
            if epic_plan.stories:
                logger.info(f"Epic plan created successfully with {len(epic_plan.stories)} stories")
            else:
                logger.warning(f"Epic plan created but has no stories! Original stories count: {len(stories)}")
            
            execution_time = time.time() - start_time
            
            warnings = []
            if skipped_stories:
                warnings.append(f"Skipped {len(skipped_stories)} existing stories: {', '.join(skipped_stories[:5])}")
            
            return PlanningResult(
                epic_key=epic_key,
                mode=OperationMode.PLANNING,
                success=True,
                created_tickets=created_tickets,
                epic_plan=epic_plan,
                warnings=warnings,
                execution_time_seconds=execution_time
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Error syncing stories from PRD for {epic_key}: {str(e)}")
            return PlanningResult(
                epic_key=epic_key,
                mode=OperationMode.PLANNING,
                success=False,
                errors=[str(e)],
                execution_time_seconds=execution_time
            )
    
    def _get_epic_stories(self, epic_key: str) -> List[str]:
        """Get all stories linked to an epic"""
        try:
            jql = f'"Epic Link" = {epic_key} AND issuetype = Story'
            issues = self.jira_client.jira.search_issues(jql, maxResults=1000)
            return [issue.key for issue in issues]
        except Exception as e:
            logger.warning(f"Error getting stories for epic {epic_key}: {str(e)}")
            return []
    
    def _update_story_ticket(self, story: 'StoryPlan'):
        """Update an existing story ticket"""
        if not story.key:
            raise ValueError("Story key is required for update")
        
        logger.info(f"Updating story ticket {story.key}")
        
        # Update description
        description_adf = story.format_description_for_jira_adf()
        
        update_data = {
            "fields": {
                "description": description_adf
            }
        }
        
        self.jira_client.jira.update_issue(story.key, update_data)
        logger.info(f"Updated story ticket {story.key}")