from typing import Dict, Any, List, Optional, Tuple
import logging
import json
from .prompts import Prompts

logger = logging.getLogger(__name__)


class StoryCoverageAnalyzer:
    """
    Analyzer for determining if task tickets adequately cover story requirements
    
    Uses LLM to analyze:
    - Whether existing tasks cover all story requirements
    - Gaps in coverage
    - Suggestions for updates to existing tasks
    - Suggestions for new tasks to fill gaps
    """
    
    def __init__(self, jira_client, llm_client, config: dict):
        """
        Initialize the analyzer
        
        Args:
            jira_client: JiraClient instance for fetching tickets
            llm_client: LLMClient instance for AI analysis
            config: Configuration dictionary with prompt templates
        """
        self.jira_client = jira_client
        self.llm_client = llm_client
        self.config = config
        
    def analyze_coverage(
        self, 
        story_key: str, 
        include_test_cases: bool = True
    ) -> Dict[str, Any]:
        """
        Main analysis method - analyzes story coverage by its tasks
        
        Args:
            story_key: The story ticket key to analyze
            include_test_cases: Whether to include test case analysis
            
        Returns:
            Dictionary with coverage analysis results
        """
        try:
            logger.info(f"Starting coverage analysis for story {story_key}")
            
            # Step 1: Fetch story and related tasks
            story_data, tasks_data = self._fetch_story_and_tasks(story_key, include_test_cases)
            
            if not story_data:
                return {
                    "success": False,
                    "error": f"Story {story_key} not found",
                    "story_key": story_key
                }
            
            # Step 2: Build LLM prompt (user prompt)
            user_prompt = self._build_llm_prompt(story_data, tasks_data, include_test_cases)
            
            # Step 3: Get system prompt from LLM client
            system_prompt = self.llm_client.get_system_prompt()
            
            # Step 4: Analyze with LLM
            llm_response = self._analyze_with_llm(user_prompt)
            
            # Step 5: Format suggestions with ready-to-submit payloads
            formatted_result = self._format_suggestions(
                story_key, 
                story_data, 
                tasks_data, 
                llm_response,
                include_test_cases,
                system_prompt,
                user_prompt
            )
            
            logger.info(f"Coverage analysis completed for {story_key}: {formatted_result['coverage_percentage']}% coverage")
            
            return formatted_result
            
        except Exception as e:
            logger.error(f"Error analyzing coverage for {story_key}: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "story_key": story_key
            }
    
    def _fetch_story_and_tasks(
        self, 
        story_key: str, 
        include_test_cases: bool
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Fetch story ticket and all related task tickets
        
        Args:
            story_key: Story ticket key
            include_test_cases: Whether to fetch test cases
            
        Returns:
            Tuple of (story_data, tasks_data_list)
        """
        try:
            # Fetch story ticket
            logger.info(f"Fetching story ticket {story_key}")
            story_data = self.jira_client.get_ticket(story_key)
            
            if not story_data:
                logger.error(f"Story ticket {story_key} not found")
                return None, []
            
            # Fetch related tasks
            logger.info(f"Fetching tasks for story {story_key}")
            tasks_data = self.jira_client.get_story_tasks(story_key)
            
            logger.info(f"Found {len(tasks_data)} tasks for story {story_key}")
            
            # Enrich task data with test cases if requested
            if include_test_cases:
                for task in tasks_data:
                    test_cases = self.jira_client.extract_test_cases(task)
                    task['extracted_test_cases'] = test_cases
            
            return story_data, tasks_data
            
        except Exception as e:
            logger.error(f"Error fetching story and tasks: {str(e)}")
            raise
    
    def _build_llm_prompt(
        self, 
        story_data: Dict[str, Any], 
        tasks_data: List[Dict[str, Any]],
        include_test_cases: bool
    ) -> str:
        """
        Build the LLM prompt for coverage analysis
        
        Args:
            story_data: Story ticket data
            tasks_data: List of task ticket data
            include_test_cases: Whether to include test cases in analysis
            
        Returns:
            Formatted prompt string
        """
        try:
            # Extract story information
            story_fields = story_data.get('fields', {})
            story_key = story_data.get('key', 'UNKNOWN')
            story_summary = story_fields.get('summary', 'No summary')
            story_description = story_fields.get('description', '')
            
            # Extract text from ADF if needed
            if isinstance(story_description, dict):
                story_description = self.jira_client._extract_text_from_adf(story_description)
            
            # Extract story test cases if available
            story_test_cases = self.jira_client.extract_test_cases(story_data) if include_test_cases else None
            
            # Build tasks summary
            tasks_summary = []
            tasks_details = []
            
            for i, task in enumerate(tasks_data, 1):
                task_fields = task.get('fields', {})
                task_key = task.get('key', 'UNKNOWN')
                task_summary = task_fields.get('summary', 'No summary')
                task_description = task_fields.get('description', '')
                
                # Extract text from ADF if needed
                if isinstance(task_description, dict):
                    task_description = self.jira_client._extract_text_from_adf(task_description)
                
                tasks_summary.append(f"{i}. {task_key}: {task_summary}")
                
                # Build detailed task info
                detail = f"**Task {i}: {task_key}**\n"
                detail += f"Summary: {task_summary}\n"
                detail += f"Description: {task_description[:500]}{'...' if len(task_description) > 500 else ''}\n"
                
                if include_test_cases:
                    test_cases = task.get('extracted_test_cases', 'No test cases')
                    if test_cases:
                        detail += f"Test Cases: {test_cases[:300]}{'...' if len(test_cases) > 300 else ''}\n"
                    else:
                        detail += "Test Cases: None\n"
                
                tasks_details.append(detail)
            
            # Get prompt template from config or use centralized default
            prompt_template = self.config.get('prompts', {}).get('story_coverage_analysis', Prompts.get_story_coverage_analysis_template())
            
            # Format the prompt
            prompt = prompt_template.format(
                story_key=story_key,
                story_summary=story_summary,
                story_description=story_description or "No description available",
                story_test_cases=story_test_cases or "No test cases in story",
                tasks_count=len(tasks_data),
                tasks_summary='\n'.join(tasks_summary) if tasks_summary else "No tasks found",
                tasks_details='\n\n'.join(tasks_details) if tasks_details else "No task details available",
                include_test_cases=include_test_cases
            )
            
            return prompt
            
        except Exception as e:
            logger.error(f"Error building LLM prompt: {str(e)}")
            raise
    
    def _analyze_with_llm(self, prompt: str) -> Dict[str, Any]:
        """
        Send prompt to LLM and get analysis results
        
        Args:
            prompt: The formatted prompt string
            
        Returns:
            Parsed JSON response from LLM
        """
        try:
            logger.info("Sending analysis request to LLM (using enforced JSON mode with config max_tokens)")
            
            # Generate response using LLM with enforced JSON mode for reliable parsing
            # max_tokens=None means use config default (from LLM_MAX_TOKENS env var)
            response_text = self.llm_client.generate_content_json(prompt, max_tokens=None)
            
            logger.info(f"LLM response length: {len(response_text)} characters")
            
            # Response from generate_content_json is already validated JSON
            # But we'll handle it defensively in case of fallback
            try:
                # Try direct parse first (should work with enforced JSON mode)
                result = json.loads(response_text)
                logger.info("Successfully parsed LLM response as JSON (direct parse)")
                
                # Normalize: Handle case where Claude returns array instead of object
                if isinstance(result, list):
                    logger.warning(f"LLM returned array instead of object - length: {len(result)}, first element type: {type(result[0]) if result else 'empty'}")
                    if len(result) == 1 and isinstance(result[0], dict):
                        logger.warning("Unwrapping single-element array containing dict")
                        result = result[0]
                    elif len(result) > 1:
                        logger.warning(f"Array has {len(result)} elements - attempting to extract dict from first element")
                        # Try to find a dict in the array
                        for idx, item in enumerate(result):
                            if isinstance(item, dict):
                                logger.info(f"Found dict at index {idx}, using it")
                                result = item
                                break
                        else:
                            # No dict found in array
                            logger.error(f"Array contains no dict elements - all elements are of type {type(result[0])}")
                            raise ValueError(f"Expected dict, but array contains no dict elements")
                    else:
                        logger.error("LLM returned empty array")
                        raise ValueError("Empty array returned by LLM")
                
                # Ensure result is a dict (expected structure)
                if not isinstance(result, dict):
                    logger.error(f"LLM returned unexpected type: {type(result)} - expected dict")
                    raise ValueError(f"Expected dict, got {type(result)}")
                
                logger.info(f"Normalized LLM response to dict with keys: {list(result.keys())}")
                return result
            except json.JSONDecodeError as e:
                # Fallback to extraction if needed (shouldn't happen with enforced JSON, but defensive)
                logger.warning(f"Direct parse failed: {e}, attempting JSON extraction")
                try:
                    json_str = self._extract_json_from_response(response_text)
                    result = json.loads(json_str)
                    logger.info("Successfully parsed LLM response as JSON (after extraction)")
                    
                    # Normalize: Handle case where Claude returns array instead of object
                    if isinstance(result, list):
                        logger.warning(f"LLM returned array instead of object - length: {len(result)}, first element type: {type(result[0]) if result else 'empty'}")
                        if len(result) == 1 and isinstance(result[0], dict):
                            logger.warning("Unwrapping single-element array containing dict")
                            result = result[0]
                        elif len(result) > 1:
                            logger.warning(f"Array has {len(result)} elements - attempting to extract dict from first element")
                            # Try to find a dict in the array
                            for idx, item in enumerate(result):
                                if isinstance(item, dict):
                                    logger.info(f"Found dict at index {idx}, using it")
                                    result = item
                                    break
                            else:
                                # No dict found in array - Claude may have misunderstood the prompt
                                logger.error(f"Array contains no dict elements - all elements are of type {type(result[0])}")
                                logger.error(f"First few array elements: {result[:3] if len(result) >= 3 else result}")
                                logger.error("Claude returned an array of strings instead of a JSON object. This suggests the prompt may not have been clear enough or Claude misunderstood the format.")
                                raise ValueError(f"Expected dict, but array contains no dict elements. Claude returned {len(result)} strings instead of a JSON object. Please check the prompt and try again.")
                        else:
                            # Empty array
                            logger.error("LLM returned empty array")
                            raise ValueError("Empty array returned by LLM")
                    
                    # Ensure result is a dict (expected structure)
                    if not isinstance(result, dict):
                        logger.error(f"LLM returned unexpected type: {type(result)} - expected dict")
                        raise ValueError(f"Expected dict, got {type(result)}")
                    
                    logger.info(f"Normalized LLM response to dict with keys: {list(result.keys())}")
                    return result
                except json.JSONDecodeError as extract_error:
                    logger.warning(f"JSON extraction also failed: {extract_error}")
                    logger.warning(f"JSON parsing error at position {extract_error.pos}: {extract_error.msg}")
                    
                    # Log more context around the error
                    if hasattr(extract_error, 'pos') and extract_error.pos:
                        start = max(0, extract_error.pos - 100)
                        end = min(len(json_str), extract_error.pos + 100)
                        logger.warning(f"Context around error:\n{json_str[start:end]}")
                    
                    # Try to repair common JSON issues
                    try:
                        repaired_json = self._try_repair_json(json_str)
                        if repaired_json:
                            result = json.loads(repaired_json)
                            logger.info("Successfully parsed JSON after repair")
                            
                            # Normalize: Handle case where Claude returns array instead of object
                            if isinstance(result, list):
                                if len(result) == 1 and isinstance(result[0], dict):
                                    logger.warning("LLM returned array with single object - unwrapping to object")
                                    result = result[0]
                                elif len(result) > 1:
                                    logger.warning(f"LLM returned array with {len(result)} elements - using first element")
                                    result = result[0] if isinstance(result[0], dict) else result
                                else:
                                    logger.error("LLM returned empty array - returning fallback structure")
                                    raise ValueError("Empty array returned by LLM")
                            
                            # Ensure result is a dict (expected structure)
                            if not isinstance(result, dict):
                                logger.error(f"LLM returned unexpected type: {type(result)} - expected dict")
                                raise ValueError(f"Expected dict, got {type(result)}")
                            
                            return result
                    except Exception as repair_error:
                        logger.warning(f"JSON repair failed: {repair_error}")
                    
                    # Save problematic response for debugging
                    logger.error(f"Full problematic response:\n{response_text}")
                    
                    # Return a fallback structure
                    return {
                        "coverage_percentage": 50.0,
                        "overall_assessment": f"JSON parsing failed: {extract_error.msg}. Manual review required.",
                        "gaps": [{
                            "requirement": "Unable to parse detailed analysis",
                            "severity": "unknown",
                            "suggestion": f"Manual review required. Parse error: {extract_error.msg}"
                        }],
                    "covered_requirements": [],
                    "suggestions_for_updates": {},
                    "suggestions_for_new_tasks": []
                }
                
        except Exception as e:
            logger.error(f"Error analyzing with LLM: {str(e)}")
            raise
    
    def _extract_json_from_response(self, response_text: str) -> str:
        """
        Extract JSON string from LLM response, handling various formats
        
        Args:
            response_text: Raw LLM response
            
        Returns:
            Extracted JSON string
        """
        # Look for JSON in markdown code blocks
        if '```json' in response_text:
            json_start = response_text.find('```json') + 7
            json_end = response_text.find('```', json_start)
            if json_end == -1:
                # No closing backticks, take everything after opening
                json_str = response_text[json_start:].strip()
            else:
                json_str = response_text[json_start:json_end].strip()
        elif '```' in response_text:
            json_start = response_text.find('```') + 3
            json_end = response_text.find('```', json_start)
            if json_end == -1:
                json_str = response_text[json_start:].strip()
            else:
                json_str = response_text[json_start:json_end].strip()
        else:
            # Try to find JSON object boundaries
            json_str = response_text.strip()
            # If response has text before JSON, try to find the opening brace
            if not json_str.startswith('{'):
                start_idx = json_str.find('{')
                if start_idx != -1:
                    json_str = json_str[start_idx:]
        
        return json_str
    
    def _try_repair_json(self, json_str: str) -> Optional[str]:
        """
        Attempt to repair common JSON formatting issues
        
        Args:
            json_str: Malformed JSON string
            
        Returns:
            Repaired JSON string or None if repair failed
        """
        try:
            # Remove any trailing text after the last closing brace
            last_brace = json_str.rfind('}')
            if last_brace != -1:
                json_str = json_str[:last_brace + 1]
            
            # Try to close unterminated strings by adding quotes before newlines
            # This is a simple heuristic and might not work in all cases
            
            return json_str
        except Exception:
            return None
    
    def _format_suggestions(
        self,
        story_key: str,
        story_data: Dict[str, Any],
        tasks_data: List[Dict[str, Any]],
        llm_response: Dict[str, Any],
        include_test_cases: bool,
        system_prompt: str,
        user_prompt: str
    ) -> Dict[str, Any]:
        """
        Format LLM response into structured output with ready-to-submit payloads
        
        Args:
            story_key: Story ticket key
            story_data: Story ticket data
            tasks_data: List of task data
            llm_response: Parsed LLM response
            include_test_cases: Whether test cases were included
            system_prompt: System prompt sent to LLM
            user_prompt: User prompt sent to LLM
            
        Returns:
            Formatted result dictionary
        """
        try:
            # Defensive check: Ensure llm_response is a dict (normalize if needed)
            if isinstance(llm_response, list):
                logger.error(f"ERROR: llm_response is a list (length: {len(llm_response)}) - attempting to normalize")
                if len(llm_response) > 0:
                    # Try to find a dict in the list
                    for idx, item in enumerate(llm_response):
                        if isinstance(item, dict):
                            logger.warning(f"Normalizing: using dict at index {idx}")
                            llm_response = item
                            break
                    else:
                        # No dict found - this is a real error
                        logger.error(f"llm_response list contains no dict elements - types: {[type(x) for x in llm_response]}")
                        raise ValueError(f"llm_response is a list with no dict elements")
                else:
                    logger.error("llm_response is an empty list")
                    raise ValueError("llm_response is an empty list")
            elif not isinstance(llm_response, dict):
                logger.error(f"llm_response is unexpected type: {type(llm_response)}")
                raise ValueError(f"llm_response must be a dict, got {type(llm_response)}")
            
            # Extract story description
            story_fields = story_data.get('fields', {})
            story_description = story_fields.get('description', '')
            if isinstance(story_description, dict):
                story_description = self.jira_client._extract_text_from_adf(story_description)
            
            # Build task summaries
            task_summaries = []
            for task in tasks_data:
                task_fields = task.get('fields', {})
                task_key = task.get('key', 'UNKNOWN')
                task_summary = task_fields.get('summary', 'No summary')
                task_description = task_fields.get('description', '')
                
                if isinstance(task_description, dict):
                    task_description = self.jira_client._extract_text_from_adf(task_description)
                
                test_cases = task.get('extracted_test_cases', None) if include_test_cases else None
                
                task_summaries.append({
                    "task_key": task_key,
                    "summary": task_summary,
                    "description": task_description or "No description",
                    "test_cases": test_cases
                })
            
            # Format update suggestions with ready-to-submit payloads
            update_suggestions = []
            raw_updates = llm_response.get('suggestions_for_updates', {})
            
            for task_key, suggestion_data in raw_updates.items():
                if isinstance(suggestion_data, dict):
                    suggested_desc = suggestion_data.get('description', '')
                    suggested_tests = suggestion_data.get('test_cases', '')
                else:
                    # Fallback if LLM returns just a string
                    suggested_desc = str(suggestion_data)
                    suggested_tests = ''
                
                # Find current task data
                current_task = next((t for t in tasks_data if t.get('key') == task_key), None)
                current_desc = ''
                if current_task:
                    current_desc = current_task.get('fields', {}).get('description', '')
                    if isinstance(current_desc, dict):
                        current_desc = self.jira_client._extract_text_from_adf(current_desc)
                
                update_suggestions.append({
                    "task_key": task_key,
                    "current_description": current_desc,
                    "suggested_description": suggested_desc,
                    "suggested_test_cases": suggested_tests if include_test_cases else None,
                    "ready_to_submit": {
                        "task_key": task_key,
                        "updated_description": suggested_desc,
                        "updated_test_cases": suggested_tests if include_test_cases else None,
                        "update_jira": False
                    }
                })
            
            # Format new task suggestions with ready-to-submit payloads
            new_task_suggestions = []
            raw_new_tasks = llm_response.get('suggestions_for_new_tasks', [])
            
            for i, task_data in enumerate(raw_new_tasks):
                if isinstance(task_data, dict):
                    task_summary = task_data.get('summary', f'New Task {i+1}')
                    task_description = task_data.get('description', '')
                    task_test_cases = task_data.get('test_cases', '')
                    gap_addressed = task_data.get('gap_addressed', 'Coverage gap')
                else:
                    # Fallback if LLM returns just a string
                    task_summary = f'New Task {i+1}'
                    task_description = str(task_data)
                    task_test_cases = ''
                    gap_addressed = 'Coverage gap'
                
                new_task_suggestions.append({
                    "summary": task_summary,
                    "description": task_description,
                    "test_cases": task_test_cases if include_test_cases else None,
                    "gap_addressed": gap_addressed,
                    "ready_to_submit": {
                        "story_key": story_key,
                        "task_summary": task_summary,
                        "task_description": task_description,
                        "test_cases": task_test_cases if include_test_cases else None,
                        "create_ticket": False
                    }
                })
            
            # Format coverage gaps
            gaps = []
            raw_gaps = llm_response.get('gaps', [])
            for gap_data in raw_gaps:
                if isinstance(gap_data, dict):
                    gaps.append({
                        "requirement": gap_data.get('requirement', 'Unknown requirement'),
                        "severity": gap_data.get('severity', 'unknown'),
                        "suggestion": gap_data.get('suggestion', 'No suggestion provided')
                    })
                else:
                    gaps.append({
                        "requirement": str(gap_data),
                        "severity": "unknown",
                        "suggestion": "Review required"
                    })
            
            # Build final response
            result = {
                "success": True,
                "story_key": story_key,
                "story_description": story_description,
                "tasks": task_summaries,
                "coverage_percentage": llm_response.get('coverage_percentage', 0.0),
                "gaps": gaps,
                "overall_assessment": llm_response.get('overall_assessment', 'Analysis completed'),
                "suggestions_for_updates": update_suggestions,
                "suggestions_for_new_tasks": new_task_suggestions,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error formatting suggestions: {str(e)}")
            raise
    
    def _get_default_prompt(self) -> str:
        """Get default prompt template if not configured (deprecated - use Prompts.get_story_coverage_analysis_template())"""
        return Prompts.get_story_coverage_analysis_template()

