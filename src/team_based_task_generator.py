"""
Team-Based Task Generation Engine
Intelligently separates tasks between Backend, Frontend, and QA teams
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum

from .planning_models import (
    StoryPlan, TaskPlan, TaskScope, TaskTeam, CycleTimeEstimate, TestCase,
    AcceptanceCriteria
)
from .planning_prompt_engine import PlanningPromptEngine
from .llm_client import LLMClient
from .prompts import Prompts

# Import for test coverage levels
try:
    from .enhanced_test_generator import TestCoverageLevel
except ImportError:
    # Fallback enum if enhanced_test_generator is not available
    class TestCoverageLevel(str, Enum):
        BASIC = "basic"
        STANDARD = "standard"
        COMPREHENSIVE = "comprehensive"
        MINIMAL = "minimal"

logger = logging.getLogger(__name__)


class StoryType(str, Enum):
    """Types of user stories for task categorization"""
    API_FEATURE = "api_feature"           # Backend-heavy API development
    UI_FEATURE = "ui_feature"             # Frontend-heavy UI development  
    DATA_FEATURE = "data_feature"         # Backend-heavy data processing
    INTEGRATION = "integration"           # Mixed Backend/Frontend integration
    ADMIN_FEATURE = "admin_feature"       # Mixed admin functionality
    USER_WORKFLOW = "user_workflow"       # Mixed user journey
    CONFIGURATION = "configuration"       # Backend configuration
    REPORTING = "reporting"               # Mixed reporting features


class TeamBasedTaskGenerator:
    """
    Enhanced task generator that intelligently separates tasks by team responsibilities
    """
    
    def __init__(self, llm_client: LLMClient, prompt_engine: PlanningPromptEngine):
        self.llm_client = llm_client
        self.prompt_engine = prompt_engine
        self.task_patterns = self._initialize_task_patterns()
        self.team_responsibilities = self._initialize_team_responsibilities()
    
    def generate_team_separated_tasks(self, 
                                    story: StoryPlan,
                                    max_cycle_days: int = 3,
                                    force_separation: bool = True,
                                    prd_content: Optional[Dict[str, Any]] = None,
                                    rfc_content: Optional[Dict[str, Any]] = None,
                                    additional_context: Optional[str] = None) -> List[TaskPlan]:
        """
        Generate tasks with proper Backend/Frontend/QA separation
        
        Args:
            story: Story to break down into tasks
            max_cycle_days: Maximum days per task
            force_separation: Whether to force 3-team separation
            prd_content: Optional PRD document content
            rfc_content: Optional RFC document content
            additional_context: Optional additional context to guide generation
            
        Returns:
            List of tasks properly assigned to teams
        """
        logger.info(f"Generating team-separated tasks for story: {story.summary}")
        
        try:
            # 1. Analyze story type and complexity
            story_type = self._analyze_story_type(story)
            complexity_analysis = self._analyze_story_complexity(story)
            
            # 2. Generate AI-powered task breakdown with team awareness
            ai_tasks = self._generate_ai_team_tasks(
                story, story_type, max_cycle_days,
                prd_content, rfc_content, additional_context
            )
            logger.info(f"DEBUG: AI generated {len(ai_tasks)} tasks")
            
            # If AI generation is successful, use only AI tasks (no need for pattern fallback)
            if ai_tasks:
                logger.info("DEBUG: AI generation successful - skipping pattern generation")
                # Tag AI tasks to skip validation splitting
                for task in ai_tasks:
                    task._ai_generated = True
                    
                all_tasks = ai_tasks
            else:
                logger.info("DEBUG: AI generation failed - using pattern generation as fallback")
                # 3. Generate pattern-based tasks as fallback
                pattern_tasks = self._generate_pattern_team_tasks(story, story_type, complexity_analysis)
                logger.info(f"DEBUG: Pattern generated {len(pattern_tasks)} tasks")
                all_tasks = pattern_tasks
            
            logger.info(f"DEBUG: Using {len(all_tasks)} tasks (AI: {len(ai_tasks) > 0}, Pattern: {len(ai_tasks) == 0})")
            
            # 4. Ensure proper team distribution (if needed)
            if force_separation:
                all_tasks = self._ensure_team_separation(all_tasks, story, story_type)
                logger.info(f"DEBUG: After team separation: {len(all_tasks)} tasks")
            
            # 5. Validate cycle times and split if needed (AI tasks will skip splitting)
            validated_tasks = self._validate_and_split_tasks(all_tasks, max_cycle_days)
            logger.info(f"DEBUG: After validation: {len(validated_tasks)} tasks")
            
            # 6. Analyze and set up task dependencies
            dependent_tasks = self._analyze_task_dependencies(validated_tasks)
            logger.info(f"DEBUG: Final task count: {len(dependent_tasks)} tasks")
            
            logger.info(f"Generated {len(dependent_tasks)} team-separated tasks: "
                       f"Backend: {len([t for t in dependent_tasks if t.team == TaskTeam.BACKEND])}, "
                       f"Frontend: {len([t for t in dependent_tasks if t.team == TaskTeam.FRONTEND])}, "
                       f"QA: {len([t for t in dependent_tasks if t.team == TaskTeam.QA])}")
            
            return dependent_tasks
            
        except Exception as e:
            logger.error(f"Error in team-separated task generation: {str(e)}")
            # Fallback to basic pattern-based generation
            return self._generate_fallback_team_tasks(story)
    
    def generate_team_separated_tasks_with_tests(self, 
                                               story: StoryPlan,
                                               max_cycle_days: int = 3,
                                               test_coverage_level: TestCoverageLevel = TestCoverageLevel.STANDARD,
                                               force_separation: bool = True,
                                               prd_content: Optional[Dict[str, Any]] = None,
                                               rfc_content: Optional[Dict[str, Any]] = None,
                                               additional_context: Optional[str] = None) -> List[TaskPlan]:
        """
        Generate tasks with embedded test cases - unified generation approach
        
        Args:
            story: Story to break down into tasks
            max_cycle_days: Maximum days per task
            test_coverage_level: Level of test coverage for generated test cases
            force_separation: Whether to force 3-team separation
            prd_content: Optional PRD document content
            rfc_content: Optional RFC document content
            additional_context: Optional additional context to guide generation
            
        Returns:
            List of tasks with embedded test cases
        """
        logger.info(f"Generating unified tasks with tests for story: {story.summary} (coverage: {test_coverage_level.value})")
        
        try:
            # 1. Analyze story type and complexity
            story_type = self._analyze_story_type(story)
            
            # 2. Generate AI-powered tasks with embedded test cases
            ai_tasks_with_tests = self._generate_ai_tasks_with_tests(
                story, story_type, max_cycle_days, test_coverage_level,
                prd_content, rfc_content, additional_context
            )
            
            if ai_tasks_with_tests:
                logger.info(f"Unified generation successful - generated {len(ai_tasks_with_tests)} tasks with embedded tests")
                # Tag AI tasks to skip validation splitting
                for task in ai_tasks_with_tests:
                    task._ai_generated = True
                    
                all_tasks = ai_tasks_with_tests
            else:
                logger.info("Unified generation failed - falling back to separate generation")
                # Fallback: Generate tasks first, then add tests separately
                all_tasks = self.generate_team_separated_tasks(
                    story, max_cycle_days, force_separation,
                    prd_content, rfc_content, additional_context
                )
                # Add test cases using fallback method
                for task in all_tasks:
                    task.test_cases = self._generate_fallback_task_tests(task, test_coverage_level)
            
            # 3. Ensure proper team distribution if needed
            if force_separation:
                all_tasks = self._ensure_team_separation(all_tasks, story, story_type)
            
            # 4. Validate and set up dependencies
            validated_tasks = self._validate_and_split_tasks(all_tasks, max_cycle_days)
            dependent_tasks = self._analyze_task_dependencies(validated_tasks)
            
            logger.info(f"Generated {len(dependent_tasks)} unified tasks with tests: "
                       f"Backend: {len([t for t in dependent_tasks if t.team == TaskTeam.BACKEND])}, "
                       f"Frontend: {len([t for t in dependent_tasks if t.team == TaskTeam.FRONTEND])}, "
                       f"QA: {len([t for t in dependent_tasks if t.team == TaskTeam.QA])}")
            
            return dependent_tasks
            
        except Exception as e:
            logger.error(f"Error in unified task+test generation: {str(e)}")
            # Double fallback: Use existing method and add minimal tests
            fallback_tasks = self._generate_fallback_team_tasks(story)
            for task in fallback_tasks:
                task.test_cases = self._generate_minimal_task_tests(task)
            return fallback_tasks
    
    def _analyze_story_type(self, story: StoryPlan) -> StoryType:
        """Analyze story to determine its primary type for task categorization"""
        text_to_analyze = f"{story.summary} {story.description}".lower()
        
        # Data-focused patterns (check first to avoid false API matches)
        if any(keyword in text_to_analyze for keyword in ['analytics', 'processing pipeline', 'data processing', 'migration', 'import', 'export']):
            return StoryType.DATA_FEATURE
            
        # API-focused patterns
        elif any(keyword in text_to_analyze for keyword in ['api', 'endpoint', 'service', 'backend', 'database']):
            return StoryType.API_FEATURE
            
        # UI-focused patterns
        elif any(keyword in text_to_analyze for keyword in ['ui', 'interface', 'component', 'page', 'view', 'frontend', 'user interface']):
            return StoryType.UI_FEATURE
            
        # Integration patterns
        elif any(keyword in text_to_analyze for keyword in ['integration', 'connect', 'sync', 'third-party', 'external']):
            return StoryType.INTEGRATION
            
        # Admin patterns
        elif any(keyword in text_to_analyze for keyword in ['admin', 'configuration', 'settings', 'management']):
            return StoryType.ADMIN_FEATURE
            
        # Reporting patterns
        elif any(keyword in text_to_analyze for keyword in ['report', 'dashboard', 'analytics', 'metrics']):
            return StoryType.REPORTING
            
        # Default to user workflow for mixed stories
        else:
            return StoryType.USER_WORKFLOW
    
    def _analyze_story_complexity(self, story: StoryPlan) -> Dict[str, str]:
        """Analyze complexity dimensions of the story"""
        # Count acceptance criteria as complexity indicator
        criteria_count = len(story.acceptance_criteria)
        
        # Analyze text complexity
        text_length = len(f"{story.summary} {story.description}")
        
        # Determine complexity levels
        ui_complexity = "high" if criteria_count > 3 or "complex" in story.description.lower() else "medium" if criteria_count > 1 else "low"
        backend_complexity = "high" if "database" in story.description.lower() or "integration" in story.description.lower() else "medium"
        qa_complexity = "high" if criteria_count > 3 else "medium" if criteria_count > 1 else "low"
        
        return {
            "ui_complexity": ui_complexity,
            "backend_complexity": backend_complexity,
            "qa_complexity": qa_complexity,
            "overall_complexity": "high" if criteria_count > 3 or text_length > 500 else "medium"
        }
    
    def _generate_ai_team_tasks(self, 
                              story: StoryPlan, 
                              story_type: StoryType,
                              max_cycle_days: int,
                              prd_content: Optional[Dict[str, Any]] = None,
                              rfc_content: Optional[Dict[str, Any]] = None,
                              additional_context: Optional[str] = None) -> List[TaskPlan]:
        """Generate tasks using AI with team-awareness"""
        try:
            # Create team-aware prompt
            prompt = self._create_team_separation_prompt(
                story, story_type, max_cycle_days,
                prd_content, rfc_content, additional_context
            )
            
            # DEBUG: Log the prompt being sent to LLM
            logger.info("=" * 80)
            logger.info("DEBUG: PROMPT SENT TO LLM FOR TASK GENERATION")
            logger.info("=" * 80)
            logger.info(prompt)
            logger.info("=" * 80)
            
            # Generate using LLM with enforced JSON mode
            # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
            response = self.llm_client.generate_content_json(
                prompt=prompt,
                system_prompt=Prompts.get_team_task_system_prompt(),
                max_tokens=None
            )
            
            # DEBUG: Log the response from LLM
            logger.info("=" * 80)
            logger.info("DEBUG: RESPONSE FROM LLM FOR TASK GENERATION")
            logger.info("=" * 80)
            logger.info(response)
            logger.info("=" * 80)
            
            # Parse response into team-assigned tasks
            parsed_tasks = self._parse_team_task_response(response, story)
            
            if not parsed_tasks:
                logger.error("DEBUG: AI task parsing returned empty list - falling back to pattern generation")
                return []
            
            logger.info(f"DEBUG: AI generation successful - returning {len(parsed_tasks)} tasks")
            return parsed_tasks
            
        except Exception as e:
            logger.error(f"DEBUG: AI team task generation failed with exception: {str(e)}")
            logger.error(f"DEBUG: Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"DEBUG: Full traceback: {traceback.format_exc()}")
            return []
    
    def _create_team_separation_prompt(self, 
                                     story: StoryPlan, 
                                     story_type: StoryType,
                                     max_cycle_days: int,
                                     prd_content: Optional[Dict[str, Any]] = None,
                                     rfc_content: Optional[Dict[str, Any]] = None,
                                     additional_context: Optional[str] = None) -> str:
        """Create AI prompt for team-separated task generation"""
        acceptance_criteria_text = [ac.format_gwt() for ac in story.acceptance_criteria]
        
        # Get centralized template and format it
        template = Prompts.get_team_separation_prompt_template()
        document_context = self._format_document_context(prd_content, rfc_content, story_type) if prd_content or rfc_content else ""
        additional_context_str = self._format_additional_context(additional_context) if additional_context else ""
        
        prompt = template.format(
            story_summary=story.summary,
            story_description=story.description,
            story_type=story_type.value,
            max_cycle_days=max_cycle_days,
            acceptance_criteria=chr(10).join(acceptance_criteria_text),
            document_context=document_context,
            additional_context=additional_context_str
        )
        
        return prompt
    
    def _parse_team_task_response(self, response: str, story: StoryPlan) -> List[TaskPlan]:
        """Parse AI JSON response into team-assigned TaskPlan objects"""
        try:
            import json
            
            logger.info(f"DEBUG: Starting JSON parsing, response length: {len(response)}")
            
            # Clean the response to extract JSON
            cleaned_response = response.strip()
            
            # Handle cases where LLM adds extra text before/after JSON
            start_idx = cleaned_response.find('[')
            end_idx = cleaned_response.rfind(']')
            
            if start_idx == -1 or end_idx == -1:
                logger.error("DEBUG: No JSON array found in LLM response")
                logger.error(f"DEBUG: Response preview: {response[:200]}...")
                return []
            
            json_str = cleaned_response[start_idx:end_idx + 1]
            logger.info(f"DEBUG: Extracted JSON string length: {len(json_str)}")
            logger.info(f"DEBUG: JSON preview: {json_str[:200]}...")
            
            # Parse JSON
            task_data = json.loads(json_str)
            logger.info(f"DEBUG: Successfully parsed JSON, got {len(task_data)} items")
            
            if not isinstance(task_data, list):
                logger.error("DEBUG: LLM response is not a JSON array")
                return []
            
            tasks = []
            for i, task_dict in enumerate(task_data):
                if not isinstance(task_dict, dict):
                    logger.warning(f"DEBUG: Item {i} is not a dict: {type(task_dict)}")
                    continue
                    
                logger.info(f"DEBUG: Processing task {i}: {task_dict.get('title', 'NO_TITLE')}")
                
                # Map team string to TaskTeam enum
                team_str = task_dict.get('team', '').lower()
                if 'backend' in team_str:
                    team = TaskTeam.BACKEND
                elif 'frontend' in team_str:
                    team = TaskTeam.FRONTEND
                elif 'qa' in team_str:
                    team = TaskTeam.QA
                else:
                    logger.warning(f"DEBUG: Unknown team: {task_dict.get('team')}, defaulting to Backend")
                    team = TaskTeam.BACKEND
                
                # Create task plan from JSON data
                task_plan = self._create_task_plan_from_json(task_dict, team, story)
                if task_plan:
                    tasks.append(task_plan)
                    logger.info(f"DEBUG: Successfully created task: {task_plan.summary}")
                else:
                    logger.error(f"DEBUG: Failed to create task plan for item {i}")
            
            logger.info(f"DEBUG: Successfully parsed {len(tasks)} tasks from JSON response")
            return tasks
            
        except json.JSONDecodeError as e:
            logger.error(f"DEBUG: JSON parsing error: {str(e)}")
            logger.error(f"DEBUG: Response was: {response[:500]}...")
            return []
        except Exception as e:
            logger.error(f"DEBUG: Error parsing team task JSON response: {str(e)}")
            logger.error(f"DEBUG: Response was: {response[:500]}...")
            return []
    
    def _create_task_plan_from_json(self, task_dict: Dict[str, Any], team: TaskTeam, story: StoryPlan) -> Optional[TaskPlan]:
        """Create TaskPlan from JSON dictionary"""
        try:
            title = task_dict.get('title', f"{team.value.title()} Task")
            purpose = task_dict.get('purpose', f"Support {team.value} implementation")
            scope_description = task_dict.get('scope', f"Implement {title}")
            expected_outcome = task_dict.get('expected_outcome', 'Task completed successfully')
            
            # Parse AI-generated dependencies
            depends_on_tasks = task_dict.get('depends_on_tasks', [])
            if isinstance(depends_on_tasks, str):
                # Handle case where AI returns string instead of array
                depends_on_tasks = [dep.strip() for dep in depends_on_tasks.split(',') if dep.strip() and dep.strip().lower() != 'none']
            elif not isinstance(depends_on_tasks, list):
                depends_on_tasks = []
            
            blocked_by_teams = task_dict.get('blocked_by_teams', [])
            if isinstance(blocked_by_teams, str):
                # Handle case where AI returns string instead of array
                blocked_by_teams = [team.strip() for team in blocked_by_teams.split(',') if team.strip() and team.strip().lower() != 'none']
            elif not isinstance(blocked_by_teams, list):
                blocked_by_teams = []
            
            # Convert team names to TaskTeam enums
            blocked_by_team_enums = []
            for team_name in blocked_by_teams:
                team_lower = team_name.lower()
                if 'backend' in team_lower:
                    blocked_by_team_enums.append(TaskTeam.BACKEND)
                elif 'frontend' in team_lower:
                    blocked_by_team_enums.append(TaskTeam.FRONTEND)
                elif 'qa' in team_lower:
                    blocked_by_team_enums.append(TaskTeam.QA)
            
            logger.info(f"DEBUG: Task '{title}' depends on: {depends_on_tasks}, blocked by teams: {blocked_by_teams}")
            
            # Create task scope
            scope = TaskScope(
                description=scope_description,
                complexity="medium",
                dependencies=[],
                deliverable=expected_outcome
            )
            
            # Create cycle time estimate based on team
            cycle_estimate = self._estimate_cycle_time_by_team(team, scope_description)
            
            # Create test cases based on team
            test_cases = self._generate_team_test_cases(team, title)
            
            import uuid
            return TaskPlan(
                task_id=str(uuid.uuid4()),  # Generate stable identifier for dependency resolution
                summary=title,
                purpose=purpose,
                scopes=[scope],
                expected_outcomes=[expected_outcome],
                team=team,
                test_cases=test_cases,
                cycle_time_estimate=cycle_estimate,
                epic_key=story.epic_key,
                story_key=getattr(story, 'key', None),
                depends_on_tasks=depends_on_tasks,  # Store AI-generated dependencies (summary strings, will be resolved later)
                blocked_by_teams=blocked_by_team_enums  # Store AI-generated team blocks
            )
            
        except Exception as e:
            logger.error(f"Error creating TaskPlan from JSON: {str(e)}")
            return None

    def _create_task_plan_from_dict(self, task_dict: Dict[str, Any], story: StoryPlan) -> Optional[TaskPlan]:
        """Create TaskPlan from parsed dictionary (legacy method)"""
        try:
            # Create task scope
            scope_description = task_dict.get('scope', f"Implement {task_dict.get('title', 'task')}")
            scope = TaskScope(
                description=scope_description,
                complexity="medium",
                dependencies=[],
                deliverable=task_dict.get('expected_outcome', 'Task completion')
            )
            
            # Create cycle time estimate based on team
            cycle_estimate = self._estimate_cycle_time_by_team(task_dict['team'], scope_description)
            
            # Create test cases based on team
            test_cases = self._generate_team_test_cases(task_dict['team'], task_dict.get('title', 'Task'))
            
            import uuid
            return TaskPlan(
                task_id=str(uuid.uuid4()),  # Generate stable identifier for dependency resolution
                summary=task_dict.get('title', f"{task_dict['team'].value.title()} Task"),
                purpose=task_dict.get('purpose', f"Support {task_dict['team'].value} implementation"),
                scopes=[scope],
                expected_outcomes=[task_dict.get('expected_outcome', 'Task completed successfully')],
                team=task_dict['team'],
                test_cases=test_cases,
                cycle_time_estimate=cycle_estimate,
                epic_key=story.epic_key,
                story_key=getattr(story, 'key', None)
            )
            
        except Exception as e:
            logger.error(f"Error creating task plan from dict: {str(e)}")
            return None
    
    def _generate_pattern_team_tasks(self, 
                                   story: StoryPlan, 
                                   story_type: StoryType,
                                   complexity_analysis: Dict[str, str]) -> List[TaskPlan]:
        """Generate pattern-based tasks with team separation"""
        tasks = []
        
        # Get patterns for this story type
        patterns = self.task_patterns.get(story_type, self.task_patterns[StoryType.USER_WORKFLOW])
        
        for pattern in patterns:
            # Create task based on pattern
            task = TaskPlan(
                summary=pattern['summary'].format(story_summary=story.summary),
                purpose=pattern['purpose'],
                scopes=[TaskScope(
                    description=pattern['scope_description'],
                    complexity=complexity_analysis.get(f"{pattern['team'].value}_complexity", "medium"),
                    dependencies=pattern.get('dependencies', []),
                    deliverable=pattern['deliverable']
                )],
                expected_outcomes=pattern['expected_outcomes'],
                team=pattern['team'],
                test_cases=self._generate_team_test_cases(pattern['team'], pattern['summary']),
                cycle_time_estimate=self._estimate_cycle_time_by_team(pattern['team'], pattern['scope_description']),
                epic_key=story.epic_key,
                story_key=getattr(story, 'key', None)
            )
            tasks.append(task)
        
        return tasks
    
    def _ensure_team_separation(self, 
                               tasks: List[TaskPlan], 
                               story: StoryPlan, 
                               story_type: StoryType) -> List[TaskPlan]:
        """Ensure at least one task for each team when applicable"""
        existing_teams = {task.team for task in tasks}
        
        # For most story types, we want Backend, Frontend, and QA representation
        required_teams = {TaskTeam.BACKEND, TaskTeam.FRONTEND, TaskTeam.QA}
        
        # Adjust required teams based on story type
        if story_type == StoryType.API_FEATURE:
            required_teams = {TaskTeam.BACKEND, TaskTeam.QA}  # API might not need frontend
        elif story_type == StoryType.CONFIGURATION:
            required_teams = {TaskTeam.BACKEND, TaskTeam.QA}  # Config typically backend-only
        
        missing_teams = required_teams - existing_teams
        
        for team in missing_teams:
            # Add a basic task for the missing team
            basic_task = self._create_basic_team_task(team, story, story_type)
            if basic_task:
                tasks.append(basic_task)
        
        return tasks
    
    def _create_basic_team_task(self, 
                              team: TaskTeam, 
                              story: StoryPlan, 
                              story_type: StoryType) -> Optional[TaskPlan]:
        """Create a basic task for a missing team"""
        team_templates = {
            TaskTeam.BACKEND: {
                'summary': f'Backend implementation for {story.summary}',
                'purpose': 'Implement backend logic and data handling',
                'scope': 'Develop backend services and API endpoints',
                'deliverable': 'Working backend implementation',
                'outcomes': ['Backend services implemented', 'API endpoints functional']
            },
            TaskTeam.FRONTEND: {
                'summary': f'Frontend implementation for {story.summary}',
                'purpose': 'Implement user interface and user experience',
                'scope': 'Develop UI components and user interactions',
                'deliverable': 'Working frontend implementation',
                'outcomes': ['UI components implemented', 'User interactions functional']
            },
            TaskTeam.QA: {
                'summary': f'Quality assurance for {story.summary}',
                'purpose': 'Ensure quality and validate functionality',
                'scope': 'Create and execute test cases for the feature',
                'deliverable': 'Test results and quality validation',
                'outcomes': ['Test cases executed', 'Quality validated', 'Bugs identified and tracked']
            }
        }
        
        template = team_templates.get(team)
        if not template:
            return None
        
        return TaskPlan(
            summary=template['summary'],
            purpose=template['purpose'],
            scopes=[TaskScope(
                description=template['scope'],
                complexity="medium",
                dependencies=[],
                deliverable=template['deliverable']
            )],
            expected_outcomes=template['outcomes'],
            team=team,
            test_cases=self._generate_team_test_cases(team, template['summary']),
            cycle_time_estimate=self._estimate_cycle_time_by_team(team, template['scope']),
            epic_key=story.epic_key,
            story_key=getattr(story, 'key', None)
        )
    
    def _estimate_cycle_time_by_team(self, team: TaskTeam, scope_description: str) -> CycleTimeEstimate:
        """Estimate cycle time based on team and scope"""
        # Base estimates by team (in days)
        base_estimates = {
            TaskTeam.BACKEND: {'dev': 2.0, 'test': 0.5, 'review': 0.5, 'deploy': 0.5},
            TaskTeam.FRONTEND: {'dev': 1.5, 'test': 0.5, 'review': 0.5, 'deploy': 0.25},
            TaskTeam.QA: {'dev': 0.5, 'test': 2.0, 'review': 0.25, 'deploy': 0.25}
        }
        
        estimates = base_estimates.get(team, base_estimates[TaskTeam.BACKEND])
        
        # Adjust based on scope complexity
        complexity_multiplier = 1.0
        if any(keyword in scope_description.lower() for keyword in ['complex', 'integration', 'database', 'external']):
            complexity_multiplier = 1.3
        elif any(keyword in scope_description.lower() for keyword in ['simple', 'basic', 'straightforward']):
            complexity_multiplier = 0.7
        
        dev_days = estimates['dev'] * complexity_multiplier
        test_days = estimates['test'] * complexity_multiplier
        review_days = estimates['review']
        deploy_days = estimates['deploy']
        total_days = dev_days + test_days + review_days + deploy_days
        
        return CycleTimeEstimate(
            development_days=dev_days,
            testing_days=test_days,
            review_days=review_days,
            deployment_days=deploy_days,
            total_days=total_days,
            confidence_level=0.75,
            exceeds_limit=total_days > 3.0
        )
    
    def _generate_team_test_cases(self, team: TaskTeam, task_summary: str) -> List[TestCase]:
        """Generate appropriate test cases based on team"""
        if team == TaskTeam.QA:
            return [
                TestCase(
                    title=f"Test plan for {task_summary}",
                    type="acceptance",
                    description=f"Create comprehensive test plan for {task_summary}",
                    expected_result="Complete test coverage documented"
                ),
                TestCase(
                    title=f"Execute test cases for {task_summary}",
                    type="integration",
                    description=f"Execute all test scenarios for {task_summary}",
                    expected_result="All test cases pass successfully"
                )
            ]
        elif team == TaskTeam.BACKEND:
            return [
                TestCase(
                    title=f"Unit test {task_summary}",
                    type="unit",
                    description=f"Test individual components of {task_summary}",
                    expected_result="All unit tests pass"
                ),
                TestCase(
                    title=f"Integration test {task_summary}",
                    type="integration",
                    description=f"Test integration points for {task_summary}",
                    expected_result="Integration tests pass"
                )
            ]
        elif team == TaskTeam.FRONTEND:
            return [
                TestCase(
                    title=f"UI component test {task_summary}",
                    type="unit",
                    description=f"Test UI components for {task_summary}",
                    expected_result="UI components render correctly"
                ),
                TestCase(
                    title=f"User interaction test {task_summary}",
                    type="e2e",
                    description=f"Test user interactions for {task_summary}",
                    expected_result="User interactions work as expected"
                )
            ]
        else:
            return [
                TestCase(
                    title=f"Verify {task_summary}",
                    type="integration",
                    description=f"Verify functionality of {task_summary}",
                    expected_result="Task functionality verified"
                )
            ]
    
    def _merge_and_optimize_tasks(self, ai_tasks: List[TaskPlan], pattern_tasks: List[TaskPlan]) -> List[TaskPlan]:
        """Merge AI and pattern tasks, removing duplicates and optimizing"""
        # Tag AI tasks to skip validation splitting (AI already respects cycle times)
        for task in ai_tasks:
            task._ai_generated = True
            
        all_tasks = ai_tasks + pattern_tasks
        
        # Simple deduplication by summary similarity
        unique_tasks = []
        seen_summaries = set()
        
        for task in all_tasks:
            normalized_summary = task.summary.lower().strip()
            if normalized_summary not in seen_summaries:
                seen_summaries.add(normalized_summary)
                unique_tasks.append(task)
        
        return unique_tasks
    
    def _validate_and_split_tasks(self, tasks: List[TaskPlan], max_cycle_days: int) -> List[TaskPlan]:
        """Validate cycle times and split oversized tasks"""
        validated_tasks = []
        
        for task in tasks:
            # Skip splitting for AI-generated tasks (they already respect cycle time constraints)
            if hasattr(task, '_ai_generated') and task._ai_generated:
                validated_tasks.append(task)
                continue
                
            if task.cycle_time_estimate and task.cycle_time_estimate.total_days > max_cycle_days:
                # Split the task
                split_tasks = self._split_oversized_task(task, max_cycle_days)
                validated_tasks.extend(split_tasks)
            else:
                validated_tasks.append(task)
        
        return validated_tasks
    
    def _split_oversized_task(self, task: TaskPlan, max_cycle_days: int) -> List[TaskPlan]:
        """Split an oversized task into smaller tasks"""
        if len(task.scopes) > 1:
            # Split by scopes
            split_tasks = []
            for i, scope in enumerate(task.scopes):
                split_task = TaskPlan(
                    summary=f"{task.summary} - Part {i+1}",
                    purpose=task.purpose,
                    scopes=[scope],
                    expected_outcomes=[task.expected_outcomes[i] if i < len(task.expected_outcomes) else task.expected_outcomes[0]],
                    team=task.team,
                    test_cases=[task.test_cases[i] if i < len(task.test_cases) else TestCase(
                        title=f"Test {task.summary} - Part {i+1}",
                        type="unit",
                        description=f"Test part {i+1} of {task.summary}",
                        expected_result="Part functions correctly"
                    )],
                    cycle_time_estimate=self._estimate_cycle_time_by_team(task.team, scope.description),
                    epic_key=task.epic_key,
                    story_key=task.story_key
                )
                split_tasks.append(split_task)
            return split_tasks
        else:
            # Split by time phases
            return [
                TaskPlan(
                    summary=f"{task.summary} - Design",
                    purpose=f"Design phase of {task.purpose}",
                    scopes=[TaskScope(
                        description=f"Design and plan {task.scopes[0].description}",
                        complexity="low",
                        dependencies=[],
                        deliverable="Design documentation"
                    )],
                    expected_outcomes=["Design completed and documented"],
                    team=task.team,
                    test_cases=[TestCase(
                        title=f"Review design for {task.summary}",
                        type="unit",
                        description="Review and validate design approach",
                        expected_result="Design approved"
                    )],
                    cycle_time_estimate=CycleTimeEstimate(
                        development_days=1.0,
                        testing_days=0.25,
                        review_days=0.25,
                        deployment_days=0.0,
                        total_days=1.5,
                        confidence_level=0.8,
                        exceeds_limit=False
                    ),
                    epic_key=task.epic_key,
                    story_key=task.story_key
                ),
                TaskPlan(
                    summary=f"{task.summary} - Implementation",
                    purpose=f"Implementation phase of {task.purpose}",
                    scopes=[TaskScope(
                        description=f"Implement {task.scopes[0].description}",
                        complexity=task.scopes[0].complexity,
                        dependencies=[f"{task.summary} - Design"],
                        deliverable=task.scopes[0].deliverable
                    )],
                    expected_outcomes=task.expected_outcomes,
                    team=task.team,
                    test_cases=task.test_cases,
                    cycle_time_estimate=CycleTimeEstimate(
                        development_days=1.5,
                        testing_days=0.5,
                        review_days=0.5,
                        deployment_days=0.5,
                        total_days=3.0,
                        confidence_level=0.7,
                        exceeds_limit=False
                    ),
                    epic_key=task.epic_key,
                    story_key=task.story_key
                )
            ]
    
    def _generate_fallback_team_tasks(self, story: StoryPlan) -> List[TaskPlan]:
        """Generate basic fallback tasks when all else fails"""
        return [
            TaskPlan(
                summary=f"Backend implementation for {story.summary}",
                purpose="Implement backend logic and data handling",
                scopes=[TaskScope(
                    description="Develop backend services and data layer",
                    complexity="medium",
                    dependencies=[],
                    deliverable="Working backend implementation"
                )],
                expected_outcomes=["Backend services implemented"],
                team=TaskTeam.BACKEND,
                test_cases=self._generate_team_test_cases(TaskTeam.BACKEND, "Backend implementation"),
                cycle_time_estimate=self._estimate_cycle_time_by_team(TaskTeam.BACKEND, "backend implementation"),
                epic_key=story.epic_key
            ),
            TaskPlan(
                summary=f"Frontend implementation for {story.summary}",
                purpose="Implement user interface and user experience",
                scopes=[TaskScope(
                    description="Develop UI components and user interactions",
                    complexity="medium",
                    dependencies=["Backend implementation"],
                    deliverable="Working frontend implementation"
                )],
                expected_outcomes=["Frontend implemented"],
                team=TaskTeam.FRONTEND,
                test_cases=self._generate_team_test_cases(TaskTeam.FRONTEND, "Frontend implementation"),
                cycle_time_estimate=self._estimate_cycle_time_by_team(TaskTeam.FRONTEND, "frontend implementation"),
                epic_key=story.epic_key
            ),
            TaskPlan(
                summary=f"Quality assurance for {story.summary}",
                purpose="Ensure quality and validate functionality",
                scopes=[TaskScope(
                    description="Create and execute comprehensive test cases",
                    complexity="medium",
                    dependencies=["Frontend implementation"],
                    deliverable="Quality validation and test results"
                )],
                expected_outcomes=["Quality validated", "Test cases executed"],
                team=TaskTeam.QA,
                test_cases=self._generate_team_test_cases(TaskTeam.QA, "Quality assurance"),
                cycle_time_estimate=self._estimate_cycle_time_by_team(TaskTeam.QA, "quality assurance"),
                epic_key=story.epic_key
            )
        ]
    
    def _initialize_task_patterns(self) -> Dict[StoryType, List[Dict[str, Any]]]:
        """Initialize task patterns for different story types"""
        return {
            StoryType.API_FEATURE: [
                {
                    'team': TaskTeam.BACKEND,
                    'summary': 'API design and implementation for {story_summary}',
                    'purpose': 'Design and implement REST API endpoints',
                    'scope_description': 'Create API endpoints, data models, and business logic',
                    'deliverable': 'Working API endpoints',
                    'expected_outcomes': ['API endpoints functional', 'Data models implemented'],
                    'dependencies': []
                },
                {
                    'team': TaskTeam.QA,
                    'summary': 'API testing for {story_summary}',
                    'purpose': 'Validate API functionality and performance',
                    'scope_description': 'Test API endpoints, data validation, and error handling',
                    'deliverable': 'API test results',
                    'expected_outcomes': ['API tested thoroughly', 'Performance validated'],
                    'dependencies': ['API implementation']
                }
            ],
            
            StoryType.UI_FEATURE: [
                {
                    'team': TaskTeam.FRONTEND,
                    'summary': 'UI design and implementation for {story_summary}',
                    'purpose': 'Create user interface components and interactions',
                    'scope_description': 'Design and implement UI components, layouts, and interactions',
                    'deliverable': 'Working UI components',
                    'expected_outcomes': ['UI components implemented', 'User interactions functional'],
                    'dependencies': []
                },
                {
                    'team': TaskTeam.BACKEND,
                    'summary': 'Backend support for {story_summary}',
                    'purpose': 'Provide backend services for UI functionality',
                    'scope_description': 'Implement backend APIs and data services for UI',
                    'deliverable': 'Backend API support',
                    'expected_outcomes': ['Backend APIs available', 'Data services implemented'],
                    'dependencies': []
                },
                {
                    'team': TaskTeam.QA,
                    'summary': 'UI testing for {story_summary}',
                    'purpose': 'Validate user interface and user experience',
                    'scope_description': 'Test UI components, user flows, and accessibility',
                    'deliverable': 'UI test results',
                    'expected_outcomes': ['UI tested thoroughly', 'User experience validated'],
                    'dependencies': ['UI implementation', 'Backend support']
                }
            ],
            
            StoryType.USER_WORKFLOW: [
                {
                    'team': TaskTeam.BACKEND,
                    'summary': 'Backend workflow implementation for {story_summary}',
                    'purpose': 'Implement business logic and data flow',
                    'scope_description': 'Create workflow logic, data processing, and state management',
                    'deliverable': 'Working backend workflow',
                    'expected_outcomes': ['Workflow logic implemented', 'Data flow functional'],
                    'dependencies': []
                },
                {
                    'team': TaskTeam.FRONTEND,
                    'summary': 'Frontend workflow interface for {story_summary}',
                    'purpose': 'Create user interface for workflow interaction',
                    'scope_description': 'Implement user interface for workflow steps and feedback',
                    'deliverable': 'Working workflow UI',
                    'expected_outcomes': ['Workflow UI implemented', 'User guidance functional'],
                    'dependencies': ['Backend workflow']
                },
                {
                    'team': TaskTeam.QA,
                    'summary': 'End-to-end workflow testing for {story_summary}',
                    'purpose': 'Validate complete workflow functionality',
                    'scope_description': 'Test complete user workflow from start to finish',
                    'deliverable': 'Workflow test results',
                    'expected_outcomes': ['Complete workflow tested', 'Edge cases validated'],
                    'dependencies': ['Frontend workflow interface']
                }
            ]
        }
    
    def _initialize_team_responsibilities(self) -> Dict[TaskTeam, List[str]]:
        """Initialize team responsibility patterns"""
        return {
            TaskTeam.BACKEND: [
                "API development and endpoints",
                "Database design and implementation", 
                "Business logic and data processing",
                "Service integrations and external APIs",
                "Security and authentication implementation",
                "Data validation and business rules",
                "Performance optimization",
                "Background jobs and scheduling"
            ],
            TaskTeam.FRONTEND: [
                "User interface components and pages",
                "User experience and interactions", 
                "Client-side logic and state management",
                "UI/UX implementation",
                "Responsive design and accessibility",
                "Form validation and user feedback",
                "Client-side routing and navigation",
                "Performance optimization (loading, caching)"
            ],
            TaskTeam.QA: [
                "Test plan creation and test case design",
                "Manual testing and exploratory testing",
                "Automated test implementation", 
                "Integration testing coordination",
                "Performance and security testing",
                "Regression testing",
                "User acceptance testing coordination",
                "Bug tracking and validation"
            ]
        }
    
    def _analyze_task_dependencies(self, tasks: List[TaskPlan]) -> List[TaskPlan]:
        """
        Analyze task dependencies and set up blocked-by relationships
        
        For AI-generated tasks: Dependencies are already set by AI, no need for hardcoded rules
        For pattern-generated tasks: Apply standard dependency flow:
        - Frontend tasks are usually blocked by Backend tasks (APIs, data structure)
        - QA tasks are usually blocked by both Backend and Frontend completion  
        - Backend tasks can depend on other Backend tasks (infrastructure, core services)
        """
        # Check if tasks are AI-generated (they already have dependencies)
        ai_generated = any(hasattr(task, '_ai_generated') and task._ai_generated for task in tasks)
        
        if ai_generated:
            logger.info("Tasks are AI-generated - using AI-provided dependencies instead of hardcoded rules")
            dependency_count = sum(1 for task in tasks if task.depends_on_tasks)
            logger.info(f"AI provided dependencies for {dependency_count}/{len(tasks)} tasks")
            
            # Convert summary-based dependencies to task_id when possible
            self._convert_dependencies_to_task_id(tasks)
            
            return tasks
        
        logger.info("Tasks are pattern-generated - applying hardcoded dependency rules")
        
        # Group tasks by team for easier analysis
        backend_tasks = [t for t in tasks if t.team == TaskTeam.BACKEND]
        frontend_tasks = [t for t in tasks if t.team == TaskTeam.FRONTEND]
        qa_tasks = [t for t in tasks if t.team == TaskTeam.QA]
        
        # Create task ID mapping for easier reference
        task_ids = {id(task): f"task_{i+1}" for i, task in enumerate(tasks)}
        
        # Apply dependency rules (only for pattern-generated tasks)
        for task in tasks:
            task.depends_on_tasks = []
            task.blocked_by_teams = []
            
            if task.team == TaskTeam.FRONTEND:
                # Frontend tasks are typically blocked by backend tasks
                for backend_task in backend_tasks:
                    if self._has_dependency_relationship(backend_task, task):
                        task.depends_on_tasks.append(task_ids[id(backend_task)])
                        if TaskTeam.BACKEND not in task.blocked_by_teams:
                            task.blocked_by_teams.append(TaskTeam.BACKEND)
                            
            elif task.team == TaskTeam.QA:
                # QA tasks are typically blocked by implementation tasks
                for impl_task in backend_tasks + frontend_tasks:
                    if self._has_dependency_relationship(impl_task, task):
                        task.depends_on_tasks.append(task_ids[id(impl_task)])
                        if impl_task.team not in task.blocked_by_teams:
                            task.blocked_by_teams.append(impl_task.team)
                            
            elif task.team == TaskTeam.BACKEND:
                # Backend tasks can depend on other backend infrastructure tasks
                for other_backend in backend_tasks:
                    if other_backend != task and self._has_backend_dependency(other_backend, task):
                        task.depends_on_tasks.append(task_ids[id(other_backend)])
                        if TaskTeam.BACKEND not in task.blocked_by_teams:
                            task.blocked_by_teams.append(TaskTeam.BACKEND)
        
        # Log dependency summary
        dependency_count = sum(1 for task in tasks if task.depends_on_tasks)
        logger.info(f"Set up dependencies for {dependency_count}/{len(tasks)} tasks")
        
        # Convert summary-based dependencies to task_id when possible
        self._convert_dependencies_to_task_id(tasks)
        
        return tasks
    
    def _convert_dependencies_to_task_id(self, tasks: List[TaskPlan]) -> None:
        """
        Convert summary-based dependencies to task_id when possible.
        This makes dependencies stable even if summaries change.
        
        Args:
            tasks: List of tasks to update dependencies for
        """
        # Build mapping from summary to task_id
        summary_to_task_id = {task.summary: task.task_id for task in tasks if task.task_id}
        
        # Also build normalized summary to task_id mapping for fuzzy matching
        normalized_to_task_id = {}
        for task in tasks:
            if task.task_id:
                # Normalize summary for matching
                normalized = self._normalize_task_summary_for_matching(task.summary)
                if normalized and normalized not in normalized_to_task_id:
                    normalized_to_task_id[normalized] = task.task_id
        
        # Update dependencies for each task
        converted_count = 0
        for task in tasks:
            if not task.depends_on_tasks:
                continue
            
            updated_dependencies = []
            for dep in task.depends_on_tasks:
                # If already a task_id (UUID format), keep it
                if self._is_uuid(dep):
                    updated_dependencies.append(dep)
                    continue
                
                # Try exact summary match
                if dep in summary_to_task_id:
                    updated_dependencies.append(summary_to_task_id[dep])
                    converted_count += 1
                    logger.debug(f"Converted dependency '{dep}' to task_id {summary_to_task_id[dep]}")
                    continue
                
                # Try normalized summary match
                normalized_dep = self._normalize_task_summary_for_matching(dep)
                if normalized_dep in normalized_to_task_id:
                    updated_dependencies.append(normalized_to_task_id[normalized_dep])
                    converted_count += 1
                    logger.debug(f"Converted dependency '{dep}' (normalized: '{normalized_dep}') to task_id {normalized_to_task_id[normalized_dep]}")
                    continue
                
                # Keep original if no match found (backward compatibility)
                updated_dependencies.append(dep)
                logger.debug(f"Could not convert dependency '{dep}' to task_id, keeping as summary")
            
            task.depends_on_tasks = updated_dependencies
        
        if converted_count > 0:
            logger.info(f"Converted {converted_count} summary-based dependencies to task_id")
    
    def _normalize_task_summary_for_matching(self, summary: str) -> str:
        """Normalize task summary for matching (same logic as planning_service)"""
        if not summary:
            return ""
        import re
        normalized = summary.strip()
        # Remove team prefixes
        normalized = re.sub(r'^\s*\[(BE|FE|QA)\]\s*', '', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'^\s*(BE|FE|QA):\s*', '', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'^\s*(BE|FE|QA)\s+', '', normalized, flags=re.IGNORECASE)
        normalized = ' '.join(normalized.split())
        normalized = normalized.lower()
        return normalized
    
    def _is_uuid(self, value: str) -> bool:
        """Check if string is a UUID"""
        import uuid
        try:
            uuid.UUID(value)
            return True
        except (ValueError, AttributeError):
            return False
    
    def _has_dependency_relationship(self, dependency_task: TaskPlan, dependent_task: TaskPlan) -> bool:
        """
        Check if dependent_task should be blocked by dependency_task
        
        Logic:
        - Frontend UI tasks depend on Backend API tasks
        - QA testing tasks depend on implementation tasks
        - Similar scope/feature tasks have dependencies
        """
        dep_summary = dependency_task.summary.lower()
        dependent_summary = dependent_task.summary.lower()
        
        # Check for common feature/scope keywords
        common_keywords = self._extract_feature_keywords(dep_summary, dependent_summary)
        if not common_keywords:
            return False
            
        # Frontend depends on Backend for same feature
        if (dependency_task.team == TaskTeam.BACKEND and 
            dependent_task.team == TaskTeam.FRONTEND):
            # API/service tasks block UI tasks
            if any(keyword in dep_summary for keyword in ['api', 'service', 'endpoint', 'data', 'backend']):
                return True
                
        # QA depends on implementation tasks for same feature  
        if dependent_task.team == TaskTeam.QA:
            return True  # QA generally depends on implementation
            
        return False
    
    def _has_backend_dependency(self, dependency_task: TaskPlan, dependent_task: TaskPlan) -> bool:
        """
        Check if one backend task depends on another backend task
        
        Infrastructure and core services typically come before feature implementations
        """
        dep_summary = dependency_task.summary.lower()
        dependent_summary = dependent_task.summary.lower()
        
        # Infrastructure tasks come first
        infrastructure_keywords = ['database', 'schema', 'migration', 'setup', 'configuration', 'infrastructure']
        feature_keywords = ['api', 'endpoint', 'service', 'feature', 'implementation']
        
        is_infrastructure = any(keyword in dep_summary for keyword in infrastructure_keywords)
        is_feature = any(keyword in dependent_summary for keyword in feature_keywords)
        
        return is_infrastructure and is_feature
    
    def _extract_feature_keywords(self, summary1: str, summary2: str) -> List[str]:
        """Extract common feature keywords between two task summaries"""
        # Simple keyword extraction - look for common meaningful words
        words1 = set(word.lower() for word in summary1.split() if len(word) > 3)
        words2 = set(word.lower() for word in summary2.split() if len(word) > 3)
        
        # Remove common non-feature words
        stop_words = {'task', 'implementation', 'create', 'build', 'develop', 'test', 'testing'}
        words1 -= stop_words
        words2 -= stop_words
        
        common_words = words1.intersection(words2)
        return list(common_words)
    
    def _format_document_context(self, 
                                 prd_content: Optional[Dict[str, Any]], 
                                 rfc_content: Optional[Dict[str, Any]],
                                 story_type: StoryType,
                                 max_chars: int = 3000) -> str:
        """
        Intelligently select and format relevant PRD/RFC sections based on story type.
        
        Args:
            prd_content: PRD dictionary with title, summary, sections
            rfc_content: RFC dictionary with title, summary, sections
            story_type: Type of story (API, UI, DATA, etc.)
            max_chars: Maximum total characters for document context
            
        Returns:
            Formatted context string with relevant sections
        """
        context_parts = []
        current_chars = 0
        
        # Define section priorities based on story type
        section_priorities = {
            StoryType.API_FEATURE: {
                'prd': ['technical_documentation', 'user_stories', 'success_criteria', 'proposed_solution'],
                'rfc': ['technical_design', 'apis', 'database_model', 'performance_requirement', 'security_implications']
            },
            StoryType.UI_FEATURE: {
                'prd': ['user_stories', 'description_flow', 'mockup_design', 'user_value', 'target_population'],
                'rfc': ['technical_design', 'architecture_tech_stack', 'apis']
            },
            StoryType.DATA_FEATURE: {
                'prd': ['technical_documentation', 'user_stories', 'proposed_solution'],
                'rfc': ['database_model', 'technical_design', 'apis', 'architecture_tech_stack']
            },
            StoryType.INTEGRATION: {
                'prd': ['technical_documentation', 'user_stories', 'proposed_solution'],
                'rfc': ['technical_design', 'apis', 'architecture_tech_stack', 'security_implications']
            }
        }
        
        # Default priorities for unknown story types
        default_priorities = {
            'prd': ['user_stories', 'proposed_solution', 'technical_documentation', 'success_criteria'],
            'rfc': ['technical_design', 'apis', 'overview']
        }
        
        priorities = section_priorities.get(story_type, default_priorities)
        
        # Process PRD content
        if prd_content and current_chars < max_chars:
            prd_sections = prd_content.get('sections', {})
            prd_title = prd_content.get('title', 'PRD')
            prd_summary = prd_content.get('summary', '')
            
            # Add title and summary (200 chars each)
            title_summary = f"**{prd_title}**\n"
            if prd_summary:
                truncated_summary = prd_summary[:200] + "..." if len(prd_summary) > 200 else prd_summary
                title_summary += f"Summary: {truncated_summary}\n"
            
            if current_chars + len(title_summary) < max_chars:
                context_parts.append(title_summary)
                current_chars += len(title_summary)
                
                # Add relevant sections
                for section_key in priorities['prd']:
                    if section_key in prd_sections and current_chars < max_chars:
                        section_content = prd_sections[section_key]
                        if len(section_content.strip()) > 10:
                            # Truncate section to 400-600 chars with smart boundaries
                            truncated_section = self._truncate_content_smart(section_content, 500)
                            section_text = f"- {section_key.replace('_', ' ').title()}: {truncated_section}\n"
                            
                            if current_chars + len(section_text) < max_chars:
                                context_parts.append(section_text)
                                current_chars += len(section_text)
        
        # Process RFC content
        if rfc_content and current_chars < max_chars:
            rfc_sections = rfc_content.get('sections', {})
            rfc_title = rfc_content.get('title', 'RFC')
            rfc_summary = rfc_content.get('summary', '')
            
            # Add title and summary
            title_summary = f"\n**{rfc_title}**\n"
            if rfc_summary:
                truncated_summary = rfc_summary[:200] + "..." if len(rfc_summary) > 200 else rfc_summary
                title_summary += f"Summary: {truncated_summary}\n"
            
            if current_chars + len(title_summary) < max_chars:
                context_parts.append(title_summary)
                current_chars += len(title_summary)
                
                # Add relevant sections
                for section_key in priorities['rfc']:
                    if section_key in rfc_sections and current_chars < max_chars:
                        section_content = rfc_sections[section_key]
                        if len(section_content.strip()) > 10:
                            # Truncate section to 400-600 chars with smart boundaries
                            truncated_section = self._truncate_content_smart(section_content, 500)
                            section_text = f"- {section_key.replace('_', ' ').title()}: {truncated_section}\n"
                            
                            if current_chars + len(section_text) < max_chars:
                                context_parts.append(section_text)
                                current_chars += len(section_text)
        
        return ''.join(context_parts)
    
    def _truncate_content_smart(self, content: str, max_length: int) -> str:
        """Truncate content with smart sentence boundaries"""
        if len(content) <= max_length:
            return content
        
        # Try to truncate at sentence boundary
        truncated = content[:max_length - 100]
        
        # Look for sentence endings within a reasonable range
        sentence_endings = ['. ', '! ', '? ', '\n\n']
        best_cut = -1
        
        for ending in sentence_endings:
            cut_pos = truncated.rfind(ending)
            if cut_pos > max_length * 0.7:  # Don't cut too early
                best_cut = max(best_cut, cut_pos + len(ending))
        
        if best_cut > 0:
            return content[:best_cut].strip() + "..."
        else:
            return content[:max_length - 3] + "..."
    
    def _format_additional_context(self, additional_context: str) -> str:
        """Format additional context for the prompt"""
        if not additional_context:
            return ""
        
        # Truncate additional context to 1000 chars max
        truncated_context = additional_context[:1000]
        if len(additional_context) > 1000:
            truncated_context += "... [truncated]"
        
        return f"**ADDITIONAL CONTEXT:**\n{truncated_context}\n"
    
    # =============================================================================
    # UNIFIED TASK + TEST GENERATION METHODS
    # =============================================================================
    
    def _generate_ai_tasks_with_tests(self, 
                                    story: StoryPlan, 
                                    story_type: StoryType,
                                    max_cycle_days: int,
                                    test_coverage_level: TestCoverageLevel,
                                    prd_content: Optional[Dict[str, Any]] = None,
                                    rfc_content: Optional[Dict[str, Any]] = None,
                                    additional_context: Optional[str] = None) -> List[TaskPlan]:
        """Generate tasks with embedded test cases using unified AI prompt"""
        try:
            # Create unified prompt that generates both tasks and tests
            prompt = self._create_unified_task_test_prompt(
                story, story_type, max_cycle_days, test_coverage_level,
                prd_content, rfc_content, additional_context
            )
            
            # Generate using LLM with enforced JSON mode
            # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
            response = self.llm_client.generate_content_json(
                prompt=prompt,
                system_prompt=Prompts.get_unified_task_test_system_prompt(),
                max_tokens=None
            )
            
            # Parse response into tasks with embedded tests
            parsed_tasks = self._parse_unified_task_test_response(response, story)
            
            if not parsed_tasks:
                logger.error("Unified task+test parsing returned empty list")
                return []
            
            logger.info(f"Unified generation successful - generated {len(parsed_tasks)} tasks with tests")
            return parsed_tasks
            
        except Exception as e:
            logger.error(f"Unified task+test generation failed: {str(e)}")
            return []
    
    def _create_unified_task_test_prompt(self, 
                                       story: StoryPlan, 
                                       story_type: StoryType,
                                       max_cycle_days: int,
                                       test_coverage_level: TestCoverageLevel,
                                       prd_content: Optional[Dict[str, Any]] = None,
                                       rfc_content: Optional[Dict[str, Any]] = None,
                                       additional_context: Optional[str] = None) -> str:
        """Create comprehensive prompt for unified task and test generation"""
        acceptance_criteria_text = [ac.format_gwt() for ac in story.acceptance_criteria]
        test_count = self._get_test_count_for_coverage(test_coverage_level)
        
        # Get centralized template and format it
        template = Prompts.get_unified_task_test_prompt_template()
        document_context = self._format_document_context(prd_content, rfc_content, story_type) if prd_content or rfc_content else ""
        additional_context_str = self._format_additional_context(additional_context) if additional_context else ""
        
        prompt = template.format(
            story_summary=story.summary,
            story_description=story.description,
            story_type=story_type.value,
            max_cycle_days=max_cycle_days,
            test_coverage_level=test_coverage_level.value,
            test_count=test_count,
            acceptance_criteria=chr(10).join(acceptance_criteria_text),
            document_context=document_context,
            additional_context=additional_context_str
        )
        
        return prompt
    
    def _parse_unified_task_test_response(self, response: str, story: StoryPlan) -> List[TaskPlan]:
        """Parse LLM response containing tasks with embedded test cases"""
        try:
            import json
            
            # Clean response and extract JSON
            response = response.strip()
            if response.startswith('```json'):
                response = response[7:]
            if response.endswith('```'):
                response = response[:-3]
            response = response.strip()
            
            # Parse JSON
            tasks_data = json.loads(response)
            
            if not isinstance(tasks_data, list):
                logger.error("Response is not a JSON array")
                return []
            
            parsed_tasks = []
            for i, task_data in enumerate(tasks_data):
                try:
                    task = self._create_task_with_tests_from_dict(task_data, story, i + 1)
                    if task:
                        parsed_tasks.append(task)
                except Exception as e:
                    logger.error(f"Error parsing task {i+1}: {str(e)}")
                    continue
            
            return parsed_tasks
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Unified response parsing failed: {str(e)}")
            return []
    
    def _create_task_with_tests_from_dict(self, task_data: Dict[str, Any], story: StoryPlan, task_num: int) -> Optional[TaskPlan]:
        """Create TaskPlan with embedded test cases from parsed JSON"""
        try:
            # Parse basic task info
            summary = task_data.get('summary', f'Generated Task {task_num}')
            team_str = task_data.get('team', 'backend').lower()
            purpose = task_data.get('purpose', 'Implementation task')
            
            # Map team string to TaskTeam enum
            team_mapping = {
                'backend': TaskTeam.BACKEND,
                'frontend': TaskTeam.FRONTEND,
                'qa': TaskTeam.QA
            }
            team = team_mapping.get(team_str, TaskTeam.BACKEND)
            
            # Parse scopes
            scopes = []
            for scope_data in task_data.get('scopes', []):
                scope = TaskScope(
                    description=scope_data.get('description', 'Task scope'),
                    deliverable=scope_data.get('deliverable', 'Deliverable')
                )
                scopes.append(scope)
            
            # Parse test cases with step cleanup
            test_cases = []
            for test_data in task_data.get('test_cases', []):
                # Clean up test steps to remove numbering
                raw_steps = test_data.get('test_steps', '')
                cleaned_steps = self._clean_test_steps(raw_steps)
                
                test_case = TestCase(
                    title=test_data.get('title', 'Generated Test'),
                    type=test_data.get('type', 'unit'),
                    description=test_data.get('description', 'Generated test case'),
                    priority=test_data.get('priority', 'P1'),
                    steps=cleaned_steps,
                    expected_result=test_data.get('expected_result', 'Expected functionality works'),
                    source="unified_generation"
                )
                test_cases.append(test_case)
            
            # Parse cycle time estimate
            cycle_data = task_data.get('cycle_time_estimate', {})
            cycle_time = CycleTimeEstimate(
                development_days=float(cycle_data.get('development_days', 2.0)),
                testing_days=float(cycle_data.get('testing_days', 0.5)),
                review_days=float(cycle_data.get('review_days', 0.5)),
                deployment_days=float(cycle_data.get('deployment_days', 0.5)),
                total_days=float(cycle_data.get('total_days', 2.5))
            )
            
            # Create task with embedded test cases
            task = TaskPlan(
                summary=summary,
                team=team,
                purpose=purpose,
                scopes=scopes,
                expected_outcomes=[scope.deliverable for scope in scopes] or ["Task completion"],
                test_cases=test_cases,  # ✅ Test cases embedded in task
                cycle_time_estimate=cycle_time,
                depends_on_tasks=task_data.get('depends_on_tasks', []),
                blocked_by_teams=[]
            )
            
            logger.info(f"Created task '{summary}' with {len(test_cases)} embedded test cases")
            return task
            
        except Exception as e:
            logger.error(f"Error creating task from dict: {str(e)}")
            return None
    
    def _get_test_count_for_coverage(self, coverage_level: TestCoverageLevel) -> int:
        """Get number of test cases per task based on coverage level"""
        coverage_mapping = {
            TestCoverageLevel.MINIMAL: 2,
            TestCoverageLevel.BASIC: 3,
            TestCoverageLevel.STANDARD: 4,
            TestCoverageLevel.COMPREHENSIVE: 6
        }
        return coverage_mapping.get(coverage_level, 4)
    
    def _generate_fallback_task_tests(self, task: TaskPlan, coverage_level: TestCoverageLevel) -> List[TestCase]:
        """Generate fallback test cases when unified generation fails"""
        test_cases = []
        test_count = self._get_test_count_for_coverage(coverage_level)
        
        # Generate basic test cases based on task team and scopes
        for i, scope in enumerate(task.scopes[:test_count]):
            test_case = TestCase(
                title=f"Test {scope.description}",
                type="unit" if task.team == TaskTeam.BACKEND else "integration",
                description=f"Verify {scope.deliverable} works correctly",
                priority="P1",
                steps=[
                    f"Given {scope.description} is implemented",
                    f"When the functionality is executed",
                    f"Then {scope.deliverable} should work as expected"
                ],
                expected_result=f"{scope.deliverable} functions correctly",
                source="fallback_generation"
            )
            test_cases.append(test_case)
        
        # Add one error handling test
        if len(test_cases) < test_count:
            error_test = TestCase(
                title=f"Error Handling: {task.summary}",
                type="unit",
                description="Verify error handling works correctly",
                priority="P2",
                steps=[
                    "Given invalid input is provided",
                    "When the functionality is executed",
                    "Then appropriate error handling occurs"
                ],
                expected_result="Errors are handled gracefully",
                source="fallback_generation"
            )
            test_cases.append(error_test)
        
        return test_cases[:test_count]
    
    def _generate_minimal_task_tests(self, task: TaskPlan) -> List[TestCase]:
        """Generate minimal test cases for emergency fallback"""
        return [
            TestCase(
                title=f"Basic Test: {task.summary}",
                type="unit",
                description="Basic functionality test",
                priority="P1",
                steps=[
                    "Given the task is implemented",
                    "When basic functionality is tested",
                    "Then it should work correctly"
                ],
                expected_result="Basic functionality works",
                source="minimal_fallback"
            )
        ]
    
    def _clean_test_steps(self, raw_steps: str) -> List[str]:
        """Clean test steps to remove numbering and ensure proper Given/When/Then format"""
        if not raw_steps:
            return []
        
        # Split by both literal \n and actual newlines
        steps = []
        # Handle both literal '\n' strings and actual newlines
        if '\\n' in raw_steps:
            step_parts = raw_steps.split('\\n')
        else:
            step_parts = raw_steps.split('\n')
            
        for step in step_parts:
            if not step.strip():
                continue
                
            # Remove common number prefixes and bullet points
            cleaned_step = step.strip()
            
            # Remove patterns like "1.", "2.", "3.", etc.
            import re
            cleaned_step = re.sub(r'^\d+\.\s*', '', cleaned_step)
            
            # Remove bullet points
            cleaned_step = re.sub(r'^[-•*]\s*', '', cleaned_step)
            
            # Remove "And" prefixes that shouldn't be there
            cleaned_step = re.sub(r'^And\s+', '', cleaned_step)
            
            if cleaned_step:
                steps.append(cleaned_step)
        
        return steps
