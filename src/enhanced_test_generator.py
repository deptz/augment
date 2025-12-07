"""
Enhanced Test Case Generation Engine
AI-powered test case generation for stories and tasks with comprehensive coverage
"""
import logging
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import re

from .planning_models import StoryPlan, TaskPlan, TestCase, AcceptanceCriteria
from .planning_prompt_engine import PlanningPromptEngine, DocumentType
from .llm_client import LLMClient
from .prompts import Prompts

logger = logging.getLogger(__name__)


class TestType(str, Enum):
    """Types of tests that can be generated"""
    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    ACCEPTANCE = "acceptance"
    PERFORMANCE = "performance"
    SECURITY = "security"
    REGRESSION = "regression"
    SMOKE = "smoke"


class TestCoverageLevel(str, Enum):
    """Test coverage levels"""
    BASIC = "basic"           # Happy path + 1 error case
    STANDARD = "standard"     # Happy path + error cases + edge cases
    COMPREHENSIVE = "comprehensive"  # All above + performance + security
    MINIMAL = "minimal"       # Just happy path


class TestDataType(str, Enum):
    """Types of test data that can be generated"""
    VALID_INPUT = "valid_input"
    INVALID_INPUT = "invalid_input"
    BOUNDARY_VALUES = "boundary_values"
    EDGE_CASES = "edge_cases"
    SECURITY_PAYLOADS = "security_payloads"
    PERFORMANCE_DATA = "performance_data"


class EnhancedTestGenerator:
    """
    AI-powered test case generation engine for comprehensive test coverage
    """
    
    def __init__(self, llm_client: LLMClient, prompt_engine: PlanningPromptEngine, jira_client=None, confluence_client=None):
        self.llm_client = llm_client
        self.prompt_engine = prompt_engine
        self.jira_client = jira_client  # For fetching story context
        self.confluence_client = confluence_client  # For fetching PRD/RFC context
        self.test_patterns = self._initialize_test_patterns()
        self.coverage_templates = self._initialize_coverage_templates()
    
    def generate_story_test_cases(self, 
                                story: StoryPlan, 
                                coverage_level: TestCoverageLevel = TestCoverageLevel.STANDARD,
                                domain_context: Optional[str] = None) -> List[TestCase]:
        """
        Generate comprehensive test cases for a story
        
        Args:
            story: Story plan to generate tests for
            coverage_level: Level of test coverage desired
            domain_context: Domain-specific context (e.g., "financial", "healthcare")
            
        Returns:
            List of generated test cases
        """
        logger.info(f"Generating story test cases for: {story.summary} (coverage: {coverage_level.value})")
        
        try:
            # Generate AI-powered test cases
            ai_tests = self._generate_ai_story_tests(story, coverage_level, domain_context)
            
            # Generate pattern-based test cases
            pattern_tests = self._generate_pattern_story_tests(story, coverage_level)
            
            # Combine and deduplicate
            all_tests = ai_tests + pattern_tests
            unique_tests = self._deduplicate_tests(all_tests)
            
            # Ensure coverage requirements
            final_tests = self._ensure_story_coverage(unique_tests, story, coverage_level)
            
            logger.info(f"Generated {len(final_tests)} test cases for story {story.summary}")
            return final_tests
            
        except Exception as e:
            logger.error(f"Error generating story test cases: {str(e)}")
            return self._generate_fallback_story_tests(story, coverage_level)
    
    def generate_task_test_cases(self,
                               task: TaskPlan,
                               coverage_level: TestCoverageLevel = TestCoverageLevel.STANDARD,
                               technical_context: Optional[str] = None) -> List[TestCase]:
        """
        Generate comprehensive test cases for a task
        
        Args:
            task: Task plan to generate tests for
            coverage_level: Level of test coverage desired
            technical_context: Technical context (e.g., "API", "database", "UI")
            
        Returns:
            List of generated test cases
        """
        logger.info(f"Generating task test cases for: {task.summary} (coverage: {coverage_level.value})")
        
        try:
            # Generate AI-powered test cases with context awareness
            ai_tests = self._generate_ai_task_tests_with_context(task, coverage_level, technical_context)
            
            # Only add pattern-based test cases if AI generation produced insufficient results
            if len(ai_tests) < 2:
                logger.info(f"AI generated only {len(ai_tests)} tests, adding pattern-based tests")
                pattern_tests = self._generate_pattern_task_tests(task, coverage_level)
                all_tests = ai_tests + pattern_tests
            else:
                logger.info(f"AI generated {len(ai_tests)} tests, skipping pattern-based tests")
                all_tests = ai_tests
            
            # Deduplicate and ensure coverage
            unique_tests = self._deduplicate_tests(all_tests)
            final_tests = self._ensure_task_coverage(unique_tests, task, coverage_level)
            
            logger.info(f"Generated {len(final_tests)} test cases for task {task.summary}")
            return final_tests
            
        except Exception as e:
            logger.error(f"Error generating task test cases: {str(e)}")
            return self._generate_fallback_task_tests(task, coverage_level)
    
    def generate_task_test_cases_with_story_context(self,
                                                  task_key: str,
                                                  coverage_level: TestCoverageLevel = TestCoverageLevel.STANDARD,
                                                  technical_context: Optional[str] = None,
                                                  include_documents: bool = True) -> List[TestCase]:
        """
        Generate task test cases with full story and document context
        
        Args:
            task_key: JIRA task key (e.g., "PROJ-123")
            coverage_level: Level of test coverage desired
            technical_context: Technical context for the task
            include_documents: Whether to include PRD/RFC context
            
        Returns:
            List of generated test cases with enhanced context
        """
        logger.info(f"Generating context-aware test cases for task: {task_key}")
        
        try:
            # Get task details
            if not self.jira_client:
                raise ValueError("JIRA client required for context-aware test generation")
            
            task = self._get_task_from_jira(task_key)
            
            # Get story context
            story_context = self._get_story_context(task)
            self._last_story_context = story_context  # Store for API response
            
            # Get document context if requested
            doc_context = None
            if include_documents:
                doc_context = self._get_document_context(task, story_context)
            self._last_document_context = doc_context  # Store for API response
            
            # Generate with enhanced context
            return self._generate_task_tests_with_full_context(
                task, story_context, doc_context, coverage_level, technical_context
            )
            
        except Exception as e:
            logger.error(f"Error in context-aware test generation: {str(e)}")
            # Fallback to basic task generation if available
            if hasattr(self, '_generate_fallback_task_tests'):
                return self._generate_fallback_task_tests(task_key, coverage_level)
            return []
            logger.error(f"Error generating task test cases: {str(e)}")
            return self._generate_fallback_task_tests(task, coverage_level)
    
    def generate_test_data(self, 
                         test_case: TestCase, 
                         data_types: List[TestDataType],
                         context: Optional[Dict[str, Any]] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generate realistic test data for test cases
        
        Args:
            test_case: Test case to generate data for
            data_types: Types of test data to generate
            context: Additional context for data generation
            
        Returns:
            Dictionary mapping data types to lists of test data
        """
        logger.info(f"Generating test data for: {test_case.title}")
        
        try:
            # Generate AI-powered test data
            data_prompt = self._create_test_data_prompt(test_case, data_types, context)
            
            # Generate AI-powered test data using enforced JSON mode
            # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
            response = self.llm_client.generate_content_json(
                prompt=data_prompt,
                system_prompt=Prompts.get_test_data_generation_system_prompt(),
                max_tokens=None
            )
            
            # Parse the response into structured test data
            test_data = self._parse_test_data_response(response, data_types)
            
            # Add pattern-based test data
            pattern_data = self._generate_pattern_test_data(test_case, data_types, context)
            
            # Combine data types
            combined_data = {}
            for data_type in data_types:
                combined_data[data_type.value] = (
                    test_data.get(data_type.value, []) + 
                    pattern_data.get(data_type.value, [])
                )
            
            return combined_data
            
        except Exception as e:
            logger.error(f"Error generating test data: {str(e)}")
            return self._generate_fallback_test_data(test_case, data_types)
    
    def _generate_ai_story_tests(self, 
                               story: StoryPlan, 
                               coverage_level: TestCoverageLevel,
                               domain_context: Optional[str]) -> List[TestCase]:
        """Generate AI-powered test cases for a story"""
        try:
            # Create comprehensive prompt for story test generation
            acceptance_criteria_text = []
            if hasattr(story, 'acceptance_criteria') and story.acceptance_criteria:
                for ac in story.acceptance_criteria:
                    if hasattr(ac, 'format_gwt'):
                        acceptance_criteria_text.append(ac.format_gwt())
                    else:
                        acceptance_criteria_text.append(f"Scenario: {getattr(ac, 'scenario', 'N/A')}, Given: {getattr(ac, 'given', 'N/A')}, When: {getattr(ac, 'when', 'N/A')}, Then: {getattr(ac, 'then', 'N/A')}")
            
            # Build prompt using centralized template
            template = Prompts.get_story_test_generation_prompt_template()
            domain_guidance = self._get_domain_specific_guidance(domain_context or 'general', 'story') if domain_context else ''
            
            prompt = template.format(
                story_summary=story.summary,
                story_description=story.description,
                coverage_level=coverage_level.value,
                domain_context=domain_context or 'general',
                acceptance_criteria=chr(10).join([f"- {ac}" for ac in acceptance_criteria_text]) if acceptance_criteria_text else "- Standard user story validation",
                test_count=self._get_test_count_for_coverage(coverage_level),
                domain_specific_guidance=domain_guidance
            )

            # Generate using LLM with enforced JSON mode for reliable parsing
            # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
            response = self.llm_client.generate_content_json(
                prompt=prompt,
                system_prompt=Prompts.get_story_test_generation_system_prompt(),
                max_tokens=None
            )
            
            return self._parse_story_test_response(response, story)
            
        except Exception as e:
            logger.warning(f"AI story test generation failed: {str(e)}")
            return []
    
    def _generate_ai_task_tests(self,
                              task: TaskPlan,
                              coverage_level: TestCoverageLevel,
                              technical_context: Optional[str]) -> List[TestCase]:
        """Generate AI-powered test cases for a task"""
        try:
            # Build prompt using centralized template
            scopes_text = [scope.description for scope in task.scopes]
            expected_outcomes = chr(10).join([f"- {outcome}" for outcome in (task.expected_outcomes or [])]) if hasattr(task, 'expected_outcomes') else "- Functional requirements met"
            technical_guidance = self._get_technical_specific_guidance(technical_context or 'general') if technical_context else ''
            
            template = Prompts.get_task_test_generation_prompt_template()
            prompt = template.format(
                task_summary=task.summary,
                task_purpose=task.purpose,
                technical_context=technical_context or 'general',
                coverage_level=coverage_level.value,
                task_scopes=chr(10).join([f"- {scope}" for scope in scopes_text]) if scopes_text else "- Implementation details",
                expected_outcomes=expected_outcomes,
                test_count=self._get_test_count_for_coverage(coverage_level),
                technical_specific_guidance=technical_guidance
            )

            # Generate with enforced JSON mode for reliable parsing
            # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
            response = self.llm_client.generate_content_json(
                prompt=prompt,
                system_prompt=Prompts.get_task_test_generation_system_prompt(),
                max_tokens=None
            )
            
            # Log the response to debug Gherkin format issues
            logger.info(f"LLM response for task {task.summary}: {response[:500]}...")
            
            # Parse response into test cases
            return self._parse_task_test_response(response, task)
            
        except Exception as e:
            logger.warning(f"AI task test generation failed: {str(e)}")
            return []
    
    def _parse_story_test_response(self, response: str, story: StoryPlan) -> List[TestCase]:
        """Parse LLM JSON response into story test cases"""
        try:
            # Check for None or empty response
            if response is None:
                logger.error("Received None response from LLM")
                return []
            
            if not isinstance(response, str):
                logger.error(f"Expected string response, got {type(response)}: {response}")
                return []
                
            if not response.strip():
                logger.error("Received empty response from LLM")
                return []
            
            # Clean up response - remove any markdown code blocks
            response = response.strip()
            if response.startswith('```json'):
                response = response[7:]
            elif response.startswith('```'):
                response = response[3:]
            if response.endswith('```'):
                response = response[:-3]
            
            # Find JSON array in response
            import json
            import re
            
            logger.info(f"Processing story test response with {len(response)} characters")
            
            # Try to find JSON array pattern
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                # If no array found, try the whole response
                json_str = response.strip()
            
            # Parse JSON
            test_data = json.loads(json_str)
            
            # Ensure it's a list
            if not isinstance(test_data, list):
                logger.error(f"Expected JSON array, got {type(test_data)}")
                return []
            
            tests = []
            for item in test_data:
                if not isinstance(item, dict):
                    logger.warning(f"Skipping non-dict item: {item}")
                    continue
                
                # Create TestCase from JSON data
                test_steps = None
                if item.get('test_steps'):
                    # Split test steps into list if they're in string format
                    steps_text = item['test_steps']
                    if isinstance(steps_text, str):
                        # Split by newlines and filter out empty lines
                        test_steps = [step.strip() for step in steps_text.split('\n') if step.strip()]
                    elif isinstance(steps_text, list):
                        test_steps = steps_text
                
                # Determine the source of the test case
                source = "llm_ai" if item.get('test_steps') else "llm_fallback"
                
                test_case = TestCase(
                    title=item.get('title', 'Generated Story Test Case'),
                    type=item.get('type', 'acceptance').lower(),
                    description=item.get('description', 'Generated story test description'),
                    steps=test_steps,
                    expected_result=item.get('expected_result', 'Story functionality works correctly'),
                    priority=self._normalize_priority(item.get('priority', 'P2')),
                    source=source
                )
                
                tests.append(test_case)
            
            logger.info(f"Successfully parsed {len(tests)} story test cases from JSON")
            return tests
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error in story tests: {str(e)}")
            logger.debug(f"Response content: {response[:500]}...")
            # Fallback to text parsing
            return self._parse_story_test_response_text_fallback(response, story)
        except Exception as e:
            logger.error(f"Error parsing story test response: {str(e)}")
            return []

    def _parse_story_test_response_text_fallback(self, response: str, story: StoryPlan) -> List[TestCase]:
        """Fallback text parsing for story test cases when JSON fails"""
        try:
            tests = []
            lines = response.strip().split('\n')
            
            current_test = {}
            current_field = None
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Look for test case headers
                if any(keyword in line.lower() for keyword in ['test case', 'title:', 'scenario:']):
                    if current_test and current_test.get('title'):
                        tests.append(self._create_test_case_from_dict(current_test, "acceptance"))
                    
                    current_test = {
                        'title': line.replace('Test Case:', '').replace('Title:', '').replace('Scenario:', '').strip(),
                        'type': 'acceptance',
                        'description': '',
                        'expected_result': ''
                    }
                    current_field = 'title'
                
                elif current_test:
                    # Look for field headers
                    if 'type:' in line.lower():
                        current_test['type'] = line.split(':', 1)[1].strip().lower()
                        current_field = 'type'
                    elif 'description:' in line.lower():
                        current_test['description'] = line.split(':', 1)[1].strip()
                        current_field = 'description'
                    elif 'expected:' in line.lower() or 'result:' in line.lower():
                        current_test['expected_result'] = line.split(':', 1)[1].strip()
                        current_field = 'expected_result'
                    elif current_field and line.startswith('-'):
                        # Handle bullet points
                        if current_field == 'description':
                            current_test['description'] += f" {line.lstrip('-').strip()}"
                        elif current_field == 'expected_result':
                            current_test['expected_result'] += f" {line.lstrip('-').strip()}"
            
            # Add the last test case
            if current_test and current_test.get('title'):
                tests.append(self._create_test_case_from_dict(current_test, "acceptance"))
            
            return tests
            
        except Exception as e:
            logger.error(f"Error in text fallback parsing: {str(e)}")
            return []
    
    def _parse_task_test_response(self, response: str, task: TaskPlan) -> List[TestCase]:
        """Parse LLM JSON response into task test cases"""
        try:
            # Check for None or empty response
            if response is None:
                logger.error("Received None response from LLM")
                return []
            
            if not isinstance(response, str):
                logger.error(f"Expected string response, got {type(response)}: {response}")
                return []
                
            if not response.strip():
                logger.error("Received empty response from LLM")
                return []
            
            # Clean up response - remove any markdown code blocks
            response = response.strip()
            if response.startswith('```json'):
                response = response[7:]
            elif response.startswith('```'):
                response = response[3:]
            if response.endswith('```'):
                response = response[:-3]
            
            # Find JSON array in response
            import json
            import re
            
            logger.info(f"Processing response with {len(response)} characters")
            
            # Try to find JSON array pattern
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                # If no array found, try the whole response
                json_str = response.strip()
            
            # Parse JSON
            test_data = json.loads(json_str)
            
            # Ensure it's a list
            if not isinstance(test_data, list):
                logger.error(f"Expected JSON array, got {type(test_data)}")
                return []
            
            tests = []
            for item in test_data:
                if not isinstance(item, dict):
                    logger.warning(f"Skipping non-dict item: {item}")
                    continue
                
                # Create TestCase from JSON data
                from .planning_models import TestCase
                
                # Parse test steps if provided, or generate from description
                test_steps = None
                if item.get('test_steps'):
                    # Split test steps into list if they're in string format
                    steps_text = item['test_steps']
                    if isinstance(steps_text, str):
                        # Split by newlines and filter out empty lines
                        test_steps = [step.strip() for step in steps_text.split('\n') if step.strip()]
                    elif isinstance(steps_text, list):
                        test_steps = steps_text
                else:
                    # Generate Gherkin steps from the description if test_steps not provided
                    test_steps = self._generate_gherkin_from_description(
                        item.get('description', ''), 
                        item.get('title', ''),
                        task
                    )
                
                # Determine the source of the test case
                source = "llm_ai" if item.get('test_steps') else "llm_fallback"
                
                test_case = TestCase(
                    title=item.get('title', 'Generated Test Case'),
                    type=item.get('type', 'unit').lower(),
                    description=item.get('description', 'Generated test description'),
                    steps=test_steps,
                    expected_result=item.get('expected_result', 'Expected functionality works correctly'),
                    priority=self._normalize_priority(item.get('priority', 'P2')),
                    source=source
                )
                
                tests.append(test_case)
            
            logger.info(f"Successfully parsed {len(tests)} test cases from JSON")
            return tests
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {str(e)}")
            logger.debug(f"Response content: {response[:500]}...")
            return []
        except Exception as e:
            logger.error(f"Error parsing task test response: {str(e)}")
            return []
    
    def _normalize_priority(self, priority: str) -> str:
        """Normalize priority values"""
        priority = str(priority).lower().strip()
        if priority in ['p0', 'high', 'critical']:
            return 'high'
        elif priority in ['p1', 'medium']:
            return 'medium'
        elif priority in ['p2', 'low']:
            return 'low'
        else:
            return 'medium'
    
    def _generate_gherkin_from_description(self, description: str, title: str, task: TaskPlan) -> List[str]:
        """Generate Gherkin format steps from test description"""
        try:
            # If description already contains Gherkin keywords, extract them
            if any(keyword in description.lower() for keyword in ['given', 'when', 'then', 'and']):
                # Try to extract existing Gherkin steps
                lines = description.split('\n')
                gherkin_lines = []
                for line in lines:
                    line = line.strip()
                    if any(line.lower().startswith(keyword) for keyword in ['given', 'when', 'then', 'and']):
                        gherkin_lines.append(line)
                if gherkin_lines:
                    return gherkin_lines
            
            # Generate basic Gherkin steps based on test type and task context
            if 'unit' in title.lower():
                return [
                    f"Given the {task.summary} component is properly initialized",
                    f"When the core functionality is tested",
                    f"Then the component behaves as expected",
                    f"And all unit requirements are met"
                ]
            elif 'integration' in title.lower():
                return [
                    f"Given all components for {task.summary} are deployed",
                    f"When integration testing is performed",
                    f"Then all components work together correctly",
                    f"And the integration meets requirements"
                ]
            elif 'e2e' in title.lower() or 'end-to-end' in title.lower():
                return [
                    f"Given the system is fully deployed",
                    f"When end-to-end workflow is executed",
                    f"Then the complete user journey works correctly",
                    f"And all acceptance criteria are satisfied"
                ]
            else:
                # Generic Gherkin steps
                return [
                    f"Given the system is in a valid state",
                    f"When the test scenario is executed",
                    f"Then the expected outcome is achieved",
                    f"And the system remains stable"
                ]
                
        except Exception as e:
            logger.warning(f"Error generating Gherkin steps: {e}")
            # Fallback to basic steps
            return [
                f"Given the test preconditions are met",
                f"When the test is executed",
                f"Then the expected result occurs"
            ]
    
    def _parse_single_test_case(self, section: str) -> Optional[TestCase]:
        """Parse a single test case section"""
        try:
            import re
            
            # Extract title - handle both **Test Title**: and Test Title: formats
            title_match = re.search(r'(?:\*\*)?Test Title(?:\*\*)?:\s*(.+?)(?:\n|Type:|$)', section, re.DOTALL)
            title = title_match.group(1).strip() if title_match else "Generated Test Case"
            
            # Extract type - handle both **Type**: and Type: formats
            type_match = re.search(r'(?:\*\*)?Type(?:\*\*)?:\s*(.+?)(?:\n|Priority:|$)', section, re.DOTALL)
            test_type = type_match.group(1).strip() if type_match else "unit"
            
            # Extract priority - handle both **Priority**: and Priority: formats
            priority_match = re.search(r'(?:\*\*)?Priority(?:\*\*)?:\s*(.+?)(?:\n|Steps:|$)', section, re.DOTALL)
            priority = priority_match.group(1).strip() if priority_match else "P2"
            
            # Extract steps - handle both **Steps**: and Steps: formats
            steps_match = re.search(r'(?:\*\*)?Steps(?:\*\*)?:\s*(.+?)(?:\n\n|$)', section, re.DOTALL)
            test_steps = steps_match.group(1).strip() if steps_match else ""
            
            # Build description from the steps content
            description = test_steps if test_steps else "Generated test description"
            
            # Extract expected result from Then clauses in steps
            then_matches = re.findall(r'Then\s+(.+?)(?:\n|$)', test_steps, re.MULTILINE)
            expected_result = "; ".join(then_matches) if then_matches else "Expected functionality works correctly"
            
            from .planning_models import TestCase
            return TestCase(
                title=title,
                type=test_type.lower(),
                description=description,
                expected_result=expected_result,
                priority=priority.lower() if priority.lower() in ['high', 'medium', 'low', 'p0', 'p1', 'p2'] else 'medium'
            )
            
        except Exception as e:
            logger.error(f"Error parsing single test case: {str(e)}")
            logger.debug(f"Section content: {section[:200]}...")
            return None
    
    def _create_test_case_from_dict(self, test_dict: Dict[str, str], default_type: str) -> TestCase:
        """Create TestCase object from parsed dictionary"""
        return TestCase(
            title=test_dict.get('title', 'Generated Test Case'),
            type=test_dict.get('type', default_type),
            description=test_dict.get('description', 'Generated test description'),
            expected_result=test_dict.get('expected_result', 'Expected functionality works correctly')
        )
    
    def _generate_pattern_story_tests(self, story: StoryPlan, coverage_level: TestCoverageLevel) -> List[TestCase]:
        """Generate pattern-based test cases for stories with Gherkin format"""
        tests = []
        
        # Basic acceptance tests from acceptance criteria
        for i, ac in enumerate(story.acceptance_criteria):
            gherkin_steps = f"Given {ac.given}\nWhen {ac.when}\nThen {ac.then}"
            tests.append(TestCase(
                title=f"Acceptance Test: {ac.scenario}",
                type="acceptance",
                description=f"Validate acceptance criteria: {ac.scenario}",
                steps=gherkin_steps.split('\n'),
                expected_result=ac.then,
                source="pattern"
            ))
        
        # Add error scenarios if coverage is standard or comprehensive
        if coverage_level in [TestCoverageLevel.STANDARD, TestCoverageLevel.COMPREHENSIVE]:
            error_steps = f"Given the system is in normal state\nWhen invalid input is provided for {story.summary}\nThen appropriate error messages are displayed\nAnd the system remains stable"
            tests.append(TestCase(
                title=f"Error Handling: {story.summary}",
                type="integration",
                description="Verify error handling and system stability",
                steps=error_steps.split('\n'),
                expected_result="Appropriate error messages are displayed and system remains stable",
                source="pattern"
            ))
        
        # Add performance tests if coverage is comprehensive
        if coverage_level == TestCoverageLevel.COMPREHENSIVE:
            perf_steps = f"Given the system is under normal load\nWhen {story.summary} functionality is executed\nThen response time meets performance requirements\nAnd system resources remain within acceptable limits"
            tests.append(TestCase(
                title=f"Performance: {story.summary}",
                type="performance",
                description="Verify performance characteristics and resource usage",
                steps=perf_steps.split('\n'),
                expected_result="Response time meets performance requirements",
                source="pattern"
            ))
        
        return tests
    
    def _generate_pattern_task_tests(self, task: TaskPlan, coverage_level: TestCoverageLevel) -> List[TestCase]:
        """Generate pattern-based test cases for tasks with Gherkin format"""
        tests = []
        
        # Basic unit tests for each scope
        for scope in task.scopes:
            unit_steps = f"Given the {scope.description} component is properly initialized\nWhen the {scope.description} functionality is invoked\nThen {scope.deliverable} functions correctly\nAnd all unit-level requirements are met"
            tests.append(TestCase(
                title=f"Unit Test: {scope.description}",
                type="unit",
                description=f"Test implementation of {scope.description}",
                steps=unit_steps.split('\n'),
                expected_result=f"{scope.deliverable} functions correctly",
                source="pattern"
            ))
        
        # Integration test for the complete task
        integration_steps = f"Given all components for {task.summary} are deployed\nWhen the complete task workflow is executed\nThen all task components work together correctly\nAnd the integration meets requirements"
        tests.append(TestCase(
            title=f"Integration Test: {task.summary}",
            type="integration",
            description=f"Test integration of all components in {task.summary}",
            steps=integration_steps.split('\n'),
            expected_result="All task components work together correctly",
            source="pattern"
        ))
        
        # Add comprehensive tests if needed
        if coverage_level == TestCoverageLevel.COMPREHENSIVE:
            edge_steps = f"Given the system is configured for {task.summary}\nWhen edge cases and boundary conditions are tested\nThen the system handles edge cases gracefully\nAnd no unexpected failures occur"
            tests.append(TestCase(
                title=f"Edge Cases: {task.summary}",
                type="unit",
                description=f"Test edge cases and boundary conditions for {task.summary}",
                steps=edge_steps.split('\n'),
                expected_result="System handles edge cases gracefully",
                source="pattern"
            ))
        
        return tests
    
    def _deduplicate_tests(self, tests: List[TestCase]) -> List[TestCase]:
        """Remove duplicate test cases"""
        seen_titles = set()
        unique_tests = []
        
        for test in tests:
            # Create a normalized title for comparison
            normalized_title = test.title.lower().strip()
            if normalized_title not in seen_titles:
                seen_titles.add(normalized_title)
                unique_tests.append(test)
        
        return unique_tests
    
    def _ensure_story_coverage(self, tests: List[TestCase], story: StoryPlan, coverage_level: TestCoverageLevel) -> List[TestCase]:
        """Ensure story has minimum required test coverage"""
        required_types = self.coverage_templates[coverage_level.value]["story_types"]
        
        # Check if we have required test types
        existing_types = {test.type for test in tests}
        missing_types = set(required_types) - existing_types
        
        # Add missing test types
        for test_type in missing_types:
            tests.append(TestCase(
                title=f"{test_type.title()} Test: {story.summary}",
                type=test_type,
                description=f"Verify {test_type} functionality for {story.summary}",
                expected_result=f"{test_type.title()} test passes successfully"
            ))
        
        return tests
    
    def _ensure_task_coverage(self, tests: List[TestCase], task: TaskPlan, coverage_level: TestCoverageLevel) -> List[TestCase]:
        """Ensure task has minimum required test coverage"""
        # If we have 3+ quality test cases (likely from AI), don't add generic ones
        if len(tests) >= 3:
            logger.info(f"Task has {len(tests)} test cases - skipping coverage enforcement to avoid generic test cases")
            return tests
            
        required_types = self.coverage_templates[coverage_level.value]["task_types"]
        
        # Check if we have required test types
        existing_types = {test.type for test in tests}
        missing_types = set(required_types) - existing_types
        
        # Only add missing test types if we have very few tests
        for test_type in missing_types:
            tests.append(TestCase(
                title=f"{test_type.title()} Test: {task.summary}",
                type=test_type,
                description=f"Verify {test_type} functionality for {task.summary}",
                expected_result=f"{test_type.title()} test passes successfully",
                source="fallback"
            ))
        
        return tests
    
    def _generate_fallback_story_tests(self, story: StoryPlan, coverage_level: TestCoverageLevel) -> List[TestCase]:
        """Generate fallback test cases for stories when AI generation fails"""
        tests = []
        
        # Basic acceptance test with Gherkin format
        acceptance_steps = f"Given the user has access to {story.summary}\nWhen the user performs the expected actions\nThen {story.summary} works as expected\nAnd all story requirements are satisfied"
        tests.append(TestCase(
            title=f"Acceptance Test: {story.summary}",
            type="acceptance",
            description=f"Verify that {story.summary} works as expected",
            steps=acceptance_steps.split('\n'),
            expected_result="Story functionality works correctly",
            source="fallback"
        ))
        
        # Add error handling test with Gherkin format
        error_steps = f"Given the system is in normal state\nWhen invalid actions are performed on {story.summary}\nThen errors are handled gracefully\nAnd appropriate error messages are shown"
        tests.append(TestCase(
            title=f"Error Handling: {story.summary}",
            type="integration",
            description=f"Verify error handling for {story.summary}",
            steps=error_steps.split('\n'),
            expected_result="Errors are handled gracefully",
            source="fallback"
        ))
        
        return tests
    
    def _generate_fallback_task_tests(self, task: TaskPlan, coverage_level: TestCoverageLevel) -> List[TestCase]:
        """Generate fallback test cases for tasks when AI generation fails"""
        tests = []
        
        # Basic unit test with Gherkin format
        unit_steps = f"Given the {task.summary} implementation is complete\nWhen the core functionality is tested\nThen the task implementation works correctly\nAnd all unit requirements are met"
        tests.append(TestCase(
            title=f"Unit Test: {task.summary}",
            type="unit",
            description=f"Test core functionality of {task.summary}",
            steps=unit_steps.split('\n'),
            expected_result="Task implementation works correctly",
            source="fallback"
        ))
        
        # Integration test with Gherkin format
        integration_steps = f"Given the {task.summary} is deployed\nWhen integration testing is performed\nThen the task integrates correctly with other components\nAnd the system functions as expected"
        tests.append(TestCase(
            title=f"Integration Test: {task.summary}",
            type="integration",
            description=f"Test integration aspects of {task.summary}",
            steps=integration_steps.split('\n'),
            expected_result="Task integrates correctly with other components",
            source="fallback"
        ))
        
        return tests
    
    def _initialize_test_patterns(self) -> Dict[str, Any]:
        """Initialize test generation patterns"""
        return {
            "story_patterns": {
                "user_journey": "Test complete user journey from start to finish",
                "error_handling": "Test error scenarios and recovery",
                "boundary_conditions": "Test edge cases and boundary values",
                "security": "Test authentication and authorization",
                "performance": "Test response time and throughput"
            },
            "task_patterns": {
                "unit_functionality": "Test individual component functionality",
                "integration_points": "Test integration with other components",
                "error_conditions": "Test error handling and exceptions",
                "performance": "Test performance characteristics",
                "security": "Test security vulnerabilities"
            }
        }
    
    def _initialize_coverage_templates(self) -> Dict[str, Dict[str, Any]]:
        """Initialize test coverage templates"""
        return {
            "minimal": {
                "story_types": ["acceptance"],
                "task_types": ["unit"],
                "story_guidance": "Generate 1-2 basic acceptance tests covering happy path scenarios.",
                "task_guidance": "Generate 1-2 unit tests covering core functionality."
            },
            "basic": {
                "story_types": ["acceptance", "integration"],
                "task_types": ["unit", "integration"],
                "story_guidance": "Generate essential acceptance tests using Gherkin format, covering primary user flows and critical error scenarios. Focus on P0/P1 priority test cases with specific test data embedded in steps.",
                "task_guidance": "Generate fundamental unit and integration tests using Gherkin format for core functionality validation. Include positive and negative test scenarios with specific input/output data."
            },
            "standard": {
                "story_types": ["acceptance", "integration", "e2e"],
                "task_types": ["unit", "integration"],
                "story_guidance": "Generate comprehensive acceptance tests using strict Gherkin format, covering user journeys, error scenarios, and end-to-end workflows. Include diverse user personas and real-world usage patterns with embedded test data.",
                "task_guidance": "Generate thorough unit and integration tests using Gherkin format. Cover technical validation, error handling, and component interactions with specific data values and expected outcomes."
            },
            "comprehensive": {
                "story_types": ["acceptance", "integration", "e2e", "performance", "security"],
                "task_types": ["unit", "integration", "performance"],
                "story_guidance": "Generate complete test suite using strict Gherkin format including acceptance, error, performance, security, and accessibility tests. Cover all user personas, edge cases, interruption scenarios, and business-critical workflows with specific test data.",
                "task_guidance": "Generate complete technical test suite using Gherkin format including unit, integration, performance, security, and edge case tests. Cover all code paths, error conditions, and system boundaries with specific data validation."
            }
        }
    
    def _get_test_count_for_coverage(self, coverage_level: TestCoverageLevel) -> int:
        """Get number of test cases to generate based on coverage level"""
        coverage_counts = {
            TestCoverageLevel.MINIMAL: 2,
            TestCoverageLevel.BASIC: 4,
            TestCoverageLevel.STANDARD: 6,
            TestCoverageLevel.COMPREHENSIVE: 10
        }
        return coverage_counts.get(coverage_level, 4)

    def _get_domain_specific_guidance(self, domain: str, item_type: str) -> str:
        """Get domain-specific test guidance"""
        domain_guides = {
            "financial": "Include Gherkin-formatted tests for monetary calculations, compliance rules, audit trails, and regulatory requirements. Use specific monetary values and transaction scenarios.",
            "healthcare": "Include Gherkin-formatted tests for HIPAA compliance, patient data privacy, safety regulations, and medical record integrity. Use specific patient scenarios and data protection cases.",
            "ecommerce": "Include Gherkin-formatted tests for payment processing, inventory management, user experience, cart functionality, and order workflows. Use specific product and transaction data.",
            "security": "Include Gherkin-formatted tests for authentication, authorization, encryption, vulnerability scanning, and access control. Use specific security scenarios and threat vectors."
        }
        return domain_guides.get(domain.lower(), "Include domain-specific business rules and compliance tests using Gherkin format with specific test data.")
    
    def _get_technical_specific_guidance(self, technical_context: str) -> str:
        """Get technical context-specific guidance"""
        tech_guides = {
            "api": "Include Gherkin-formatted tests for endpoint functionality, input validation, error codes, response formats, and API contract validation. Use specific request/response data.",
            "database": "Include Gherkin-formatted tests for data integrity, transactions, performance, backup/recovery, and data consistency. Use specific database operations and data sets.",
            "ui": "Include Gherkin-formatted tests for user interactions, accessibility, responsive design, browser compatibility, and visual elements. Use specific UI elements and user actions.",
            "microservice": "Include Gherkin-formatted tests for service communication, fault tolerance, distributed system behavior, and inter-service contracts. Use specific service scenarios and data flows."
        }
        return tech_guides.get(technical_context.lower(), "Include technical validation tests using Gherkin format with specific technical scenarios and data.")
    
    def _create_test_data_prompt(self, test_case: TestCase, data_types: List[TestDataType], context: Optional[Dict[str, Any]]) -> str:
        """Create prompt for test data generation"""
        required_data_types = chr(10).join([f"- {dt.value}" for dt in data_types])
        additional_context = f"\n**Additional Context:**\n{str(context)}" if context else ""
        
        template = Prompts.get_test_data_prompt_template()
        prompt = template.format(
            test_case_title=test_case.title,
            test_case_type=test_case.type,
            test_case_description=test_case.description,
            required_data_types=required_data_types,
            additional_context=additional_context
        )
        
        return prompt
    
    # Context-aware test generation methods
    
    def _get_task_from_jira(self, task_key: str):
        """Fetch task details from JIRA"""
        try:
            task_info = self.jira_client.get_ticket(task_key)
            if not task_info:
                raise ValueError(f"Could not fetch task {task_key} from JIRA")
                
            # Convert JIRA issue to TaskPlan object
            from .planning_models import TaskPlan, TaskScope
            
            # Extract task scopes from description or custom fields
            fields = task_info.get('fields', {})
            
            # Debug logging
            logger.info(f"Task fields summary: {fields.get('summary', 'N/A')}")
            logger.info(f"Task fields description type: {type(fields.get('description'))}")
            logger.info(f"Task fields description: {str(fields.get('description', 'N/A'))[:200]}...")
            
            try:
                scopes = self._extract_task_scopes(fields)
                logger.info(f"Scopes extracted successfully: {len(scopes)}")
            except Exception as scope_error:
                logger.error(f"Error in _extract_task_scopes: {str(scope_error)}")
                raise scope_error
                
            try:
                expected_outcomes = self._extract_expected_outcomes(fields)
                logger.info(f"Outcomes extracted successfully: {len(expected_outcomes)}")
            except Exception as outcome_error:
                logger.error(f"Error in _extract_expected_outcomes: {str(outcome_error)}")
                raise outcome_error
            
            # Debug logging
            logger.info(f"Extracted {len(scopes)} scopes: {[s.description for s in scopes]}")
            logger.info(f"Extracted {len(expected_outcomes)} outcomes: {expected_outcomes}")
            
            # Extract the description text for TaskPlan creation
            description_text = fields.get('description', '')
            if isinstance(description_text, dict):
                description_text = self._extract_text_from_adf(description_text)
            
            # Determine team assignment
            from .planning_models import TaskTeam
            assignee_name = fields.get('assignee', {}).get('displayName', 'Unassigned') if fields.get('assignee') else 'Unassigned'
            
            task_plan = TaskPlan(
                key=task_key,
                summary=fields.get('summary', ''),
                purpose=description_text,
                scopes=scopes,
                expected_outcomes=expected_outcomes,
                team=TaskTeam.FULLSTACK  # Default team, could be enhanced with better logic
            )
            
            return task_plan
        except Exception as e:
            logger.error(f"Error fetching task from JIRA: {str(e)}")
            raise
    
    def _get_story_context(self, task):
        """Get parent story context if available"""
        try:
            if not self.jira_client:
                return None
                
            # Look for "split from" relationship or issue links
            story_context = self._find_parent_story(task)
            if story_context:
                logger.info(f"Found parent story context for task")
                return {
                    'story': story_context,
                    'acceptance_criteria': self._extract_acceptance_criteria(story_context),
                    'user_journey': story_context.get('description', ''),
                    'story_key': story_context.get('key', ''),
                    'story_summary': story_context.get('summary', '')
                }
        except Exception as e:
            logger.warning(f"Could not fetch story context: {str(e)}")
        return None
    
    def _find_parent_story(self, task):
        """Find parent story through issue links"""
        try:
            # Get the task key from the task object
            task_key = getattr(task, 'key', None)
            if not task_key:
                logger.warning("Task object doesn't have key attribute - parent story lookup will fail")
                return None
            
            # Get issue links
            links = self.jira_client.get_issue_links(task_key)
            
            for link in links:
                # Look for "split from" or "child of" relationships
                link_type = link.get('type', {}).get('name', '').lower()
                if link_type in ['split from', 'child of', 'implements', 'subtask of']:
                    # Check inward and outward links
                    linked_issue = link.get('inwardIssue') or link.get('outwardIssue')
                    if linked_issue:
                        issue_type = linked_issue.get('fields', {}).get('issuetype', {}).get('name', '').lower()
                        if issue_type == 'story':
                            return linked_issue.get('fields', {})
            
            return None
        except Exception as e:
            logger.warning(f"Error finding parent story: {str(e)}")
            return None
    
    def _get_document_context(self, task, story_context):
        """Get PRD/RFC document context using enhanced extraction"""
        try:
            if not self.confluence_client or not self.jira_client:
                return None
                
            doc_context = {}
            
            # Get epic key and epic issue to fetch PRD/RFC URLs
            epic_key = self._get_epic_key(task, story_context)
            if epic_key:
                try:
                    # Get epic issue to access PRD/RFC custom fields
                    epic_issue = self.jira_client.get_ticket(epic_key)
                    if not epic_issue:
                        logger.warning(f"Epic {epic_key} not found")
                        return None
                    
                    # Get PRD content using enhanced extraction
                    prd_url = self._get_custom_field_value(epic_issue, 'PRD')
                    if prd_url:
                        page_data = self.confluence_client.get_page_content(prd_url)
                        if page_data:
                            # Use enhanced PRD sections for test generation context
                            prd_sections = page_data.get('prd_sections', {})
                            # Focus on test-relevant sections
                            test_relevant_sections = {
                                'user_stories': prd_sections.get('user_stories', ''),
                                'acceptance_criteria': prd_sections.get('acceptance_criteria', ''),
                                'constraints_limitation': prd_sections.get('constraints_limitation', ''),
                                'description_flow': prd_sections.get('description_flow', ''),
                                'strategic_impact': prd_sections.get('strategic_impact', '')
                            }
                            doc_context['prd'] = {
                                'title': page_data.get('title', ''),
                                'sections': test_relevant_sections,
                                'content_summary': page_data.get('content', '')[:800]  # Planning mode limit
                            }
                    
                    # Get RFC content using enhanced extraction  
                    rfc_url = self._get_custom_field_value(epic_issue, 'RFC')
                    if rfc_url:
                        page_data = self.confluence_client.get_page_content(rfc_url)
                        if page_data:
                            # Use enhanced RFC sections for test generation context
                            rfc_sections = page_data.get('rfc_sections', {})
                            doc_context['rfc'] = {
                                'title': page_data.get('title', ''),
                                'sections': rfc_sections,
                                'content_summary': page_data.get('content', '')[:800]  # Planning mode limit
                            }
                    
                except Exception as e:
                    logger.warning(f"Error getting epic issue {epic_key}: {str(e)}")
                    return None
            
            return doc_context if doc_context else None
        except Exception as e:
            logger.warning(f"Could not fetch document context: {str(e)}")
            return None
    
    def _generate_ai_task_tests_with_context(self, task, coverage_level, technical_context):
        """Enhanced AI task test generation with story context"""
        try:
            # Try to get story context for this task
            story_context = None
            if hasattr(task, 'key'):
                story_context = self._get_story_context(task)
            
            # Generate base prompt
            prompt = self._create_enhanced_task_prompt(task, story_context, coverage_level, technical_context)
            
            # Generate test cases using LLM with enforced JSON mode for reliable parsing
            # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
            response = self.llm_client.generate_content_json(
                prompt=prompt,
                system_prompt=Prompts.get_enhanced_task_test_system_prompt(),
                max_tokens=None
            )
            
            # Parse response into test cases
            return self._parse_task_test_response(response, task)
            
        except Exception as e:
            logger.warning(f"Enhanced AI task test generation failed: {str(e)}")
            # Fallback to original method
            return self._generate_ai_task_tests(task, coverage_level, technical_context)
    
    def _generate_task_tests_with_full_context(self, task, story_context, doc_context, coverage_level, technical_context):
        """Generate task tests with complete context"""
        try:
            # Create comprehensive prompt with all context
            prompt = self._create_comprehensive_task_prompt(
                task, story_context, doc_context, coverage_level, technical_context
            )
            
            # Generate test cases using LLM with enforced JSON mode for reliable parsing
            # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
            response = self.llm_client.generate_content_json(
                prompt=prompt,
                system_prompt=Prompts.get_full_context_test_system_prompt(),
                max_tokens=None
            )
            
            # Parse response into test cases
            return self._parse_task_test_response(response, task)
            
        except Exception as e:
            logger.error(f"Full context test generation failed: {str(e)}")
            return []
    
    def _create_enhanced_task_prompt(self, task, story_context, coverage_level, technical_context):
        """Create optimized prompt with story context"""
        # Extract scopes for context
        scopes_text = [scope.description for scope in task.scopes] if hasattr(task, 'scopes') else []
        
        # Debug logging
        logger.info(f"Task object type: {type(task)}")
        logger.info(f"Task summary: '{task.summary}'")
        logger.info(f"Task purpose: '{getattr(task, 'purpose', 'N/A')}'")
        logger.info(f"Task scopes count: {len(scopes_text)}")
        
        # Use centralized template
        template = Prompts.get_enhanced_task_prompt_template()
        prompt = template.format(
            task_summary=task.summary,
            task_description=getattr(task, 'purpose', task.summary),
            task_scopes='; '.join(scopes_text) if scopes_text else 'Implementation details',
            expected_outcomes='; '.join(getattr(task, 'expected_outcomes', [])) if hasattr(task, 'expected_outcomes') else 'Functional requirements met'
        )
        
        return prompt
    
    def _create_comprehensive_task_prompt(self, task, story_context, doc_context, coverage_level, technical_context):
        """Create comprehensive prompt with enhanced document context"""
        # Start with enhanced prompt
        prompt = self._create_enhanced_task_prompt(task, story_context, coverage_level, technical_context)
        
        # Add enhanced document context if available
        if doc_context:
            prompt += f"\n\n**ENHANCED DOCUMENT CONTEXT:**"
            
            if doc_context.get('prd'):
                prd_data = doc_context['prd']
                prd_title = prd_data.get('title', 'Product Requirements')
                prompt += f"\n\n**PRD Context - {prd_title}:**"
                
                # Add specific PRD sections relevant to testing
                sections = prd_data.get('sections', {})
                prd_sections = []
                if sections.get('user_stories'):
                    prd_sections.append(f"- User Stories: {sections['user_stories'][:300]}...")
                if sections.get('acceptance_criteria'):
                    prd_sections.append(f"- Acceptance Criteria: {sections['acceptance_criteria'][:300]}...")
                if sections.get('constraints_limitation'):
                    prd_sections.append(f"- Constraints & Limitations: {sections['constraints_limitation'][:300]}...")
                if sections.get('description_flow'):
                    prd_sections.append(f"- Process Flow: {sections['description_flow'][:300]}...")
                if sections.get('strategic_impact'):
                    prd_sections.append(f"- Strategic Impact: {sections['strategic_impact'][:200]}...")
                
                if prd_sections:
                    prompt += "\n" + "\n".join(prd_sections)
                
                prompt += f"\n{Prompts.get_prd_usage_guidance()}"
            
            if doc_context.get('rfc'):
                rfc_data = doc_context['rfc']
                rfc_title = rfc_data.get('title', 'Technical Specification')
                prompt += f"\n\n**RFC Context - {rfc_title}:**"
                
                # Add RFC sections relevant to testing
                sections = rfc_data.get('sections', {})
                rfc_summary = rfc_data.get('content_summary', '')
                if rfc_summary:
                    prompt += f"\n- Technical Overview: {rfc_summary[:400]}..."
                
                prompt += f"\n{Prompts.get_rfc_usage_guidance()}"
        
        # Add context prioritization guidance based on available context
        focus_messages = Prompts.get_testing_focus_messages()
        testing_focus_template = Prompts.get_testing_focus_template()
        
        if not story_context and not doc_context:
            focus_message = focus_messages["limited_context"]
        elif story_context and not doc_context:
            focus_message = focus_messages["story_only"]
        elif doc_context and not story_context:
            focus_message = focus_messages["document_only"]
        else:  # story_context and doc_context
            focus_message = focus_messages["full_context"]
        
        prompt += f"\n\n{testing_focus_template.format(focus_message=focus_message)}"
        
        return prompt
    
    # Helper methods for context extraction
    
    def _extract_task_scopes(self, task_info):
        """Extract task scopes from JIRA task"""
        try:
            from .planning_models import TaskScope
            
            # Get description - handle both string and ADF format
            description = task_info.get('description', '')
            logger.info(f"Description type: {type(description)}")
            logger.info(f"Description value: {str(description)[:100]}...")
            
            if isinstance(description, dict):
                # Handle Atlassian Document Format (ADF)
                logger.info("Processing ADF description")
                description = self._extract_text_from_adf(description)
                logger.info(f"Extracted ADF text: {description[:100]}...")
            
            scopes = []
            
            # Method 1: Look for explicit scope indicators
            if description and 'scope' in description.lower():
                logger.info("Method 1: Looking for scope indicators")
                import re
                scope_patterns = [
                    r'scope[s]?:\s*(.+?)(?:\n|$)',
                    r'what.*?to.*?do[:]?\s*(.+?)(?:\n|$)',
                    r'tasks?[:]?\s*(.+?)(?:\n|$)',
                    r'deliverable[s]?[:]?\s*(.+?)(?:\n|$)'
                ]
                
                for pattern in scope_patterns:
                    matches = re.findall(pattern, description, re.IGNORECASE | re.MULTILINE)
                    for match in matches:
                        scope_text = match.strip()
                        if scope_text and len(scope_text) > 3:
                            logger.info(f"Found scope via pattern: {scope_text}")
                            scopes.append(TaskScope(
                                description=scope_text,
                                deliverable=f"Implementation of {scope_text}"
                            ))
            
            # Method 2: Look for bullet points or numbered lists
            if not scopes and description:
                logger.info("Method 2: Looking for bullet points")
                import re
                bullet_patterns = [
                    r'[-*•]\s+(.+?)(?:\n|$)',
                    r'\d+\.\s+(.+?)(?:\n|$)'
                ]
                
                for pattern in bullet_patterns:
                    matches = re.findall(pattern, description, re.MULTILINE)
                    for match in matches:
                        scope_text = match.strip()
                        if scope_text and len(scope_text) > 5:
                            logger.info(f"Found scope via bullet: {scope_text}")
                            scopes.append(TaskScope(
                                description=scope_text,
                                deliverable=f"Completion of {scope_text}"
                            ))
                            if len(scopes) >= 3:  # Limit to avoid too many scopes
                                break
            
            # Method 3: Use summary if no detailed scopes found
            if not scopes:
                logger.info("Method 3: Using summary as scope")
                summary = task_info.get('summary', '')
                if summary:
                    logger.info(f"Using summary as scope: {summary}")
                    scopes.append(TaskScope(
                        description=f"Implement {summary}",
                        deliverable=f"Completed {summary}"
                    ))
                else:
                    logger.info("No summary available, using default scope")
                    scopes.append(TaskScope(
                        description="Implement core functionality",
                        deliverable="Completed core functionality"
                    ))
            
            logger.info(f"Final scopes count: {len(scopes)}")
            return scopes[:3]  # Limit to 3 scopes maximum
            
        except Exception as e:
            logger.error(f"Error extracting task scopes: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            from .planning_models import TaskScope
            return [TaskScope(
                description="Core implementation",
                deliverable="Completed implementation"
            )]
    
    def _extract_expected_outcomes(self, task_info):
        """Extract expected outcomes from JIRA task"""
        try:
            # Get description - handle both string and ADF format
            description = task_info.get('description', '')
            if isinstance(description, dict):
                description = self._extract_text_from_adf(description)
                
            summary = task_info.get('summary', '')
            outcomes = []
            
            # Method 1: Look for explicit outcome indicators
            if description:
                import re
                outcome_patterns = [
                    r'(?:outcome|result|deliverable|output)[s]?[:]?\s*(.+?)(?:\n|$)',
                    r'(?:expected|should|will|must)[:]?\s*(.+?)(?:\n|$)',
                    r'(?:completion|finish|done)[:]?\s*(.+?)(?:\n|$)',
                    r'(?:after|when\s+complete)[:]?\s*(.+?)(?:\n|$)'
                ]
                
                for pattern in outcome_patterns:
                    matches = re.findall(pattern, description, re.IGNORECASE | re.MULTILINE)
                    for match in matches:
                        outcome_text = match.strip()
                        if outcome_text and len(outcome_text) > 5:
                            outcomes.append(outcome_text)
            
            # Method 2: Look for acceptance criteria or definition of done
            if not outcomes and description:
                import re
                criteria_patterns = [
                    r'(?:acceptance\s+criteria|definition\s+of\s+done|success\s+criteria)[:]?\s*(.+?)(?:\n\n|$)',
                    r'(?:verify|validate|ensure|confirm)[:]?\s*(.+?)(?:\n|$)'
                ]
                
                for pattern in criteria_patterns:
                    matches = re.findall(pattern, description, re.IGNORECASE | re.DOTALL)
                    for match in matches:
                        # Split by bullet points or new lines
                        criteria_items = re.split(r'[-*•]|\d+\.', match)
                        for item in criteria_items:
                            item = item.strip()
                            if item and len(item) > 5:
                                outcomes.append(item)
                                if len(outcomes) >= 3:
                                    break
            
            # Method 3: Generate outcomes based on summary
            if not outcomes:
                if summary:
                    outcomes.append(f"{summary} is successfully implemented and tested")
                    outcomes.append("Code quality standards are met")
                    outcomes.append("Integration tests pass successfully")
                else:
                    outcomes.append("Implementation completed and tested")
                    outcomes.append("Functionality works as expected")
                    outcomes.append("Code is ready for deployment")
            
            return outcomes[:3]  # Limit to 3 outcomes
            
        except Exception as e:
            logger.error(f"Error extracting expected outcomes: {str(e)}")
            return ["Implementation completed and tested", "Quality standards met"]

    def _extract_text_from_adf(self, adf_content):
        """Extract plain text from Atlassian Document Format (ADF)"""
        try:
            if isinstance(adf_content, dict):
                def extract_text_recursive(node):
                    if isinstance(node, dict):
                        text_parts = []
                        if node.get('type') == 'text':
                            text_parts.append(node.get('text', ''))
                        elif 'content' in node:
                            for child in node['content']:
                                text_parts.append(extract_text_recursive(child))
                        return ' '.join(filter(None, text_parts))
                    elif isinstance(node, list):
                        return ' '.join(extract_text_recursive(item) for item in node)
                    return str(node) if node else ''
                
                return extract_text_recursive(adf_content)
            else:
                return str(adf_content)
        except Exception as e:
            logger.error(f"Error extracting text from ADF: {str(e)}")
            return str(adf_content) if adf_content else ''
    
    def _extract_estimated_days(self, task_info):
        """Extract estimated days from JIRA task"""
        try:
            # Try to get from time tracking fields
            time_estimate = task_info.get('timeestimate') or task_info.get('originalestimate')
            if time_estimate:
                # Convert seconds to days (assuming 8 hour work day)
                return time_estimate / (8 * 3600)
            return 1.0  # Default estimate
        except Exception:
            return 1.0
    
    def _extract_acceptance_criteria(self, story_info):
        """Extract acceptance criteria from story"""
        try:
            description = story_info.get('description', '')
            criteria = []
            
            # Look for Gherkin format or bullet points
            import re
            gherkin_matches = re.findall(r'(?:Given|When|Then).+?(?=(?:Given|When|Then|$))', description, re.DOTALL | re.IGNORECASE)
            if gherkin_matches:
                criteria.extend([match.strip() for match in gherkin_matches])
            else:
                # Look for bullet points or numbered lists
                bullet_matches = re.findall(r'[-*•]\s*(.+?)(?:\n|$)', description)
                criteria.extend([match.strip() for match in bullet_matches])
            
            return criteria[:5]  # Limit to 5 criteria
        except Exception:
            return []
    
    def _get_epic_key(self, task, story_context):
        """Get epic key for document searching"""
        try:
            if story_context and 'epic_key' in story_context:
                return story_context['epic_key']
            
            # Try to extract from task or story
            if hasattr(task, 'epic_key'):
                return task.epic_key
            
            # Default pattern matching
            task_key = getattr(task, 'key', '') or getattr(task, 'summary', '')
            if task_key:
                # Extract project prefix (e.g., "PROJ" from "PROJ-123")
                import re
                match = re.match(r'([A-Z]+)-', task_key)
                if match:
                    return f"{match.group(1)}-EPIC"
            
            return None
        except Exception:
            return None
    
    def _get_custom_field_value(self, issue, field_type: str) -> Optional[str]:
        """Get custom field value for PRD or RFC"""
        try:
            if field_type == 'PRD':
                field_id = 'customfield_10050'  # PRD URL field
            elif field_type == 'RFC':
                field_id = 'customfield_10051'  # RFC URL field
            else:
                return None
            
            if not field_id:
                logger.warning(f"No custom field configured for {field_type}")
                return None
                
            return issue.get('fields', {}).get(field_id, None)
        except Exception:
            return None
    
    def _parse_test_data_response(self, response: str, data_types: List[TestDataType]) -> Dict[str, List[Dict[str, Any]]]:
        """Parse LLM response into structured test data"""
        # This would be enhanced with more sophisticated JSON parsing
        # For now, return basic structure
        data = {}
        for data_type in data_types:
            data[data_type.value] = [
                {"description": f"Sample {data_type.value} data", "value": "sample_value"}
            ]
        return data
    
    def _generate_pattern_test_data(self, test_case: TestCase, data_types: List[TestDataType], context: Optional[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Generate pattern-based test data"""
        data = {}
        
        for data_type in data_types:
            if data_type == TestDataType.VALID_INPUT:
                data[data_type.value] = [
                    {"description": "Valid standard input", "value": "valid_data"},
                    {"description": "Valid edge case input", "value": "edge_valid_data"}
                ]
            elif data_type == TestDataType.INVALID_INPUT:
                data[data_type.value] = [
                    {"description": "Null input", "value": None},
                    {"description": "Empty string", "value": ""},
                    {"description": "Invalid format", "value": "invalid_format"}
                ]
            elif data_type == TestDataType.BOUNDARY_VALUES:
                data[data_type.value] = [
                    {"description": "Minimum boundary", "value": 0},
                    {"description": "Maximum boundary", "value": 999999},
                    {"description": "Just below minimum", "value": -1},
                    {"description": "Just above maximum", "value": 1000000}
                ]
        
        return data
    
    def _generate_fallback_test_data(self, test_case: TestCase, data_types: List[TestDataType]) -> Dict[str, List[Dict[str, Any]]]:
        """Generate fallback test data when AI generation fails"""
        return self._generate_pattern_test_data(test_case, data_types, None)
